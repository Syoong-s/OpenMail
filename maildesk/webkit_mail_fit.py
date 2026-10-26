"""Host-owned Linux mail fitting with isolated scripts and inert document markup."""
import ctypes as C
import json
from .gtk_native import P, I, S
from .reader_fit import MEASURE_MAIL, fitted_height

# Native async callbacks must outlive closed/recycled readers until WebKit delivers their result.
_PENDING = {}

# ==========================================
# Function: Fit conversation leaves to the browser's actual content bounds.
# Method: Execute only trusted host code in a separate world; email markup scripting stays disabled.
# ==========================================
class WebKitMailFit:
    # ==========================================
    # Function: Bind the stable WebKitGTK asynchronous script-result ABI.
    # Method: Keep document scripts disabled separately from privileged host evaluation.
    # ==========================================
    def __init__(self, reader):
        from .document_reader import library
        self.reader, self.g, self.lib = reader, reader.g, reader.lib
        signatures = {
            'webkit_settings_set_enable_javascript_markup': (None, P, I),
            'webkit_web_view_run_javascript_in_world': (None, P, S, S, P, P, P),
            'webkit_web_view_run_javascript_in_world_finish': (P, P, P, P),
            'webkit_javascript_result_get_js_value': (P, P),
            'webkit_javascript_result_unref': (None, P)}
        for name, signature in signatures.items():
            function = getattr(self.lib, name)
            function.restype, function.argtypes = signature[0], signature[1:]
        self.jsc = library('javascriptcoregtk-4.1', {'jsc_value_to_json': (P, P, C.c_uint)})
        settings = self.lib.webkit_web_view_get_settings(reader.view)
        self.lib.webkit_settings_set_enable_javascript_markup(settings, 0)
        self.lib.webkit_settings_set_enable_javascript(settings, 1)
        self.pending, self.height, self.timer = False, None, 0
        self.callback = C.CFUNCTYPE(I, P)(self.poll)

    # ==========================================
    # Function: Start finite per-reader polling after compact mode is requested.
    # Method: Retain one GLib source and skip hidden or unready documents on each tick.
    # ==========================================
    def start(self):
        if not self.timer:
            self.timer = self.g.g_timeout_add(350, C.cast(self.callback, P), None)

    # ==========================================
    # Function: Read one trusted expression without sharing the document's script world.
    # Method: Retain callback/widget ownership until completion and release every native result.
    # ==========================================
    def query(self, expression, done):
        reader, g, lib = self.reader, self.g, self.lib
        widget = reader.view
        g.g_object_ref(widget)
        # ==========================================
        # Function: Project one asynchronous native result into plain Python data.
        # Method: Free errors, JSON strings and native result references even after reader closure.
        # ==========================================
        def finished(view, result, unused):
            error, native, encoded = P(), None, None
            value = None
            try:
                native = lib.webkit_web_view_run_javascript_in_world_finish(view, result, C.byref(error))
                if native:
                    encoded = self.jsc.jsc_value_to_json(lib.webkit_javascript_result_get_js_value(native), 0)
                    if encoded:
                        value = json.loads(C.string_at(encoded).decode('utf-8'))
                done(value)
            finally:
                if error: g.g_error_free(error)
                if encoded: g.g_free(encoded)
                if native: lib.webkit_javascript_result_unref(native)
                g.g_object_unref(widget)
                _PENDING.pop(id(callback), None)
        callback = C.CFUNCTYPE(None, P, P, P)(finished)
        _PENDING[id(callback)] = callback
        lib.webkit_web_view_run_javascript_in_world(widget, expression.encode(), b'maildesk-layout',
                                                    None, C.cast(callback, P), None)

    # ==========================================
    # Function: Resize only the still-current, visible conversation document.
    # Method: Bind each result to its load generation and title, then convert CSS pixels to GTK units.
    # ==========================================
    def poll(self, *unused):
        reader, g = self.reader, self.g
        if reader.closed:
            self.timer = 0
            return 0
        if self.pending or not reader.document_ready or not g.gtk_widget_get_mapped(reader.widget):
            return 1
        if g.gtk_widget_get_allocated_height(reader.widget) < 8:
            return 1
        generation = reader.load_generation
        allocation = (g.gtk_widget_get_allocated_width(reader.widget),
                      g.gtk_widget_get_allocated_height(reader.widget), reader.zoom)
        self.pending = True
        # ==========================================
        # Function: Apply one completed measurement without reviving a retired reader.
        # Method: Reject stale generations and use the shared bounded DPI-aware allocation helper.
        # ==========================================
        def measured(value):
            self.pending = False
            if reader.closed or generation != reader.load_generation or not isinstance(value, dict):
                return
            if allocation != (g.gtk_widget_get_allocated_width(reader.widget),
                              g.gtk_widget_get_allocated_height(reader.widget), reader.zoom):
                return
            if value.get('title') != reader.expected_title:
                return
            height = fitted_height(value, g.gtk_widget_get_allocated_height(reader.widget))
            if height and (self.height is None or abs(height - self.height) > 2):
                self.height = height
                g.gtk_widget_set_size_request(reader.widget, -1, height)
        allocated = g.gtk_widget_get_allocated_height(reader.widget)
        self.query('(()=>{if(document.title!==' + json.dumps(reader.expected_title) + ')return null;const result=' + MEASURE_MAIL + ';if(result)document.documentElement.style.overflowY='
                   "result.height*" + str(allocated) + "/result.viewport<4998?'hidden':'auto';return result})()", measured)
        return 1

    # ==========================================
    # Function: Retire the reader's timer before its native widget enters the reuse pool.
    # Method: Let outstanding native results drain under closed/generation guards.
    # ==========================================
    def close(self):
        if self.timer:
            self.g.g_source_remove(self.timer)
            self.timer = 0
