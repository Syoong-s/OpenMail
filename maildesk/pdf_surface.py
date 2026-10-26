"""Isolated trusted PDF surfaces; mail HTML keeps its separate inert policy."""
import ctypes as C
import os
from urllib.parse import urlsplit
from .gtk_native import P, I, S

# ==========================================
# Function: Embed one trusted local PDF.js document in an independent WebKit context.
# Method: Enable viewer JavaScript only in this non-pooled surface and reject other navigation.
# ==========================================
class WebKitPDFSurface:
    # ==========================================
    # Function: Create a sandboxed ephemeral WebKit widget with finite PDF-specific bindings.
    # Method: Keep it outside the inert mail widget pool and observe only native document titles.
    # ==========================================
    def __init__(self, app, group, url, changed):
        from .document_reader import library
        from .reader_runtime import reader_software_graphics
        self.app, self.g, self.group = app, app.g, group
        self.url, self.changed, self.closed, self.document_ready = url, changed, False, False
        self.lib = library('webkit2gtk-4.1', {
            'webkit_web_context_new_ephemeral': (P,),
            'webkit_web_context_set_sandbox_enabled': (None, P, I),
            'webkit_web_view_new_with_context': (P, P),
            'webkit_web_view_get_settings': (P, P),
            'webkit_settings_set_enable_javascript': (None, P, I),
            'webkit_settings_set_enable_webgl': (None, P, I),
            'webkit_settings_set_hardware_acceleration_policy': (None, P, I),
            'webkit_web_view_get_title': (S, P),
            'webkit_web_view_load_uri': (None, P, S),
            'webkit_policy_decision_ignore': (None, P),
            'webkit_navigation_policy_decision_get_navigation_action': (P, P),
            'webkit_navigation_action_get_request': (P, P),
            'webkit_uri_request_get_uri': (S, P),
            'webkit_web_view_run_javascript': (None, P, S, P, P, P),
            'webkit_web_view_stop_loading': (None, P),
            'webkit_web_view_try_close': (None, P),
            'webkit_web_view_terminate_web_process': (None, P)})
        context = self.lib.webkit_web_context_new_ephemeral()
        self.lib.webkit_web_context_set_sandbox_enabled(context, 1)
        self.widget = self.lib.webkit_web_view_new_with_context(context)
        self.g.g_object_unref(context)
        settings = self.lib.webkit_web_view_get_settings(self.widget)
        self.lib.webkit_settings_set_enable_javascript(settings, 1)
        self.lib.webkit_settings_set_enable_webgl(settings, 0)
        if reader_software_graphics():
            self.lib.webkit_settings_set_hardware_acceleration_policy(settings, 2)
        self.g.gtk_widget_set_hexpand(self.widget, 1)
        self.g.gtk_widget_set_vexpand(self.widget, 1)
        self.g.connect(self.widget, 'notify::title', self.title_changed, count=3, group=group)
        self.g.connect(self.widget, 'decide-policy', self.navigation, count=4,
                       types=[P, P, I, P], returns=True, group=group)
        self.lib.webkit_web_view_load_uri(self.widget, url.encode())

    # ==========================================
    # Function: Deliver trusted state changes to the PDF owner.
    # Method: Read the native title rather than exposing a native callable to document scripts.
    # ==========================================
    def title_changed(self, *unused):
        if not self.closed:
            title = (self.lib.webkit_web_view_get_title(self.widget) or b'').decode('utf-8', errors='replace')
            self.document_ready = title.startswith('TeleMailPDF:')
            self.changed(title)

    # ==========================================
    # Function: Keep PDF annotation links and popups from navigating the privileged viewer.
    # Method: Permit only the exact local viewer with optional same-document fragments.
    # ==========================================
    def navigation(self, widget, decision, kind, unused):
        if kind == 2:
            return False
        action = self.lib.webkit_navigation_policy_decision_get_navigation_action(decision)
        request = self.lib.webkit_navigation_action_get_request(action)
        uri = (self.lib.webkit_uri_request_get_uri(request) or b'').decode('utf-8', errors='replace')
        if kind == 0 and uri.split('#', 1)[0] == self.url and not self.closed:
            return False
        self.lib.webkit_policy_decision_ignore(decision)
        return True

    # ==========================================
    # Function: Execute only the native owner's JSON-encoded PDF toolbar command.
    # Method: Use the existing WebKit asynchronous JavaScript API without a result callback.
    # ==========================================
    def execute(self, script):
        if not self.closed:
            self.lib.webkit_web_view_run_javascript(self.widget, script.encode(), None, None, None)

    # ==========================================
    # Function: Stop an inactive PDF without returning its script-enabled widget to the mail pool.
    # Method: Disconnect callbacks and cancel loading before the owning panel destroys the widget.
    # ==========================================
    def close(self):
        if self.closed:
            return
        self.closed = True
        self.document_ready = False
        self.lib.webkit_web_view_stop_loading(self.widget)
        self.g.disconnect(self.group)

    # ==========================================
    # Function: Join the application's graceful native renderer shutdown sequence.
    # Method: Stop the PDF then request closure while its GTK owner still retains the widget.
    # ==========================================
    def begin_shutdown(self):
        self.close()
        self.lib.webkit_web_view_try_close(self.widget)

    # ==========================================
    # Function: End this PDF's own renderer after the ordinary shutdown grace period.
    # Method: Use WebKit's public termination API while GTK widget ownership remains live.
    # ==========================================
    def finish_shutdown(self):
        self.lib.webkit_web_view_terminate_web_process(self.widget)


