"""Contact-policy, directional discovery and complete offline read-state regressions."""
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
import time
from maildesk.service import MailService
from maildesk.contact_conversations import ContactConversations
from maildesk import address_book
from maildesk.contact_policies import save_many,get,quiet_addresses
from maildesk.desktop_organization import OrganizationUI

# ==========================================
# Function: Exercise persisted contact behavior using isolated real SQLite and synthetic RFC messages.
# Method: Verify visible projections and notification outcomes rather than duplicating query implementation.
# ==========================================
class ContactPreferencesTests(TestCase):
    # ==========================================
    # Function: Create two own identities with no network or provider credentials.
    # Method: Use the real demo service, account-aware Store and current projection.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.service=MailService(Path(self.temp.name),demo=True);self.store=self.service.store
        self.service.accounts={'one':SimpleNamespace(id='one',email='self@example.com'),'two':SimpleNamespace(id='two',email='other.self@example.com')}
        self.core=ContactConversations(self.store,self.service.accounts.values(),extra_own=('demo@example.com',));self.serial=0
    # ==========================================
    # Function: Close all owned local service state after each independent scenario.
    # Method: Reuse the production service shutdown contract before removing temporary files.
    # ==========================================
    def tearDown(self):
        self.service.close();self.temp.cleanup()
    # ==========================================
    # Function: Ingest stable incoming or outgoing fixture mail with exact participant headers.
    # Method: Generate complete MIME with deterministic dates and no provider access.
    # ==========================================
    def mail(self,sender='Alice <alice@example.com>',to='Self <self@example.com>',cc='',bcc='',account='one',folder='INBOX',seen=False):
        self.serial+=1;m=EmailMessage();m['From']=sender;m['To']=to;m['Subject']='Message '+str(self.serial);m['Message-ID']='<fixture'+str(self.serial)+'@example.com>';m['Date']=datetime(2026,10,23,tzinfo=timezone.utc)+timedelta(seconds=self.serial)
        if cc:m['Cc']=cc
        if bcc:m['Bcc']=bcc
        m.set_content('Body '+str(self.serial));return self.store.ingest(account,folder,'fixture',str(self.serial),m.as_bytes(),seen=seen)
    # ==========================================
    # Function: Read current contact rows keyed by stable external mailbox.
    # Method: Ask the real projection to process the fixture's complete bounded metadata set.
    # ==========================================
    def contacts(self):return {item['contact_address']:item for item in self.core.list_conversations(limit=200)['items']}
    # ==========================================
    # Function: Require inbound senders and every own-sent recipient in the directory and list.
    # Method: Include To/Cc/Bcc, multiple own aliases and unrelated incoming recipients.
    # ==========================================
    def test_bidirectional_discovery_and_outgoing_avatar_identity(self):
        self.mail(to='self@example.com, Unrelated <incoming.to@example.com>',cc='incoming.cc@example.com',bcc='incoming.hidden@example.com')
        sent=self.mail('Self <other.self@example.com>','Alice <alice@example.com>, Bob <bob@example.com>','Carol <carol@example.com>','Dave <dave@example.com>',account='two',folder='@sent',seen=True)
        rows=self.contacts();self.assertEqual(set(rows),{'alice@example.com','bob@example.com','carol@example.com','dave@example.com'})
        directory={address for item in address_book.page(self.store,limit=120)['items'] for address in item['addresses']};self.assertEqual(directory,set(rows))
        alice=rows['alice@example.com'];self.assertEqual(alice['latest_id'],sent);self.assertEqual(alice['latest_author'],'我');self.assertEqual(alice['contact_name'],'Alice');self.assertEqual(alice['peers'],[{'address':'alice@example.com','name':'Alice'}]);self.assertFalse(alice['route']['safe'])
        self.assertTrue(all(row['kind']=='direct' and row['person_id'] for row in rows.values()))
    # ==========================================
    # Function: Reject ambiguous From identities before any sender or recipient is auto-recorded.
    # Method: Supply multiple RFC From mailboxes and verify unrelated recipients never become contacts.
    # ==========================================
    def test_ambiguous_sender_does_not_promote_recipients(self):
        self.mail('Self <self@example.com>, Other <forged@example.com>','Target <target@example.com>',cc='other.target@example.com')
        self.assertEqual(address_book.page(self.store)['items'],[])
        self.assertTrue(all(not item['person_id'] and not item['contact_address'] for item in self.core.list_conversations()['items']))

    # ==========================================
    # Function: Verify saved policies survive refresh/restart and apply to every merged alias.
    # Method: Exercise SQL pin ordering/block filtering without changing underlying read flags.
    # ==========================================
    def test_policies_pinning_blocking_aliases_and_restart(self):
        first=self.mail();self.mail('Bob <bob@example.com>');rows=self.contacts();alice=rows['alice@example.com'];person=alice['person_id']
        address_book.save(self.store,person,'Alice',['alice@example.com','alice.work@example.com']);self.mail('Alice <alice.work@example.com>');self.mail('Self <self@example.com>','Alice <alice@example.com>, Alice <alice.work@example.com>',folder='@sent',seen=True)
        save_many(self.store,{person:{'muted':True,'pinned':True,'blocked':False}});items=self.core.list_conversations()['items'];self.assertEqual(items[0]['person_id'],person);self.assertTrue(items[0]['muted']);self.assertEqual(items[0]['count'],3);self.assertEqual(items[0]['copies'],3);self.assertEqual(len(items[0]['copy_ids']),1);self.assertFalse(self.store.get(first)['seen'])
        with self.store.db() as db:self.assertEqual(quiet_addresses(db),{'alice@example.com','alice.work@example.com'})
        self.assertEqual(address_book.sender_detail(self.store,person=person)['muted'],1)
        save_many(self.store,{person:{'muted':True,'pinned':True,'blocked':True}});self.assertNotIn(person,[row['person_id'] for row in self.core.list_conversations()['items']]);self.assertTrue(any(item['id']==person for item in address_book.page(self.store)['items']))
        self.service.close();self.service=MailService(Path(self.temp.name),demo=True);self.store=self.service.store;self.assertTrue(get(self.store,person)['blocked'])
        save_many(self.store,{person:{'muted':False,'pinned':True,'blocked':False}});self.core=ContactConversations(self.store,['self@example.com','other.self@example.com'],extra_own=('demo@example.com',));self.assertEqual(self.core.list_conversations()['items'][0]['person_id'],person)
    # ==========================================
    # Function: Mark the complete contact read beyond both current timeline and index batch limits.
    # Method: Include multiple remote account copies, local copies and unrelated unread mail.
    # ==========================================
    def test_contact_read_all_copies_including_unindexed_older_messages(self):
        ids=[self.mail(account='one' if i%2 else 'two') for i in range(285)];ids.append(self.store.ingest('two','Archive','copy','same',self.store.get(ids[0],raw=True)['raw'],seen=False));local=self.mail(folder='@local-cache');other=self.mail('Bob <bob@example.com>')
        result=self.core.list_conversations(backfill_limit=16);self.assertTrue(result['indexing']['incomplete']);row=next(item for item in result['items'] if item['contact_address']=='alice@example.com')
        sources=self.core.unread_sources(row['key']);self.assertEqual({source['id'] for source in sources},set(ids+[local]));self.assertEqual(self.store.mark_contact_opened(sources,remote=True),287)
        self.assertTrue(all(self.store.get(identity)['seen'] for identity in ids+[local]));self.assertFalse(self.store.get(other)['seen']);self.assertEqual({row['message'] for row in self.store.pending_read_flags()},set(ids));self.assertEqual(self.store.mark_contact_opened(sources,remote=True),0)
    # ==========================================
    # Function: Preserve policy semantics through explicit person merge and mailbox split.
    # Method: Retain conservative flags without deleting any original messages.
    # ==========================================
    def test_merge_split_preserve_policy_and_sources(self):
        first=self.mail();second=self.mail('Bob <bob@example.com>');rows=self.contacts();a,b=rows['alice@example.com']['person_id'],rows['bob@example.com']['person_id']
        save_many(self.store,{a:{'muted':True,'pinned':False,'blocked':False},b:{'muted':False,'pinned':True,'blocked':True}});address_book.merge(self.store,a,b);self.assertEqual(get(self.store,a),{'muted':True,'pinned':True,'blocked':True})
        split=address_book.split(self.store,a,'bob@example.com');self.assertEqual(get(self.store,split),get(self.store,a));self.assertTrue(self.store.get(first));self.assertTrue(self.store.get(second))
    # ==========================================
    # Function: Silence muted and blocked aliases in all mail-related notification paths.
    # Method: Capture observable notice calls for new mail, receipts and due reminders, including later unmute.
    # ==========================================
    def test_notifications_new_mail_reminders_and_receipts_respect_policies(self):
        self.mail();self.mail('Bob <bob@example.com>');rows=self.contacts();a,b=rows['alice@example.com']['person_id'],rows['bob@example.com']['person_id'];address_book.save(self.store,a,'Alice',['alice@example.com','alice.work@example.com'])
        save_many(self.store,{a:{'muted':True,'pinned':False,'blocked':False},b:{'muted':False,'pinned':False,'blocked':True}})
        with self.store.db() as db:known={row[0] for row in db.execute('SELECT id FROM messages')}
        muted=self.mail('Alice <alice.work@example.com>');blocked=self.mail('Bob <bob@example.com>');normal=self.mail('Carol <carol@example.com>');self.store.organize(muted,reminder=time.time()-5)
        own_muted=self.mail('Self <self@example.com>','Alice <alice@example.com>',folder='@sent',seen=True);self.store.organize(own_muted,reminder=time.time()-4)
        self.mail('Self <self@example.com>','',bcc='Alice <alice.work@example.com>',folder='@sent',seen=True)
        self.store.save_draft('one',{'body':'Receipt fixture','to':'alice.work@example.com'},'fixturejob')
        with self.store.db() as db:db.execute('INSERT INTO read_receipts VALUES(?,?,?,?)',('fixturejob','alice.work@example.com',time.time(),muted))
        notices=[];app=SimpleNamespace(service=self.service,known_messages=known,notify=lambda title,text:notices.append((title,text)),refresh=lambda:None)
        OrganizationUI.check_notifications(app);self.assertEqual(len(notices),1);self.assertEqual(notices[0],('收到新邮件','1 封新邮件已同步'))
        save_many(self.store,{a:{'muted':False,'pinned':False,'blocked':False}});OrganizationUI.check_notifications(app);self.assertEqual(len(notices),1)
        self.mail('Alice <alice.work@example.com>');OrganizationUI.check_notifications(app);self.assertEqual(len(notices),2)
    # ==========================================
    # Function: Revisit legacy cache when the configured own-account set changes and later returns.
    # Method: Exercise scoped directory migration without altering old raw mail or drafts.
    # ==========================================
    def test_old_cache_discovery_tracks_own_account_changes(self):
        source=self.mail('External self <third.self@example.com>','Only Sent <sent.only@example.com>',folder='Sent')
        with self.store.db() as db:raw=db.execute('SELECT raw FROM messages WHERE id=?',(source,)).fetchone()[0]
        address_book.backfill(self.store);self.assertFalse(any('sent.only@example.com' in item['addresses'] for item in address_book.page(self.store)['items']))
        self.service.accounts['third']=SimpleNamespace(id='third',email='third.self@example.com');address_book.backfill(self.store);self.assertTrue(any('sent.only@example.com' in item['addresses'] for item in address_book.page(self.store)['items']))
        self.service.accounts.pop('third');address_book.backfill(self.store);self.service.accounts['third']=SimpleNamespace(id='third',email='third.self@example.com');self.assertTrue(address_book.backfill(self.store)['complete']);
        with self.store.db() as db:self.assertEqual(db.execute('SELECT raw FROM messages WHERE id=?',(source,)).fetchone()[0],raw)
