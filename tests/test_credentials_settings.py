"""Credential restart/authentication boundaries and dark-reading regressions."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock

from maildesk.credentials import aes_gcm,session_secret
from maildesk.desktop_profile import DesktopProfile
from maildesk.document_content import reader_document
from maildesk.service import MailService
from maildesk.transport import imap_connection

# ==========================================
# Function: Exercise real encryption/storage and provider authentication boundaries.
# Method: Use disposable configs and mocked authenticated IMAP transports without real accounts.
# ==========================================
class CredentialSettingsTests(unittest.TestCase):
    # ==========================================
    # Function: Create an isolated mailbox configuration and fresh credential namespace.
    # Method: Use a unique config path while keeping all network operations mocked.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.profile=DesktopProfile(config=self.root/'accounts.json',data=self.root/'data')
        values={'id':'vault-test','email':'test@example.com','imap_host':'imap.example.com',
                'smtp_host':'smtp.example.com','secret_env':'UNSET_VAULT_TEST'}
        self.account=self.profile.save_account(values)[0];session_secret(self.account,'')

    # ==========================================
    # Function: Drop process-only credentials between regression scenarios.
    # Method: Forget only the disposable account state and remove its temporary directory.
    # ==========================================
    def tearDown(self):
        from maildesk.credentials import authenticated
        session_secret(self.account,'');authenticated(self.account,clear=True);self.temp.cleanup()

    # ==========================================
    # Function: Validate AES-256-GCM against a standard zero-key/nonce plaintext vector.
    # Method: Compare ciphertext/tag and require authenticated recovery of original bytes.
    # ==========================================
    def test_aes_known_vector(self):
        ciphertext,tag=aes_gcm(bytes(32),bytes(12),bytes(16))
        self.assertEqual(ciphertext.hex(),'cea7403d4d606b6e074ec5d3baf39d18')
        self.assertEqual(tag.hex(),'d0d1c8a799996bf0265b98b5d48ab919')
        self.assertEqual(aes_gcm(bytes(32),bytes(12),ciphertext,tag=tag),bytes(16))

    # ==========================================
    # Function: Reject altered ciphertext, tags and account metadata without plaintext.
    # Method: Change each authenticated component and require explicit GCM failure.
    # ==========================================
    def test_tamper_and_cross_account_rejected(self):
        ciphertext,tag=aes_gcm(bytes(32),bytes(12),b'credential',b'account-one')
        for data,aad,mac in [(bytes([ciphertext[0]^1])+ciphertext[1:],b'account-one',tag),
                             (ciphertext,b'account-two',tag),(ciphertext,b'account-one',bytes(16))]:
            with self.assertRaises(ValueError):aes_gcm(bytes(32),bytes(12),data,aad,mac)

    # ==========================================
    # Function: Keep unverified credentials in memory and out of all persistent settings.
    # Method: Stage a desktop password without a successful login and inspect files/environment.
    # ==========================================
    def test_staged_secret_not_persisted_or_exported(self):
        self.profile.stage_credential(self.account,'test-only-secret')
        self.assertEqual(self.account.secret(),'test-only-secret')
        self.assertNotIn('UNSET_VAULT_TEST',os.environ)
        self.assertFalse(self.profile.vault.records.exists())
        self.assertNotIn('test-only-secret',self.profile.config.read_text())

    # ==========================================
    # Function: Persist only an IMAP login accepted after TLS authentication.
    # Method: Drive the actual connection adapter through both rejected and accepted responses.
    # ==========================================
    def test_only_successful_provider_login_saves(self):
        self.profile.stage_credential(self.account,'test-only-secret')
        client=MagicMock();client.login.return_value=('NO',[b'rejected'])
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=client):
            with self.assertRaises(RuntimeError):
                with imap_connection(self.account):pass
            self.assertFalse(self.profile.vault.records.exists())
            client.login.return_value=('OK',[b'accepted'])
            with imap_connection(self.account):pass
        self.assertEqual(self.profile.vault.get(self.account),'test-only-secret')
        self.assertNotIn(self.account.id,self.profile.pending)

    # ==========================================
    # Function: Restore remembered credentials in a completely fresh application process.
    # Method: Reconstruct the profile and compare decrypted values without printing them.
    # ==========================================
    def test_restart_private_encrypted_store(self):
        self.profile.stage_credential(self.account,'test-only-secret');self.profile.confirm_login(self.account)
        files=(self.profile.vault.records,self.profile.config) if os.name=='nt' else (self.profile.vault.keyfile,self.profile.vault.records,self.profile.config)
        for file in files:
            if os.name!='nt':self.assertEqual(file.stat().st_mode&0o777,0o600)
            self.assertNotIn(b'test-only-secret',file.read_bytes())
        code='import sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[1]))+');from maildesk.desktop_profile import DesktopProfile; import sys; p=DesktopProfile(config=sys.argv[1]); a=p.accounts(); p.restore_credentials(a); assert a[0].secret()=="test-only-secret"; from maildesk.desktop_forms import ask_credential; ask_credential(None,a[0])'
        result=subprocess.run([sys.executable,'-c',code,str(self.profile.config)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr.decode())

    # ==========================================
    # Function: Keep a previously valid remembered password when a replacement is unverified.
    # Method: Save an accepted value and then stage a different failed-attempt candidate.
    # ==========================================
    def test_failed_replacement_preserves_saved_login(self):
        self.profile.stage_credential(self.account,'old-accepted');self.profile.confirm_login(self.account)
        self.profile.stage_credential(self.account,'new-unverified')
        self.assertEqual(self.profile.vault.get(self.account),'old-accepted')
        changed=replace(self.account,imap_host='changed.example.com')
        self.assertEqual(self.profile.vault.get(changed),'')

    # ==========================================
    # Function: Honor session-only and forget actions without touching downloaded mail.
    # Method: Save/forget encrypted envelopes and remove connection settings around a real local store.
    # ==========================================
    def test_forget_remove_and_session_only(self):
        service=MailService(self.root/'mail',[self.account])
        identity=service.store.ingest(self.account.id,'INBOX','1','1',b'From: a@example.com\r\nSubject: keep\r\n\r\nbody')
        self.profile.stage_credential(self.account,'saved');self.profile.confirm_login(self.account)
        self.profile.stage_credential(self.account,'temporary',False);self.profile.confirm_login(self.account)
        self.assertFalse(self.profile.vault.records.exists());self.assertEqual(self.account.secret(),'temporary')
        self.profile.remove_account(self.account)
        self.assertEqual(self.profile.accounts(),[]);self.assertEqual(session_secret(self.account),'')
        self.assertEqual(service.store.get(identity)['subject'],'keep')

    # ==========================================
    # Function: Reject unsafe credential file permissions and a lost device key.
    # Method: Modify only disposable vault files and require failures without key regeneration.
    # ==========================================
    @unittest.skipIf(os.name=='nt','POSIX permissions/device key; Windows DPAPI authenticity covered separately')
    def test_unsafe_or_missing_key_fails_closed(self):
        self.profile.vault.save(self.account,'saved');self.profile.vault.records.chmod(0o644)
        with self.assertRaises(ValueError):self.profile.vault.get(self.account)
        self.profile.vault.records.chmod(0o600);self.profile.vault.keyfile.unlink()
        with self.assertRaises(ValueError):self.profile.vault.get(self.account)
        self.assertFalse(self.profile.vault.keyfile.exists())

    # ==========================================
    # Function: Keep pause and synchronization interval settings effective in the service.
    # Method: Persist preferences then inspect actual provider invocation boundaries.
    # ==========================================
    def test_pause_interval_and_sender_name(self):
        service=MailService(self.root/'mail',[replace(self.account,display_name='测试发件人')])
        service.store.set_preference('sync_interval',300);service.store.set_preference('paused_accounts',[self.account.id])
        restarted=MailService(self.root/'mail',[self.account]);self.assertEqual(restarted.interval,300)
        with patch('maildesk.transport.sync_account',return_value={}) as sync:
            restarted.sync();sync.assert_not_called()
            service.store.set_preference('paused_accounts',[]);restarted.sync();sync.assert_called_once()
        result=service.compose({'account':self.account.id,'to':'b@example.com','subject':'name','body':'hello'},send=True)
        with service.store.db() as database:
            raw=database.execute('SELECT raw FROM jobs WHERE id=?',(result['id'],)).fetchone()[0]
        self.assertIn('=?utf-8?',bytes(raw).decode().lower())

    # ==========================================
    # Function: Keep black author fonts and aggressive CSS resets readable in dark HTML.
    # Method: Verify conflicting color/style rules are removed while structure and text survive.
    # ==========================================
    def test_dark_html_palette_and_original_light(self):
        source='<style>p{color:black!important}*{all:initial}</style><p style="color:#000!important;background:white;all:initial;font-weight:bold;text-align:center"><font color="black">同学你好</font></p>'
        dark=reader_document(source,font_size=18)
        self.assertNotIn('color:black',dark);self.assertNotIn('color:#000',dark);self.assertNotIn('all:initial',dark)
        self.assertIn('同学你好',dark);self.assertIn('font-weight:bold',dark);self.assertIn('font:18px',dark)
        light=reader_document(source,dark=False);self.assertIn('color:black',light)
        self.assertIn('color:#000',reader_document(source,adapt_dark=False))

if __name__=='__main__':unittest.main()