if os.name == 'nt':
    from .windows_reader import HTMLReader

    # ==========================================
    # Function: Reuse native WebView2 placement and lifecycle for a separately trusted PDF viewer.
    # Method: Navigate only to a validated local capability and publish bounded title metadata.
    # ==========================================
    class WindowsPDFSurface(HTMLReader):
        # ==========================================
        # Function: Prepare PDF-only navigation without relaxing any mail renderer's CSP.
        # Method: Allocate the existing lazy surface and declare the two new native PDF APIs.
        # ==========================================
        def __init__(self, app, group, url, changed):
            self.pdf_url, self.pdf_changed = url, changed
            self.last_pdf_title = ''
            super().__init__(app, group)
            self.lib.md_webview_open_pdf.restype = I
            self.lib.md_webview_open_pdf.argtypes = [P, C.c_wchar_p]
            self.lib.md_webview_title.restype = I
            self.lib.md_webview_title.argtypes = [P, C.c_wchar_p, I]
            self.source, self.remote = '<!doctype html><title>Loading PDF</title>', False

        # ==========================================
        # Function: Route this surface's first and recreated controller to its PDF capability.
        # Method: Let the base class own GTK/COM setup, then replace the pending inert placeholder.
        # ==========================================
        def realized(self, *unused):
            previous = self.handle
            super().realized(*unused)
            if self.handle and self.handle != previous:
                if not self.lib.md_webview_open_pdf(self.handle, self.pdf_url):
                    raise RuntimeError('无法打开本机 PDF 阅读器')

        # ==========================================
        # Function: Reflect PDF page, search and scale changes while preserving native clipping.
        # Method: Poll the document title independently from the bridge's diagnostic query slot.
        # ==========================================
        def poll(self, *unused):
            active = super().poll(*unused)
            if active and self.handle:
                title = C.create_unicode_buffer(4096)
                if self.lib.md_webview_title(self.handle, title, len(title)) and title.value != self.last_pdf_title:
                    self.last_pdf_title = title.value
                    self.pdf_changed(title.value)
            return active

        # ==========================================
        # Function: Run a finite application-generated PDF command in its trusted viewer.
        # Method: Keep the native host script API unavailable to PDF content itself.
        # ==========================================
        def execute(self, script):
            if self.handle and not self.closed:
                self.lib.md_webview_script(self.handle, script)


# ==========================================
# Function: Select the existing platform browser technology for a trusted PDF document.
# Method: Share the PDF.js session and command protocol across native Windows and Linux surfaces.
# ==========================================
def create_pdf_surface(app, group, url, changed):
    if urlsplit(url).hostname != '127.0.0.1':
        raise ValueError('PDF viewer must use loopback')
    return (WindowsPDFSurface if os.name == 'nt' else WebKitPDFSurface)(app, group, url, changed)
