"""Local-first state, crash recovery and provider reconciliation using synthetic mail."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from maildesk.config import Account
from maildesk.service import MailService
from maildesk import folders,transport
from tests.test_sync_performance import Provider,Session


# ==========================================
# Function: Exercise durable mailbox mutations against an observable synthetic provider.
# Method: Keep real SQLite, MIME and protocol adapter code, replacing only authenticated sessions.
# ==========================================
class MailMutationTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare cached inbox mail and discovered special folders.
    # Method: Use a private temporary profile without credentials or a background worker.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.account=Account('test','me@example.invalid','imap.invalid','smtp.invalid')
        self.provider=Provider(3);self.service=MailService(self.root,[self.account]);self.store=self.service.store
        self.store.set_preference('mail_retention_enabled',False)
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.sync()
        self.ids=[row['id'] for row in self.store.list_messages()['items']];self.identity=self.ids[0]
        self.provider.commands.clear()

    # ==========================================
    # Function: Dispose only this test's isolated profile after all work finishes.
    # Method: Stop the service before removing SQLite files.
    # ==========================================
    def tearDown(self):
        self.service.close();self.temp.cleanup()

    # ==========================================
    # Function: Read compact durable move records for assertions.
    # Method: Query production queue state without invoking a provider.
    # ==========================================
    def moves(self):
        with self.store.db() as db:return [dict(row) for row in db.execute('SELECT * FROM pending_moves')]

    # ==========================================
    # Function: Verify immediate state, coalescing, persistence and exact remote acknowledgement.
    # Method: Make repeated offline edits, reopen SQLite and flush a single final flag.
    # ==========================================
    def test_flags_coalesce_and_survive_restart(self):
        with patch('maildesk.transport.imap_connection',side_effect=AssertionError('UI attempted network')):
            for value in (True,False,True):self.service.update(self.identity,{'seen':value})
        self.assertTrue(self.store.state(self.identity)['seen']);self.assertEqual(len(self.store.pending_read_flags()),1)
        self.service.close();self.service=MailService(self.root,[self.account]);self.store=self.service.store
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertEqual(self.store.pending_read_flags(),[])
        self.assertEqual(sum(cmd[0]=='STORE' for cmd in self.provider.commands),1)

    # ==========================================
    # Function: Keep a new user intention when an older remote response arrives.
    # Method: Write unread inside the successful read STORE boundary and compare generations.
    # ==========================================
    def test_inflight_flag_does_not_erase_newer_intent(self):
        self.service.update(self.identity,{'seen':True})
        with patch('maildesk.transport.set_seen',side_effect=lambda *args:self.service.update(self.identity,{'seen':False})):
            self.service.flush_mutations()
        self.assertFalse(self.store.state(self.identity)['seen']);self.assertEqual(self.store.pending_read_flags()[0]['seen'],0)
        self.store.reconcile('test','INBOX','77',{'1','2','3'},{'1':True,'2':True,'3':True})
        self.assertFalse(self.store.state(self.identity)['seen'])

    # ==========================================
    # Function: Preserve a stable cached identity through multiple coalesced moves.
    # Method: Archive, trash and restore locally before flush; assert no redundant MOVE is sent.
    # ==========================================
    def test_move_coalesces_and_undo_cancels_wire_work(self):
        self.service.bulk_action([self.identity],'done',True)
        self.assertEqual(self.store.state(self.identity)['folder'],'Archive')
        self.assertEqual(self.store.list_messages(view='done')['items'][0]['id'],self.identity)
        self.service.move_message(self.identity,special='trash')
        self.assertEqual(self.store.list_messages(view='trash')['items'][0]['id'],self.identity)
        self.service.move_message(self.identity,special='inbox')
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertEqual(self.moves(),[]);self.assertEqual(self.provider.commands,[])
        self.assertEqual(self.store.state(self.identity)['validity'],'77');self.assertFalse(self.store.state(self.identity)['done'])

    # ==========================================
    # Function: Keep pending destination mail visible during a concurrent stale remote snapshot.
    # Method: Reconcile both folders before flush, then verify UID mapping and source suppression.
    # ==========================================
    def test_move_survives_stale_sync_and_keeps_identity(self):
        old=self.store.state(self.identity);raw=self.store.get(self.identity,raw=True)['raw']
        self.service.move_message(self.identity,special='archive')
        self.assertEqual(self.store.ingest('test','INBOX','77',old['uid'],raw),self.identity)
        self.store.mailbox('test','Archive','77');self.store.reconcile('test','Archive','77',set(),{})
        self.assertFalse(self.store.state(self.identity)['remote_gone'])
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.sync()
        current=self.store.state(self.identity)
        self.assertEqual(current['folder'],'Archive');self.assertEqual(current['validity'],'77')
        self.assertNotIn(old['uid'],self.provider.boxes['INBOX'])
        self.assertEqual(self.store.list_messages(view='all')['total'],3);self.assertEqual(self.moves(),[])

    # ==========================================
    # Function: Resolve read changes against the source until a queued move has been confirmed.
    # Method: Queue a destination and a flag, then verify the server's moved source contains that flag.
    # ==========================================
    def test_read_flag_uses_real_source_before_move(self):
        self.service.move_message(self.identity,special='archive');self.service.update(self.identity,{'seen':True})
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        uid=self.store.state(self.identity)['uid']
        self.assertIn(b'\\Seen',self.provider.boxes['Archive'][uid]['flags']);self.assertEqual(self.store.pending_read_flags(),[])

    # ==========================================
    # Function: Recover a command that succeeded remotely but lost its response.
    # Method: Move once, raise a simulated disconnect, restart and recover via exact MIME without another MOVE.
    # ==========================================
    def test_lost_move_response_is_not_replayed(self):
        self.service.move_message(self.identity,special='archive');real=folders.transfer
        # ==========================================
        # Function: Lose the acknowledgement after the synthetic provider committed the move.
        # Method: Execute the real adapter before raising the connection error.
        # ==========================================
        def lost(*args):
            real(*args);raise OSError('response lost')
        with patch('maildesk.transport.imap_connection',self.provider.connection),patch('maildesk.folders.transfer',side_effect=lost):
            self.service.flush_mutations()
        self.assertEqual(self.moves()[0]['state'],'uncertain')
        self.service.close();self.service=MailService(self.root,[self.account]);self.store=self.service.store
        with self.store.db() as db:db.execute('UPDATE pending_moves SET retry_at=0')
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertEqual(self.moves(),[]);self.assertEqual(sum(cmd[0]=='MOVE' for cmd in self.provider.commands),1)
        self.assertEqual(len(self.provider.boxes['Archive']),1);self.assertEqual(self.store.state(self.identity)['folder'],'Archive')

    # ==========================================
    # Function: Retain a newer destination chosen while an earlier move is in flight.
    # Method: Inject a second local move before the first acknowledgement and flush the successor separately.
    # ==========================================
    def test_new_destination_during_move_is_preserved(self):
        self.service.move_message(self.identity,special='archive');real=folders.transfer
        # ==========================================
        # Function: Apply a later user action while the provider response is outstanding.
        # Method: Update only local intent after the real first MOVE has completed.
        # ==========================================
        def newer(*args):
            result=real(*args);self.service.move_message(self.identity,special='trash');return result
        with patch('maildesk.transport.imap_connection',self.provider.connection),patch('maildesk.folders.transfer',side_effect=newer):self.service.flush_mutations()
        self.assertEqual(self.store.state(self.identity)['folder'],'Trash');self.assertEqual(self.moves()[0]['source_folder'],'Archive')
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertEqual(self.moves(),[]);self.assertEqual(len(self.provider.boxes['Trash']),1);self.assertFalse(self.provider.boxes['Archive'])

    # ==========================================
    # Function: Keep UIDVALIDITY changes from applying an action to an unrelated generation.
    # Method: Corrupt only cached source generation and inspect zero provider MOVE/STORE commands.
    # ==========================================
    def test_stale_generation_remains_visible_and_pending(self):
        with self.store.db() as db:db.execute("UPDATE messages SET validity='88' WHERE id=?",(self.identity,))
        self.service.move_message(self.identity,special='trash')
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertFalse(any(cmd[0] in ('MOVE','STORE') for cmd in self.provider.commands))
        self.assertEqual(self.store.state(self.identity)['folder'],'Trash');self.assertTrue(self.moves()[0]['error'])

    # ==========================================
    # Function: Reject invalid bulk selections atomically without partially changing local flags.
    # Method: Mix one real identity with a missing identity in a single SQLite transaction.
    # ==========================================
    def test_bulk_validation_rolls_back_all_flags(self):
        with self.assertRaises(ValueError):self.service.bulk_action([self.identity,'missing'],'seen',True)
        self.assertFalse(self.store.state(self.identity)['seen']);self.assertEqual(self.store.pending_read_flags(),[])

    # ==========================================
    # Function: Upgrade legacy done flags to provider archives without hiding unmapped messages.
    # Method: Persist the old local flag and run the real migration during the next flush.
    # ==========================================
    def test_legacy_done_becomes_archive(self):
        self.store.organize(self.identity,done=True)
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertEqual(self.store.state(self.identity)['folder'],'Archive');self.assertEqual(self.moves(),[])

    # ==========================================
    # Function: Resolve a confirmed MOVE even when the provider omits COPYUID.
    # Method: Exercise exact-byte recovery and retain the original local message identity.
    # ==========================================
    def test_move_without_copyuid_recovers_exact_content(self):
        self.service.move_message(self.identity,special='archive');original=Session.response
        with patch('maildesk.transport.imap_connection',self.provider.connection),patch.object(Session,'response',lambda client,code:('COPYUID',[None]) if code=='COPYUID' else original(client,code)):
            self.service.flush_mutations()
        self.assertFalse(self.moves());self.assertEqual(self.store.state(self.identity)['folder'],'Archive')
        self.assertEqual(len(self.store.list_messages(view='all')['items']),3)

    # ==========================================
    # Function: Preserve ambiguous source-plus-destination copies without another destructive command.
    # Method: Simulate a lost MOVE response that left two copies and require manual-safe pending state.
    # ==========================================
    def test_ambiguous_two_copies_are_never_replayed(self):
        source=self.store.state(self.identity);self.service.move_message(self.identity,special='archive')
        self.provider.boxes['Archive']['1001']=dict(self.provider.boxes['INBOX'][source['uid']])
        with self.store.db() as db:db.execute("UPDATE pending_moves SET state='uncertain',attempted_destination='Archive'")
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        self.assertTrue(self.moves()[0]['error']);self.assertFalse(any(cmd[0] in ('MOVE','STORE','EXPUNGE') for cmd in self.provider.commands))
        self.assertIn(source['uid'],self.provider.boxes['INBOX'])

    # ==========================================
    # Function: Receive unrelated destination mail while a previous move awaits recovery.
    # Method: Sync with a deferred ambiguous move and assert exact duplicate suppression only.
    # ==========================================
    def test_pending_move_does_not_block_destination_sync(self):
        import time
        source=self.store.state(self.identity);self.service.move_message(self.identity,special='archive')
        self.provider.boxes['Archive']['1001']=dict(self.provider.boxes['INBOX'][source['uid']])
        raw=b'From: other@example.invalid\r\nMessage-ID: <new-destination>\r\nSubject: New destination mail\r\n\r\nnew'
        self.provider.boxes['Archive']['1002']={'raw':raw,'flags':set()}
        with self.store.db() as db:db.execute("UPDATE pending_moves SET state='uncertain',attempted_destination='Archive',retry_at=?",(time.time()+600,))
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.sync()
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM messages').fetchone()[0],4)
            self.assertEqual(db.execute("SELECT count(*) FROM messages WHERE message_id='<new-destination>'").fetchone()[0],1)
        self.assertEqual(self.store.state(self.identity)['validity'],'pending')

    # ==========================================
    # Function: Notify only genuinely new unread inbox mail, independently of UID remapping.
    # Method: Move out/back, ingest a copied destination and then add new incoming mail through real notification filtering.
    # ==========================================
    def test_moves_and_copies_do_not_notify_as_new_mail(self):
        from types import SimpleNamespace
        from maildesk.desktop_organization import OrganizationUI
        notices=[];app=SimpleNamespace(service=self.service,known_messages=None,notify=lambda *args:notices.append(args),refresh=lambda:None)
        OrganizationUI.check_notifications(app)
        self.service.move_message(self.identity,special='archive')
        with patch('maildesk.transport.imap_connection',self.provider.connection):self.service.flush_mutations()
        OrganizationUI.check_notifications(app)
        self.store.ingest('test','INBOX','77','90',self.store.get(self.identity,raw=True)['raw'])
        OrganizationUI.check_notifications(app);self.assertFalse(notices)
        self.store.ingest('test','INBOX','77','91',b'From: new@example.invalid\r\nMessage-ID: <new-incoming>\r\nSubject: New\r\n\r\nnew')
        OrganizationUI.check_notifications(app);self.assertEqual(notices,[('收到新邮件','1 封新邮件已同步')])

    # ==========================================
    # Function: Keep an RFC All mailbox distinct from the user's actual archive destination.
    # Method: Require an advertised Archive or explicit mapping before turning completion into a move.
    # ==========================================
    def test_all_mail_requires_explicit_archive_mapping(self):
        with self.store.db() as db:
            db.execute("UPDATE folders SET present=0 WHERE account='test' AND special='archive'")
            db.execute("INSERT INTO folders(account,folder,validity,special) VALUES('test','All Mail','77','all')")
        identity=self.store.ingest('test','All Mail','77','1',self.store.get(self.identity,raw=True)['raw'])
        self.assertFalse(self.store.state(identity)['done']);self.assertEqual(self.store.special_folder('test','archive'),'')
        self.store.set_preference('folder_mapping',{'test':{'archive':'All Mail'}})
        self.service.move_message(self.identity,special='archive')
        self.assertTrue(self.store.state(self.identity)['done']);self.assertEqual(self.moves()[0]['destination'],'All Mail')

    # ==========================================
    # Function: Highlight archive state consistently even for mail archived in another client.
    # Method: Ingest a server archive source and compare compact, full, list and RFC-card projections.
    # ==========================================
    def test_remote_archive_has_consistent_done_state(self):
        identity=self.store.ingest('test','Archive','77','98',b'From: other@example.invalid\r\nMessage-ID: <remote-archive>\r\nSubject: Archived elsewhere\r\n\r\nbody')
        for row in (self.store.state(identity),self.store.get(identity),next(r for r in self.store.list_messages(view='done')['items'] if r['id']==identity),self.store.thread(identity)[0]):
            self.assertTrue(row['done']);self.assertTrue(row['archived'])

    # ==========================================
    # Function: Preserve durable move identities when folder metadata changes before a flush.
    # Method: Rename a pending destination, then hide it in LIST and retain the optimistic message.
    # ==========================================
    def test_pending_destination_tracks_rename_and_missing_list(self):
        self.service.move_message(self.identity,destination='Archive')
        self.store.rename_folder('test','Archive','Kept')
        self.assertEqual(self.moves()[0]['destination'],'Kept');self.assertEqual(self.store.state(self.identity)['folder'],'Kept')
        self.store.save_folders('test',[{'name':'INBOX','special':'inbox'}])
        self.assertFalse(self.store.state(self.identity)['remote_gone']);self.assertTrue(self.moves())
