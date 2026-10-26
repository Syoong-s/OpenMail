"""Offline regression coverage for retention, contact stars and verified cache pruning."""
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import hashlib
import unittest
from unittest.mock import patch

from maildesk import address_book,cache_maintenance,mail_retention,transport
from maildesk.contact_policies import get as policies,save_many
from maildesk.service import MailService
from maildesk.store import Store

# ==========================================
# Function: Provide deterministic IMAP existence and move replies without any live provider.
# Method: Track selected mailbox generations, exact commands and physical source/destination UID membership.
# ==========================================
class MailboxFixture:
    # ==========================================
    # Function: Build two independent mailbox generations and optional remote-star state.
    # Method: Keep bytes-shaped protocol responses compatible with the production parsers.
    # ==========================================
    def __init__(self,starred=(),capabilities=(b'MOVE',b'UIDPLUS'),star_flag=b'\\Flagged'):
        self.star_flag=star_flag;self.capabilities=capabilities;self.selected='';self.commands=[];self.starred=set(starred);self.fail='';self.bad_search=False
        self.boxes={'INBOX':('7',{'1','2','3','4','5'}),'Deleted Items':('9',set())}
        self.last_copy=None
    # ==========================================
    # Function: Advertise authoritative inbox and account-specific trash folders.
    # Method: Return LIST rows with special-use flags, skipping optional STATUS/LSUB metadata.
    # ==========================================
    def list(self,*unused):
        return 'OK',[b'(\\Inbox) "/" "INBOX"',b'(\\Trash) "/" "Deleted Items"']
    # ==========================================
    # Function: Select a real fixture mailbox and expose only its own UID generation.
    # Method: Reject a configured failure before a caller may accept complete account evidence.
    # ==========================================
    def select(self,folder,readonly=False):
        self.selected=folder.strip('"');self.commands.append(('select',self.selected,readonly))
        return ('NO',[b'failure']) if self.selected==self.fail else ('OK',[b'0'])
    # ==========================================
    # Function: Return exact UIDVALIDITY or COPYUID confirmation after a transfer.
    # Method: Reset COPYUID after consumption so later messages cannot borrow earlier evidence.
    # ==========================================
    def response(self,code):
        if code=='UIDVALIDITY':return code,[self.boxes[self.selected][0].encode()]
        value=self.last_copy;self.last_copy=None;return code,[value] if value else [None]
    # ==========================================
    # Function: Model the UID commands relevant to cleanup and safe retention.
    # Method: SEARCH returns full membership, FLAGS reports current stars, MOVE/COPY assigns fresh target UIDs.
    # ==========================================
    def uid(self,command,*args):
        self.commands.append((command,*args))
        if command=='SEARCH':return 'OK',[None] if self.bad_search else [b' '.join(uid.encode() for uid in sorted(self.boxes[self.selected][1]))]
        if command=='FETCH':
            rows=[]
            for uid in args[0].split(','):
                if uid not in self.boxes[self.selected][1]:continue
                flags=self.star_flag if uid in self.starred else b''
                rows.append(b'1 (UID '+uid.encode()+b' FLAGS ('+flags+b'))')
            return 'OK',rows or [None]
        if command in ('MOVE','COPY'):
            uid,destination=args;destination=destination.strip('"');validity,uids=self.boxes[destination];new=str(100+len(uids));uids.add(new)
            self.last_copy=f'{validity} {uid} {new}'.encode()
            if command=='MOVE':self.boxes[self.selected][1].remove(uid)
        if command=='EXPUNGE':self.boxes[self.selected][1].discard(args[0])
        return 'OK',[b'done']

