"""Sign-in boundaries: isolated verification, explicit commit and native OAuth grants."""
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock,patch
from urllib.parse import parse_qs,urlsplit,urlencode
from urllib.request import urlopen

from maildesk.account_login import (LoginError,PROVIDERS,browser_authorize,decode_oauth,
    detect_provider,encode_oauth,import_google_client,verify_login)
from maildesk.config import Account
from maildesk.credentials import authenticated,session_secret,refresh_saver
from maildesk.desktop_profile import DesktopProfile

# ==========================================
# Function: Exercise real persistence and loopback OAuth boundaries in disposable profiles.
# Method: Mock only provider TLS/token responses while keeping state/PKCE/callback code real.
# ==========================================
class AccountLoginTests(unittest.TestCase):
    # ==========================================
    # Function: Build a fresh profile with an existing trusted local login.
    # Method: Save a synthetic credential and isolate each test's account fingerprint.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.profile=DesktopProfile(config=self.root/'accounts.json',data=self.root/'mail')
        self.account=Account('account-'+self.root.name.replace('_','-'),'person@example.invalid','imap.example.invalid','smtp.example.invalid')
        self.profile.save_account(asdict(self.account));self.profile.vault.save(self.account,'accepted-before')
        session_secret(self.account,'accepted-before');self.before=self.profile.config.read_bytes()

    # ==========================================
    # Function: Forget only synthetic in-process credentials and temporary files.
    # Method: Clear observers and OAuth refresh callbacks before removing the profile.
    # ==========================================
    def tearDown(self):
        session_secret(self.account,'');authenticated(self.account,clear=True);refresh_saver(self.account,clear=True)
        self.temp.cleanup()

    # ==========================================
    # Function: Supply authenticated provider doubles without performing any mail submission.
    # Method: Return successful IMAP tagged responses and SMTP AUTH from adapter-level mocks.
    # ==========================================
    def providers(self):
        imap=MagicMock();imap.login.return_value=('OK',[]);imap.noop.return_value=('OK',[])
        imap.authenticate.return_value=('OK',[])
        smtp=MagicMock();smtp.docmd.return_value=(235,b'accepted')
        return imap,smtp

    # ==========================================
    # Function: Verify the callback socket is closed despite WSL forwarding connection ACKs.
    # Method: Require native Windows connection refusal or no Linux LISTEN entry, plus no readable HTTP response.
    # ==========================================
    def assert_listener_closed(self,port):
        listening=True;deadline=time.monotonic()+.3
        while listening and time.monotonic()<deadline:
            if os.name=='nt':
                with socket.socket() as probe:
                    probe.settimeout(.1);listening=probe.connect_ex(('127.0.0.1',port))==0
            else:
                listening=any(int(row.split()[1].rsplit(':',1)[1],16)==port and row.split()[3]=='0A'
                    for table in ('/proc/net/tcp','/proc/net/tcp6') for row in Path(table).read_text().splitlines()[1:])
            if listening:time.sleep(.01)
        self.assertFalse(listening)
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=.3) as connection:
                connection.sendall(b'GET / HTTP/1.0\r\n\r\n')
                self.assertEqual(connection.recv(20),b'')
        except OSError:pass

    # ==========================================
    # Function: Keep successful trials completely isolated until final native confirmation.
    # Method: Observe both checks, existing globals, encrypted vault and config before commit.
    # ==========================================
    def test_probe_isolated_and_commit_explicit(self):
        imap,smtp=self.providers();observer=MagicMock();authenticated(self.account,observer);stages=[]
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):
            receipt=verify_login(self.account,'candidate',progress=lambda *args:stages.append(args))
        self.assertEqual(stages,[('imap','checking'),('imap','verified'),('smtp','checking'),('smtp','verified')])
        self.assertEqual(session_secret(self.account),'accepted-before');observer.assert_not_called()
        self.assertEqual(self.profile.vault.get(self.account),'accepted-before');self.assertEqual(self.profile.config.read_bytes(),self.before)
        smtp.sendmail.assert_not_called();smtp.mail.assert_not_called();smtp.rcpt.assert_not_called();smtp.data.assert_not_called()
        self.profile.commit_verified_login(self.account,'candidate',receipt)
        self.assertEqual(self.account.secret(),'candidate');self.assertEqual(self.profile.vault.get(self.account),'candidate')
        self.assertNotIn(b'candidate',self.profile.vault.records.read_bytes())

    # ==========================================
    # Function: Preserve a good login when outgoing authentication rejects a trial.
    # Method: Include candidate material in a fake provider exception and verify redaction.
    # ==========================================
    def test_smtp_failure_redacts_and_preserves(self):
        imap,smtp=self.providers();smtp.login.side_effect=RuntimeError('candidate secret response')
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):
            with self.assertRaises(LoginError) as error:verify_login(self.account,'candidate')
        self.assertNotIn('candidate',str(error.exception));self.assertIn('发件',str(error.exception))
        self.assertEqual(session_secret(self.account),'accepted-before');self.assertEqual(self.profile.vault.get(self.account),'accepted-before')
        self.assertEqual(self.profile.config.read_bytes(),self.before)

    # ==========================================
    # Function: Stop after incoming authentication when a user cancels before outgoing AUTH.
    # Method: Set the actual attempt event from the first verified progress notification.
    # ==========================================
    def test_cancel_between_stages_does_not_touch_smtp(self):
        imap,smtp=self.providers();cancel=threading.Event()
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp) as outgoing:
            with self.assertRaises(LoginError):verify_login(self.account,'candidate',cancel,lambda stage,status:cancel.set() if status=='verified' else None)
        outgoing.assert_not_called();self.assertEqual(self.profile.config.read_bytes(),self.before)

    # ==========================================
    # Function: Bind confirmation to the exact account, credential and recent successful attempt.
    # Method: Alter each receipt input and require unchanged persistent account state.
    # ==========================================
    def test_wrong_or_stale_receipt_cannot_commit(self):
        imap,smtp=self.providers()
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):receipt=verify_login(self.account,'candidate')
        for account,secret,proof in [(self.account,'different',receipt),(replace(self.account,imap_host='changed.invalid'),'candidate',receipt),
                                      (self.account,'candidate',{**receipt,'verified_at':time.time()-601})]:
            with self.assertRaises(ValueError):self.profile.commit_verified_login(account,secret,proof)
        self.assertEqual(self.profile.config.read_bytes(),self.before);self.assertEqual(self.profile.vault.get(self.account),'accepted-before')

    # ==========================================
    # Function: Retain the previous encrypted login when account configuration cannot commit.
    # Method: Fail atomic configuration writing after encrypted staging and require rollback.
    # ==========================================
    def test_commit_rollback_and_session_only(self):
        imap,smtp=self.providers()
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):receipt=verify_login(self.account,'candidate')
        with patch.object(self.profile,'write_accounts',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.profile.commit_verified_login(self.account,'candidate',receipt)
        self.assertEqual(self.profile.vault.get(self.account),'accepted-before');self.assertEqual(self.account.secret(),'accepted-before')
        self.profile.commit_verified_login(self.account,'candidate',receipt,remember=False)
        self.assertEqual(self.profile.vault.get(self.account),'');self.assertEqual(self.account.secret(),'candidate')

    # ==========================================
    # Function: Keep consumer and work Microsoft templates distinct and secure.
    # Method: Verify exact provider transport endpoints, encryption and domain detection.
    # ==========================================
    def test_provider_templates(self):
        self.assertEqual(detect_provider('a@gmail.com'),'gmail');self.assertEqual(detect_provider('a@HOTMAIL.COM'),'outlook')
        self.assertEqual(detect_provider('a@sjtu.edu.cn'),'other')
        workspace=replace(self.account,email='person@workspace.invalid',imap_host='imap.gmail.com',smtp_host='smtp.gmail.com',auth='oauth2')
        self.assertEqual(detect_provider(workspace.email,workspace),'gmail')
        self.assertEqual(PROVIDERS['outlook']['smtp_host'],'smtp-mail.outlook.com')
        self.assertEqual(PROVIDERS['microsoft365']['smtp_host'],'smtp.office365.com')
        self.assertEqual(PROVIDERS['outlook']['smtp_security'],'starttls');self.assertEqual(PROVIDERS['outlook']['smtp_port'],587)

    # ==========================================
    # Function: Prevent token exfiltration through edited advanced server fields.
    # Method: Reject a refreshable Google grant before any connection to non-Google endpoints.
    # ==========================================
    def test_oauth_bundle_provider_binding(self):
        bundle=encode_oauth('google','own-client',{'access_token':'access','expires_at':time.time()+3600})
        with patch('maildesk.transport.imaplib.IMAP4_SSL') as connection:
            with self.assertRaises(LoginError):verify_login(replace(self.account,auth='oauth2'),bundle)
        connection.assert_not_called()

    # ==========================================
    # Function: Verify real callback state/path and code-to-PKCE binding without external traffic.
    # Method: Send one invalid local callback followed by the valid callback to the actual listener.
    # ==========================================
    def test_browser_pkce_state_and_callback(self):
        seen={};threads=[]
        # ==========================================
        # Function: Simulate a provider redirect in a separate browser thread.
        # Method: Exercise the real ephemeral loopback HTTP server with invalid and valid states.
        # ==========================================
        def open_browser(url):
            query=parse_qs(urlsplit(url).query);seen.update(query)
            # ==========================================
            # Function: Submit local callback requests without logging code-bearing URLs.
            # Method: Reject the first bad state and complete the second authenticated callback.
            # ==========================================
            def redirect():
                from urllib.error import HTTPError
                wrong=query['redirect_uri'][0]+'?'+urlencode({'state':'wrong','code':'not-accepted'})
                try:urlopen(wrong,timeout=2)
                except HTTPError as error:seen['bad_status']=error.code;error.close()
                target=query['redirect_uri'][0]+'?'+urlencode({'state':query['state'][0],'code':'synthetic-code'})
                with urlopen(target,timeout=2) as response:seen['accepted_status']=response.status
            thread=threading.Thread(target=redirect);threads.append(thread);thread.start();return True
        token={'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_at':time.time()+3600}
        with patch('maildesk.account_login.token_request',return_value=token) as exchange:
            bundle=browser_authorize('google','own-client','person@gmail.com',opener=open_browser,timeout=4)
        for thread in threads:thread.join(3)
        request=exchange.call_args.args[1];verifier=request['code_verifier']
        import base64,hashlib
        self.assertEqual(seen['code_challenge'][0],base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
        self.assertEqual(seen['code_challenge_method'],['S256']);self.assertEqual(request['code'],'synthetic-code')
        self.assertEqual(seen['bad_status'],400);self.assertEqual(seen['accepted_status'],200)
        self.assertEqual(decode_oauth(bundle)['refresh_token'],'synthetic-refresh')
        port=urlsplit(seen['redirect_uri'][0]).port
        self.assert_listener_closed(port)

    # ==========================================
    # Function: Close a cancelled browser attempt without a token exchange or listener leak.
    # Method: Cancel during browser open and require the temporary port to be unreachable.
    # ==========================================
    def test_browser_cancel_closes_listener(self):
        cancel=threading.Event();seen={}
        # ==========================================
        # Function: Cancel the fake browser handoff immediately after observing its callback.
        # Method: Keep the callback only in test memory and return browser-open success.
        # ==========================================
        def opener(url):seen.update(parse_qs(urlsplit(url).query));cancel.set();return True
        with patch('maildesk.account_login.token_request') as exchange:
            with self.assertRaises(LoginError):browser_authorize('microsoft','own-client',cancel=cancel,opener=opener)
        exchange.assert_not_called()
        self.assert_listener_closed(urlsplit(seen['redirect_uri'][0]).port)

    # ==========================================
    # Function: Avoid opening a browser when no legitimate application registration is supplied.
    # Method: Validate Client ID before creating a listener or invoking the browser opener.
    # ==========================================
    def test_missing_client_id_never_opens_browser(self):
        opener=MagicMock()
        with self.assertRaises(LoginError):browser_authorize('google','',opener=opener)
        opener.assert_not_called()

    # ==========================================
    # Function: Reject web-client JSON and provider-controlled token URLs during config import.
    # Method: Require installed-client data and retain only the ID and optional local secret.
    # ==========================================
    def test_desktop_client_import(self):
        file=self.root/'client.json';file.write_text(json.dumps({'web':{'client_id':'web'}}))
        with self.assertRaises(LoginError):import_google_client(file)
        file.write_text(json.dumps({'installed':{'client_id':'own-client','client_secret':'private-test','token_uri':'https://evil.invalid/token'}}))
        values=import_google_client(file);self.assertEqual(set(values),{'provider','client_id','client_secret'})

    # ==========================================
    # Function: Refresh concurrent expired sessions once and persist refresh-token rotation privately.
    # Method: Share the per-account refresh lock across five actual worker threads.
    # ==========================================
    def test_refresh_rotation_concurrency_and_restart(self):
        account=replace(self.account,auth='oauth2');self.account=account
        initial=encode_oauth('google','own-client',{'access_token':'expired','refresh_token':'old-refresh','expires_at':time.time()-1})
        self.profile.save_account(asdict(account));self.profile.vault.save(account,initial);session_secret(account,initial)
        refresh_saver(account,self.profile.vault.save);results=[]
        token={'access_token':'new-access','refresh_token':'rotated-refresh','expires_at':time.time()+3600}
        with patch('maildesk.account_login.token_request',return_value=token) as exchange:
            threads=[threading.Thread(target=lambda:results.append(account.secret())) for _ in range(5)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(3)
        exchange.assert_called_once();self.assertEqual(results,['new-access']*5)
        saved=self.profile.vault.get(account);self.assertEqual(decode_oauth(saved)['refresh_token'],'rotated-refresh')
        self.assertNotIn(b'rotated-refresh',self.profile.vault.records.read_bytes());session_secret(account,'')
        fresh=DesktopProfile(config=self.profile.config);fresh.restore_credentials(fresh.accounts());self.assertEqual(account.secret(),'new-access')

    # ==========================================
    # Function: Keep revoked grants from falling back to expired access tokens.
    # Method: Fail refresh and require a safe relogin error without changing encrypted tokens.
    # ==========================================
    def test_refresh_failure_does_not_replace_grant(self):
        account=replace(self.account,auth='oauth2');self.account=account
        initial=encode_oauth('microsoft','own-client',{'access_token':'expired','refresh_token':'revoked','expires_at':time.time()-1})
        session_secret(account,initial)
        with patch('maildesk.account_login.token_request',side_effect=LoginError('请重新登录')):
            with self.assertRaises(LoginError):account.secret()
        self.assertEqual(session_secret(account),initial)

    # ==========================================
    # Function: Prevent a late refresh from reviving a deliberately forgotten grant.
    # Method: Pause token HTTP in a worker, forget immediately, then release its response.
    # ==========================================
    def test_forget_during_refresh_does_not_wait_or_resurrect(self):
        account=replace(self.account,auth='oauth2');self.account=account
        initial=encode_oauth('google','own-client',{'access_token':'expired','refresh_token':'old','expires_at':time.time()-1})
        self.profile.save_account(asdict(account));self.profile.vault.save(account,initial);session_secret(account,initial)
        refresh_saver(account,self.profile.vault.save);entered=threading.Event();release=threading.Event();outcomes=[]
        # ==========================================
        # Function: Hold a synthetic token response while native account state changes.
        # Method: Use finite events without acquiring the accepted-credential commit lock.
        # ==========================================
        def exchange(*unused):
            entered.set();release.wait(2)
            return {'access_token':'late','refresh_token':'late-refresh','expires_at':time.time()+3600}
        # ==========================================
        # Function: Resolve a refresh and retain only its exception type for assertions.
        # Method: Avoid any test logging of token or HTTP response values.
        # ==========================================
        def refresh():
            try:account.secret();outcomes.append('resolved')
            except LoginError:outcomes.append('cancelled')
        with patch('maildesk.account_login.token_request',side_effect=exchange):
            thread=threading.Thread(target=refresh);thread.start();self.assertTrue(entered.wait(2))
            before=time.monotonic();self.profile.forget_credential(account);self.assertLess(time.monotonic()-before,.5)
            release.set();thread.join(3)
        self.assertEqual(outcomes,['cancelled']);self.assertEqual(session_secret(account),'');self.assertEqual(self.profile.vault.get(account),'')

    # ==========================================
    # Function: Preserve a confirmed changed connection against an older in-flight refresh.
    # Method: Replace the same logical account under a new identity before old HTTP completes.
    # ==========================================
    def test_changed_connection_rejects_old_refresh_persistence(self):
        old=replace(self.account,auth='oauth2');self.account=old
        initial=encode_oauth('google','own-client',{'access_token':'expired','refresh_token':'old','expires_at':time.time()-1})
        self.profile.save_account(asdict(old));self.profile.vault.save(old,initial);session_secret(old,initial)
        refresh_saver(old,self.profile.vault.save)
        replacement=replace(old,auth='password',imap_host='new-imap.invalid');imap,smtp=self.providers()
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):
            receipt=verify_login(replacement,'new-candidate')
        entered=threading.Event();release=threading.Event();outcomes=[]
        # ==========================================
        # Function: Delay one old-identity refresh until its replacement commits.
        # Method: Return a token only after the test releases the synthetic network boundary.
        # ==========================================
        def exchange(*unused):
            entered.set();release.wait(2)
            return {'access_token':'obsolete','expires_at':time.time()+3600}
        # ==========================================
        # Function: Observe obsolete refresh rejection without exposing credential values.
        # Method: Record the public LoginError outcome instead of the token response.
        # ==========================================
        def refresh():
            try:old.secret();outcomes.append('resolved')
            except LoginError:outcomes.append('cancelled')
        with patch('maildesk.account_login.token_request',side_effect=exchange):
            thread=threading.Thread(target=refresh);thread.start();self.assertTrue(entered.wait(2))
            self.profile.commit_verified_login(replacement,'new-candidate',receipt)
            release.set();thread.join(3)
        self.assertEqual(outcomes,['cancelled']);self.assertEqual(self.profile.vault.get(replacement),'new-candidate')
        self.assertEqual(self.profile.vault.get(old),'');session_secret(replacement,'');refresh_saver(replacement,clear=True)

    # ==========================================
    # Function: Stop a denied provider consent response without exchanging any code.
    # Method: Use the real loopback state check and verify token HTTP was never called.
    # ==========================================
    def test_browser_denied_consent_no_exchange(self):
        threads=[]
        # ==========================================
        # Function: Deliver a synthetic denial from a browser callback thread.
        # Method: Include valid state and a fixed provider error code over local HTTP only.
        # ==========================================
        def opener(url):
            query=parse_qs(urlsplit(url).query)
            # ==========================================
            # Function: Return a denied consent callback to the actual transient listener.
            # Method: Close the HTTP response immediately without retaining its URL.
            # ==========================================
            def redirect():
                with urlopen(query['redirect_uri'][0]+'?'+urlencode({'state':query['state'][0],'error':'access_denied'}),timeout=2):pass
            thread=threading.Thread(target=redirect);threads.append(thread);thread.start();return True
        with patch('maildesk.account_login.token_request') as exchange:
            with self.assertRaises(LoginError):browser_authorize('microsoft','own-client',opener=opener,timeout=3)
        for thread in threads:thread.join(3)
        exchange.assert_not_called()

    # ==========================================
    # Function: Keep another account's rotated grant during a failed candidate commit.
    # Method: Rotate a separate encrypted envelope at the failing configuration boundary.
    # ==========================================
    def test_rollback_preserves_other_account_rotation(self):
        other=replace(self.account,id='separate-account',email='other@example.invalid')
        self.profile.vault.save(other,'old-other');imap,smtp=self.providers()
        with patch('maildesk.transport.imaplib.IMAP4_SSL',return_value=imap),patch('maildesk.transport.smtplib.SMTP_SSL',return_value=smtp):receipt=verify_login(self.account,'candidate')
        # ==========================================
        # Function: Reenter the private vault for an unrelated rotation before disk failure.
        # Method: Write only the second account's envelope, then simulate config commit failure.
        # ==========================================
        def fail_config(accounts):
            self.profile.vault.save(other,'rotated-other');raise OSError('simulated config failure')
        with patch.object(self.profile,'write_accounts',side_effect=fail_config):
            with self.assertRaises(OSError):self.profile.commit_verified_login(self.account,'candidate',receipt)
        self.assertEqual(self.profile.vault.get(self.account),'accepted-before')
        self.assertEqual(self.profile.vault.get(other),'rotated-other')

if __name__=='__main__':unittest.main()
