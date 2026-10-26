"""Verified-TLS folder workflows and persistent organization acceptance tests."""
from pathlib import Path
import shlex
import socketserver
import tempfile
import time
import unittest
from unittest.mock import MagicMock,patch
import test_protocols as protocols
from maildesk.config import Account
from maildesk import transport,folders
from maildesk.service import MailService
from maildesk.store import Store
from maildesk.richtext import InertRichText

# ==========================================
# Function: Serve a mutable IMAP hierarchy with isolated UID generations.
# Method: Record commands and respond with actual LIST, FETCH and COPYUID wire replies.
# ==========================================
class FolderIMAP(socketserver.StreamRequestHandler):
    # ==========================================
    # Function: Serve one TLS connection against deterministic mailbox state.
    # Method: Implement folder CRUD, UID MOVE/COPY/STORE and targeted EXPUNGE.
    # ==========================================
    def handle(self):
        self.wfile.write(b'* OK folder fixture\r\n');selected=None
        while line:=self.rfile.readline():
            self.server.commands.append(line)
            tokens=shlex.split(line.decode().strip());tag,command=tokens[:2];args=tokens[2:];response='OK complete';boxes=self.server.mailboxes
            # ==========================================
            # Function: Emit a framed fixture reply.
            # Method: Keep protocol bytes separate from state mutations.
            # ==========================================
            def emit(value):self.wfile.write(value+b'\r\n')
            if command=='CAPABILITY':emit(b'* CAPABILITY IMAP4rev1 UIDPLUS'+(b' MOVE' if self.server.allow_move else b''))
            elif command in ('LIST','LSUB'):
                for path,data in boxes.items():
                    if command=='LSUB' and not data['subscribed']:continue
                    emit(b'* '+command.encode()+b' ('+data['flags']+b') "/" '+transport.mailbox_name(path).encode())
            elif command in ('SELECT','EXAMINE'):
                selected=folders.decode_mailbox(args[0])
                if selected not in boxes:response='NO missing'
                else:
                    emit(b'* FLAGS (\\Seen \\Flagged \\Deleted)');emit(b'* '+str(len(boxes[selected]['messages'])).encode()+b' EXISTS')
                    emit(b'* OK [UIDVALIDITY '+boxes[selected]['validity'].encode()+b'] generation')
            elif command=='CREATE':boxes[folders.decode_mailbox(args[0])]={'validity':'99','flags':b'','subscribed':False,'messages':{}}
            elif command=='RENAME':
                old,new=map(folders.decode_mailbox,args)
                for path in list(boxes):
                    if path==old or path.startswith(old+'/'):boxes[new+path[len(old):]]=boxes.pop(path)
            elif command=='DELETE':
                path=folders.decode_mailbox(args[0])
                if boxes[path]['messages']:response='NO not empty'
                else:del boxes[path]
            elif command in ('SUBSCRIBE','UNSUBSCRIBE'):boxes[folders.decode_mailbox(args[0])]['subscribed']=command=='SUBSCRIBE'
            elif command=='UID':
                operation=args[0];messages=boxes[selected]['messages']
                if operation=='SEARCH':emit(b'* SEARCH '+b' '.join(uid.encode() for uid in messages))
                elif operation=='FETCH':
                    for uid in args[1].split(','):
                        if uid not in messages:continue
                        item=messages[uid];base=b'* 1 FETCH (UID '+uid.encode()
                        if b'RFC822.SIZE' in line:emit(base+b' RFC822.SIZE '+str(len(item['raw'])).encode()+b')')
                        elif b'BODY.PEEK[]' in line:
                            emit(base+b' FLAGS ('+b' '.join(item['flags'])+b') BODY[] {'+str(len(item['raw'])).encode()+b'}');self.wfile.write(item['raw']+b')\r\n')
                        else:emit(base+b' FLAGS ('+b' '.join(item['flags'])+b'))')
                elif operation=='STORE':
                    uid=args[1];flag=b'\\Deleted' if b'\\Deleted' in line else b'\\Flagged' if b'\\Flagged' in line else b'\\Seen'
                    if args[2].startswith('+'):messages[uid]['flags'].add(flag)
                    else:messages[uid]['flags'].discard(flag)
                elif operation in ('MOVE','COPY'):
                    uid=args[1];dest=folders.decode_mailbox(args[2]);target=boxes[dest]['messages'];new=str(max([int(v) for v in target]+[100])+1)
                    target[new]={'raw':messages[uid]['raw'],'flags':set(messages[uid]['flags'])}
                    if operation=='MOVE':del messages[uid]
                    response='OK [COPYUID '+boxes[dest]['validity']+' '+uid+' '+new+'] transferred'
                elif operation=='EXPUNGE':
                    uid=args[1]
                    if uid in messages and b'\\Deleted' in messages[uid]['flags']:del messages[uid];emit(b'* 1 EXPUNGE')
            elif command=='LOGOUT':emit(b'* BYE goodbye');emit(tag.encode()+b' OK logout');return
            emit(tag.encode()+b' '+response.encode())

