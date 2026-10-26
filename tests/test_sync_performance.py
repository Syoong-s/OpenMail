"""Deterministic provider work, foreground scheduling and bounded ingest regressions."""
from contextlib import contextmanager
from datetime import datetime,timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import threading,time,unittest
from unittest.mock import patch
from maildesk import folders,transport
from maildesk.config import Account
from maildesk.service import MailService
from maildesk.store import Store
from maildesk.sync_batches import BODY_BATCH,BODY_BYTES,body_batches,fetch_new

# ==========================================
# Function: Model a counted provider with reorderable literals and an interruptible slow body response.
# Method: Share mailbox state between separate authenticated sessions while keeping selection state connection-local.
# ==========================================
class Provider:
    # ==========================================
    # Function: Seed a realistic hundred-message inbox and empty destinations without contacting an account.
    # Method: Build small actual MIME sources with independent UID/RFC identities and observable command counters.
    # ==========================================
    def __init__(self,count=120,delay=0):
        self.boxes={name:{} for name in ('INBOX','Archive','Trash')};self.commands=[];self.delay=delay
        self.entered=threading.Event();self.release=threading.Event();self.block=False;self.blocks=0
        for index in range(1,count+1):
            mail=EmailMessage();mail['From']='person@example.invalid';mail['To']='me@example.invalid';mail['Subject']='Fixture '+str(index);mail['Message-ID']='<batch-'+str(index)+'@example.invalid>';mail['Date']=datetime.now(timezone.utc);mail.set_content('Body '+str(index))
            self.boxes['INBOX'][str(index)]={'raw':mail.as_bytes(),'flags':set()}

    # ==========================================
    # Function: Account for one provider round trip and a controlled in-flight response.
    # Method: Use events for scheduling assertions and an optional finite delay only for measured diagnostics.
    # ==========================================
    def command(self,name,*args):
        self.commands.append((name,*args))
        if self.delay:time.sleep(self.delay)
        if self.block and name=='FETCH' and 'BODY.PEEK[]' in str(args) and not self.blocks:
            self.blocks+=1;self.entered.set()
            if not self.release.wait(5):raise TimeoutError('Fixture body was not released')

    # ==========================================
    # Function: Give each operation its own authenticated session over shared synthetic provider state.
    # Method: Match production context-manager cleanup while keeping only a per-session selected folder.
    # ==========================================
    @contextmanager
    def connection(self,*unused,**kwargs):
        self.command('LOGIN');client=Session(self)
        try:yield client
        finally:self.command('LOGOUT')

