"""Local general/appearance contracts, independent of live providers and displays."""
import os
from email.message import EmailMessage
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from maildesk.desktop_preferences import parse_mailto, row_presentation, cached_attachments
from maildesk.desktop_install import set_autostart, default_mail_client
from maildesk.store import Store

# ==========================================
# Function: Exercise user-controlled local desktop behavior and safe document options.
# Method: Use disposable XDG paths, a private SQLite cache and mocked OS integration.
# ==========================================
class GeneralAppearanceTests(unittest.TestCase):
    # ==========================================
    # Function: Restore saved zoom across launches and reject unusable imported values.
    # Method: Reopen a real preference store and exercise bounded numeric recovery.
    # ==========================================
    def test_ui_scale_persistence_and_bounds(self):
        from maildesk.appearance_theme import preferences
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mail.db';store=Store(path)
            self.assertEqual(preferences(store)['ui_scale'],100)
            store.set_preference('ui_scale',150)
            self.assertEqual(preferences(Store(path))['ui_scale'],150)
            for value,expected in [(0,100),(900,200),('invalid',100),(None,100)]:
                store.set_preference('ui_scale',value)
                self.assertEqual(preferences(store)['ui_scale'],expected)

    # ==========================================
    # Function: Cancel live zoom without persisting it or accumulating global providers.
    # Method: Preview several scales, cancel through the settings lifecycle, then save and reopen.
    # ==========================================
    def test_ui_scale_preview_cancel_and_save(self):
        from maildesk.appearance_theme import apply,preferences
        from maildesk.appearance_settings import AppearanceSettings
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.db');g=Mock();g.gtk_css_provider_new.side_effect=[11,12]
            app=SimpleNamespace(g=g,service=SimpleNamespace(store=store),window=1,closing=False)
            editor=AppearanceSettings.__new__(AppearanceSettings)
            editor.app=app;editor.g=g;editor.closed=False;editor.timer=0
            baseline=preferences(store);editor.values=lambda:{**baseline,'ui_scale':150}
            apply(app,editor.values());first=app.ui_scale_provider
            self.assertEqual(store.preference('ui_scale',100),100)
            apply(app,{**baseline,'ui_scale':200});editor.close()
            self.assertEqual(app.ui_scale_percent,100)
            self.assertEqual(app.ui_scale_provider,first)
            self.assertEqual(g.gtk_style_context_add_provider_for_screen.call_count,2)
            editor.save();apply(app)
            self.assertEqual(app.ui_scale_percent,150)
            self.assertEqual(preferences(Store(store.path))['ui_scale'],150)

    # ==========================================
    # Function: Preserve safe mailto fields without allowing executable MIME headers.
    # Method: Decode RFC6068-style recipient/subject/body values and reject injection.
    # ==========================================
    def test_mailto_safe_fields(self):
        value=parse_mailto('mailto:a@example.com?cc=b%40example.com&subject=Hello%20world&body=one%0Atwo')
        self.assertEqual(value,{'to':'a@example.com','cc':'b@example.com','subject':'Hello world','body':'one\ntwo'})
        for uri in ('http://example.com','mailto:a@example.com?bcc=x@example.com','mailto:a@example.com?subject=x%0ABcc:y@example.com','mailto:a@example.com?attach=/etc/passwd','mailto:a@example.com%0D%0ABcc:x@example.com'):
            with self.assertRaises(ValueError):parse_mailto(uri)

    # ==========================================
    # Function: Apply bounded list preview settings to actual row geometry.
    # Method: Assert hide/expanded modes and three-line overrides while preserving default compact rows.
    # ==========================================
    def test_row_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.db')
            self.assertEqual(row_presentation(store)['row_height'],63)
            store.set_preference('email_preview_lines','0')
            self.assertEqual(row_presentation(store)['preview_lines'],0)
            store.set_preference('email_preview_lines','3')
            self.assertEqual(row_presentation(store)['preview_lines'],3)
            self.assertGreater(row_presentation(store)['row_height'],63)
            store.set_preference('layout_mode','fullScreen');store.set_preference('mail_list_preview','compact')
            self.assertEqual(row_presentation(store)['preview_lines'],0)
            store.set_preference('mail_list_preview','expanded')
            self.assertEqual(row_presentation(store)['preview_lines'],2)

    # ==========================================
    # Function: Materialize attachments only when the user enables the local cache option.
    # Method: Verify private files, stable reuse, safe basename and no cloud/provider calls.
    # ==========================================
    def test_private_attachment_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.db');store.cache_dir=Path(folder)/'private-cache';mail=EmailMessage()
            mail['From']='a@example.com';mail['To']='b@example.com';mail.set_content('body')
            mail.add_attachment(b'private-data',maintype='application',subtype='octet-stream',filename='../../item.txt')
            identity=store.ingest('local','INBOX','1','1',mail.as_bytes())
            self.assertEqual(cached_attachments(store),0)
            store.set_preference('autodownload_attachments',True)
            self.assertEqual(cached_attachments(store),1)
            files=list((store.cache_dir/'attachments').rglob('*.txt'))
            self.assertEqual(len(files),1);self.assertEqual(files[0].read_bytes(),b'private-data')
            if os.name!='nt':self.assertEqual(files[0].stat().st_mode & 0o777,0o600)
            self.assertEqual(cached_attachments(store),0)
            self.assertEqual(store.get(identity)['parsed']['attachments'][0]['name'],'../../item.txt')

    # ==========================================
    # Function: Register startup and default handling only through explicit actions.
    # Method: Patch XDG directories and subprocess execution; ensure shell-free argv and URI expansion.
    # ==========================================
    @unittest.skipIf(os.name=='nt','Linux XDG integration; Windows registry boundaries covered separately')
    def test_explicit_os_integration(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'XDG_CONFIG_HOME':folder,'XDG_DATA_HOME':folder}):
            installed=Path(folder)/'applications/org.telemail.Desktop.desktop';installed.parent.mkdir()
            installed.write_text('[Desktop Entry]\nType=Application\nExec="/opt/TeleMail" %u\n')
            path=set_autostart(True);self.assertTrue(path.exists());self.assertIn('/opt/TeleMail',path.read_text())
            self.assertNotIn('%u',path.read_text());set_autostart(False);self.assertFalse(path.exists())
            with patch('maildesk.desktop_install.subprocess.run') as run:
                run.return_value.returncode=0;run.return_value.stdout=''
                default_mail_client()
                self.assertEqual(run.call_args.args[0],['xdg-mime','default','org.telemail.Desktop.desktop','x-scheme-handler/mailto'])
                self.assertFalse(run.call_args.kwargs.get('shell',False))

    # ==========================================
    # Function: Permit user-selected remote raster sources without allowing active/local content.
    # Method: Inspect sanitized HTML/CSP under opt-in and default-deny policies.
    # ==========================================
    def test_remote_image_opt_in(self):
        from maildesk.document_content import reader_document
        source='<img src="https://example.com/p.png"><img src="file:///etc/passwd"><script>alert(1)</script><img src="http://user:pass@example.com/p">'
        self.assertNotIn('src="https:',reader_document(source))
        enabled=reader_document(source,remote_images=True)
        self.assertIn('src="https://example.com/p.png"',enabled)
        self.assertNotIn('file:',enabled);self.assertNotIn('alert(1)',enabled);self.assertNotIn('user:pass',enabled)
        self.assertIn('img-src data: https: http:',enabled)
        self.assertIn("default-src 'none'",enabled)

if __name__=='__main__':unittest.main()