# ==========================================
# Function: Test real encrypted folder workflows without using live credentials.
# Method: Reuse the ephemeral certificate and loopback server lifecycle.
# ==========================================
class FolderProtocolTests(unittest.TestCase):
    setUpClass=classmethod(protocols.ProtocolTests.setUpClass.__func__)
    tearDownClass=classmethod(protocols.ProtocolTests.tearDownClass.__func__)
    fixture=protocols.ProtocolTests.fixture
    # ==========================================
    # Function: Seed different generations, Unicode paths and an unrelated deleted UID.
    # Method: Initialize every remote folder independently for each test connection.
    # ==========================================
    def prepare(self,server):
        server.allow_move=True
        server.mailboxes={name:{'validity':str(77+i),'flags':flag,'subscribed':True,'messages':{}} for i,(name,flag) in enumerate([('INBOX',b'\\Inbox'),('工作',b''),('工作/项目 & 资料',b''),('Archive',b'\\Archive'),('Trash',b'\\Trash'),('Spam',b'\\Junk')])}
        server.mailboxes['INBOX']['messages']={'8':{'raw':server.raw,'flags':set()},'9':{'raw':server.raw.replace(b'<tls@example.com>',b'<unrelated@example.com>'),'flags':{b'\\Deleted'}}}
        return Account('test','me@example.com','127.0.0.1','127.0.0.1',imap_port=server.server_address[1],secret_env='TEST_PASSWORD')
    # ==========================================
    # Function: Verify discovery, hierarchy CRUD, favorites and subscriptions.
    # Method: Operate through the service and assert remote/cache identities agree.
    # ==========================================
    def test_remote_hierarchy_crud(self):
        with self.fixture(FolderIMAP) as server,tempfile.TemporaryDirectory() as root:
            account=self.prepare(server);service=MailService(root,[account]);service.sync()
            self.assertIn('工作/项目 & 资料',[r['folder'] for r in service.store.list_folders('test')])
            self.assertEqual(service.store.special_folder('test','spam'),'Spam')
            service.folder_action('test','create','工作/研究成果');service.store.folder_options('test','工作/研究成果',favorite=True,color='purple')
            service.folder_action('test','rename','工作/研究成果','工作/研究归档')
            self.assertEqual(next(r for r in service.store.list_folders('test') if r['folder']=='工作/研究归档')['favorite'],1)
            service.folder_action('test','unsubscribe','工作/研究归档');self.assertFalse(server.mailboxes['工作/研究归档']['subscribed'])
            service.folder_action('test','subscribe','工作/研究归档');service.folder_action('test','delete','工作/研究归档')
            self.assertNotIn('工作/研究归档',server.mailboxes)
            with self.assertRaises(ValueError):service.folder_action('test','delete','INBOX')
            with self.assertRaises(ValueError):service.folder_action('test','rename','工作','工作/子级')
            self.assertFalse(any(b' CLOSE\r\n' in c for c in server.commands))
    # ==========================================
    # Function: Verify MOVE and fallback never expunge unrelated deleted messages.
    # Method: Run both capability profiles through real TLS and inspect exact UID commands.
    # ==========================================
    def test_uid_move_and_targeted_fallback(self):
        for allow in (True,False):
            with self.subTest(move=allow),self.fixture(FolderIMAP) as server,tempfile.TemporaryDirectory() as root:
                account=self.prepare(server);server.allow_move=allow;service=MailService(root,[account]);service.sync()
                identity=next(r['id'] for r in service.store.list_messages()['items'] if service.store.get(r['id'])['uid']=='8')
                service.update(identity,{'pinned':True})
                service.store.organize(identity,labels=['移动保留'])
                service.move_message(identity,'工作/项目 & 资料');service.sync()
                self.assertNotIn('8',server.mailboxes['INBOX']['messages']);self.assertIn('9',server.mailboxes['INBOX']['messages'])
                result=service.store.list_messages(view='all',account='test',folder='工作/项目 & 资料')
                self.assertEqual(result['total'],1)
                moved=service.store.get(result['items'][0]['id']);self.assertEqual(moved['pinned'],1);self.assertIn('移动保留',moved['labels'])
                self.assertTrue(any((b'UID MOVE 8' if allow else b'UID EXPUNGE 8') in c for c in server.commands))
                self.assertFalse(any(c.split()[1:]==[b'EXPUNGE'] for c in server.commands))
    # ==========================================
    # Function: Refuse stale generations and unsupported safe-move capability.
    # Method: Ensure refusal occurs before any COPY, STORE or MOVE mutation.
    # ==========================================
    def test_generation_and_capability_guards(self):
        with self.fixture(FolderIMAP) as server,tempfile.TemporaryDirectory() as root:
            account=self.prepare(server);store=Store(Path(root)/'db');transport.sync_account(account,store)
            message=store.get(store.list_messages()['items'][0]['id']);message['validity']='wrong'
            with self.assertRaises(ValueError):folders.transfer(account,message,'Archive')
            self.assertFalse(any(b'UID MOVE' in c or b'UID COPY' in c for c in server.commands))
        fake=MagicMock();fake.capabilities=(b'IMAP4rev1',);fake.select.return_value=('OK',[]);fake.response.return_value=('UIDVALIDITY',[b'77'])
        message.update(validity='77',uid='8',remote_gone=0)
        with patch('maildesk.transport.imap_connection') as connection:
            connection.return_value.__enter__.return_value=fake
            with self.assertRaises(ValueError):folders.transfer(account,message,'Archive')
            fake.uid.assert_not_called()
    # ==========================================
    # Function: Verify copy retains the source and permanent deletion is UID-specific.
    # Method: Exercise real protocol outcomes with an unrelated deleted UID present.
    # ==========================================
    def test_copy_and_permanent_delete(self):
        with self.fixture(FolderIMAP) as server,tempfile.TemporaryDirectory() as root:
            account=self.prepare(server);service=MailService(root,[account]);service.sync()
            identity=next(r['id'] for r in service.store.list_messages()['items'] if service.store.get(r['id'])['uid']=='8')
            service.move_message(identity,'Archive',copy=True)
            self.assertIn('8',server.mailboxes['INBOX']['messages']);self.assertEqual(len(server.mailboxes['Archive']['messages']),1)
            service.permanently_delete(identity);self.assertNotIn('8',server.mailboxes['INBOX']['messages']);self.assertIn('9',server.mailboxes['INBOX']['messages'])