# ==========================================
# Function: Exercise production sync parsing, UID STORE and safe MOVE/CRUD with controlled response order.
# Method: Return imaplib-shaped tuples, never infer a literal's UID from request position.
# ==========================================
class Session:
    capabilities=(b'IMAP4rev1',b'MOVE',b'UIDPLUS')
    # ==========================================
    # Function: Keep selected mailbox and COPYUID state independent between sessions.
    # Method: Retain the shared provider and initialize exact-generation responses.
    # ==========================================
    def __init__(self,provider):self.p=provider;self.selected='INBOX';self.copyuid=None
    # ==========================================
    # Function: Decode the client's real quoted mailbox command.
    # Method: Remove quoting and protocol escapes before modified UTF-7 decoding.
    # ==========================================
    def path(self,name):return folders.decode_mailbox(name[1:-1].replace('\\"','"').replace('\\\\','\\'))
    # ==========================================
    # Function: Return an authoritative hierarchy without synthetic network shortcuts.
    # Method: Advertise actual special-use flags used by production destination resolution.
    # ==========================================
    def list(self,*unused):
        self.p.command('LIST');return 'OK',[('('+{'INBOX':'\\Inbox','Archive':'\\Archive','Trash':'\\Trash'}.get(name,'')+') "/" '+transport.mailbox_name(name)).encode() for name in self.p.boxes]
    # ==========================================
    # Function: Report every synthetic folder subscribed.
    # Method: Reuse hierarchy rows while tracking a separate LSUB round trip.
    # ==========================================
    def lsub(self,*unused):
        self.p.command('LSUB');return 'OK',[]
    # ==========================================
    # Function: Return total/unread counters for sync while exposing unwanted CRUD-wide STATUS work.
    # Method: Count only the selected synthetic mailbox's actual data.
    # ==========================================
    def status(self,name,*unused):
        path=self.path(name);self.p.command('STATUS',path);rows=self.p.boxes[path]
        return 'OK',[(transport.mailbox_name(path)+' (MESSAGES '+str(len(rows))+' UNSEEN '+str(sum(b'\\Seen' not in row['flags'] for row in rows.values()))+')').encode()]
    # ==========================================
    # Function: Select one exact session-local source mailbox.
    # Method: Keep readonly requests observable and use the provider's stable UID generation.
    # ==========================================
    def select(self,name,readonly=False):self.selected=self.path(name);self.p.command('SELECT',self.selected,readonly);return 'OK',[]
    # ==========================================
    # Function: Supply mandatory UIDVALIDITY and optional source-to-destination UID mapping.
    # Method: Match imaplib's response tuple without issuing another wire command.
    # ==========================================
    def response(self,code):return code,[b'77'] if code=='UIDVALIDITY' else [self.copyuid]
    # ==========================================
    # Function: Implement the protocol operations exercised by actual sync and interactive services.
    # Method: Reverse FETCH rows deliberately; modify only requested UID sets and preserve unrelated sources.
    # ==========================================
    def uid(self,operation,*args):
        self.p.command(operation,*args);rows=self.p.boxes[self.selected]
        if operation=='SEARCH':return 'OK',[(' '.join(rows)).encode()]
        uids=str(args[0]).split(',')
        if operation=='FETCH':
            result=[]
            for uid in reversed(uids):
                if uid not in rows:continue
                row=rows[uid];header=b'1 (UID '+uid.encode()
                if 'RFC822.SIZE' in args[1]:result.append(header+b' RFC822.SIZE '+str(row.get('size',len(row['raw']))).encode()+b' INTERNALDATE '+transport.imaplib.Time2Internaldate(row.get('received_at',time.time())).encode()+b')')
                elif 'BODY.PEEK[]' in args[1]:result.extend([(header+b' FLAGS ('+b' '.join(row['flags'])+b') BODY[] {'+str(len(row['raw'])).encode()+b'}',row['raw']),b')'])
                else:result.append(header+b' FLAGS ('+b' '.join(row['flags'])+b'))')
            return 'OK',result
        if operation=='STORE':
            flag=args[2].strip('()').encode()
            for uid in uids:
                if uid in rows:
                    if args[1].startswith('+'):rows[uid]['flags'].add(flag)
                    else:rows[uid]['flags'].discard(flag)
        elif operation=='MOVE':
            destination=self.p.boxes[self.path(args[1])];new=str(max([int(value) for value in destination]+[1000])+1);destination[new]=rows.pop(uids[0]);self.copyuid=('77 '+uids[0]+' '+new).encode()
        return 'OK',[]
    # ==========================================
    # Function: Create one synthetic folder before the production metadata refresh.
    # Method: Add only the explicitly named empty mailbox and record its command.
    # ==========================================
    def create(self,name):self.p.command('CREATE',name);self.p.boxes[self.path(name)]={};return 'OK',[]
    # ==========================================
    # Function: Accept the explicit subscription following folder creation.
    # Method: Record the request without adding unrelated STATUS replies.
    # ==========================================
    def subscribe(self,name):self.p.command('SUBSCRIBE',name);return 'OK',[]

