"""Cross-platform contracts for the native Windows adapter."""
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch,MagicMock
from maildesk import platform_native as native

# ==========================================
# Function: Verify platform resolution without requiring Windows DLLs on Linux.
# Method: Test deterministic paths, URI policy and operating-system locking boundaries.
# ==========================================
class WindowsPlatformTests(unittest.TestCase):
    # ==========================================
    # Function: Keep DLL names platform-specific and architecture-independent.
    # Method: Resolve public ABI aliases against a synthetic Windows runtime directory.
    # ==========================================
    def test_windows_library_aliases(self):
        self.assertEqual(native.library_name('gtk', windows=True),'libgtk-3-0.dll')
        with self.assertRaises(ValueError):native.library_name('poppler-glib', windows=True)
        self.assertEqual(native.library_name('cairo', windows=False),'libcairo.so.2')
        with self.assertRaises(ValueError):native.library_name('../evil',windows=True)

    # ==========================================
    # Function: Refuse an incomplete private runtime without searching ambient DLL locations.
    # Method: Force the Windows resolver against an empty directory and observe the loader boundary.
    # ==========================================
    def test_missing_windows_dll_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(native,'WINDOWS',True),patch.object(native,'runtime_root',return_value=Path(folder)),patch.object(native.C,'CDLL') as loader:
            with self.assertRaises(RuntimeError):native.load_library('gtk')
            loader.assert_not_called()

    # ==========================================
    # Function: Place Windows data under the user's native app directories.
    # Method: Override environment only and preserve explicit profile isolation.
    # ==========================================
    def test_windows_paths(self):
        with patch.dict(os.environ,{'APPDATA':'C:/User/Roaming','LOCALAPPDATA':'C:/User/Local'}):
            config,data=native.profile_homes(windows=True)
            self.assertEqual(config,Path('C:/User/Roaming'))
            self.assertEqual(data,Path('C:/User/Local'))

    # ==========================================
    # Function: Keep image loaders usable beneath Unicode installation directories.
    # Method: Check the third-party helper receives relative filenames and caches all module records.
    # ==========================================
    def test_pixbuf_helper_unicode_root(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{}):
            home=Path(folder);root=home/'便携 客户端 📨';modules=root/'lib/gdk-pixbuf-2.0/2.10.0/loaders'
            modules.mkdir(parents=True);(modules/'libpixbufloader-svg.dll').touch()
            (root/'bin').mkdir();(root/'bin/gdk-pixbuf-query-loaders.exe').touch()
            data=b'"lib/gdk-pixbuf-2.0/2.10.0/loaders/libpixbufloader-svg.dll"\n"svg"\n'
            with patch.object(native,'profile_homes',return_value=(home,home)),patch.object(native.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=data)) as run:
                native.prepare_pixbuf_cache(root)
                self.assertEqual(run.call_args.kwargs['cwd'],root)
                self.assertFalse(Path(run.call_args.args[0][1]).is_absolute())
                self.assertEqual(Path(os.environ['GDK_PIXBUF_MODULE_FILE']).read_bytes(),data)
                native.prepare_pixbuf_cache(root);self.assertEqual(run.call_count,1)

    # ==========================================
    # Function: Reject a successful helper exit that silently omitted an unavailable image loader.
    # Method: Return only the real helper header and require that no invalid cache is committed.
    # ==========================================
    def test_pixbuf_helper_incomplete_output(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);root=home/'runtime';modules=root/'lib/gdk-pixbuf-2.0/2.10.0/loaders'
            modules.mkdir(parents=True);(modules/'libpixbufloader-svg.dll').touch()
            (root/'bin').mkdir();(root/'bin/gdk-pixbuf-query-loaders.exe').touch()
            with patch.object(native,'profile_homes',return_value=(home,home)),patch.object(native.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'# GdkPixbuf Image Loader Modules file\n')):
                with self.assertRaises(RuntimeError):native.prepare_pixbuf_cache(root)
                self.assertEqual(list(home.glob('TeleMail/cache/*/loaders.cache')),[])

    # ==========================================
    # Function: Reject executable or filesystem URIs at the OS open boundary.
    # Method: Permit only HTTP, HTTPS and mailto with no control characters.
    # ==========================================
    def test_external_uri_policy(self):
        for value in ('file:///C:/bad.exe','javascript:bad()','https://host/\nfile'):
            with self.assertRaises(ValueError):native.open_uri(value)
        with patch('subprocess.Popen') as launch:
            native.open_uri('https://example.test/path',windows=False)
            self.assertEqual(launch.call_args.args[0],['gio','open','https://example.test/path'])

    # ==========================================
    # Function: Prevent concurrent cache writers on the existing Linux platform.
    # Method: Acquire the exact same byte-range/flock resource through two handles.
    # ==========================================
    def test_instance_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            with (Path(folder)/'lock').open('a+b') as one,(Path(folder)/'lock').open('a+b') as two:
                native.lock_instance(one)
                with self.assertRaises(OSError):native.lock_instance(two)

