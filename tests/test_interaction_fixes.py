"""Offline read intents and conservative unsent-draft lifecycle regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from maildesk.config import Account
from maildesk.draft_content import has_draft_content
from maildesk.mime import compose
from maildesk.service import MailService

# ==========================================
# Function: Protect authored content while automatically removing empty editor artifacts.
# Method: Exercise full durable draft records and explicitly generated reply/signature baselines.
# ==========================================
class DraftContentTests(unittest.TestCase):
    # ==========================================
    # Function: Keep intentionally addressed, titled, attached and rich-media-only drafts.
    # Method: Verify independent meaningful-content cases instead of checking implementation fields.
    # ==========================================
    def test_meaningful_content_survives(self):
        for draft in [{'to':'friend@example.com'},{'subject':'仅主题'},{'body':'mailto 提供的正文'},
                      {'attachments':[{'name':'file.txt'}]},{'html':'<p>HTML 正文</p>'},{'html':'<img src="cid:photo">'}]:
            with self.subTest(draft=draft):self.assertTrue(has_draft_content(draft))

    # ==========================================
    # Function: Avoid empty reply or signature-only orphan drafts.
    # Method: Ignore only untouched generated fields and retain a changed reply or authored suffix.
    # ==========================================
    def test_generated_reply_fields_are_not_authored_content(self):
        baseline={'to':'friend@example.com','subject':'Re: 测试','body':'\n\n> 历史引用\n\n-- \n签名'}
        draft={**baseline,'editor_baseline':baseline}
        self.assertFalse(has_draft_content(draft))
        self.assertTrue(has_draft_content({**draft,'body':'我的回复'+baseline['body']}))
        self.assertTrue(has_draft_content({**draft,'subject':'Re: 新主题'}))
        self.assertFalse(has_draft_content({'body':'\n\n-- \n签名','editor_baseline':{'body':'\n\n-- \n签名'}}))

    # ==========================================
    # Function: Delete cleared saved drafts without deleting queued or sent records.
    # Method: Use actual compare-and-delete storage and reopen it to check durability.
    # ==========================================
    def test_pruning_is_empty_and_draft_state_only(self):
        with tempfile.TemporaryDirectory() as directory:
            service=MailService(directory,demo=True);store=service.store
            blank=store.save_draft('demo',{'body':'  '})
            titled=store.save_draft('demo',{'subject':'保留'})
            attached=store.save_draft('demo',{'attachments':[{'name':'data'}]})
            generated=store.save_draft('demo',{'to':'a@example.com','editor_baseline':{'to':'a@example.com'}})
            queued=store.save_draft('demo',{})
            store.enqueue(queued,b'raw',['a@example.com'],'<queued@example.com>',0)
            self.assertEqual(set(store.prune_empty_drafts()),{blank,generated})
            for identity in (titled,attached,queued):self.assertEqual(store.job(identity)['id'],identity)
            with self.assertRaises(ValueError):store.delete_draft(queued)
            store.save_draft('demo',{},titled);self.assertEqual(store.prune_empty_drafts(),[titled])
            service.close();reopened=MailService(directory,demo=True)
            with self.assertRaises(KeyError):reopened.store.job(titled)
            self.assertEqual(reopened.store.job(queued)['state'],'queued');reopened.close()

    # ==========================================
    # Function: Persist provenance and safely resume replies from their exact source mail.
    # Method: Round-trip metadata through the normal compose service and source-scoped lookup.
    # ==========================================
    def test_reply_baseline_round_trip_and_scoped_lookup(self):
        with tempfile.TemporaryDirectory() as directory:
            service=MailService(directory,demo=True)
            result=service.compose({'account':'demo','to':'a@example.com','subject':'Re: 保留','body':'我的正文','reply_source':'origin',
                'editor_baseline':{'to':'a@example.com','subject':'Re: 保留','body':''}})
            self.assertTrue(has_draft_content(service.store.job(result['id'])['draft']))
            self.assertEqual([row['id'] for row in service.store.reply_drafts(['origin'])],[result['id']])
            self.assertEqual(service.store.reply_drafts(['other']),[])
            with self.assertRaises(ValueError):service.compose({'account':'demo','editor_baseline':{'unexpected':'bad'}})
            service.close()

# ==========================================
# Function: Persist local read state before provider responses and retry exact safe remote flags.
# Method: Use a real SQLite cache with synthetic MIME and mocked provider boundaries only.
# ==========================================
class AutomaticReadTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare a provider-shaped isolated message without connecting to a mailbox.
    # Method: Cache a stable UID identity and supply a fake account configuration.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.account=Account('test','me@example.com','imap.example.com','smtp.example.com')
        self.service=MailService(Path(self.temp.name),[self.account]);self.store=self.service.store
        message,_=compose('friend@example.com',{'to':'me@example.com','subject':'读取测试','body':'缓存正文'},'<read-test@example.com>')
        self.raw=message.as_bytes();self.identity=self.store.ingest('test','INBOX','42','7',self.raw)

    # ==========================================
    # Function: Release only the isolated service used by this test.
    # Method: No background worker or real account secret is started.
    # ==========================================
    def tearDown(self):
        self.service.close();self.temp.cleanup()

    # ==========================================
    # Function: Mark opened mail locally even when a provider cannot respond.
    # Method: Assert durable cache state first, preserve it across stale server snapshots, then retry.
    # ==========================================
    def test_offline_open_persists_and_retries(self):
        self.assertTrue(self.service.mark_opened(self.identity));self.assertTrue(self.store.get(self.identity)['seen'])
        with patch('maildesk.transport.set_seen',side_effect=OSError('offline')) as remote:
            self.assertEqual(self.service.flush_read_flags(),1);remote.assert_called_once()
        self.store.reconcile('test','INBOX','42',{'7'},{'7':False})
        self.store.ingest('test','INBOX','42','7',self.raw,seen=False)
        self.assertTrue(self.store.get(self.identity)['seen'])
        with patch('maildesk.transport.set_seen') as remote:
            self.assertEqual(self.service.flush_read_flags(),0)
            self.assertEqual(remote.call_args.args[1]['uid'],'7');self.assertTrue(remote.call_args.args[2])
        self.assertEqual(self.store.pending_read_flags(),[])
        self.store.reconcile('test','INBOX','42',{'7'},{'7':False})
        self.assertFalse(self.store.get(self.identity)['seen'])

    # ==========================================
    # Function: Retain pending read intent across restarting the local application.
    # Method: Reopen the same database and confirm provider retries are not memory-only.
    # ==========================================
    def test_pending_read_intent_survives_restart(self):
        self.service.mark_opened(self.identity);self.service.close()
        self.service=MailService(Path(self.temp.name),[self.account]);self.store=self.service.store
        self.assertTrue(self.store.get(self.identity)['seen']);self.assertEqual(len(self.store.pending_read_flags()),1)

    # ==========================================
    # Function: Honor a later manual unread command instead of replaying an older automatic read.
    # Method: Commit a successful explicit provider update and verify the pending intent is removed.
    # ==========================================
    def test_explicit_unread_supersedes_pending_read(self):
        self.service.mark_opened(self.identity)
        with patch('maildesk.transport.set_seen') as remote:self.service.update(self.identity,{'seen':False})
        self.assertFalse(self.store.get(self.identity)['seen']);self.assertEqual(self.store.pending_read_flags(),[])
        self.assertFalse(remote.call_args.args[2])

    # ==========================================
    # Function: Never send a cached flag to a disappeared UID or removed account.
    # Method: Preserve the local intent for inspection while avoiding all provider calls.
    # ==========================================
    def test_remote_identity_boundaries(self):
        self.service.mark_opened(self.identity)
        self.store.reconcile('test','INBOX','42',set(),{})
        with patch('maildesk.transport.set_seen') as remote:self.assertEqual(self.service.flush_read_flags(),1)
        remote.assert_not_called();self.assertTrue(self.store.get(self.identity)['seen'])
        self.store.reconcile('test','INBOX','42',{'7'},{})
        self.service.accounts={}
        with patch('maildesk.transport.set_seen') as remote:self.assertEqual(self.service.flush_read_flags(),1)
        remote.assert_not_called()

    # ==========================================
    # Function: Avoid duplicate read intents and stale-generation acknowledgements.
    # Method: Reopen only unread mail and compare explicit persisted generation tokens.
    # ==========================================
    def test_idempotence_and_acknowledgement_generation(self):
        self.service.mark_opened(self.identity);intent=self.store.pending_read_flags()[0]
        self.assertFalse(self.service.mark_opened(self.identity))
        self.store.acknowledge_read(self.identity,'not-the-generation')
        self.assertEqual(self.store.pending_read_flags()[0]['generation'],intent['generation'])

    # ==========================================
    # Function: Keep account-free local reading entirely offline.
    # Method: Import real synthetic EML and forbid provider flag adapters.
    # ==========================================
    def test_local_import_does_not_queue_remote_read(self):
        path=Path(self.temp.name)/'local.eml';path.write_bytes(self.raw)
        identity=self.service.import_eml(path)
        with patch('maildesk.transport.set_seen') as remote:
            self.assertTrue(self.service.mark_opened(identity));self.assertEqual(self.service.flush_read_flags(),0)
        remote.assert_not_called();self.assertTrue(self.store.get(identity)['seen'])

if __name__=='__main__':unittest.main()