# ==========================================
# Function: Verify practical speedup and action priority using real local service/cache behavior.
# Method: Control only the provider, keep UID safety, SQLite transactions and service locking in production code.
# ==========================================
class SyncPerformanceTests(unittest.TestCase):
    # ==========================================
    # Function: Isolate each provider/database scenario from live profiles.
    # Method: Use a private temporary folder and no usable credential or network host.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name);self.account=Account('test','me@example.invalid','imap.invalid','smtp.invalid');self.store=Store(self.root/'mail.sqlite3');self.store.set_preference('mail_retention_enabled',False)
    # ==========================================
    # Function: Release every temporary database after connections have closed.
    # Method: Bound thread joins inside tests before removing the profile directory.
    # ==========================================
    def tearDown(self):self.temp.cleanup()
    # ==========================================
    # Function: Reduce new-mail wire work while preserving message/flag identities under reordered responses.
    # Method: Import120 UIDs, assert batch counts and compare each source body to its own cached UID.
    # ==========================================
    def test_hundred_message_batches_match_reordered_uids(self):
        provider=Provider();provider.boxes['INBOX']['4']['flags']={b'\\Seen',b'\\Flagged'}
        with patch('maildesk.transport.imap_connection',provider.connection):result=transport.sync_account(self.account,self.store)
        self.assertEqual(result['imported'],120)
        fetches=[row for row in provider.commands if row[0]=='FETCH'];sizes=[row for row in fetches if 'RFC822.SIZE' in row[-1]];bodies=[row for row in fetches if 'BODY.PEEK[]' in row[-1]]
        self.assertEqual(len(sizes),2);self.assertEqual(len(bodies),9);self.assertTrue(all(len(row[1].split(','))<=BODY_BATCH for row in bodies))
        with self.store.db() as db:
            for row in db.execute('SELECT uid,body,seen,pinned FROM messages'):
                self.assertIn('Body '+row['uid'],row['body'])
                if row['uid']=='4':self.assertTrue(row['seen']);self.assertTrue(row['pinned'])
    # ==========================================
    # Function: Resume missing UID backfill after interruption without duplicating committed mail.
    # Method: Yield after the first body batch, then complete a second real sync over the same provider/cache.
    # ==========================================
    def test_interrupted_sync_resumes_committed_batches(self):
        provider=Provider()
        with patch('maildesk.transport.imap_connection',provider.connection):
            result=transport.sync_account(self.account,self.store,should_yield=lambda:any(row[0]=='FETCH' and 'BODY.PEEK[]' in row[-1] for row in provider.commands))
            self.assertTrue(result['interrupted']);self.assertEqual(result['imported'],16)
            self.assertEqual(transport.sync_account(self.account,self.store)['imported'],104)
        self.assertEqual(self.store.list_messages(view='all')['total'],120)
    # ==========================================
    # Function: Keep body requests within count/byte bounds and omit advertised oversized mail.
    # Method: Exercise a source larger than MAX_MESSAGE_BYTES and partition valid2MiB bodies.
    # ==========================================
    def test_size_limits_and_byte_budget(self):
        from maildesk.mime import MAX_MESSAGE_BYTES
        batches=list(body_batches([(str(index),2*1024*1024) for index in range(5)]));self.assertEqual(list(map(len,batches)),[2,2,1]);self.assertEqual(BODY_BYTES,4*1024*1024)
        provider=Provider(3);provider.boxes['INBOX']['2']['size']=MAX_MESSAGE_BYTES+1
        with patch('maildesk.transport.imap_connection',provider.connection):result=transport.sync_account(self.account,self.store)
        self.assertEqual((result['imported'],result['skipped_large']),(2,1));self.assertTrue(all('2' not in row[1].split(',') for row in provider.commands if row[0]=='FETCH' and 'BODY.PEEK[]' in row[-1]))
    # ==========================================
    # Function: Reject a MIME literal carrying an unrelated UID before importing any wrongly identified source.
    # Method: Feed a tagged-OK malicious response with missing requested UID and verify the cache remains empty.
    # ==========================================
    def test_mismatched_literal_uid_fails_closed(self):
        provider=Provider(1);client=Session(provider);original=client.uid
        # ==========================================
        # Function: Corrupt only literal identity, preserving a plausible size lookup.
        # Method: Replace the expected UID with a different UID in the actual tuple header.
        # ==========================================
        def corrupt(operation,*args):
            if 'BODY.PEEK[]' in str(args):return 'OK',[(b'1 (UID 999 FLAGS () BODY[] {5}',b'wrong')]
            return original(operation,*args)
        with patch.object(client,'uid',corrupt),self.assertRaises(RuntimeError):fetch_new(client,self.store,'test','INBOX','77',['1'])
        self.assertEqual(self.store.list_messages(view='all')['total'],0)
    # ==========================================
    # Function: Roll back every cache side effect if one source in a batch cannot be observed.
    # Method: Fail the second contact observation, then verify source/link/person atomicity and connection cleanup.
    # ==========================================
    def test_batch_ingest_rolls_back_all_identity_writes(self):
        from maildesk.address_book import observe_message
        provider=Provider(2);sources=[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()];calls=[]
        # ==========================================
        # Function: Fail after the first source has already modified its transaction.
        # Method: Let production contact observation run once before injecting a second-source storage error.
        # ==========================================
        def observe(*args):
            calls.append(1)
            if len(calls)==2:raise RuntimeError('fixture write failed')
            return observe_message(*args)
        with patch('maildesk.address_book.observe_message',observe),self.assertRaises(RuntimeError):self.store.ingest_many('test','INBOX','77',sources)
        with self.store.db() as db:
            for table in ('messages','address_people','address_observed'):self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(len(self.store.ingest_many('test','INBOX','77',sources)),2)
    # ==========================================
    # Function: Let a state, move or folder command finish before the rest of a hundred-mail sync.
    # Method: Block a real body response, queue an actual service mutation, then release exactly that in-flight command.
    # ==========================================
    def test_interactive_operations_preempt_large_sync(self):
        for operation in ('state','move','folder'):
            with self.subTest(operation=operation):
                provider=Provider();provider.block=True;service=MailService(self.root/operation,[self.account]);service.store.set_preference('mail_retention_enabled',False)
                identity=service.store.ingest('test','INBOX','77','1',provider.boxes['INBOX']['1']['raw']);errors=[];finished=threading.Event()
                # ==========================================
                # Function: Run the user operation through its real service entry point.
                # Method: Capture errors and signal completion independently of synchronization.
                # ==========================================
                def action():
                    try:
                        if operation=='state':service.update(identity,{'pinned':True})
                        elif operation=='move':service.move_message(identity,'Archive')
                        else:service.folder_action('test','create','Work')
                    except Exception as error:errors.append(error)
                    finally:finished.set()
                with patch('maildesk.transport.imap_connection',provider.connection):
                    sync=threading.Thread(target=service.sync);sync.start();self.assertTrue(provider.entered.wait(2));worker=threading.Thread(target=action);worker.start()
                    deadline=time.monotonic()+2
                    while not service.lock.interrupted() and time.monotonic()<deadline:time.sleep(.001)
                    self.assertTrue(service.lock.interrupted());provider.release.set();self.assertTrue(finished.wait(3));sync.join(3);worker.join(3)
                self.assertFalse(sync.is_alive());self.assertFalse(errors,errors);self.assertTrue(service.sync_event.is_set())
                self.assertLess(service.store.list_messages(view='all')['total'],120)
                self.assertTrue(service.status['accounts']['test'].get('interrupted'));service.close()
    # ==========================================
    # Function: Keep purely local priority changes independent of an in-flight provider response.
    # Method: Hold synchronization inside BODY FETCH and require local state to commit before releasing it.
    # ==========================================
    def test_local_state_does_not_wait_for_network(self):
        provider=Provider();provider.block=True;service=MailService(self.root/'local',[self.account]);service.store.set_preference('mail_retention_enabled',False);identity=service.store.ingest('test','INBOX','77','1',provider.boxes['INBOX']['1']['raw'])
        with patch('maildesk.transport.imap_connection',provider.connection):
            sync=threading.Thread(target=service.sync);sync.start();self.assertTrue(provider.entered.wait(2))
            try:self.assertTrue(service.update(identity,{'priority':True})['priority'])
            finally:provider.release.set();sync.join(5);service.close()
    # ==========================================
    # Function: Clear many read intents with bounded provider sessions without losing a newer local generation.
    # Method: Queue101 sources and inject a newer token while the first100-UID STORE is confirmed.
    # ==========================================
    def test_read_all_batches_and_newer_intent_survives(self):
        provider=Provider(101);service=MailService(self.root/'read-all',[self.account]);identities=service.store.ingest_many('test','INBOX','77',[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()])
        for identity in identities:service.store.mark_opened(identity,remote=True)
        # ==========================================
        # Function: Represent a newer local read intent arriving during a remote group acknowledgement.
        # Method: Change its generation inside the mocked successful transport boundary.
        # ==========================================
        def confirm(*args):
            with service.store.db() as db:db.execute("UPDATE pending_read_flags SET generation='newer' WHERE message=?",(identities[0],))
        with patch('maildesk.transport.set_seen_many',side_effect=confirm) as many,patch('maildesk.transport.set_seen') as one:self.assertEqual(service.flush_read_flags(),1)
        self.assertEqual(many.call_count,1);self.assertEqual(len(many.call_args.args[1]),100);self.assertEqual(one.call_count,1);self.assertEqual(service.store.pending_read_flags()[0]['generation'],'newer');service.close()
    # ==========================================
    # Function: Avoid querying every unrelated folder's status after a single folder mutation.
    # Method: Perform real create/discovery against25 synthetic mailboxes and assert zero STATUS commands.
    # ==========================================
    def test_folder_crud_refresh_omits_status_fanout(self):
        provider=Provider(0)
        for index in range(25):provider.boxes['Folder'+str(index)]={}
        with patch('maildesk.transport.imap_connection',provider.connection):result=folders.mutate_folder(self.account,'create','Work')
        self.assertIn('Work',[row['name'] for row in result]);self.assertFalse(any(row[0]=='STATUS' for row in provider.commands))

    # ==========================================
    # Function: Set explicit bulk states without one login or body lookup per message.
    # Method: Apply101 pinned changes against the real service and require exactly two bounded UID STORE sessions.
    # ==========================================
    def test_explicit_bulk_flags_use_uid_sets(self):
        provider=Provider(101);service=MailService(self.root/'bulk',[self.account]);identities=service.store.ingest_many('test','INBOX','77',[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()])
        with patch('maildesk.transport.imap_connection',provider.connection):self.assertEqual(len(service.bulk_action(identities,'pinned',True)),101)
        self.assertEqual(sum(row[0]=='LOGIN' for row in provider.commands),2);self.assertEqual(sum(row[0]=='STORE' for row in provider.commands),2)
        self.assertTrue(all(b'\\Flagged' in row['flags'] for row in provider.boxes['INBOX'].values()))
        with service.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM messages WHERE pinned=1').fetchone()[0],101)
        service.close()

    # ==========================================
    # Function: Keep failed bulk remote operations from claiming unconfirmed local state.
    # Method: Fail the second100-source provider group and verify exact partial progress in both error and cache.
    # ==========================================
    def test_bulk_flags_partial_failure_preserves_confirmed_groups(self):
        provider=Provider(101);service=MailService(self.root/'partial',[self.account]);identities=service.store.ingest_many('test','INBOX','77',[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()])
        with patch('maildesk.transport.set_seen_many',side_effect=[None,OSError('fixture offline')]),self.assertRaisesRegex(ValueError,'100 / 101'):service.bulk_action(identities,'seen',True)
        with service.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM messages WHERE seen=1').fetchone()[0],100)
        service.close()

    # ==========================================
    # Function: Refuse mixed or stale UID generations before any bulk STORE can mutate another mailbox generation.
    # Method: Combine real source identities with a changed cached/server generation and inspect all provider commands.
    # ==========================================
    def test_batch_flags_generation_guards(self):
        provider=Provider(2);ids=self.store.ingest_many('test','INBOX','77',[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()]);rows=[self.store.get(identity) for identity in ids];rows[1]['validity']='88'
        with patch('maildesk.transport.imap_connection',provider.connection):
            with self.assertRaises(ValueError):transport.set_seen_many(self.account,rows,True)
            self.assertFalse(provider.commands)
            rows[0]['validity']='88'
            with self.assertRaises(ValueError):transport.set_seen_many(self.account,rows,True)
        self.assertFalse(any(row[0]=='STORE' for row in provider.commands))

    # ==========================================
    # Function: Retain authoritative counts for unchanged folders after metadata-only CRUD discovery.
    # Method: Create a folder while only one of120 remote messages is cached and compare the saved inbox total.
    # ==========================================
    def test_folder_crud_preserves_remote_counts(self):
        provider=Provider();service=MailService(self.root/'folder-count',[self.account]);service.store.ingest('test','INBOX','77','1',provider.boxes['INBOX']['1']['raw'])
        with patch('maildesk.transport.imap_connection',provider.connection):
            with provider.connection() as client:service.store.save_folders('test',folders.discover(client,self.account))
            service.folder_action('test','create','Work')
        self.assertEqual(next(row['total'] for row in service.store.list_folders('test') if row['folder']=='INBOX'),120);service.close()

    # ==========================================
    # Function: Avoid repeatedly authenticating an offline mailbox for every queued read chunk in the same flush.
    # Method: Fail the first100-source provider batch and keep every durable intent for the next normal retry.
    # ==========================================
    def test_failed_read_batch_defers_rest_of_mailbox(self):
        provider=Provider(101);service=MailService(self.root/'offline-read',[self.account]);identities=service.store.ingest_many('test','INBOX','77',[{'uid':uid,**row} for uid,row in provider.boxes['INBOX'].items()])
        for identity in identities:service.store.mark_opened(identity,remote=True)
        with patch('maildesk.transport.set_seen_many',side_effect=OSError('offline')) as many,patch('maildesk.transport.set_seen') as one:self.assertEqual(service.flush_read_flags(),101)
        self.assertEqual(many.call_count,1);one.assert_not_called();service.close()

if __name__=='__main__':unittest.main()
