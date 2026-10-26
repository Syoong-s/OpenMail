"""Asynchronous PDF.js adapter for the existing native attachment toolbar."""
import json
import math
from .pdf_resources import PDFSession
from .pdf_surface import create_pdf_surface

# ==========================================
# Function: Keep the native page/search/zoom contract while PDF.js renders off the GTK thread.
# Method: Own a local capability session and accept only identity-bound, bounded viewer metadata.
# ==========================================
class PDFReader:
    # ==========================================
    # Function: Open one PDF with a locally bundled engine rather than a native Poppler binding.
    # Method: Start the resource session first and clean it up if native surface creation fails.
    # ==========================================
    def __init__(self, app, data, group, changed):
        self.app, self.g, self.group, self.changed = app, app.g, group, changed
        self.closed = False
        self.count, self.index, self.zoom = 0, 0, 1
        self.ready, self.error, self.rendered = False, '', 0
        self.matches, self.query, self.pending = [], '', []
        self.session = PDFSession(data)
        try:
            self.surface = create_pdf_surface(app, group, self.session.url, self.state_changed)
            self.widget = self.surface.widget
        except Exception:
            self.session.close()
            raise

    # ==========================================
    # Function: Validate native viewer metadata before changing toolbar state.
    # Method: Reject other document identities, booleans-as-integers, nonfinite scales and large counts.
    # ==========================================
    def state_changed(self, title):
        if self.closed or not title.startswith('TeleMailPDF:') or len(title) > 4096:
            return
        try:
            state = json.loads(title[len('TeleMailPDF:'):])
            if not isinstance(state, dict) or state.get('token') != self.session.token:
                return
            count, index, zoom = state['count'], state['index'], state['zoom']
            matches, rendered = state['matches'], state['rendered']
            if (type(count) is not int or not 0 <= count <= 100000 or type(index) is not int or
                    not 0 <= index < max(1, count) or type(zoom) not in (int, float) or
                    not math.isfinite(zoom) or not 0 < zoom <= 100 or type(matches) is not int or
                    not 0 <= matches <= 10000000 or type(rendered) is not int or rendered < 0 or
                    not isinstance(state['error'], str) or type(state['ready']) is not bool):
                return
        except (ValueError, KeyError, TypeError):
            return
        self.count, self.index, self.zoom = count, index, zoom
        self.ready, self.rendered = state['ready'], rendered
        self.matches = [None] * min(matches, 10000)
        error = state['error'][:200]
        if error and error != self.error:
            self.app.message(error)
        self.error = error
        self.changed()
        if self.ready and self.pending:
            pending, self.pending = self.pending, []
            for command in pending:
                self.send(command)

    # ==========================================
    # Function: Queue toolbar input until PDF.js has actually rendered its first page.
    # Method: Retain a bounded command sequence and serialize values as JSON, never executable strings.
    # ==========================================
    def send(self, command):
        if self.closed:
            return
        if not self.ready:
            self.pending = (self.pending + [command])[-32:]
            return
        self.surface.execute('window.maildeskPdf?.command(' + json.dumps(command, ensure_ascii=True) + ')')

    # ==========================================
    # Function: Select a bounded PDF page using the existing zero-based native contract.
    # Method: Defer the actual page/label update until confirmed by the viewer.
    # ==========================================
    def set_page(self, index):
        self.send({'action': 'page', 'value': max(0, min(max(0, self.count - 1), int(index)))})

    # ==========================================
    # Function: Preserve rapid consecutive native next/previous clicks despite asynchronous state updates.
    # Method: Apply each delta against the viewer's authoritative current page, not a stale native index.
    # ==========================================
    def turn_page(self, delta):
        self.send({'action': 'step', 'value': max(-100000, min(100000, int(delta)))})

    # ==========================================
    # Function: Scale the active PDF through PDF.js rather than enlarging browser chrome.
    # Method: Reject invalid factors and let the viewer clamp its actual document scale.
    # ==========================================
    def scale(self, factor):
        factor = float(factor)
        if not math.isfinite(factor) or not .1 <= factor <= 10:
            raise ValueError('PDF 缩放比例无效')
        self.send({'action': 'scale', 'value': factor})

    # ==========================================
    # Function: Fit the active page using the browser's real content viewport.
    # Method: Keep the native API while delegating page-width calculations to PDF.js.
    # ==========================================
    def fit(self, width):
        self.send({'action': 'fit'})

    # ==========================================
    # Function: Search/select text across PDF pages with real text-layer highlights.
    # Method: Use PDF.js find controller and bound the literal query length.
    # ==========================================
    def find(self, text):
        self.query = str(text)[:2048]
        self.send({'action': 'find', 'value': self.query})

    # ==========================================
    # Function: Expose readiness without mistaking an HTML placeholder for a rendered PDF.
    # Method: Reflect PDF.js pagerendered metadata, not just browser navigation completion.
    # ==========================================
    @property
    def document_ready(self):
        return self.ready and not self.closed

    # ==========================================
    # Function: Preserve the current PDF through an appearance settings refresh.
    # Method: Keep its live document, page, scale and search rather than recreating a worker.
    # ==========================================
    def reload(self):
        pass

    # ==========================================
    # Function: Revoke the document URL and release its browser exactly once.
    # Method: Stop the surface before retiring the listener and clear queued commands.
    # ==========================================
    def close(self):
        if self.closed:
            return
        self.closed = True
        self.pending.clear()
        self.surface.close()
        self.session.close()

    # ==========================================
    # Function: Join the application's existing graceful browser shutdown sequence.
    # Method: Let the platform request close before releasing the session's PDF bytes.
    # ==========================================
    def begin_shutdown(self):
        self.surface.begin_shutdown()
        self.close()

    # ==========================================
    # Function: Complete the platform's bounded renderer drain.
    # Method: Delegate while native ownership is still retained by the application.
    # ==========================================
    def finish_shutdown(self):
        self.surface.finish_shutdown()