# ==========================================
# Function: Verify public maintenance behavior on real temporary SQLite stores.
# Method: Use original MIME, independent accounts, durable state and deterministic IMAP boundary fixtures.
# ==========================================
class MaintenanceTests(unittest.TestCase):
    # ==========================================
    # Function: Isolate cache, mail and contacts from the user's actual profile.
    # Method: Construct the real service without starting its background worker.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name);self.service=MailService(self.root)
        self.store=self.service.store;self.store.cache_dir=self.root/'cache';self.serial=0
        self.account=SimpleNamespace(id='one',email='self@example.com',folders=['INBOX'])
        self.service.accounts={'one':self.account};self.now=datetime(2026,10,25,12,tzinfo=timezone.utc)
        self.store.save_folders('one',[{'name':'INBOX','special':'inbox'},{'name':'Deleted Items','special':'trash'},{'name':'Sent','special':'sent'}])
    # ==========================================
    # Function: Dispose every temporary database and fixture after each regression.
    # Method: Close the real service before removing owned directories.
    # ==========================================
    def tearDown(self):
        self.service.close();self.temp.cleanup()
    # ==========================================
    # Function: Cache independently identifiable MIME with controllable age and participant roles.
    # Method: Preserve real parsing and original metadata for contact and copy-existence assertions.
    # ==========================================
    def mail(self,age=0,folder='INBOX',account='one',validity='7',uid=None,sender='Alice <alice@example.com>',to='self@example.com',cc='',bcc=''):
        self.serial+=1;m=EmailMessage();m['From']=sender;m['To']=to;m['Subject']='fixture '+str(self.serial);m['Date']=self.now-timedelta(days=age);m['Message-ID']='<maintenance'+str(self.serial)+'@example.com>'
        if cc:m['Cc']=cc
        if bcc:m['Bcc']=bcc
        m.set_content('Cached body '+str(self.serial));return self.store.ingest(account,folder,validity,uid or str(self.serial),m.as_bytes())
    # ==========================================
    # Function: Require star priority in shared directory pages, searches, jumps and completion.
    # Method: Put a late alphabetic contact first and verify absolute offsets remain correct after restart.
    # ==========================================
    def test_star_sort_pagination_search_and_reopen(self):
        for person,name in [('a','Ada'),('b','Bob'),('z','Zoe'),('h','张三')]:address_book.save(self.store,person,name,[person+'@example.com'])
        address_book.star_many(self.store,['z','h'],True)
        page=address_book.page(self.store,limit=2);self.assertEqual([i['id'] for i in page['items']],['z','h']);self.assertEqual(page['letters'].count('★'),1)
        self.assertEqual([i['id'] for i in address_book.page(self.store,offset=2)['items']],['a','b'])
        jumped=address_book.page(self.store,letter='B',limit=3);self.assertEqual(jumped['jump_offset'],3);self.assertEqual(jumped['items'][jumped['jump_offset']-jumped['offset']]['id'],'b')
        self.assertEqual(address_book.page(self.store,'Zoe')['items'][0]['starred'],1)
        reopened=Store(self.store.path);self.assertEqual(address_book.sender_detail(reopened,person='z')['starred'],1)
        self.assertEqual({email for email,_ in address_book.suggestions(reopened,2)},{'z@example.com','h@example.com'})
        address_book.star_many(reopened,['z'],False);self.assertEqual(address_book.page(reopened)['items'][0]['id'],'h')
    # ==========================================
    # Function: Preserve existing pin/mute policies while carrying stars through alias edits, merge and split.
    # Method: Exercise public person transactions and reject partially invalid bulk changes atomically.
    # ==========================================
    def test_stars_independent_from_policies_and_membership(self):
        a=address_book.save(self.store,'a','A',['a@example.com']);b=address_book.save(self.store,'b','B',['b@example.com'])
        save_many(self.store,{a:{'muted':True,'pinned':True,'blocked':False}});address_book.star_many(self.store,[b])
        address_book.merge(self.store,a,b);self.assertTrue(address_book.sender_detail(self.store,person=a)['starred']);self.assertTrue(policies(self.store,a)['pinned'])
        other=address_book.split(self.store,a,'b@example.com');self.assertTrue(address_book.sender_detail(self.store,person=other)['starred'])
        address_book.save(self.store,a,'renamed',['a@example.com','alias@example.com']);self.assertTrue(address_book.sender_detail(self.store,person=a)['starred'])
        with self.assertRaises(ValueError):address_book.star_many(self.store,[a,'missing'],False)
        self.assertTrue(address_book.sender_detail(self.store,person=a)['starred'])
    # ==========================================
    # Function: Add stars to an existing pre-upgrade directory without losing contact policies or mail.
    # Method: Reopen a real store after removing only the new additive column to emulate version 0.44.
    # ==========================================
    def test_upgrade_existing_directory(self):
        person=address_book.save(self.store,'old','Existing',['old@example.com']);identity=self.mail()
        with self.store.db() as db:db.execute('ALTER TABLE address_people DROP COLUMN starred')
        reopened=Store(self.store.path);self.assertEqual(address_book.sender_detail(reopened,person=person)['starred'],0);self.assertEqual(reopened.get(identity)['sender'],'alice@example.com')
    # ==========================================
    # Function: Apply a strict elapsed-day boundary, including leap-year dates.
    # Method: Count the configured number of24-hour periods and keep mail exactly on the boundary.
    # ==========================================
    def test_day_cutoff(self):
        self.assertEqual(mail_retention.days_cutoff(365,self.now),datetime(2025,10,25,12,tzinfo=timezone.utc).timestamp())
        self.assertEqual(mail_retention.days_cutoff(365,datetime(2024,2,29,8,tzinfo=timezone.utc)),datetime(2023,3,1,8,tzinfo=timezone.utc).timestamp())
    # ==========================================
    # Function: Move only old unpinned inbox messages and make the mapped trash copy visible immediately.
    # Method: Include boundary-age, pinned, sent, other-account and local records in the same store.
    # ==========================================
    def test_retention_scope_and_idempotence(self):
        expired=self.mail(366,uid='1');boundary=self.mail(365,uid='2');pinned=self.mail(800,uid='3');sent=self.mail(800,folder='Sent',uid='4');other=self.mail(800,account='two',uid='5');local=self.mail(800,validity='local',uid='local')
        self.store.update(pinned,{'pinned':True});client=MailboxFixture()
        result=mail_retention.expire_inbox(self.account,self.store,client,now=self.now);self.assertEqual(result['moved'],1)
        self.assertTrue(self.store.get(expired)['remote_gone']);self.assertNotIn(expired,[i['id'] for i in self.store.list_messages()['items']])
        self.assertEqual(self.store.list_messages(view='trash')['total'],1)
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],0)
        for identity in (boundary,pinned,sent,other,local):self.assertFalse(self.store.get(identity)['remote_gone'])
        self.assertFalse(any(c[0]=='EXPUNGE' for c in client.commands))
    # ==========================================
    # Function: Protect a message newly starred remotely and stale UID generations before transfer.
    # Method: Check the final FLAGS reply and force generation mismatch on a separate retry.
    # ==========================================
    def test_retention_fresh_star_and_generation_guard(self):
        identity=self.mail(800,uid='1');client=MailboxFixture(starred=['1'])
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],0);self.assertTrue(self.store.get(identity)['pinned'])
        self.store.update(identity,{'pinned':False});client.boxes['INBOX']=('999',{'1'})
        with self.assertRaises(ValueError):mail_retention.expire_inbox(self.account,self.store,client,now=self.now)
        self.assertFalse(any(c[0] in ('MOVE','COPY') for c in client.commands));self.assertFalse(self.store.get(identity)['remote_gone'])
    # ==========================================
    # Function: Protect remotely starred messages when a provider changes system-flag letter casing.
    # Method: Return lowercase Flagged evidence for an old locally unpinned source and require no move.
    # ==========================================
    def test_retention_case_insensitive_remote_flag(self):
        identity=self.mail(800,uid='1');client=MailboxFixture(starred=['1'],star_flag=b'\\flagged')
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],0)
        self.assertTrue(self.store.get(identity)['pinned']);self.assertFalse(any(row[0] in ('MOVE','COPY') for row in client.commands))

    # ==========================================
    # Function: Keep the original inbox record when the provider cannot perform a safe move.
    # Method: Reject unsupported capabilities before COPY and protect missing-trash mappings.
    # ==========================================
    def test_retention_unsupported_server_and_missing_trash(self):
        identity=self.mail(800,uid='1');client=MailboxFixture(capabilities=())
        with self.assertRaises(ValueError):mail_retention.expire_inbox(self.account,self.store,client,now=self.now)
        self.assertFalse(self.store.get(identity)['remote_gone']);self.assertFalse(any(c[0]=='COPY' for c in client.commands))
        with self.store.db() as db:db.execute("UPDATE folders SET special='' WHERE special='trash'")
        self.assertIn('pending',mail_retention.expire_inbox(self.account,self.store,client,now=self.now))
    # ==========================================
    # Function: Verify providers without MOVE only expunge the exact source UID using UIDPLUS.
    # Method: Keep an unrelated inbox UID present through COPY/STORE/EXPUNGE fallback.
    # ==========================================
    def test_retention_uidplus_fallback(self):
        identity=self.mail(800,uid='1');client=MailboxFixture(capabilities=(b'UIDPLUS',))
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],1)
        self.assertIn(('EXPUNGE','1'),client.commands);self.assertIn('2',client.boxes['INBOX'][1]);self.assertTrue(self.store.get(identity)['remote_gone'])
    # ==========================================
    # Function: Require complete read-only account evidence before accepting a cleanup snapshot.
    # Method: Fail the final mailbox, inject malformed SEARCH and ensure no remote mutation is attempted.
    # ==========================================
    def test_cloud_snapshot_readonly_and_all_or_nothing(self):
        client=MailboxFixture()
        with patch('maildesk.transport.imap_connection',return_value=nullcontext(client)):
            snapshot=cache_maintenance.cloud_snapshot(self.account)
        self.assertEqual(snapshot['INBOX'],('7',frozenset({'1','2','3','4','5'})));self.assertTrue(all(c[2] for c in client.commands if c[0]=='select'))
        for failure in ('last-folder','bad-search'):
            client=MailboxFixture();client.fail='Deleted Items' if failure=='last-folder' else '';client.bad_search=failure=='bad-search'
            with patch('maildesk.transport.imap_connection',return_value=nullcontext(client)):
                with self.assertRaises((RuntimeError,ValueError)):cache_maintenance.cloud_snapshot(self.account)
        self.assertFalse(any(c[0] in ('MOVE','STORE','EXPUNGE') for c in client.commands))
    # ==========================================
    # Function: Remove stale copies and dependent projections while retaining shared/local MIME and drafts.
    # Method: Include UID reuse, disappeared folder, read intent, labels and a shared attachment-cache hash.
    # ==========================================
    def test_purge_exact_copies_and_keep_local_shared_attachments(self):
        gone=self.mail(uid='8');valid=self.mail(uid='1');old_generation=self.mail(validity='6',uid='1');missing_folder=self.mail(folder='Removed',uid='4');local=self.mail(folder='@sent',validity='local');other=self.mail(account='two',uid='8')
        raw=self.store.get(gone,raw=True)['raw'];shared=self.store.ingest('one','@import','local','copy',raw);digest=hashlib.sha256(raw).hexdigest();cache=self.store.cache_dir/'attachments'/digest;cache.mkdir(parents=True);(cache/'cached.txt').write_text('attachment')
        self.store.mark_opened(gone);self.store.organize(gone,labels=['Keep audit']);self.store.save_draft('one',{'body':'unsent'},'draft')
        self.assertEqual(cache_maintenance.purge_messages(self.store,'one',{'INBOX':('7',{'1'})}),3)
        for identity in (gone,old_generation,missing_folder):
            with self.assertRaises(KeyError):self.store.get(identity)
        for identity in (valid,local,other,shared):self.assertTrue(self.store.get(identity))
        self.assertTrue(cache.exists());self.assertEqual(self.store.job('draft')['id'],'draft')
        with self.store.db() as db:
            for table in ('message_labels','pending_read_flags','message_display','address_observed','address_pending','contact_envelopes','contact_member_index'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table+' WHERE message=?',(gone,)).fetchone()[0],0)
    # ==========================================
    # Function: Remove private extracted attachment files only when their last physical MIME copy disappears.
    # Method: Keep a dedicated user download untouched and prune only the cache hash directory.
    # ==========================================
    def test_purge_unshared_attachment_cache(self):
        identity=self.mail(uid='8');raw=self.store.get(identity,raw=True)['raw'];cache=self.store.cache_dir/'attachments'/hashlib.sha256(raw).hexdigest();cache.mkdir(parents=True);(cache/'cached.txt').write_text('attachment');download=self.root/'download.txt';download.write_text('saved')
        cache_maintenance.purge_messages(self.store,'one',{'INBOX':('7',set())});self.assertFalse(cache.exists());self.assertEqual(download.read_text(),'saved')
    # ==========================================
    # Function: Keep stars and any saved alias referenced by a remaining cached participant header.
    # Method: Include outbound Bcc, inbound Cc, renamed/merged aliases and a mail-free pinned contact.
    # ==========================================
    def test_prune_contacts_stars_aliases_and_header_roles(self):
        for person in ('star','orphan','pin','to','cc','bcc','merged'):address_book.save(self.store,person,person,[person+'@example.com'])
        self.mail(sender='Self <self@example.com>',to='to@example.com',cc='cc@example.com',bcc='bcc@example.com',folder='@sent')
        address_book.merge(self.store,'merged','to');address_book.star_many(self.store,['star']);save_many(self.store,{'pin':{'muted':False,'pinned':True,'blocked':False}})
        self.assertEqual(cache_maintenance.prune_contacts(self.store),2)
        remaining={item['id'] for item in address_book.page(self.store)['items']};self.assertTrue({'star','merged','cc','bcc'}<=remaining);self.assertFalse({'orphan','pin'}&remaining)
        self.mail(sender='orphan@example.com');self.assertTrue(address_book.sender_detail(self.store,'orphan@example.com').get('id'))
    # ==========================================
    # Function: Retain an unreachable account's MIME even if it was previously marked remote-gone.
    # Method: Verify a second account independently, delete its stale copy, and report partial success.
    # ==========================================
    def test_cleanup_failure_isolated_and_repeatable(self):
        one=self.mail(uid='8');two=self.mail(account='two',uid='8');self.store.reconcile('one','INBOX','7',set(),{})
        self.service.accounts['two']=SimpleNamespace(id='two',email='other@example.com');star=address_book.save(self.store,'star','Star',['star@example.com']);address_book.star_many(self.store,[star])
        with patch('maildesk.cache_maintenance.cloud_snapshot',side_effect=[OSError('offline'),{'INBOX':('7',set())}]):result=self.service.clean_cache()
        self.assertEqual(result['skipped'],['one']);self.assertEqual(result['verified'],['two']);self.assertEqual(result['messages'],1);self.assertTrue(self.store.get(one))
        with self.assertRaises(KeyError):self.store.get(two)
        self.assertTrue(address_book.sender_detail(self.store,person=star)['starred'])
        with patch('maildesk.cache_maintenance.cloud_snapshot',return_value={'INBOX':('7',{'8'})}):self.assertEqual(self.service.clean_cache()['messages'],0)
    # ==========================================
    # Function: Invoke retention from the real sync path only after all remote star flags are reconciled.
    # Method: Reuse a complete two-folder fixture and verify one sync moves old normal mail but retains stars.
    # ==========================================
    def test_sync_integrates_retention_after_flag_refresh(self):
        expired=self.mail(800,uid='1');starred=self.mail(800,uid='2');client=MailboxFixture(starred=['2']);client.boxes['INBOX']=('7',{'1','2'})
        descriptors=[{'name':'INBOX','special':'inbox','selectable':True},{'name':'Deleted Items','special':'trash','selectable':True}]
        with patch('maildesk.transport.imap_connection',return_value=nullcontext(client)),patch('maildesk.folders.discover',return_value=descriptors):
            result=transport.sync_account(self.account,self.store,limit=0)
        self.assertEqual(result['retention']['moved'],1);self.assertTrue(self.store.get(expired)['remote_gone']);self.assertTrue(self.store.get(starred)['pinned']);self.assertEqual(self.store.list_messages()['total'],1)

    # ==========================================
    # Function: Disable automatic expiry without contacting the provider or requiring a trash mapping.
    # Method: Cache an old source, save the switch off and assert both remote and local state remain untouched.
    # ==========================================
    def test_retention_disabled(self):
        identity=self.mail(800,uid='1');mail_retention.save_policy(self.store,False,30);client=MailboxFixture()
        with self.store.db() as db:db.execute("UPDATE folders SET special='' WHERE special='trash'")
        result=mail_retention.expire_inbox(self.account,self.store,client,now=self.now)
        self.assertTrue(result['disabled']);self.assertEqual(client.commands,[]);self.assertFalse(self.store.get(identity)['remote_gone'])

    # ==========================================
    # Function: Honor custom day limits while preserving the exact boundary and pinned mail.
    # Method: Change the persisted threshold from30 to7 days and verify only older unpinned sources move.
    # ==========================================
    def test_custom_retention_days(self):
        old=self.mail(8,uid='1');boundary=self.mail(7,uid='2');pinned=self.mail(800,uid='3');self.store.update(pinned,{'pinned':True});client=MailboxFixture()
        mail_retention.save_policy(self.store,True,30);self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],0)
        mail_retention.save_policy(self.store,True,7);self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],1)
        self.assertTrue(self.store.get(old)['remote_gone']);self.assertFalse(self.store.get(boundary)['remote_gone']);self.assertFalse(self.store.get(pinned)['remote_gone'])

    # ==========================================
    # Function: Preserve coherent typed settings across restart and reject invalid updates atomically.
    # Method: Reopen SQLite and exercise invalid booleans, fractional/zero/negative and excessive day counts.
    # ==========================================
    def test_retention_policy_validation_and_restart(self):
        self.assertEqual(mail_retention.get_policy(self.store),(True,365));mail_retention.save_policy(self.store,False,30)
        self.assertEqual(mail_retention.get_policy(Store(self.store.path)),(False,30))
        for enabled,days in [(True,0),(True,-1),(True,36501),(True,1.5),(True,True),(True,'30'),('yes',30)]:
            with self.subTest(enabled=enabled,days=days):
                with self.assertRaises(ValueError):mail_retention.save_policy(self.store,enabled,days)
                self.assertEqual(mail_retention.get_policy(self.store),(False,30))
        mail_retention.save_policy(self.store,True,36500);self.assertEqual(mail_retention.get_policy(self.store),(True,36500))

    # ==========================================
    # Function: Validate settings text before any saved policy changes.
    # Method: Exercise the form boundary with empty, fractional, negative, non-ASCII and oversized input.
    # ==========================================
    def test_retention_form_values(self):
        from maildesk.storage_settings import retention_values
        for text in ('','0','-1','1.5','36501','１２','999999999999999999999'):
            with self.subTest(text=text):
                form=SimpleNamespace(value=lambda key,t=text:True if key=='mail_retention_enabled' else t)
                with self.assertRaises(ValueError):retention_values(form)
        form=SimpleNamespace(value=lambda key:False if key=='mail_retention_enabled' else ' 30 ')
        self.assertEqual(retention_values(form),(False,30))

    # ==========================================
    # Function: Stop an ongoing batch after the enable switch changes, retaining remaining originals.
    # Method: Disable the policy after the first successful remote move and require no second move.
    # ==========================================
    def test_retention_stops_changed_batch(self):
        first=self.mail(800,uid='1');second=self.mail(799,uid='2');client=MailboxFixture();original=client.uid
        # ==========================================
        # Function: Model settings being saved while the provider handles the first transfer.
        # Method: Preserve the real fixture command and change only the independent local policy.
        # ==========================================
        def changing(command,*args):
            result=original(command,*args)
            if command=='MOVE':mail_retention.save_policy(self.store,False,365)
            return result
        client.uid=changing
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],1)
        self.assertTrue(self.store.get(first)['remote_gone']);self.assertFalse(self.store.get(second)['remote_gone'])

    # ==========================================
    # Function: Respect disablement saved after the final remote FLAGS check but before MOVE.
    # Method: Change the switch in a provider reply and require zero remote transfers.
    # ==========================================
    def test_retention_disable_during_flags(self):
        identity=self.mail(800,uid='1');client=MailboxFixture();original=client.uid
        # ==========================================
        # Function: Model a saved disable action racing a pending remote flag response.
        # Method: Update the policy after producing FLAGS while leaving the source message intact.
        # ==========================================
        def changing(command,*args):
            result=original(command,*args)
            if command=='FETCH':mail_retention.save_policy(self.store,False,365)
            return result
        client.uid=changing
        self.assertEqual(mail_retention.expire_inbox(self.account,self.store,client,now=self.now)['moved'],0)
        self.assertFalse(self.store.get(identity)['remote_gone']);self.assertFalse(any(row[0]=='MOVE' for row in client.commands))

    # ==========================================
    # Function: Treat the reserved INBOX mailbox case-insensitively during cloud existence checks.
    # Method: Keep a valid lowercase cache source and remove an absent UID from the same folder.
    # ==========================================
    def test_cleanup_inbox_case_alias(self):
        valid=self.mail(folder='inbox',uid='1');stale=self.mail(folder='inbox',uid='8')
        self.assertEqual(cache_maintenance.purge_messages(self.store,'one',{'INBOX':('7',{'1'})}),1);self.assertTrue(self.store.get(valid))
        with self.assertRaises(KeyError):self.store.get(stale)

    # ==========================================
    # Function: Keep starred orphan people even when the complete cache becomes empty.
    # Method: Remove the final source copy and distinguish cleanup from an explicit permanent contact suppression.
    # ==========================================
    def test_empty_cache_preserves_only_starred_contacts(self):
        self.mail(uid='1');star=address_book.save(self.store,'star','Star',['star@example.com']);address_book.star_many(self.store,[star])
        cache_maintenance.purge_messages(self.store,'one',{'INBOX':('7',set())});self.assertEqual(cache_maintenance.prune_contacts(self.store),1)
        self.assertEqual([row['id'] for row in address_book.page(self.store)['items']],['star'])

    # ==========================================
    # Function: Keep paused account caches intact without opening a provider connection.
    # Method: Exercise explicit cleanup while its configured account is paused.
    # ==========================================
    def test_cleanup_paused_account(self):
        identity=self.mail(uid='8');self.store.set_preference('paused_accounts',['one'])
        with patch('maildesk.cache_maintenance.cloud_snapshot') as snapshot:result=self.service.clean_cache();snapshot.assert_not_called()
        self.assertEqual(result['skipped'],['one']);self.assertTrue(self.store.get(identity))

if __name__=='__main__':unittest.main()
