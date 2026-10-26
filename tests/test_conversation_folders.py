"""Folder aggregation semantics across contact summaries, sources, settings persistence and read state."""
from pathlib import Path
from tempfile import TemporaryDirectory
from email.message import EmailMessage
from unittest import TestCase
from maildesk.store import Store
from maildesk.contact_conversations import ContactConversations
from maildesk.conversation_folders import save,load,inventory,normalized

# ==========================================
# Function: Verify folder choices with actual SQLite metadata and immutable RFC source copies.
# Method: Exercise public projections and read actions using isolated generated mail, without native or provider dependencies.
# ==========================================
class ConversationFolderTests(TestCase):
    # ==========================================
    # Function: Initialize two accounts with identically named folders and one cloud junk folder.
    # Method: Use Store's real folder inventory and contact core with one explicit own identity.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.path=Path(self.temp.name)/'mail.db';self.store=Store(self.path);self.core=ContactConversations(self.store,['self@example.com']);self.serial=0
        for account in ('one','two'):
            self.store.save_folders(account,[{'name':name,'special':special} for name,special in [('INBOX','inbox'),('Sent','sent'),('Archive','archive'),('Work/项目',''),('云端垃圾','spam'),('Trash','trash'),('Drafts','drafts')]])
    # ==========================================
    # Function: Release isolated SQLite files after each independent scope scenario.
    # Method: Store connections are context-owned and workers are not started by these tests.
    # ==========================================
    def tearDown(self):self.temp.cleanup()
    # ==========================================
    # Function: Insert a genuine source or a physical copy into an account/folder.
    # Method: Preserve raw bytes for dedup tests while giving each stored location a unique UID.
    # ==========================================
    def mail(self,folder='INBOX',account='one',raw=None):
        self.serial+=1
        if raw is None:
            message=EmailMessage();message['From']='Peer <peer@example.com>';message['To']='self@example.com';message['Subject']='Folder '+str(self.serial);message['Message-ID']='<folder-'+str(self.serial)+'@example.com>';message.set_content('Body '+str(self.serial));raw=message.as_bytes()
        return self.store.ingest(account,folder,'folder-tests',str(self.serial),raw)
    # ==========================================
    # Function: Select the fixture contact through the real bounded index and current folder policy.
    # Method: Return no contact when custom scope contains no matching sources.
    # ==========================================
    def contact(self):return next((item for item in self.core.list_conversations()['items'] if item['contact_address']=='peer@example.com'),None)
    # ==========================================
    # Function: Save an exact custom account/path selection through the production preference API.
    # Method: Preserve arbitrary Unicode and delimiter-containing names without pattern expansion.
    # ==========================================
    def choose(self,*pairs):save(self.store,{'mode':'custom','folders':[{'account':account,'folder':folder} for account,folder in pairs]})
    # ==========================================
    # Function: Preserve the040 default across regular, sent, cloud junk, trash and draft mail.
    # Method: Verify only the currently eligible physical source IDs are exposed by the timeline.
    # ==========================================
    def test_default_preserves_existing_scope(self):
        expected={self.mail(name) for name in ('INBOX','Sent','Archive','Work/项目')};self.mail('云端垃圾');self.mail('Trash');self.mail('Drafts');hidden=self.mail();self.store.organize(hidden,spam=True)
        row=self.contact();self.assertEqual(row['count'],4);self.assertEqual({item['id'] for item in self.core.conversation_messages(row['key'])['items']},expected)
    # ==========================================
    # Function: Isolate equal paths across accounts and match literal folder identity.
    # Method: Change choices on the same core instance and reopen Store to verify persistence/freshness.
    # ==========================================
    def test_exact_account_path_and_restart(self):
        first=self.mail('Work/项目','one');second=self.mail('Work/项目','two');self.mail('Archive');self.choose(('two','Work/项目'))
        row=self.contact();self.assertEqual(row['count'],1);self.assertEqual(row['accounts'],['two']);self.assertEqual([item['id'] for item in self.core.conversation_messages(row['key'])['items']],[second])
        reopened=Store(self.path);self.assertEqual(load(reopened),load(self.store));self.choose(('one','Work/项目'));self.assertEqual([item['id'] for item in self.core.conversation_messages(row['key'])['items']],[first])
    # ==========================================
    # Function: Allow explicitly chosen special folders while preserving local-hidden flags elsewhere.
    # Method: Include physical cloud junk/trash/drafts and exclude marked spam still residing in INBOX.
    # ==========================================
    def test_explicit_special_folder_selection(self):
        junk=self.mail('云端垃圾');trash=self.mail('Trash');draft=self.mail('Drafts');hidden=self.mail();self.store.organize(junk,spam=True);self.store.organize(trash,trashed=True);self.store.organize(hidden,spam=True)
        self.choose(('one','云端垃圾'),('one','Trash'),('one','Drafts'),('one','INBOX'));row=self.contact();items=self.core.conversation_messages(row['key'])['items'];self.assertEqual({item['id'] for item in items},{junk,trash,draft})
    # ==========================================
    # Function: Apply an intentionally empty selection without silently reverting to defaults.
    # Method: Restore the default explicitly and verify previously cached mail remains present.
    # ==========================================
    def test_empty_custom_and_default_restore(self):
        identity=self.mail();self.choose();self.assertIsNone(self.contact());self.assertEqual(load(self.store)['mode'],'custom');save(self.store,{'mode':'default'});self.assertIsNotNone(self.contact());self.assertTrue(self.store.get(identity))
    # ==========================================
    # Function: Keep source copies, account choices and mark-all-read within the selected aggregation scope.
    # Method: Store one MIME in two folders and require only selected physical copies to be read.
    # ==========================================
    def test_duplicates_and_read_actions_obey_selected_folders(self):
        first=self.mail();copy=self.mail('Archive',raw=self.store.get(first,raw=True)['raw']);self.choose(('one','INBOX'));row=self.contact();self.assertEqual(row['copies'],1);sources=self.core.unread_sources(row['key']);self.assertEqual({source['id'] for source in sources},{first});self.assertEqual(self.store.mark_contact_opened(sources,remote=False),1);self.assertFalse(self.store.get(copy)['seen'])
        self.choose(('one','Archive'));row=self.contact();self.assertEqual(row['unread_count'],1);self.assertEqual({source['id'] for source in self.core.unread_sources(row['key'])},{copy})
    # ==========================================
    # Function: Include discovered empty cloud folders, cache-only paths and unavailable saved choices in settings.
    # Method: Read the public inventory without moving or altering underlying messages.
    # ==========================================
    def test_inventory_and_removed_choice_preservation(self):
        self.mail('@sent');self.choose(('missing','Past folder'));items=inventory(self.store);lookup={(item['account'],item['folder']):item for item in items};self.assertEqual(lookup[('one','Work/项目')]['cached'],0);self.assertIn(('one','@sent'),lookup);self.assertEqual(lookup[('missing','Past folder')]['present'],0)
    # ==========================================
    # Function: Treat folder names as literal bound data and keep a selected folder's special mapping live.
    # Method: Exercise quotes/SQL text in a path and later change default special-use classification without reindexing.
    # ==========================================
    def test_literal_names_and_live_folder_metadata(self):
        name="Projects' OR 1=1 --";identity=self.mail(name);self.mail();self.choose(('one',name));row=self.contact();self.assertEqual([item['id'] for item in self.core.conversation_messages(row['key'])['items']],[identity]);self.assertEqual(normalized({'mode':'custom','folders':[{'account':'one','folder':name}]*2})['folders'],[{'account':'one','folder':name}])
        save(self.store,{'mode':'default'});self.assertEqual(self.contact()['count'],2)
        with self.store.db() as db:db.execute("INSERT INTO folders(account,folder,validity,special) VALUES('one',?,'folder-tests','spam')",(name,))
        self.assertEqual(self.contact()['count'],1)

    # ==========================================
    # Function: Include an explicitly chosen user-mapped junk folder even when server special-use metadata is absent.
    # Method: Persist the existing folder mapping and verify default/custom behavior with marked spam sources.
    # ==========================================
    def test_user_mapped_special_folder(self):
        identity=self.mail('Work/项目');self.store.set_preference('folder_mapping',{'one':{'spam':'Work/项目'}});self.store.organize(identity,spam=True);self.assertIsNone(self.contact());self.choose(('one','Work/项目'));row=self.contact();self.assertIsNotNone(row);self.assertEqual([item['id'] for item in self.core.conversation_messages(row['key'])['items']],[identity]);self.assertEqual(next(row for row in inventory(self.store) if row['account']=='one' and row['folder']=='Work/项目')['special'],'spam')

    # ==========================================
    # Function: Keep a large explicit folder scope below SQLite expression-tree limits.
    # Method: Select one real folder alongside1100 unavailable paths and execute the actual contact/copy/read projections.
    # ==========================================
    def test_large_selection_uses_bounded_expression_depth(self):
        identity=self.mail();pairs=[('one','INBOX')]+[('one','Folder'+str(index)) for index in range(1100)];self.choose(*pairs);row=self.contact();self.assertEqual(row['count'],1);self.assertEqual({item['id'] for item in self.core.unread_sources(row['key'])},{identity})