# ==========================================
# Function: Verify durable personal organization and hostile-input handling.
# Method: Use synthetic MIME and isolated databases without any network access.
# ==========================================
class OrganizationTests(unittest.TestCase):
    # ==========================================
    # Function: Verify quoted/literal folder names and modified UTF-7 decoding.
    # Method: Round-trip Unicode, escapes, NIL hierarchy and reserved names.
    # ==========================================
    def test_mailbox_parser(self):
        for path in ('INBOX','工作/项目 & 资料','has "quotes"','a\\b'):
            self.assertEqual(folders.parse_folder(b'() "/" '+transport.mailbox_name(path).encode())['name'],path)
        self.assertIsNone(folders.parse_folder(b'(\\Noselect) NIL "namespace"')['delimiter'])
        self.assertEqual(folders.parse_folder((b'() "/" {5}',b'hello'))['name'],'hello')
        for path in ('','@local','abc\nmalicious'):
            with self.assertRaises(ValueError):folders.valid_path(path)
    # ==========================================
    # Function: Verify account scope, labels, snooze, screening, saved searches and local moves.
    # Method: Reopen durable state and query each personal-workflow view.
    # ==========================================
    def test_personal_workflows_and_scope(self):
        from maildesk.demo import seed
        with tempfile.TemporaryDirectory() as root:
            service=MailService(root,demo=True);seed(service.store);store=service.store
            identity=store.list_messages()['items'][0]['id'];raw=store.get(identity,raw=True)['raw'];store.ingest('other','INBOX','1','1',raw)
            self.assertEqual(store.list_messages(folder='INBOX',account='other')['total'],1)
            store.organize(identity,snoozed_until=time.time()+1000,labels=['研究'],reminder=time.time()+50)
            self.assertEqual(store.list_messages(account='demo')['total'],7);self.assertEqual(store.list_messages(view='snoozed')['total'],1)
            self.assertEqual(store.list_messages(view='all',search='label:研究 from:linxia is:unread')['total'],1)
            self.assertEqual(store.list_messages(view='all',search='has:attachment')['total'],1)
            smart=store.save_smart_folder('研究','label:研究',account='demo');self.assertIn(smart,[r['id'] for r in Store(store.path).smart_folders()])
            store.organize(identity,snoozed_until=0,sender_policy='blocked');self.assertEqual(store.list_messages(view='blocked',account='demo')['total'],2)
            store.organize(identity,sender_policy='accepted',aside=True);self.assertEqual(store.list_messages(view='aside')['total'],1)
            store.organize(identity,aside=False,done=True);self.assertEqual(store.list_messages(view='done')['total'],1)
            store.organize(identity,sender_policy='domain:blocked');self.assertGreaterEqual(store.list_messages(view='blocked',account='demo')['total'],2)
            self.assertEqual(store.list_messages(view='blocked',account='other')['total'],0)
            service.move_message(identity,'工作/项目资料');self.assertEqual(store.list_messages(folder='工作/项目资料',account='demo')['total'],1)
            with self.assertRaises(ValueError):service.folder_action('demo','delete','工作/项目资料')
    # ==========================================
    # Function: Preserve message identity and local flags after a folder rename.
    # Method: Re-ingest the same UID generation and reopen saved preferences/templates.
    # ==========================================
    def test_rename_identity_and_preferences(self):
        from maildesk.demo import seed
        with tempfile.TemporaryDirectory() as root:
            store=Store(Path(root)/'db');seed(store);message=store.get(store.list_messages()['items'][0]['id'],raw=True)
            store.rename_folder('demo','INBOX','Renamed');identity=store.ingest('demo','Renamed',message['validity'],message['uid'],message['raw'])
            self.assertEqual(identity,message['id']);self.assertEqual(store.get(identity)['priority'],1)
            template=store.save_template('模板','主题','正文');store.set_preference('signature','签名')
            self.assertEqual(Store(store.path).preference('signature'),'签名');self.assertEqual(store.templates()[0]['id'],template)
    # ==========================================
    # Function: Keep search injections bound and HTML inactive while preserving MIME formatting.
    # Method: Inspect parser outputs and compose a multipart alternative message.
    # ==========================================
    def test_search_and_html(self):
        from maildesk.search import search_terms
        from maildesk.mime import compose,parse_message
        parser=InertRichText();parser.feed('<p>Hello <b>世界</b><script>secret</script><img src="https://tracker" alt="图"></p>')
        self.assertNotIn('secret',''.join(parser.parts));self.assertIn(('bold',6,8),parser.ranges)
        for query in ('from:"unfinished','is:unknown','after:not-a-date'):
            with self.assertRaises(ValueError):search_terms(query)
        clauses,values=search_terms('from:"x\' OR 1=1 --"');self.assertNotIn('OR 1=1',clauses[0]);self.assertIn('OR 1=1',values[0])
        msg,_=compose('me@example.com',{'to':'you@example.com','body':'你好','html':'<b>你好</b>'});parsed=parse_message(msg.as_bytes())
        self.assertEqual(parsed['body'],'你好');self.assertIn('<b>',parsed['html'])

if __name__=='__main__':unittest.main()
