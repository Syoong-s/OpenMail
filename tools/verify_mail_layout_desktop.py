"""Real Linux conversation geometry, styling and inert-script acceptance using synthetic mail."""
import argparse
import ctypes as C
from email.message import EmailMessage
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
DIAGNOSTIC = r'''(()=>{const s=x=>getComputedStyle(document.querySelector(x));
const end=document.getElementById('end');return {viewport:innerHeight,width:innerWidth,
body:document.body.scrollHeight,bottom:end.getBoundingClientRect().bottom+scrollY,
border:s('td').borderTopWidth,padding:s('td').paddingTop,round:s('#primary').borderTopLeftRadius,
button:s('#primary').backgroundColor,text:s('#primary').color,avatar:document.querySelector('img').getBoundingClientRect().width,
active:document.querySelectorAll('script,iframe,form').length,attack:window.ATTACK||0,
overflow:document.documentElement.scrollWidth>innerWidth+4,title:document.title}})()'''

# ==========================================
# Function: Exercise the actual conversation owner and native WebKit widget lifecycle.
# Method: Drive isolated synthetic mail through asynchronous GTK and browser geometry stages.
# ==========================================
class Scenario:
    # ==========================================
    # Function: Retain one bounded native acceptance state machine.
    # Method: Keep callbacks alive and allow a baseline run against unfitted Linux source.
    # ==========================================
    def __init__(self, app, output, baseline=False):
        self.app, self.output, self.baseline = app, output, baseline
        self.step, self.complete, self.error = 0, False, ''
        self.deadline = time.monotonic() + 90
        self.checks, self.metrics = [], {}
        self.result, self.pending, self.until = None, False, 0
        self.logged_step = None
        self.callback = C.CFUNCTYPE(C.c_int, C.c_void_p)(self.tick)

    # ==========================================
    # Function: Enter the scenario after ordinary desktop activation.
    # Method: Schedule checks on the GTK thread without nested event loops.
    # ==========================================
    def start(self, *unused):
        self.app.g.g_timeout_add(100, C.cast(self.callback, C.c_void_p), None)

    # ==========================================
    # Function: Read browser styles and content bounds without altering the mail title.
    # Method: Use the same isolated host world as production fitting and await one callback.
    # ==========================================
    def query(self, expression=DIAGNOSTIC):
        if self.result is not None:
            result, self.result = self.result, None
            return result
        if not self.pending:
            self.pending = True
            # ==========================================
            # Function: Retain the completed synthetic diagnostic for the next GTK tick.
            # Method: Keep native async result ownership inside the fitting bridge.
            # ==========================================
            def done(value):
                self.pending = False
                self.result = value
            self.reader.content_fit.query(expression, done)
        return None

    # ==========================================
    # Function: Validate fitted geometry and preserve authored table/button presentation.
    # Method: Compare actual allocated pixels to browser content after width and zoom changes.
    # ==========================================
    def geometry(self, name):
        value = self.query()
        if value is None:
            return False
        value['allocated'] = self.app.g.gtk_widget_get_allocated_height(self.reader.widget)
        value['fit_height'] = self.reader.content_fit.height
        value['fit_pending'] = self.reader.content_fit.pending
        value['fit_timer'] = self.reader.content_fit.timer
        self.metrics[name] = value
        assert value['border'] == value['padding'] == '0px', value
        assert value['round'] == '6px' and value['button'] == 'rgb(8, 102, 255)', value
        assert value['text'] == 'rgb(255, 255, 255)' and value['avatar'] >= 90, value
        assert not value['overflow'] and not value['active'] and not value['attack'], value
        if not self.baseline:
            assert -2 <= value['viewport'] - value['bottom'] <= 45, value
            assert value['body'] <= value['viewport'] + 35, value
        return True

    # ==========================================
    # Function: Reproduce whitespace and verify resizing, zoom, reuse and malicious markup handling.
    # Method: Use real conversation rendering with synthetic MIME and explicit readiness deadlines.
    # ==========================================
    def tick(self, *unused):
        app, g = self.app, self.app.g
        try:
            if self.step != self.logged_step:
                self.logged_step = self.step
                print('Linux mail layout step', self.step, flush=True)
            assert time.monotonic() < self.deadline, ('timeout', self.step, self.metrics, app.selected_chat, len(app.chat_items), app.chat_load_error)
            if not app.service or time.monotonic() < self.until:
                return 1
            if self.step == 0:
                title = g.libs['gtk'].gtk_window_get_title
                title.argtypes, title.restype = [C.c_void_p], C.c_char_p
                self.metrics['application_title'] = (title(app.window) or b'').decode()
                assert self.metrics['application_title'].startswith('TeleMail')
                from tests.test_email_layout import FACEBOOK_LAYOUT
                for key, value in (('notifications', 'off'), ('close_to_tray', False), ('motion', 'off'), ('load_remote_images', False)):
                    app.service.store.set_preference(key, value)
                image = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI5NiIgaGVpZ2h0PSI5NiI+PHJlY3Qgd2lkdGg9Ijk2IiBoZWlnaHQ9Ijk2IiBmaWxsPSJibHVlIi8+PC9zdmc+'
                self.source = FACEBOOK_LAYOUT.replace('alt="logo"', 'alt="logo" src="'+image+'"') + '<p id="end">Linux 气泡正文末尾 / wrapping text ' + '排版内容 ' * 35 + '</p>' + '\n' * 150 + '<div style="min-height:1200px"><p><br></p></div><script>window.ATTACK=1</script>'
                message = EmailMessage()
                message['From'], message['To'] = 'sender@example.invalid', 'demo@example.com'
                message['Subject'], message['Message-ID'] = 'Synthetic Linux bubble', '<linux-fit@example.invalid>'
                message.set_content('Synthetic body')
                message.add_alternative(self.source, subtype='html')
                self.identity = app.service.store.ingest('demo', 'INBOX', 'linux-fit', '1', message.as_bytes())
                app.read(self.identity)
                self.step = 1
            elif self.step == 1:
                card = app.conversation_cards.get(self.identity)
                if not card or not card.get('reader') or not card['reader'].document_ready:
                    return 1
                self.reader = card['reader']
                if not hasattr(self.reader, 'content_fit'):
                    from maildesk.webkit_mail_fit import WebKitMailFit
                    self.reader.content_fit = WebKitMailFit(self.reader)
                self.until, self.step = time.monotonic() + 2, 2
            elif self.step == 2:
                if not self.geometry('initial'):
                    return 1
                self.checks.append('real-conversation-table-image-button-and-tight-bottom')
                if self.baseline:
                    self.complete = True
                    app.on_delete(force=True)
                    return 0
                self.initial_width = self.metrics['initial']['width']
                g.gtk_widget_set_margin_start(self.reader.widget, 140)
                g.gtk_widget_set_margin_end(self.reader.widget, 140)
                self.until, self.step = time.monotonic() + 2, 3
            elif self.step == 3:
                if not self.geometry('resized'):
                    return 1
                assert self.metrics['resized']['width'] < self.initial_width - 100
                self.reader.scale(1.4)
                self.until, self.step = time.monotonic() + 2, 4
            elif self.step == 4:
                if not self.geometry('zoomed'):
                    return 1
                self.checks.append('actual-webkit-width-and-zoom-reflow-refits-height')
                self.reader.reload()
                self.until, self.step = time.monotonic() + 2, 5
            elif self.step == 5:
                if not self.reader.document_ready or not self.geometry('reloaded'):
                    return 1
                self.retired = self.reader
                self.retired.content_fit.poll()
                app.toggle_conversation_card(self.identity, False)
                assert self.retired.closed and not self.retired.content_fit.timer
                app.toggle_conversation_card(self.identity, True)
                self.step = 6
            elif self.step == 6:
                self.reader = app.conversation_cards[self.identity]['reader']
                if not self.reader.document_ready:
                    return 1
                assert self.reader is not self.retired
                self.until, self.step = time.monotonic() + 2, 7
            elif self.step == 7:
                if not self.geometry('reused'):
                    return 1
                self.checks.append('collapse-cancels-fit-and-widget-reuse-rejects-stale-results')
                # Deliberately bypass the sanitizer/CSP only for this synthetic security fixture.
                title = self.reader.expected_title
                self.reader.lib.webkit_web_view_load_html(self.reader.view,
                    ('<html><head><title>'+title+'</title></head><body><script>document.body.dataset.attack="script"</script>'
                     '<img src="data:image/png;base64,invalid" onerror="document.body.dataset.attack=\'handler\'">'
                     '<a href="javascript:document.body.dataset.attack=\'url\'">test</a></body></html>').encode(), b'about:blank')
                self.until, self.step = time.monotonic() + 1, 8
            elif self.step == 8:
                value = self.query("({attack:document.body.dataset.attack||'',scripts:document.querySelectorAll('script,[onerror]').length})")
                if value is None:
                    return 1
                assert value == {'attack': '', 'scripts': 0}, value
                self.metrics['native_markup_security'] = value
                self.checks.append('native-javascript-markup-blocks-scripts-and-handlers-without-csp')
                contacts = app.contact_core().list_conversations(search='sender@example.invalid')['items']
                assert contacts, 'synthetic sender not indexed'
                key = contacts[0]['key']
                self.chat_key = key
                app.select_inbox_mode('conversations')
                self.step = 9
            elif self.step == 9:
                if not app.contact_mode() or not any(row.get('key') == self.chat_key for row in app.items):
                    return 1
                app.read_chat(self.chat_key)
                self.step = 91
            elif self.step == 91:
                readers = [leaf['reader'] for leaf in app.chat_surface.leaves if leaf['reader'] and leaf['reader'].document_ready]
                if not readers:
                    return 1
                self.reader = readers[0]
                self.until, self.step = time.monotonic() + 2, 10
            elif self.step == 10:
                if not self.geometry('contact_bubble'):
                    return 1
                self.checks.append('contact-chat-hydrated-rich-bubble-has-tight-real-content-height')
                self.reader.content_fit.query("document.images[0].style.width='140px'", lambda value: None)
                self.until, self.step = time.monotonic() + 2, 11
            elif self.step == 11:
                if not self.geometry('image_reflow'):
                    return 1
                assert self.metrics['image_reflow']['avatar'] > self.metrics['contact_bubble']['avatar']
                self.checks.append('late-image-layout-change-refits-contact-bubble')
                self.reader.load('<p>Long synthetic mail</p>' * 400 + '<p id="long-end">Final line</p>')
                self.until, self.step = time.monotonic() + 2, 12
            elif self.step == 12:
                if not self.reader.document_ready:
                    return 1
                value = self.query("({viewport:innerHeight,scroll:document.body.scrollHeight,overflow:getComputedStyle(document.documentElement).overflowY})")
                if value is None:
                    return 1
                assert self.reader.content_fit.height == 5000 and value['viewport'] == 5000, value
                assert value['scroll'] > 5000 and value['overflow'] == 'auto', value
                self.metrics['long_mail'] = value
                self.checks.append('very-long-mail-stays-bounded-and-internally-scrollable')
                self.complete = True
                app.on_delete(force=True)
                return 0
        except Exception as error:
            import traceback
            traceback.print_exc()
            self.error = repr(error)
            app.on_delete(force=True)
            return 0
        return 1

