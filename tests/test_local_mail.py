"""Account-free local mail workflows must not contact mail-provider adapters."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from maildesk.config import Account
from maildesk.local_mail import LOCAL_ACCOUNT
from maildesk.mime import compose
from maildesk.service import MailService

# ==========================================
# Function: Validate real local workflows with all provider transports forbidden.
# Method: Use isolated on-disk databases and fail immediately on any attempted provider call.
# ==========================================
class LocalMailTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare a reusable synthetic EML and isolated application data.
    # Method: Patch network boundaries instead of mocking the local store operations under test.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        message,_=compose('friend@example.com',{'to':'me@example.com','subject':'离线邮件','body':'本地保存','attachments':[{'name':'note.txt','data':b'local attachment'}]},'<local-test@example.com>')
        self.eml=self.root/'offline.eml';self.eml.write_bytes(message.as_bytes())
        self.blockers=[]
        for target in ('maildesk.transport.imap_connection','maildesk.transport.deliver','maildesk.transport.set_seen','maildesk.folders.mutate_folder','maildesk.folders.transfer','maildesk.folders.delete_message'):
            blocker=patch(target,side_effect=AssertionError('Local operation attempted network: '+target));blocker.start();self.blockers.append(blocker)
        self.service=MailService(self.root/'data')

    # ==========================================
    # Function: Stop owned resources and restore adapter boundaries.
    # Method: Close the optional local worker before removing the temporary database.
    # ==========================================
    def tearDown(self):
        self.service.close()
        for blocker in reversed(self.blockers):blocker.stop()
        self.temp.cleanup()

    # ==========================================
    # Function: Import, organize, copy, move, rename and remove local mail without an account.
    # Method: Verify persisted content, metadata and hierarchy across real store operations.
    # ==========================================
    def test_account_free_folder_workflow(self):
        service=self.service;store=service.store
        self.assertEqual(service.accounts,{})
        self.assertEqual(store.special_folder(LOCAL_ACCOUNT,'inbox'),'INBOX')
        identity=service.import_eml(self.eml)
        self.assertEqual(service.import_eml(self.eml),identity)
        service.folder_action(LOCAL_ACCOUNT,'create','工作/研究')
        self.assertIn('工作',[r['folder'] for r in store.list_folders(LOCAL_ACCOUNT)])
        service.update(identity,{'seen':True,'pinned':True})
        store.organize(identity,labels=['离线'],reminder=time.time()+3600)
        copied=service.move_message(identity,'工作/研究',copy=True)
        self.assertEqual(store.list_messages(folder='INBOX',account=LOCAL_ACCOUNT)['total'],1)
        self.assertIn('离线',store.get(copied)['labels']);self.assertTrue(store.get(copied)['pinned'])
        service.folder_action(LOCAL_ACCOUNT,'rename','工作','资料')
        self.assertEqual(store.get(copied)['folder'],'资料/研究')
        service.move_message(identity,special='archive')
        self.assertEqual(store.list_messages(folder='Archive',account=LOCAL_ACCOUNT)['total'],1)
        self.assertEqual(store.list_messages(folder='INBOX',account=LOCAL_ACCOUNT)['total'],0)
        with self.assertRaises(ValueError):service.folder_action(LOCAL_ACCOUNT,'delete','资料/研究')
        service.permanently_delete(copied);service.folder_action(LOCAL_ACCOUNT,'delete','资料/研究')
        service.folder_action(LOCAL_ACCOUNT,'delete','资料')
        with self.assertRaises(ValueError):service.folder_action(LOCAL_ACCOUNT,'delete','INBOX')
        service.sync();service.start();service.close()

    # ==========================================
    # Function: Persist local drafts while refusing to enqueue them as outgoing mail.
    # Method: Reopen the database and migrate a chosen draft to an explicitly configured account.
    # ==========================================
    def test_local_draft_persistence_and_send_guard(self):
        payload={'account':LOCAL_ACCOUNT,'to':'you@example.com','subject':'本地草稿','body':'离线编辑'}
        result=self.service.compose(payload);identity=result['id']
        self.assertEqual(result['state'],'draft')
        with self.assertRaisesRegex(ValueError,'本地草稿不能发送'):self.service.compose({**payload,'id':identity},send=True)
        reopened=MailService(self.root/'data')
        self.assertEqual(reopened.store.job(identity)['draft']['body'],'离线编辑')
        self.assertFalse(reopened.process_one())
        reopened.accounts['real']=Account('real','me@example.com','mail.example.com','mail.example.com')
        updated=reopened.compose({**payload,'account':'real','id':identity})
        self.assertEqual(updated['id'],identity);self.assertEqual(reopened.store.job(identity)['account'],'real')
        reopened.close()

    # ==========================================
    # Function: Prevent local initialization from resetting data and favorites at restart.
    # Method: Reopen a real cache while retaining a separate provider folder of the same name.
    # ==========================================
    def test_namespace_and_restart_preserve_user_state(self):
        store=self.service.store
        with self.assertRaises(ValueError):Account(LOCAL_ACCOUNT,'me@example.com','mail.example.com','mail.example.com')
        self.service.folder_action(LOCAL_ACCOUNT,'create','个人')
        store.folder_options(LOCAL_ACCOUNT,'个人',favorite=True,color='purple')
        store.save_folders('remote',[{'name':'个人','special':'','selectable':True}])
        identity=self.service.import_eml(self.eml,'个人')
        reopened=MailService(self.root/'data')
        local=next(r for r in reopened.store.list_folders(LOCAL_ACCOUNT) if r['folder']=='个人')
        self.assertEqual(local['favorite'],1);self.assertEqual(local['color'],'purple')
        self.assertEqual(reopened.store.get(identity)['folder'],'个人')
        self.assertEqual(reopened.store.list_messages(folder='个人',account='remote')['total'],0)
        reopened.folder_action(LOCAL_ACCOUNT,'rename','个人','本地个人')
        self.assertEqual(reopened.store.list_folders('remote')[0]['folder'],'个人')
        reopened.close()

    # ==========================================
    # Function: Reject malformed local paths and unusable imports before writing message records.
    # Method: Exercise validation against missing destinations, invalid MIME and bounded file size.
    # ==========================================
    def test_local_path_and_import_guards(self):
        for path in ('a//b','/root','@private'):
            with self.assertRaises(ValueError):self.service.folder_action(LOCAL_ACCOUNT,'create',path)
        with self.assertRaises(ValueError):self.service.import_eml(self.eml,'missing')
        with patch('maildesk.local_mail.MAX_MESSAGE_BYTES',1):
            with self.assertRaisesRegex(ValueError,'30 MiB'):self.service.import_eml(self.eml)
        self.assertEqual(self.service.store.list_messages(account=LOCAL_ACCOUNT)['total'],0)

if __name__=='__main__':unittest.main()
