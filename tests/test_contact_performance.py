"""Foreground contact performance contracts with real SQLite and isolated cached mail."""
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import json
from maildesk.store import Store
from maildesk.contact_conversations import ContactConversations
from maildesk.desktop_loading import LocalLoader

# ==========================================
# Function: Preserve foreground responsiveness while retaining complete cached-mail behavior.
# Method: Test lock independence, upgrade completeness, index maintenance and worker isolation through public operations.
# ==========================================
class ContactPerformanceTests(TestCase):
    # ==========================================
    # Function: Create a disposable real cache with no network or credentials.
    # Method: Own only SQLite metadata and generated RFC fixtures.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.store=Store(Path(self.temp.name)/'mail.sqlite3');self.core=ContactConversations(self.store,['self@example.com']);self.serial=0
    # ==========================================
    # Function: Remove the isolated cache after worker and connection scopes close.
    # Method: Let Store's per-operation contexts release handles before temporary cleanup.
    # ==========================================
    def tearDown(self):self.temp.cleanup()
    # ==========================================
    # Function: Ingest one genuine incoming or own-sent source for contact discovery.
    # Method: Exercise production MIME parsing and Store ingestion with unique source identities.
    # ==========================================
    def mail(self,sender='Alice <alice@example.com>',to='self@example.com'):
        self.serial+=1;m=EmailMessage();m['From']=sender;m['To']=to;m['Message-ID']='<perf'+str(self.serial)+'@example.com>';m['Subject']='Performance '+str(self.serial);m.set_content('Plain body '+str(self.serial))
        return self.store.ingest('one','INBOX','perf',str(self.serial),m.as_bytes())
    # ==========================================
    # Function: Keep a selected conversation readable during another worker's global index batch.
    # Method: Hold the index lock, forbid global count scans and require the real foreground query to finish.
    # ==========================================
    def test_foreground_read_does_not_wait_for_index_lock_or_status(self):
        identity=self.mail();key=self.core.list_conversations()['items'][0]['key']
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.core._index_lock,patch.object(self.core,'_status',side_effect=AssertionError('global count on foreground')):
                result=pool.submit(self.core.conversation_messages,key,backfill_limit=0,verification_limit=0).result(timeout=2)
        self.assertEqual([item['id'] for item in result['items']],[identity]);self.assertEqual(result['indexing']['processed'],0)
        from maildesk.desktop_chat import ContactChatUI
        app=SimpleNamespace(chat_due=123.0);ContactChatUI.contact_progress(app,result['indexing']);self.assertEqual(app.chat_due,123.0)
    # ==========================================
    # Function: Upgrade an existing v038 projection without losing contacts during partial metadata batches.
    # Method: Remove only the new materialization, read through fallback, fill bounded batches and verify indexed query planning.
    # ==========================================
    def test_legacy_membership_upgrade_is_bounded_and_complete(self):
        identities=[self.mail() for _ in range(9)];key=self.core.list_conversations()['items'][0]['key'];scope=self.core.scope
        with self.store.db() as db:
            db.execute('DELETE FROM contact_member_index');db.execute('DELETE FROM contact_member_scopes')
        reopened=ContactConversations(self.store,['self@example.com']);reopened.initialize()
        self.assertEqual(reopened.fill_members(3),3);self.assertFalse(reopened._members_complete)
        self.assertEqual(len(reopened.conversation_messages(key,backfill_limit=0,verification_limit=0)['items']),9)
        self.assertEqual(reopened.fill_members(3),3);self.assertEqual(reopened.fill_members(3),3);self.assertTrue(reopened._members_complete);self.assertEqual(scope,reopened.scope)
        self.assertEqual({item['id'] for item in reopened.conversation_messages(key,backfill_limit=0,verification_limit=0)['items']},set(identities))
        ctes,values=reopened._ctes('',key)
        with self.store.db() as db:plan='\n'.join(row['detail'] for row in db.execute('EXPLAIN QUERY PLAN '+ctes+' SELECT * FROM unique_mail',values))
        self.assertIn('contact_member_key',plan);self.assertNotIn('SCAN cm VIRTUAL TABLE',plan)
    # ==========================================
    # Function: Mark relevant unindexed mail read without filling any unrelated contact envelopes.
    # Method: Include older inbound mail, an invalid sender and own-sent recipient mail.
    # ==========================================
    def test_read_all_does_not_build_unrelated_contacts(self):
        first=self.mail();key=self.core.list_conversations()['items'][0]['key'];older=self.mail();invalid=self.mail('Alice <alice@example.com.>');sent=self.mail('Self <self@example.com>','alice@example.com');other=self.mail('Bob <bob@example.com>')
        with self.store.db() as db:before=db.execute('SELECT count(*) FROM contact_envelopes').fetchone()[0]
        sources=self.core.unread_sources(key);self.assertEqual({source['id'] for source in sources},{first,older,sent});self.assertEqual(self.store.mark_contact_opened(sources,remote=False),3)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM contact_envelopes').fetchone()[0],before)
        self.assertFalse(self.store.get(other)['seen']);self.assertFalse(self.store.get(invalid)['seen'])
    # ==========================================
    # Function: Preserve raw-key recipient read actions while a legacy multi-recipient index is still upgrading.
    # Method: Resolve a contact present only on own-sent multi-recipient mail without forcing index completion.
    # ==========================================
    def test_partial_upgrade_keeps_multi_recipient_read_complete(self):
        first=self.mail('Self <self@example.com>','Alice <alice@example.com>, Bob <bob@example.com>');row=next(item for item in self.core.list_conversations()['items'] if item['contact_address']=='alice@example.com')
        with self.store.db() as db:db.execute('DELETE FROM contact_member_index');db.execute('DELETE FROM contact_member_scopes')
        second=self.mail('Self <self@example.com>','Alice <alice@example.com>, Carol <carol@example.com>');other=self.mail('Self <self@example.com>','bob@example.com');core=ContactConversations(self.store,['self@example.com'])
        self.assertEqual({source['id'] for source in core.unread_sources(row['key'])},{first,second});self.assertFalse(core._members_complete);self.assertFalse(self.store.get(other)['seen'])

    # ==========================================
    # Function: Keep fully indexed membership current when compact source envelopes change or disappear.
    # Method: Exercise real envelope update/delete triggers and subsequent projection visibility.
    # ==========================================
    def test_membership_tracks_update_delete_and_new_sources(self):
        first=self.mail();key=self.core.list_conversations()['items'][0]['key'];second=self.mail();self.core.backfill()
        with self.store.db() as db:
            row=db.execute('SELECT envelope FROM contact_envelopes WHERE message=?',(first,)).fetchone();envelope=json.loads(row[0]);envelope['contacts'][0]['name']='Updated'
            db.execute('UPDATE contact_envelopes SET envelope=? WHERE message=?',(json.dumps(envelope),first))
            self.assertEqual(json.loads(db.execute('SELECT value FROM contact_member_index WHERE message=?',(first,)).fetchone()[0])['name'],'Updated')
            db.execute('DELETE FROM contact_envelopes WHERE message=?',(first,));self.assertIsNone(db.execute('SELECT 1 FROM contact_member_index WHERE message=?',(first,)).fetchone())
        result=self.core.conversation_messages(key,backfill_limit=0,verification_limit=0);self.assertEqual([item['id'] for item in result['items']],[second])
    # ==========================================
    # Function: Let navigation and read actions complete while both background workers are occupied.
    # Method: Block migration lanes with events and observe a real foreground action's completion queue.
    # ==========================================
    def test_user_action_has_independent_worker_capacity(self):
        app=SimpleNamespace(queue=Queue(),closing=False);loader=LocalLoader(app);started=[Event(),Event()];release=Event();results=[]
        # ==========================================
        # Function: Simulate an unrelated bounded migration that currently occupies a background lane.
        # Method: Use deterministic events and always release both workers before shutdown.
        # ==========================================
        def occupy(index):started[index].set();release.wait(3)
        try:
            for index in range(2):loader.executor.submit(occupy,index)
            self.assertTrue(all(event.wait(1) for event in started));loader.action(lambda:42,results.append,lambda error:results.append(error));callback,value=app.queue.get(timeout=1);callback(value);self.assertEqual(results,[42])
        finally:release.set();loader.close()