# ==========================================
# Function: Run Linux mail acceptance without using any real mailbox or installed profile.
# Method: Isolate storage, block provider operations and emit anonymous browser geometry evidence.
# ==========================================
def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.bundle:
        sys.path.insert(0, str(args.bundle.resolve() / 'app'))
    from maildesk.reader_runtime import prepare_readers
    prepare_readers()
    from maildesk.desktop import DesktopApp
    from maildesk.gtk_native import GtkNative
    with tempfile.TemporaryDirectory(prefix='maildesk-linux-mail-') as directory:
        root = Path(directory)
        for key in ('APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME'):
            location = root / key
            location.mkdir()
            os.environ[key] = str(location)
        options = SimpleNamespace(demo=True, config=root/'accounts.json', data=root/'mail',
                                  self_test=False, report=None, screenshot=None)
        with patch('maildesk.transport.sync_account') as sync, patch('maildesk.transport.deliver') as send:
            app = DesktopApp(options)
            scenario = Scenario(app, args.output, args.baseline)
            app.g.connect(app.application, 'activate', scenario.start)
            app.run()
            assert not sync.called and not send.called
        from release_context import provenance
        report = {'provenance': provenance(args.bundle), 'ok': scenario.complete, 'checks': scenario.checks, 'metrics': scenario.metrics,
                  'error': scenario.error, 'real_provider_calls': 0}
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if scenario.complete else 1

if __name__ == '__main__':
    raise SystemExit(main())