# ==========================================
# Function: Validate real Windows credential protection without provider connections.
# Method: Use a temporary synthetic vault and exercise DPAPI authenticity and account binding.
# ==========================================
@unittest.skipUnless(sys.platform=='win32','Windows DPAPI runtime required')
class WindowsCredentialTests(unittest.TestCase):
    # ==========================================
    # Function: Keep saved passwords encrypted and reusable only for the intended identity.
    # Method: Round-trip a real DPAPI blob, reject corruption and changed entropy.
    # ==========================================
    def test_dpapi_round_trip_and_authentication(self):
        secret=b'synthetic-password-for-test';entropy=b'test-account-identity'
        protected=native.protect_data(secret,entropy)
        self.assertNotIn(secret,protected)
        self.assertEqual(native.protect_data(protected,entropy,decrypt=True),secret)
        with self.assertRaises(ValueError):native.protect_data(protected,b'changed-account',decrypt=True)
        damaged=bytearray(protected);damaged[len(damaged)//2]^=1
        with self.assertRaises(ValueError):native.protect_data(bytes(damaged),entropy,decrypt=True)

    # ==========================================
    # Function: Restore a verified Windows login without saving plaintext or a device key.
    # Method: Exercise the production vault envelope using only a synthetic account.
    # ==========================================
    def test_native_vault_persistence(self):
        from maildesk.config import Account
        from maildesk.credentials import CredentialVault
        from dataclasses import replace
        account=Account('synthetic','test@example.test','imap.example.test','smtp.example.test')
        with tempfile.TemporaryDirectory() as folder:
            vault=CredentialVault(Path(folder)/'accounts.json');vault.save(account,'synthetic-local-test')
            self.assertEqual(CredentialVault(Path(folder)/'accounts.json').get(account),'synthetic-local-test')
            self.assertNotIn(b'synthetic-local-test',vault.records.read_bytes())
            self.assertFalse(vault.keyfile.exists())
            self.assertEqual(vault.get(replace(account,username='different')),'')
            vault.forget(account);self.assertEqual(vault.get(account),'')

# ==========================================
# Function: Verify Windows integration cannot mutate real registry state during tests.
# Method: Substitute only the winreg boundary while preserving actual command construction.
# ==========================================
class WindowsIntegrationTests(unittest.TestCase):
    # ==========================================
    # Function: Limit mailto registration to user-owned capability keys and inert URI argv.
    # Method: Check all real adapter writes against a fake registry module and synthetic EXE.
    # ==========================================
    def test_user_registry_and_uri_separator(self):
        from maildesk.windows_integration import register_application,set_autostart,startup_enabled
        registry=MagicMock();registry.HKEY_CURRENT_USER=17;registry.REG_SZ=1
        with tempfile.TemporaryDirectory() as folder:
            launcher=Path(folder)/'中文 folder'/'TeleMail.exe';launcher.parent.mkdir();launcher.write_bytes(b'MZ')
            with patch.dict(sys.modules,{'winreg':registry}),patch.dict(os.environ,{'TELEMAIL_LAUNCHER':str(launcher)}):
                self.assertEqual(register_application(),launcher)
                self.assertTrue(all(call.args[0]==17 for call in registry.CreateKey.call_args_list))
                written=[call.args[-1] for call in registry.SetValueEx.call_args_list]
                self.assertTrue(any(str(value).endswith(' -- "%1"') for value in written))
                self.assertFalse(any('UserChoice' in str(call.args) for call in registry.CreateKey.call_args_list))
                self.assertFalse(any('Maildesk' in str(call.args) for call in registry.CreateKey.call_args_list))
                set_autostart(True)
                command=registry.SetValueEx.call_args.args[-1]
                self.assertTrue(command.endswith(' --background'))
                self.assertEqual(registry.SetValueEx.call_args.args[1], 'TeleMail')
                registry.QueryValueEx.return_value=(command,1)
                self.assertTrue(startup_enabled())
                self.assertEqual(registry.QueryValueEx.call_args.args[-1], 'TeleMail')
                set_autostart(False);registry.DeleteValue.assert_called_once()

    # ==========================================
    # Function: Reject an incomplete Windows bundle before user registry or shortcuts change.
    # Method: Pass a disposable directory and require no registration calls.
    # ==========================================
    def test_incomplete_install_has_no_side_effects(self):
        from maildesk.windows_integration import install_user
        with tempfile.TemporaryDirectory() as folder,patch('maildesk.windows_integration.register_application') as register:
            with self.assertRaises(ValueError):install_user(folder)
            register.assert_not_called()

# ==========================================
# Function: Preserve native appearance and selection behavior without opening a GUI in unit tests.
# Method: Exercise real event routing against deterministic platform facades.
# ==========================================
class WindowsInteractionTests(unittest.TestCase):
    # ==========================================
    # Function: Coalesce Windows appearance broadcasts before repainting system-following views.
    # Method: Deliver both native messages and require a single main-loop observer callback.
    # ==========================================
    def test_theme_broadcasts_are_coalesced(self):
        from types import SimpleNamespace
        import ctypes as C
        from maildesk.windows_tray import WindowsTray
        tray=WindowsTray.__new__(WindowsTray);tray.closed=False;tray.theme_timer=0
        timer=MagicMock(return_value=77);changed=MagicMock()
        tray.app=SimpleNamespace(g=SimpleNamespace(g_timeout_add=timer),window=1,service=1,closing=False,system_theme_changed=changed)
        tray.theme_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(tray.theme_changed)
        tray.dispatch(1,0x1a,0,0);tray.dispatch(1,0x31a,0,0)
        timer.assert_called_once();changed.assert_not_called()
        tray.theme_changed(None);changed.assert_called_once();self.assertEqual(tray.theme_timer,0)
        tray.closed=True;tray.theme_changed(None);changed.assert_called_once()

    # ==========================================
    # Function: Release owned interfaces before host exit without waiting for per-process browser caches.
    # Method: Drive pending-controller grace and require COM release before application quit while a browser process still exists.
    # ==========================================
    def test_shutdown_releases_interfaces_before_host_exit(self):
        from types import SimpleNamespace
        from maildesk.desktop import DesktopApp
        from maildesk.reader_shutdown import ReaderDrain
        events=[];pending=[True]
        bridge=SimpleNamespace(md_webview_drained=lambda:not pending[0],md_webview_shutdown=lambda:None,md_webview_metrics=lambda field:1 if field==1 and pending[0] else 0,md_webview_finish=lambda:events.append('finish'))
        native=SimpleNamespace(disconnect=lambda *args:None,gtk_widget_destroy=lambda *args:events.append('destroy'),
            g_application_release=lambda *args:events.append('release'),g_application_quit=lambda *args:events.append('quit'))
        app=SimpleNamespace(reader_shutdown_phase='views',reader_process_seen={},reader_drain=ReaderDrain(0),reader_termination_requested=False,
            shutdown_readers=[object()],g=native,windows_webview_bridge=bridge,window=1,application=2,
            clear_conversation=lambda:events.append('clear'),close_document=lambda:events.append('document'),close_thread_window=lambda:events.append('thread'),
            close_general=lambda:events.append('begin'),release_reader_widgets=lambda:events.append('destroy'))
        with patch('maildesk.desktop.os.name','nt'),patch('maildesk.reader_shutdown.owned_renderers',return_value=set()),patch('maildesk.desktop.time.monotonic',return_value=1):
            app.reader_drain.quiet_since=.1
            self.assertEqual(DesktopApp.drain_readers(app,None),1)
            self.assertEqual(events,['begin'])
            self.assertEqual(app.reader_shutdown_phase,'context')
            self.assertEqual(DesktopApp.drain_readers(app,None),1);self.assertEqual(events,['begin'])
            pending[0]=False;self.assertEqual(DesktopApp.drain_readers(app,None),0)
            self.assertEqual(events,['begin','destroy','finish','release','quit'])

    # ==========================================
    # Function: Reload the same sanitized Unicode document without retaining a third rendered copy.
    # Method: Exercise actual preparation and force reload with a fake renderer boundary only.
    # ==========================================
    def test_reader_reload_retains_source_policy_without_rendered_copy(self):
        from types import SimpleNamespace
        from maildesk.windows_reader import HTMLReader
        reader=HTMLReader.__new__(HTMLReader)
        reader.app=SimpleNamespace(service=SimpleNamespace(store=SimpleNamespace(preference=lambda key,default:default)))
        reader.g=SimpleNamespace(gtk_widget_get_window=lambda widget:0);reader.handle=None;reader.widget=1
        reader.source='';reader.load_generation=0
        reader.load('<p>中文邮件<strong>current</strong></p><script>BAD_SCRIPT()</script>')
        self.assertFalse(hasattr(reader,'rendered'),'the prepared HTML must not have an additional persistent title-injected copy')
        self.assertIn('Content-Security-Policy',reader.source);self.assertNotIn('BAD_SCRIPT',reader.source)
        source=reader.source;first_title=reader.expected_title
        reader.handle=7;reader.lib=SimpleNamespace(md_webview_load=MagicMock())
        reader.reload();rendered=reader.lib.md_webview_load.call_args.args[1]
        self.assertEqual(reader.source,source);self.assertNotEqual(reader.expected_title,first_title)
        self.assertIn(reader.expected_title,rendered);self.assertIn('中文邮件',rendered)
        self.assertIn('Content-Security-Policy',rendered);self.assertFalse(hasattr(reader,'rendered'))

    # ==========================================
    # Function: Recreate a native child after unrealize with the same current document identity and zoom.
    # Method: Record real adapter calls while substituting only native GDK/bridge entry points.
    # ==========================================
    def test_reader_unrealize_recreates_prepared_document(self):
        from types import SimpleNamespace
        from maildesk.windows_reader import HTMLReader
        with tempfile.TemporaryDirectory() as folder:
            reader=HTMLReader.__new__(HTMLReader);reader.closed=False;reader.handle=7;reader.timer=11;reader.widget=1;reader.group='synthetic'
            reader.source='<html><head></head><body>中文 current</body></html>';reader.expected_title='exact-current-document';reader.zoom=1.5;reader.remote=False
            reader.document_ready=True;reader.pending_image=3
            ensure=MagicMock(return_value=1);hwnd=MagicMock(return_value=88)
            reader.g=SimpleNamespace(g_source_remove=MagicMock(),gtk_widget_get_window=lambda widget:70,
                libs={'gdk':SimpleNamespace(gdk_window_ensure_native=ensure,gdk_win32_window_get_handle=hwnd)},
                g_timeout_add=MagicMock(return_value=19),gtk_widget_get_mapped=lambda widget:True,
                gtk_widget_get_toplevel=lambda widget:1,gtk_widget_get_ancestor=lambda *args:0,
                gtk_scrolled_window_get_type=lambda:0,gtk_widget_get_allocated_width=lambda widget:300,
                gtk_widget_get_allocated_height=lambda widget:300,gtk_widget_translate_coordinates=lambda *args:0)
            reader.app=SimpleNamespace(profile=SimpleNamespace(data=Path(folder)))
            reader.lib=SimpleNamespace(md_webview_close=MagicMock(),md_webview_create=MagicMock(return_value=99),
                md_webview_zoom=MagicMock(),md_webview_load=MagicMock(),md_webview_resize=MagicMock(),
                md_webview_position=MagicMock(),md_webview_overlay=MagicMock(),md_webview_viewport=MagicMock(),md_webview_exclusions=MagicMock())
            reader.unrealized();reader.g.g_source_remove.assert_called_once_with(11);reader.lib.md_webview_close.assert_called_once_with(7)
            self.assertIsNone(reader.handle);self.assertEqual(reader.timer,0);self.assertFalse(reader.document_ready)
            self.assertEqual(reader.pending_image,3);reader.realized()
            self.assertEqual(reader.handle,99);self.assertEqual(reader.timer,19);reader.lib.md_webview_zoom.assert_called_once_with(99,1.5)
            rendered=reader.lib.md_webview_load.call_args.args[1]
            self.assertIn('exact-current-document',rendered);self.assertIn('中文 current',rendered)
            self.assertFalse(hasattr(reader,'rendered'))

    # ==========================================
    # Function: Select mail rows in multi-select mode while preserving ordinary HTML text selection.
    # Method: Dispatch the actual embedded-browser shortcut adapter with fake native boundaries.
    # ==========================================
    def test_browser_select_all_matches_application_mode(self):
        from types import SimpleNamespace
        from maildesk.windows_reader import HTMLReader
        select=MagicMock();script=MagicMock();enabled=[True]
        reader=HTMLReader.__new__(HTMLReader);reader.handle=1
        reader.g=SimpleNamespace(gtk_list_box_select_all=select)
        reader.lib=SimpleNamespace(md_webview_script=script)
        app=SimpleNamespace(document=None,multi=True,widget=lambda name:23,service=SimpleNamespace(store=SimpleNamespace(preference=lambda *args:enabled[0])))
        reader.app=app;reader.shortcut(65|0x10000);select.assert_called_once_with(23);script.assert_not_called()
        app.multi=False;reader.shortcut(65|0x10000);script.assert_called_once_with(1,'document.execCommand("selectAll")')
        app.multi=True;enabled[0]=False;reader.shortcut(65|0x10000);self.assertEqual(select.call_count,1);self.assertEqual(script.call_count,2)

    # ==========================================
    # Function: Hand only unconsumed native browser scrolling to the GTK conversation.
    # Method: Use the actual adapter with a bounded adjustment and verify manual reveal cancellation.
    # ==========================================
    def test_browser_boundary_wheel_scrolls_parent(self):
        from types import SimpleNamespace
        from maildesk.windows_reader import HTMLReader
        value=MagicMock(return_value=120);upper=MagicMock(return_value=600);page=MagicMock(return_value=200);set_value=MagicMock()
        gtk=SimpleNamespace(gtk_adjustment_get_value=value,gtk_adjustment_get_upper=upper,gtk_adjustment_get_page_size=page,gtk_adjustment_set_value=set_value)
        reader=HTMLReader.__new__(HTMLReader);reader.widget=1;reader.app=SimpleNamespace(pending_conversation_reveal=('synthetic',0))
        reader.g=SimpleNamespace(libs={'gtk':gtk},gtk_widget_get_ancestor=lambda *args:2,gtk_scrolled_window_get_type=lambda:9,gtk_scrolled_window_get_vadjustment=lambda widget:3)
        reader.scroll_parent(-80);set_value.assert_called_with(3,40);self.assertIsNone(reader.app.pending_conversation_reveal)
        reader.scroll_parent(10000);set_value.assert_called_with(3,400)

if __name__=='__main__':unittest.main()
