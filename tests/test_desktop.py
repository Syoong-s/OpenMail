"""Headless regressions for native-desktop profiles and Linux packaging boundaries."""
import json
import os
from pathlib import Path,PurePosixPath
import tempfile
import unittest
from unittest.mock import patch

from maildesk.desktop_profile import DesktopProfile
from maildesk.desktop_install import desktop_entry, desktop_exec, install_user
from maildesk.service import MailService

# ==========================================
# Function: Check native desktop behavior without needing a display server.
# Method: Isolate XDG directories and validate settings, secrets and import actions.
# ==========================================
class DesktopTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare clean XDG settings and mailbox data directories.
    # Method: Override only the test process environment and use temporary native paths.
    # ==========================================
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'XDG_CONFIG_HOME':str(self.root/'config'), 'XDG_DATA_HOME':str(self.root/'data'),'APPDATA':str(self.root/'config'),'LOCALAPPDATA':str(self.root/'data')})
        self.environment.start()
        self.values = {'id':'work','email':'you@example.com','imap_host':'imap.example.com','smtp_host':'smtp.example.com','secret_env':'TEST_DESKTOP_SECRET','folders':['INBOX']}

    # ==========================================
    # Function: Remove settings and restore the caller's environment.
    # Method: Stop the environment patch before deleting temporary files.
    # ==========================================
    def tearDown(self):
        from maildesk.credentials import session_secret,authenticated
        for account in DesktopProfile().accounts():
            session_secret(account,'');authenticated(account,clear=True)
        os.environ.pop('TEST_DESKTOP_SECRET',None)
        self.environment.stop()
        self.temp.cleanup()

    # ==========================================
    # Function: Verify XDG paths and single-instance application identities.
    # Method: Compare default live, demo and custom-data profiles.
    # ==========================================
    def test_profile_paths_and_identity(self):
        profile, demo = DesktopProfile(), DesktopProfile(demo=True)
        self.assertEqual(profile.config,self.root/'config/telemail/accounts.json')
        self.assertEqual(profile.data,self.root/'data/telemail/live')
        self.assertNotEqual(profile.data,demo.data)
        self.assertEqual(profile.application_id,'org.telemail.Desktop')
        self.assertEqual(DesktopProfile(data=self.root/'one').application_id,DesktopProfile(data=self.root/'one').application_id)
        self.assertNotEqual(DesktopProfile(data=self.root/'one').application_id,DesktopProfile(data=self.root/'two').application_id)

    # ==========================================
    # Function: Isolate TeleMail from every automatically discovered Maildesk profile.
    # Method: Seed old account/data/locator files and require a clean independent TeleMail profile without modifying them.
    # ==========================================
    def test_renamed_app_ignores_maildesk_profile(self):
        old_config = self.root/'config/maildesk/accounts.json'
        old_config.parent.mkdir(parents=True)
        old_config.write_text(json.dumps({'accounts': [self.values]}))
        old_locator = old_config.parent/'storage-locations.json'
        old_locator.write_text('invalid old locator; TeleMail must not read it')
        old_data = self.root/'data/maildesk/live'
        old_data.mkdir(parents=True)
        old_mail = old_data/'mail.sqlite'
        old_mail.write_bytes(b'old mailbox and draft bytes')
        snapshots = {path: path.read_bytes() for path in (old_config, old_locator, old_mail)}
        profile = DesktopProfile()
        self.assertEqual(profile.accounts(), [])
        self.assertFalse(profile.config.exists())
        self.assertEqual(profile.config, self.root/'config/telemail/accounts.json')
        self.assertEqual(profile.data, self.root/'data/telemail/live')
        self.assertEqual(profile.storage.locator, self.root/'config/telemail/storage-locations.json')
        self.assertEqual(profile.storage.downloads.name, 'TeleMail')
        self.assertEqual(profile.application_id, 'org.telemail.Desktop')
        for path, content in snapshots.items(): self.assertEqual(path.read_bytes(), content)

    # ==========================================
    # Function: Keep typed credentials out of saved desktop configuration.
    # Method: Inspect the actual private JSON file and the current session environment.
    # ==========================================
    def test_gui_settings_session_secret(self):
        profile = DesktopProfile()
        profile.save_account(self.values,'session-only-secret')
        self.assertEqual(profile.accounts()[0].email,'you@example.com')
        self.assertNotIn('session-only-secret',profile.config.read_text())
        self.assertEqual(profile.accounts()[0].secret(),'session-only-secret')
        self.assertNotIn('TEST_DESKTOP_SECRET',os.environ)
        self.assertFalse(profile.vault.records.exists())
        if os.name!='nt':self.assertEqual(profile.config.stat().st_mode & 0o777,0o600)
        self.assertEqual(len(profile.save_account({**self.values,'smtp_port':587,'smtp_security':'starttls'})),1)

    # ==========================================
    # Function: Reject invalid settings before changing a saved account.
    # Method: Compare configuration bytes before and after failed validation.
    # ==========================================
    def test_invalid_settings_preserve_file(self):
        profile = DesktopProfile()
        profile.save_account(self.values)
        original = profile.config.read_bytes()
        with self.assertRaises(ValueError):
            profile.save_account({**self.values,'smtp_security':'none'})
        self.assertEqual(profile.config.read_bytes(),original)
        with self.assertRaises(ValueError):
            DesktopProfile(demo=True).save_account(self.values)

    # ==========================================
    # Function: Keep imported local EML read actions independent of remote UID state.
    # Method: Assert local import updates never call an IMAP adapter.
    # ==========================================
    def test_import_seen_is_local(self):
        service = MailService(self.root/'mail',DesktopProfile().save_account(self.values))
        raw = b'From: friend@example.com\r\nTo: you@example.com\r\nSubject: local\r\n\r\nbody'
        identity = service.store.ingest('work','@import','local','one',raw)
        with patch('maildesk.transport.set_seen') as remote:
            service.update(identity,{'seen':True})
            remote.assert_not_called()
        self.assertTrue(service.store.get(identity)['seen'])

    # ==========================================
    # Function: Describe an actual desktop app rather than a terminal/browser shortcut.
    # Method: Check the generated entry's application type, executable and demo action.
    # ==========================================
    def test_desktop_entry(self):
        command = desktop_exec(PurePosixPath('/tmp/path with spaces/100%/TeleMail'))
        self.assertEqual(command,'"/tmp/path with spaces/100%%/TeleMail"')
        value = desktop_entry('/opt/telemail/TeleMail','/opt/telemail/icon.svg')
        self.assertIn('Name=TeleMail\n',value)
        self.assertIn('StartupWMClass=TeleMail\n',value)
        self.assertIn('Type=Application\n',value)
        self.assertIn('Terminal=false\n',value)
        self.assertNotIn('python',value)
        self.assertNotIn('http',value)
        self.assertIn('[Desktop Action Demo]',value)

    # ==========================================
    # Function: Reject incomplete bundles before any desktop installation writes.
    # Method: Require an ELF entry point and the native application payload.
    # ==========================================
    def test_incomplete_install_rejected(self):
        with self.assertRaises(ValueError):
            install_user(self.root)
        self.assertFalse((self.root/'data/applications').exists())

if __name__ == '__main__':
    unittest.main()
