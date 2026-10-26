"""Real PDF.js worker/page/search/zoom lifecycle acceptance with a disposable native profile."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

# ==========================================
# Function: Generate two selectable PDF pages without depending on a PDF rendering library.
# Method: Write a finite standard-font document with exact xref offsets and distinct search text.
# ==========================================
def fixture_pdf():
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>',
               None,
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>',
               None, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for index, text in ((3, 'TeleMail PDF page one'), (5, 'Search target on second page')):
        stream = ('BT /F1 24 Tf 50 700 Td (' + text + ') Tj ET').encode()
        objects[index] = b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream'
    data = bytearray(b'%PDF-1.7\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n')
    xref = len(data)
    data.extend(b'xref\n0 8\n0000000000 65535 f \n')
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(data)

# ==========================================
# Function: Exercise actual PDF.js rendering through the application attachment workspace.
# Method: Wait for confirmed asynchronous states and drive the native toolbar and close/tab lifecycle.
# ==========================================
class Scenario:
    # ==========================================
    # Function: Retain one finite native test state machine and its callback ownership.
    # Method: Run only on the GTK main loop with explicit readiness deadlines.
    # ==========================================
    def __init__(self, app, output, encrypted=None, screenshot=False):
        self.app, self.output = app, output
        self.step, self.complete, self.error = 0, False, ''
        self.checks, self.metrics = [], {}
        self.deadline = time.monotonic() + 150
        self.encrypted, self.cycles = encrypted, 0
        self.capture_screenshot = screenshot
        self.step_times = []
        self.callback = C.CFUNCTYPE(C.c_int, C.c_void_p)(self.tick)
        self.query_pending = False
        self.logged_step = None

    # ==========================================
    # Function: Begin the scenario after the application has activated its native window.
    # Method: Schedule periodic inspection without nested GTK loops.
    # ==========================================
    def start(self, *unused):
        self.app.g.g_timeout_add(80, C.cast(self.callback, C.c_void_p), None)

    # ==========================================
    # Function: Inspect only the synthetic test document's real canvas, text layer and highlights.
    # Method: Exchange a fixed diagnostic title without sharing the production metadata identity.
    # ==========================================
    def query(self, expression):
        surface = self.reader.surface
        prefix = 'TeleMailTest:'
        if self.query_pending:
            if os.name == 'nt':
                value = C.create_unicode_buffer(8192)
                surface.lib.md_webview_title(surface.handle, value, len(value))
                title = value.value
            else:
                title = (surface.lib.webkit_web_view_get_title(surface.widget) or b'').decode()
            if title.startswith(prefix):
                self.query_pending = False
                return json.loads(title[len(prefix):])
        surface.execute('document.title=' + json.dumps(prefix) + '+JSON.stringify(' + expression + ')')
        self.query_pending = True
        return None

    # ==========================================
    # Function: Validate real worker rendering, toolbar behavior and session retirement.
    # Method: Require rendered pages, search results and scale updates rather than mere HTML readiness.
    # ==========================================
    def tick(self, *unused):
        app, g = self.app, self.app.g
        try:
            if self.step != self.logged_step:
                self.logged_step = self.step
                self.step_times.append({'step': self.step, 'remaining_seconds': round(self.deadline-time.monotonic(), 2)})
                print('PDF native scenario step', self.step, flush=True)
            assert time.monotonic() < self.deadline, ('timeout', self.step,
                    getattr(getattr(self, 'reader', None), 'error', ''),
                    getattr(getattr(self, 'reader', None), 'count', 0))
            if not app.service:
                return 1
            if self.step == 0:
                title = g.libs['gtk'].gtk_window_get_title
                title.argtypes, title.restype = [C.c_void_p], C.c_char_p
                self.metrics['application_title'] = (title(app.window) or b'').decode()
                assert self.metrics['application_title'].startswith('TeleMail')
                for key, value in (('notifications', 'off'), ('close_to_tray', False), ('motion', 'off')):
                    app.service.store.set_preference(key, value)
                app.show_document('fixture.pdf', fixture_pdf())
                self.reader = app.document.engine
                self.step = 1
            elif self.step == 1:
                assert not self.reader.error, self.reader.error
                if not self.reader.ready:
                    return 1
                assert self.reader.count == 2 and self.reader.rendered > 0
                self.checks.append('pdfjs-real-worker-two-selectable-pages')
                self.initial_zoom = self.reader.zoom
                g.gtk_button_clicked(app.document.panel.next_button)
                self.step = 2
            elif self.step == 2:
                if self.reader.index != 1:
                    return 1
                entry = app.document.panel.search_entry
                g.gtk_entry_set_text(entry, b'Search target')
                g.libs['gtk'].gtk_widget_activate.argtypes = [C.c_void_p]
                g.libs['gtk'].gtk_widget_activate(entry)
                self.step = 3
            elif self.step == 3:
                if not self.reader.matches:
                    return 1
                result = self.query("(()=>{const page=document.querySelector('.page[data-page-number=\"2\"]');"
                    "const canvas=page?.querySelector('canvas');if(!canvas||!page.querySelector('.highlight'))return null;"
                    "const p=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;let ink=0;"
                    "for(let i=0;i<p.length;i+=4)if(p[i]<180&&p[i+1]<180&&p[i+2]<180&&p[i+3]>0)ink++;"
                    "return {text:page.querySelector('.textLayer').textContent,ink,highlights:page.querySelectorAll('.highlight').length}})()")
                if result is None:
                    return 1
                assert 'Search target' in result['text'] and result['ink'] > 100 and result['highlights'] > 0, result
                self.metrics['canvas'] = result
                self.checks.append('native-next-and-pdfjs-cross-page-search-highlights')
                self.checks.append('real-canvas-ink-and-selectable-highlighted-text-layer')
                g.gtk_button_clicked(app.document.panel.zoom_in_button)
                self.step = 4
            elif self.step == 4:
                if self.reader.zoom <= self.initial_zoom:
                    return 1
                self.metrics.update({'pages': self.reader.count, 'page_index': self.reader.index,
                                'matches': len(self.reader.matches), 'rendered': self.reader.rendered,
                                'initial_zoom': self.initial_zoom, 'zoom': self.reader.zoom})
                self.checks.append('native-pdf-zoom-confirmed-asynchronously')
                if self.capture_screenshot:
                    try:
                        g.screenshot(app.window, self.output / 'pdfjs-page-two.png')
                        self.metrics['screenshot'] = 'captured (WSL GDK output may not contain browser pixels)'
                    except RuntimeError as error:
                        self.metrics['screenshot'] = 'not captured: ' + str(error)
                self.session = self.reader.session
                app.close_document()
                assert self.reader.closed and self.session.closed and not self.session.thread.is_alive()
                self.checks.append('close-revokes-url-releases-document-and-listener')
                app.show_document('invalid.pdf', b'%PDF-1.7\ninvalid')
                self.reader = app.document.engine
                self.step = 5
            elif self.step == 5:
                if not self.reader.error:
                    return 1
                self.checks.append('malformed-pdf-shows-load-error-without-native-crash')
                app.close_document()
                app.show_document('reopened.pdf', fixture_pdf())
                self.reader = app.document.engine
                self.step = 6
            elif self.step == 6:
                assert not self.reader.error, self.reader.error
                if not self.reader.ready:
                    return 1
                assert self.reader.count == 2
                self.checks.append('reopen-uses-fresh-capability-and-live-worker')
                if self.encrypted:
                    app.close_document()
                    app.show_document('encrypted.pdf', self.encrypted)
                    self.reader = app.document.engine
                    self.step = 7
                else:
                    self.step = 10
            elif self.step == 7:
                result = self.query("({prompt:!document.getElementById('passwordForm').hidden})")
                if not result or not result['prompt']:
                    return 1
                self.reader.surface.execute("document.getElementById('password').value='wrong-synthetic';document.getElementById('passwordForm').requestSubmit()")
                self.step = 8
            elif self.step == 8:
                result = self.query("({retry:!document.getElementById('passwordForm').hidden&&!!document.getElementById('passwordError').textContent})")
                if not result or not result['retry']:
                    return 1
                self.reader.surface.execute("document.getElementById('password').value='synthetic-only';document.getElementById('passwordForm').requestSubmit()")
                self.step = 9
            elif self.step == 9:
                assert not self.reader.error, self.reader.error
                if not self.reader.ready:
                    return 1
                result = self.query("({cleared:!document.getElementById('password').value,pages:window.maildeskPdf.state().count})")
                if result is None:
                    return 1
                assert result == {'cleared': True, 'pages': 2}, result
                self.checks.append('encrypted-pdf-wrong-password-retry-local-decryption-and-cleared-input')
                self.step = 10
            elif self.step == 10:
                self.session = self.reader.session
                app.close_document()
                assert self.session.closed and not self.session.thread.is_alive()
                app.show_document('cycle.pdf', fixture_pdf())
                self.reader = app.document.engine
                self.step = 11
            elif self.step == 11:
                assert not self.reader.error, self.reader.error
                if not self.reader.ready:
                    return 1
                self.cycles += 1
                if self.cycles < 3:
                    self.step = 10
                else:
                    self.checks.append('three-additional-native-close-reopen-worker-cycles')
                    self.metrics['step_timings'] = self.step_times
                    self.complete = True
                    app.on_delete(force=True)
                    return 0
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.error = f'step {self.step}: {error!r}'
            if hasattr(self, 'reader'):
                surface = self.reader.surface
                self.metrics['failure_resources'] = dict(self.reader.session.server.served)
                self.metrics['failure_surface'] = {'handle': bool(getattr(surface, 'handle', None)),
                    'browser_ready': surface.document_ready, 'mapped': bool(g.gtk_widget_get_mapped(surface.widget))}
                if os.name == 'nt' and surface.handle:
                    self.metrics['failure_surface']['status'] = surface.lib.md_webview_status(surface.handle)
            app.on_delete(force=True)
            return 0
        return 1

# ==========================================
# Function: Run the same native PDF acceptance against Linux source or a Windows staged bundle.
# Method: Isolate all profile paths and explicitly forbid real IMAP/SMTP operations.
# ==========================================
def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--font-bundle', type=Path)
    parser.add_argument('--encrypted', type=Path)
    parser.add_argument('--screenshot', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.bundle:
        os.environ['TELEMAIL_WINDOWS_RUNTIME'] = str(args.bundle.resolve() / 'runtime')
        sys.path.insert(0, str(args.bundle.resolve() / 'app'))
    from maildesk.reader_runtime import prepare_readers
    prepare_readers()
    from maildesk.desktop import DesktopApp
    from maildesk.gtk_native import GtkNative
    fonts = GtkNative.fonts
    font_bundle = args.font_bundle
    if font_bundle and os.name == 'nt' and font_bundle.as_posix().startswith('/mnt/'):
        value = font_bundle.as_posix()
        font_bundle = Path(value[5] + ':/' + value[7:])
    if os.name == 'nt':
        from windows_capture import screenshot
    else:
        screenshot = GtkNative.screenshot
    with tempfile.TemporaryDirectory(prefix='maildesk-pdfjs-') as directory:
        root = Path(directory)
        for key in ('APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            location = root / key
            location.mkdir()
            os.environ[key] = str(location)
        options = SimpleNamespace(demo=True, config=root / 'accounts.json', data=root / 'mail',
                                  self_test=False, report=None, screenshot=None)
        with patch.object(GtkNative, 'screenshot', screenshot), patch('maildesk.transport.sync_account') as sync, patch(
                'maildesk.transport.deliver') as send:
            print('Constructing isolated PDF.js desktop', flush=True)
            if font_bundle:
                with patch.object(GtkNative, 'fonts', lambda self, folder: fonts(
                        self, font_bundle / 'app/maildesk/desktop_assets/fonts')):
                    app = DesktopApp(options)
            else:
                app = DesktopApp(options)
            print('Running native PDF.js checks', flush=True)
            scenario = Scenario(app, args.output, args.encrypted.read_bytes() if args.encrypted else None, args.screenshot)
            app.g.connect(app.application, 'activate', scenario.start)
            app.run()
            assert not sync.called and not send.called
        from release_context import provenance
        report = {'provenance': provenance(args.bundle), 'ok': scenario.complete, 'checks': scenario.checks, 'metrics': scenario.metrics,
                  'error': scenario.error, 'real_provider_calls': 0}
        (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if scenario.complete else 1

if __name__ == '__main__':
    raise SystemExit(main())
