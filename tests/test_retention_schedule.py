"""Offline daily-retention scheduling across restarts, backlog, policy changes and failures."""
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maildesk import mail_retention
from maildesk.store import Store
from maildesk.sync_batches import SyncInterrupted
from tests.test_cache_maintenance import MailboxFixture

# ==========================================
# Function: Exercise the production daily scheduler with real durable stores and synthetic IMAP.
# Method: Advance an explicit clock and reopen SQLite without accessing user accounts or the network.
# ==========================================
class DailyRetentionTests(unittest.TestCase):
    # ==========================================
    # Function: Isolate a mapped account and its cache for each scheduling scenario.
    # Method: Create a temporary real store with a fixed UTC reference and deterministic cloud fixture.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'mail.sqlite3');self.store.cache_dir=Path(self.temp.name)/'cache'
        self.account=SimpleNamespace(id='one');self.client=MailboxFixture()
        self.now=datetime(2026,10,25,12,tzinfo=timezone.utc)
        self.folders=[{'name':'INBOX','special':'inbox'},{'name':'Deleted Items','special':'trash'}]
        self.store.save_folders('one',self.folders)

    # ==========================================
    # Function: Cache a known old source with a real MIME date and stable UID.
    # Method: Keep message identity and age independent from the scheduler's simulated wall clock.
    # ==========================================
    def mail(self,uid='1',age=800):
        message=EmailMessage();message['From']='sender@example.invalid';message['To']='me@example.invalid'
        message['Subject']='daily fixture';message['Date']=self.now-timedelta(days=age)
        message['Message-ID']='<daily-'+uid+'@example.invalid>';message.set_content('fixture')
        return self.store.ingest('one','INBOX','7',uid,message.as_bytes())

    # ==========================================
    # Function: Run the production scheduler at an explicitly controlled time.
    # Method: Delegate all matching, remote guards and persistence to the actual implementation.
    # ==========================================
    def run_at(self,when=None,**kwargs):
        return mail_retention.run_due(self.account,self.store,self.client,now=when or self.now,**kwargs)

    # ==========================================
    # Function: Preserve the completed interval across restart without issuing candidate or remote work.
    # Method: Reopen the store and fail if the raw scanner runs before the exact24-hour boundary.
    # ==========================================
    def test_restart_keeps_completion_and_exact_boundary(self):
        self.assertEqual(self.run_at()['moved'],0)
        self.store=Store(self.store.path)
        with patch.object(mail_retention,'expire_inbox',side_effect=AssertionError('premature scan')):
            self.assertTrue(self.run_at(self.now+timedelta(hours=23,minutes=59,seconds=59))['skipped'])
        with patch.object(mail_retention,'expire_inbox',wraps=mail_retention.expire_inbox) as scanner:
            self.run_at(self.now+timedelta(hours=24));self.assertEqual(scanner.call_count,1)
        self.assertTrue(self.run_at(self.now+timedelta(hours=24,seconds=1))['skipped'])

    # ==========================================
    # Function: Catch up after multiple days closed with one current scan rather than replaying missed days.
    # Method: Complete an empty scan, cache a newly expired source and reopen several days later.
    # ==========================================
    def test_closed_for_days_catches_up_once(self):
        identity=self.mail(age=364);self.run_at();self.store=Store(self.store.path)
        result=self.run_at(self.now+timedelta(days=5));self.assertEqual(result['moved'],1)
        self.assertTrue(self.store.get(identity)['remote_gone'])
        self.assertTrue(self.run_at(self.now+timedelta(days=5,minutes=1))['skipped'])

    # ==========================================
    # Function: Keep completion records independent for separate accounts.
    # Method: Complete one account and require the other account's first scan at the same instant.
    # ==========================================
    def test_accounts_have_independent_schedules(self):
        self.run_at();self.store.save_folders('two',self.folders)
        with patch.object(mail_retention,'expire_inbox',wraps=mail_retention.expire_inbox) as scanner:
            mail_retention.run_due(SimpleNamespace(id='two'),self.store,self.client,now=self.now)
            self.assertEqual(scanner.call_count,1)
        self.assertTrue(self.run_at()['skipped'])

    # ==========================================
    # Function: Avoid repeated scanning from unrelated settings saves while honoring a new day threshold.
    # Method: Save the same policy, then shorten retention and require immediate next-sync eligibility.
    # ==========================================
    def test_policy_changes_invalidate_but_noop_saves_preserve(self):
        identity=self.mail(age=30);self.run_at();mail_retention.save_policy(self.store,True,365)
        self.assertTrue(self.run_at()['skipped']);mail_retention.save_policy(self.store,True,7)
        self.assertEqual(self.run_at()['moved'],1);self.assertTrue(self.store.get(identity)['remote_gone'])

    # ==========================================
    # Function: Resume promptly after disabling and re-enabling within the previously completed day.
    # Method: Return to the identical enabled/day pair and verify the revision still invalidates old completion.
    # ==========================================
    def test_reenable_same_policy_requires_new_check(self):
        self.run_at();identity=self.mail();mail_retention.save_policy(self.store,False,365)
        self.assertTrue(self.run_at()['disabled']);self.assertEqual(self.client.commands,[])
        mail_retention.save_policy(self.store,True,365);self.assertEqual(self.run_at()['moved'],1)
        self.assertTrue(self.store.get(identity)['remote_gone'])

    # ==========================================
    # Function: Continue a full batch on subsequent syncs before marking the day's check complete.
    # Method: Process three old sources with a two-source cap and then verify daily gating.
    # ==========================================
    def test_bounded_backlog_finishes_before_daily_completion(self):
        for uid in ('1','2','3'):self.mail(uid)
        first=self.run_at(limit=2);self.assertEqual(first['moved'],2);self.assertTrue(first['more'])
        self.store=Store(self.store.path)
        second=self.run_at(limit=2);self.assertEqual(second['moved'],1);self.assertFalse(second['more'])
        self.assertTrue(self.run_at(limit=2)['skipped'])

    # ==========================================
    # Function: Retry unresolved account mappings without waiting another day.
    # Method: Remove trash, observe pending work, restore the mapping and repeat at the same instant.
    # ==========================================
    def test_missing_trash_remains_due(self):
        self.mail()
        with self.store.db() as db:db.execute("UPDATE folders SET special='' WHERE special='trash'")
        self.assertIn('pending',self.run_at());self.assertEqual(self.client.commands,[])
        self.store.save_folders('one',self.folders);self.assertEqual(self.run_at()['moved'],1)

    # ==========================================
    # Function: Leave failed work eligible and avoid moving already confirmed sources again.
    # Method: Fail the second MOVE, reopen the store, and complete only the remaining source.
    # ==========================================
    def test_partial_network_failure_does_not_record_completion(self):
        first=self.mail('1',age=801);second=self.mail('2',age=800);original=self.client.uid
        # ==========================================
        # Function: Interrupt one cloud operation before it mutates the fixture.
        # Method: Reject only UID2's MOVE while preserving the first confirmed transfer.
        # ==========================================
        def fail_second(command,*args):
            if command=='MOVE' and args[0]=='2':raise OSError('synthetic disconnect')
            return original(command,*args)
        self.client.uid=fail_second
        with self.assertRaises(OSError):self.run_at()
        self.assertTrue(self.store.get(first)['remote_gone']);self.assertFalse(self.store.get(second)['remote_gone'])
        self.client.uid=original;self.store=Store(self.store.path);self.assertEqual(self.run_at()['moved'],1)
        self.assertTrue(self.run_at()['skipped'])

    # ==========================================
    # Function: Yield to foreground work without losing the due check across restart.
    # Method: Interrupt at the scanner checkpoint, then rerun normally at the same clock time.
    # ==========================================
    def test_interrupted_batch_stays_due(self):
        identity=self.mail()
        with self.assertRaises(SyncInterrupted):self.run_at(should_yield=lambda:True)
        self.assertFalse(self.store.get(identity)['remote_gone']);self.store=Store(self.store.path)
        self.assertEqual(self.run_at()['moved'],1)

    # ==========================================
    # Function: Do not record successful completion when shutdown arrives after scanning an empty inbox.
    # Method: Interrupt the scheduler's final checkpoint and require the next call to perform a real scan.
    # ==========================================
    def test_interrupted_completion_stays_due(self):
        with self.assertRaises(SyncInterrupted):self.run_at(should_yield=lambda:True)
        with patch.object(mail_retention,'expire_inbox',wraps=mail_retention.expire_inbox) as scanner:
            self.run_at();self.assertEqual(scanner.call_count,1)

    # ==========================================
    # Function: Prevent a stale scan from completing a policy changed concurrently during its work.
    # Method: Disable and re-enable during the scanner callback and check eligibility remains immediate.
    # ==========================================
    def test_policy_revision_race_cannot_stamp_new_policy(self):
        # ==========================================
        # Function: Simulate a policy change between the scheduling snapshot and final commit.
        # Method: Return a finished scan after cycling the switch back to its original value.
        # ==========================================
        def change(*args,**kwargs):
            mail_retention.save_policy(self.store,False,365);mail_retention.save_policy(self.store,True,365)
            return {'moved':0}
        with patch.object(mail_retention,'expire_inbox',side_effect=change):self.run_at()
        with patch.object(mail_retention,'expire_inbox',wraps=mail_retention.expire_inbox) as scanner:
            self.run_at();self.assertEqual(scanner.call_count,1)

    # ==========================================
    # Function: Recover from a wall clock moved backward rather than suppressing scans for an extended future.
    # Method: Complete at the reference time, roll back a day and confirm the new timestamp becomes stable.
    # ==========================================
    def test_clock_rollback_recovers(self):
        self.run_at();earlier=self.now-timedelta(days=1)
        with patch.object(mail_retention,'expire_inbox',wraps=mail_retention.expire_inbox) as scanner:
            self.run_at(earlier);self.assertEqual(scanner.call_count,1)
        self.assertTrue(self.run_at(earlier+timedelta(minutes=1))['skipped'])


if __name__=='__main__':unittest.main()
