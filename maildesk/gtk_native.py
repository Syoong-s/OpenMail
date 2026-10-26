"""Small typed GTK 3 C-ABI adapter using only Python's standard library."""
import ctypes as C
from pathlib import Path
import sys

P, I, U, S = C.c_void_p, C.c_int, C.c_uint, C.c_char_p

# ==========================================
# Function: Read GLib-owned error messages safely.
# Method: Match GError's documented C layout and free it after projection.
# ==========================================
class GError(C.Structure):
    _fields_ = [('domain', U), ('code', I), ('message', S)]

# ==========================================
# Function: Traverse GTK container child lists.
# Method: Match GList's pointer layout without inspecting widget internals.
# ==========================================
class GList(C.Structure):
    pass

GList._fields_ = [('data', P), ('next', C.POINTER(GList)), ('prev', C.POINTER(GList))]

# ==========================================
# Function: Bind the finite native widget API used by TeleMail.
# Method: Declare every C signature and retain callbacks until disconnect.
# ==========================================
class GtkNative:
    # ==========================================
    # Function: Load platform-native GTK runtime libraries and fixed API prototypes.
    # Method: Resolve private Windows DLLs or Linux SONAMEs; no GIR, pip package or web engine is required.
    # ==========================================
    def __init__(self):
        from .platform_native import load_library
        self.libs = {name:load_library(name) for name in ('gtk','gdk','object','gio','glib','pixbuf')}
        self.callbacks = {}
        signatures = {
            'gtk': {
                'gtk_init_check': (I, P, P), 'gtk_widget_get_accessible': (P,P), 'gtk_application_new': (P, S, I),
                'gtk_application_get_windows': (C.POINTER(GList),P), 'gtk_widget_get_child_visible': (I,P), 'gtk_application_window_new': (P, P), 'gtk_window_set_application': (None, P, P),
                'gtk_window_present': (None, P), 'gtk_window_set_title': (None, P, S),
                'gtk_window_begin_resize_drag':(None,P,I,I,I,I,U), 'gtk_gesture_get_last_event':(P,P,P), 'gtk_gesture_set_state':(I,P,I),
                'gtk_window_set_default_size': (None, P, I, I), 'gtk_window_set_transient_for': (None, P, P),
                'gtk_window_maximize': (None,P), 'gtk_window_unmaximize': (None,P), 'gtk_window_is_maximized': (I,P),
                'gtk_window_set_icon_from_file': (I, P, S, P),
                'gtk_builder_new': (P,), 'gtk_builder_add_from_string': (U, P, S, C.c_size_t, P),
                'gtk_builder_get_object': (P, P, S), 'gtk_widget_show_all': (None, P), 'gtk_widget_show':(None,P), 'gtk_widget_reparent':(None,P,P), 'gtk_widget_get_parent':(P,P),
                'gtk_stack_get_transition_running': (I,P), 'gtk_stack_set_visible_child_name': (None,P,S), 'gtk_stack_get_visible_child_name': (S,P), 'gtk_entry_set_width_chars': (None,P,I),'gtk_entry_set_max_length':(None,P,I),'gtk_entry_set_alignment':(None,P,C.c_float),'gtk_entry_set_input_purpose':(None,P,I),
                'gtk_label_get_type':(C.c_size_t,),'gtk_container_get_type':(C.c_size_t,),
                'gtk_widget_set_no_show_all': (None,P,I), 'gtk_list_box_row_set_selectable': (None,P,I), 'gtk_widget_hide': (None, P), 'gtk_widget_destroy': (None, P),
                'gtk_drag_source_set':(None,P,I,P,I,I), 'gtk_drag_dest_set':(None,P,I,P,I,I), 'gtk_drag_finish':(None,P,I,I,U), 'gtk_selection_data_set_text':(I,P,S,I), 'gtk_selection_data_get_text':(P,P), 'gtk_selection_data_get_length':(I,P),
                'gtk_box_query_child_packing':(None,P,P,C.POINTER(I),C.POINTER(I),C.POINTER(U),C.POINTER(I)), 'gtk_combo_box_get_model':(P,P), 'gtk_tree_model_get_iter_first':(I,P,P), 'gtk_tree_model_iter_next':(I,P,P),
                'gtk_widget_child_focus':(I,P,I), 'gtk_window_get_focus':(P,P), 'gtk_overlay_new':(P,), 'gtk_widget_get_name':(S,P), 'gtk_widget_get_toplevel':(P,P), 'gtk_widget_is_ancestor':(I,P,P),
                'gtk_widget_get_preferred_width':(None,P,C.POINTER(I),C.POINTER(I)), 'gtk_widget_get_preferred_height':(None,P,C.POINTER(I),C.POINTER(I)), 'gtk_widget_set_margin_top':(None,P,I),
                'gtk_scrolled_window_set_max_content_height':(None,P,I), 'gtk_scrolled_window_set_propagate_natural_height':(None,P,I),
                'gtk_style_context_list_classes':(C.POINTER(GList),P),
                'gtk_range_get_value':(C.c_double,P), 'gtk_range_set_value':(None,P,C.c_double),
                'gtk_range_set_range':(None,P,C.c_double,C.c_double), 'gtk_range_set_increments':(None,P,C.c_double,C.c_double),
                'gtk_scale_new_with_range':(P,I,C.c_double,C.c_double,C.c_double),
                'gtk_range_get_adjustment':(P,P),'gtk_spin_button_new_with_range':(P,C.c_double,C.c_double,C.c_double),
                'gtk_spin_button_set_adjustment':(None,P,P),'gtk_spin_button_set_digits':(None,P,U),'gtk_spin_button_set_numeric':(None,P,I),'gtk_spin_button_set_update_policy':(None,P,I),'gtk_spin_button_update':(None,P),
                'gtk_widget_queue_resize':(None,P),'gtk_stack_get_visible_child':(P,P),
                'gtk_scale_set_draw_value':(None,P,I),'gtk_scale_set_digits':(None,P,I),
                'gtk_paned_get_position':(I,P), 'gtk_paned_set_position':(None,P,I),
                'gtk_gesture_drag_new':(P,P), 'gtk_gesture_single_set_touch_only':(None,P,I),
                'gtk_window_set_decorated':(None,P,I), 'gtk_window_set_resizable':(None,P,I),
                'gtk_window_set_skip_taskbar_hint':(None,P,I), 'gtk_window_set_skip_pager_hint':(None,P,I),
                'gtk_window_set_accept_focus':(None,P,I), 'gtk_window_set_focus_on_map':(None,P,I),
                'gtk_window_set_keep_above':(None,P,I), 'gtk_window_move':(None,P,I,I),
                'gtk_window_set_type_hint':(None,P,I), 'gtk_widget_set_tooltip_markup':(None,P,S),
                'gtk_widget_add_events':(None,P,I), 'gtk_event_box_new':(P,), 'gtk_event_box_set_visible_window':(None,P,I),
                'gtk_widget_get_pointer':(None,P,C.POINTER(I),C.POINTER(I)), 'gtk_gesture_multi_press_new':(P,P), 'gtk_gesture_single_set_button':(None,P,U), 'gtk_event_controller_set_propagation_phase':(None,P,I),
                'gtk_toggle_button_new':(P,), 'gtk_combo_box_text_new':(P,), 'gtk_editable_select_region':(None,P,I,I),
                'gtk_widget_set_sensitive': (None, P, I), 'gtk_widget_get_sensitive': (I,P), 'gtk_widget_get_visible': (I,P), 'gtk_widget_set_visible': (None, P, I),
                'gtk_widget_set_name': (None, P, S), 'gtk_widget_get_style_context': (P, P),
                'gtk_widget_get_window': (P, P), 'gtk_widget_get_allocated_width': (I, P),
                'gtk_widget_get_allocated_height': (I, P), 'gtk_widget_get_mapped': (I, P), 'gtk_widget_grab_focus': (None, P),
                'gtk_widget_set_tooltip_text': (None,P,S), 'gtk_widget_set_opacity': (None,P,C.c_double),
                'gtk_widget_set_valign': (None,P,I), 'gtk_widget_set_halign': (None,P,I), 'gtk_widget_set_margin_start': (None,P,I), 'gtk_widget_set_margin_end': (None,P,I), 'gtk_widget_set_margin_bottom': (None,P,I), 'gtk_widget_set_hexpand': (None,P,I), 'gtk_widget_set_vexpand': (None,P,I), 'gtk_widget_set_size_request': (None,P,I,I), 'gtk_widget_queue_draw': (None,P), 'gtk_drawing_area_new': (P,), 'gtk_entry_new': (P,),
                'gtk_overlay_add_overlay': (None,P,P), 'gtk_overlay_set_overlay_pass_through':(None,P,P,I),
                'gtk_style_context_remove_class': (None,P,S), 'gtk_label_set_markup': (None,P,S),
                'gtk_button_set_image': (None,P,P), 'gtk_button_set_always_show_image': (None,P,I),
                'gtk_image_new_from_pixbuf': (P,P), 'gtk_image_new_from_icon_name': (P,S,I), 'gtk_image_new_from_file': (P,S),
                'gtk_list_box_set_selection_mode': (None,P,I), 'gtk_list_box_get_selected_rows': (C.POINTER(GList),P),
                'gtk_list_box_select_all': (None,P), 'gtk_list_box_unselect_all': (None,P),
                'gtk_expander_get_label_widget':(P,P), 'gtk_expander_new': (P,S), 'gtk_expander_get_expanded': (I,P), 'gtk_expander_set_expanded': (None,P,I),
                'gtk_revealer_new':(P,), 'gtk_revealer_set_reveal_child': (None,P,I), 'gtk_revealer_get_reveal_child':(I,P), 'gtk_revealer_get_child_revealed':(I,P), 'gtk_revealer_set_transition_duration': (None,P,U),
                'gtk_spinner_start': (None,P), 'gtk_spinner_stop': (None,P),
                'gtk_widget_get_settings': (P,P), 'gtk_clipboard_get': (P,P), 'gtk_clipboard_set_text': (None,P,S,I),
                'gtk_menu_button_new':(P,), 'gtk_popover_new':(P,P), 'gtk_menu_button_set_popover':(None,P,P), 'gtk_bin_get_child': (P,P), 'gtk_popover_popup': (None,P), 'gtk_popover_popdown': (None,P),
                'gtk_box_new': (P, I, I), 'gtk_box_pack_start': (None, P, P, I, I, U),
                'gtk_box_reorder_child':(None,P,P,I), 'gtk_calendar_new':(P,), 'gtk_calendar_get_date':(None,P,P,P,P),
                'gtk_calendar_select_month':(None,P,U,U), 'gtk_calendar_select_day':(None,P,U),
                'gtk_widget_get_ancestor':(P,P,C.c_size_t),'gtk_widget_translate_coordinates':(I,P,P,I,I,C.POINTER(I),C.POINTER(I)),
                'gtk_scrolled_window_get_type':(C.c_size_t,), 'gtk_scrolled_window_get_vadjustment':(P,P),'gtk_adjustment_clamp_page':(None,P,C.c_double,C.c_double),
                'gtk_scrolled_window_new':(P,P,P),'gtk_scrolled_window_set_policy':(None,P,I,I),
                'gtk_flow_box_new':(P,), 'gtk_flow_box_set_selection_mode':(None,P,I), 'gtk_flow_box_set_max_children_per_line':(None,P,U),
                'gtk_flow_box_set_min_children_per_line':(None,P,U), 'gtk_flow_box_set_column_spacing':(None,P,U), 'gtk_flow_box_set_row_spacing':(None,P,U),
                'gtk_container_remove':(None,P,P), 'gtk_container_add': (None, P, P), 'gtk_container_get_children': (C.POINTER(GList), P),
                'gtk_container_set_border_width': (None, P, U),
                'gtk_list_box_row_new': (P,), 'gtk_list_box_row_set_header': (None,P,P), 'gtk_list_box_row_get_header': (P,P), 'gtk_list_box_set_header_func': (None,P,P,P,P), 'gtk_list_box_get_row_at_index': (P, P, I),
                'gtk_list_box_select_row': (None, P, P),
                'gtk_label_new': (P, S), 'gtk_label_set_text': (None, P, S), 'gtk_label_set_selectable': (None,P,I),
                'gtk_label_set_xalign': (None, P, C.c_float), 'gtk_label_set_line_wrap': (None, P, I), 'gtk_label_set_single_line_mode': (None, P, I),
                'gtk_label_set_ellipsize': (None, P, I), 'gtk_label_set_width_chars': (None, P, I), 'gtk_label_set_max_width_chars': (None, P, I), 'gtk_label_set_lines':(None,P,I),
                'gtk_entry_set_text': (None, P, S), 'gtk_entry_get_text': (S, P),
                'gtk_entry_set_visibility': (None, P, I), 'gtk_entry_set_placeholder_text': (None, P, S),
                'gtk_text_view_get_buffer': (P, P), 'gtk_text_view_set_editable': (None,P,I), 'gtk_text_buffer_set_text': (None, P, S, I),
                'gtk_text_buffer_get_bounds': (None, P, P, P), 'gtk_text_buffer_get_text': (P, P, P, P, I),
                'gtk_combo_box_text_append': (None, P, S, S), 'gtk_combo_box_text_remove_all': (None, P),
                'gtk_combo_box_set_active_id': (I, P, S), 'gtk_combo_box_get_active_id': (S, P),
                'gtk_toggle_button_set_active': (None, P, I), 'gtk_toggle_button_get_active': (I, P),
                'gtk_switch_set_active':(None,P,I),'gtk_switch_get_active':(I,P),
                'gtk_button_set_alignment': (None,P,C.c_float,C.c_float), 'gtk_button_set_label': (None, P, S), 'gtk_button_clicked': (None, P),
                'gtk_css_provider_new': (P,), 'gtk_css_provider_load_from_data': (I, P, S, C.c_ssize_t, P),
                'gtk_style_context_add_provider': (None,P,P,U), 'gtk_style_context_add_provider_for_screen': (None, P, P, U), 'gtk_style_context_remove_provider_for_screen': (None,P,P),
                'gtk_style_context_add_class': (None, P, S),
                'gtk_window_new':(P,I), 'gtk_dialog_new': (P,), 'gtk_button_new':(P,), 'gtk_button_new_with_label': (P, S), 'gtk_dialog_run': (I, P), 'gtk_dialog_add_button': (P, P, S, I),
                'gtk_dialog_get_content_area': (P, P), 'gtk_dialog_response': (None, P, I),
                'gtk_file_chooser_native_new': (P, S, P, I, S, S),
                'gtk_native_dialog_run': (I, P), 'gtk_native_dialog_destroy': (None, P),
                'gtk_file_chooser_get_filename': (P, P), 'gtk_file_chooser_set_current_name': (None, P, S),
                'gtk_file_chooser_set_current_folder': (I,P,S), 'gtk_progress_bar_new':(P,),
                'gtk_progress_bar_set_fraction':(None,P,C.c_double), 'gtk_progress_bar_pulse':(None,P),
                'gtk_file_chooser_set_do_overwrite_confirmation': (None, P, I),
            },
            'object': {'g_type_check_instance_is_a':(I,P,C.c_size_t),
                'g_signal_connect_data': (C.c_ulong, P, S, P, P, P, I),
                'g_signal_handler_is_connected': (I,P,C.c_ulong), 'g_object_ref_sink':(P,P), 'g_object_ref': (P,P), 'g_signal_handler_disconnect': (None, P, C.c_ulong), 'g_object_unref': (None, P), 'g_object_set': (None,P,S,I,P),
            },
            'gio': {'g_notification_new': (P,S), 'g_notification_set_body': (None,P,S), 'g_application_send_notification': (None,P,S,P), 'g_simple_action_new': (P, S, P), 'g_action_map_add_action': (None, P, P), 'g_application_run': (I, P, I, P), 'g_application_hold':(None,P), 'g_application_release':(None,P), 'g_application_quit': (None, P)},
            'glib': {'g_main_loop_new':(P,P,I), 'g_main_loop_run':(None,P), 'g_main_loop_quit':(None,P), 'g_main_loop_unref':(None,P), 'g_set_prgname': (None, S), 'g_set_application_name': (None, S), 'g_idle_add':(U,P,P), 'g_timeout_add': (U, U, P, P), 'g_source_remove': (I, U),
                     'g_free': (None, P), 'g_list_free': (None, P), 'g_error_free': (None, P)},
            'gdk': {'gdk_event_get_root_coords':(I,P,C.POINTER(C.c_double),C.POINTER(C.c_double)), 'gdk_event_get_time':(U,P), 'gdk_screen_get_default': (P,), 'gdk_event_get_button':(I,P,C.POINTER(U)), 'gdk_event_get_keyval': (I,P,C.POINTER(U)), 'gdk_event_get_state': (I,P,C.POINTER(U)), 'gdk_atom_intern_static_string': (P,S), 'gdk_pixbuf_get_from_window': (P, P, I, I, I, I)},
            'pixbuf': {'gdk_pixbuf_new_from_file_at_scale': (P,S,I,I,I,P), 'gdk_pixbuf_savev': (I, P, S, S, P, P, P)},
        }
        for lib, functions in signatures.items():
            for name, signature in functions.items():
                function = getattr(self.libs[lib], name)
                function.restype, function.argtypes = signature[0], signature[1:]
                setattr(self, name, function)
        focus=self.libs['gtk'].gtk_button_set_focus_on_click;focus.argtypes=[P,I];focus.restype=None
        # ==========================================
        # Function: Keep pointer-activated momentary controls from retaining keyboard-focus fills.
        # Method: Preserve Tab/Space navigation while leaving the current editor focus unchanged on click.
        # ==========================================
        def quiet_button(constructor,*arguments):
            button=constructor(*arguments);focus(button,0);return button
        for name in ('gtk_button_new','gtk_button_new_with_label'):
            constructor=getattr(self,name)
            setattr(self,name,lambda *arguments,create=constructor:quiet_button(create,*arguments))
        from .native_surfaces import NativeSurfaces
        self.surfaces=NativeSurfaces(self)

    # ==========================================
    # Function: Parse a native GtkBuilder definition with recoverable diagnostics.
    # Method: Own the builder reference and project GError on failure.
    # ==========================================
    def builder(self, xml):
        xml,metadata=self.surfaces.prepare_builder(xml)
        builder = self.gtk_builder_new()
        encoded, error = xml.encode('utf-8'), P()
        if not self.gtk_builder_add_from_string(builder, encoded, len(encoded), C.byref(error)):
            detail = C.cast(error, C.POINTER(GError)).contents.message.decode() if error else 'Invalid GTK definition'
            if error:
                self.g_error_free(error)
            self.g_object_unref(builder)
            raise RuntimeError(detail)
        self.surfaces.finish_builder(builder,metadata)
        return builder

    # ==========================================
    # Function: Resolve a named object from a builder.
    # Method: Fail early rather than pass a null widget into C.
    # ==========================================
    def object(self, builder, name):
        pointer = self.gtk_builder_get_object(builder, name.encode())
        if not pointer:
            raise KeyError(f'GTK object not found: {name}')
        return pointer

    # ==========================================
    # Function: Connect a strongly retained Python callback to a native signal.
    # Method: Match argument count and retain dynamic widgets until their signal group disconnects.
    # ==========================================
    def connect(self, widget, signal, callback, count=2, group='app', returns=False, types=None):
        signature = C.CFUNCTYPE(I if returns else None, *(types or [P] * count))
        # ==========================================
        # Function: Dispatch a native signal without unwinding through C.
        # Method: Report unexpected failures to stderr and return a safe default.
        # ==========================================
        def dispatch(*args):
            try:
                result = callback(*args)
                return int(bool(result)) if returns else None
            except Exception as error:
                print(f'TeleMail native signal {signal}: {type(error).__name__}: {error}', file=sys.stderr)
                return 0 if returns else None
        if group!='app':self.g_object_ref(widget)
        wrapped = signature(dispatch)
        identity = self.g_signal_connect_data(widget, signal.encode(), C.cast(wrapped, P), None, None, 0)
        self.callbacks.setdefault(group, []).append((widget, identity, wrapped))
        return identity

    # ==========================================
    # Function: Disconnect dynamic UI callbacks before destroying their widgets.
    # Method: Retain each trampoline until its native closure is disconnected.
    # ==========================================
    def disconnect(self, group):
        for widget, identity, callback in self.callbacks.pop(group, []):
            if self.g_signal_handler_is_connected(widget,identity):self.g_signal_handler_disconnect(widget, identity)
            if group!='app':self.g_object_unref(widget)

    # ==========================================
    # Function: Read and clear a GTK container without leaking GList nodes.
    # Method: Copy borrowed widget pointers before freeing the returned list.
    # ==========================================
    def clear(self, container):
        children = self.gtk_container_get_children(container)
        cursor, widgets = children, []
        while cursor:
            widgets.append(cursor.contents.data)
            cursor = cursor.contents.next
        self.g_list_free(children)
        for widget in widgets:
            self.destroy_tree(widget)

    # ==========================================
    # Function: Destroy a native source tree unless its one bounded navigation handoff still owns it.
    # Method: Let the application holder release protected old widgets after a replacement controller exists.
    # ==========================================
    def destroy_tree(self,widget):
        handoff=getattr(self,'reader_handoff',None)
        if handoff and handoff.protects(widget):return
        self.gtk_widget_destroy(widget)

    # ==========================================
    # Function: Read or replace a text entry/view using UTF-8.
    # Method: Handle GtkTextIter as an aligned opaque buffer and free returned text.
    # ==========================================
    def text(self, widget, value=None, view=False):
        if not view:
            if value is not None:
                self.gtk_entry_set_text(widget, str(value).encode())
            return (self.gtk_entry_get_text(widget) or b'').decode()
        buffer = self.gtk_text_view_get_buffer(widget)
        if value is not None:
            self.gtk_text_buffer_set_text(buffer, str(value).encode(), -1)
            return value
        start, end = (C.c_uint64 * 16)(), (C.c_uint64 * 16)()
        self.gtk_text_buffer_get_bounds(buffer, start, end)
        result = self.gtk_text_buffer_get_text(buffer, start, end, 0)
        try:
            return C.string_at(result).decode() if result else ''
        finally:
            self.g_free(result)

    # ==========================================
    # Function: Set a label or button caption without enabling markup.
    # Method: Pass untrusted mail text directly to GTK's plain-text setter.
    # ==========================================
    def label(self, widget, value, button=False):
        function = self.gtk_button_set_label if button else self.gtk_label_set_text
        function(widget, str(value).encode())

    # ==========================================
    # Function: Register the bundled open Chinese font for this process only.
    # Method: Add application fonts to Fontconfig without editing system/user font caches.
    # ==========================================
    def fonts(self, folder):
        from .platform_native import load_library,WINDOWS
        if WINDOWS:
            pango=load_library('pango');cairo=load_library('pangocairo')
            cairo.pango_cairo_font_map_get_default.argtypes=[];cairo.pango_cairo_font_map_get_default.restype=P
            register=pango.pango_font_map_add_font_file;register.argtypes=[P,S,P];register.restype=I
            fontmap=cairo.pango_cairo_font_map_get_default()
            for path in Path(folder).glob('*.otf'):
                error=P()
                if not register(fontmap,str(path).encode(),C.byref(error)):
                    detail=C.cast(error,C.POINTER(GError)).contents.message.decode() if error else '无法加载程序附带的中文字体'
                    if error:self.g_error_free(error)
                    raise RuntimeError(detail)
        self.fontconfig = load_library('fontconfig')
        add = self.fontconfig.FcConfigAppFontAddFile
        add.restype, add.argtypes = I, (P, S)
        for path in Path(folder).glob('*.otf'):
            if not add(None, str(path).encode()):
                raise RuntimeError('无法加载程序附带的中文字体')

    # ==========================================
    # Function: Apply the desktop stylesheet.
    # Method: Load a local GTK CSS provider on the default screen.
    # ==========================================
    def css(self, path):
        provider = self.gtk_css_provider_new()
        data = Path(path).read_bytes()
        error = P()
        if not self.gtk_css_provider_load_from_data(provider, data, len(data), C.byref(error)):
            detail = C.cast(error, C.POINTER(GError)).contents.message.decode() if error else 'Invalid CSS'
            if error:
                self.g_error_free(error)
            raise RuntimeError(detail)
        self.gtk_style_context_add_provider_for_screen(self.gdk_screen_get_default(), provider, 600)
        self.g_object_unref(provider)

    # ==========================================
    # Function: Choose an existing file or a new download destination.
    # Method: Use the native file chooser and release its allocated filename.
    # ==========================================
    def choose(self, parent, title, save_name=None):
        dialog = self.gtk_file_chooser_native_new(title.encode(), parent, 1 if save_name is not None else 0, '保存'.encode() if save_name is not None else '打开'.encode(), '取消'.encode())
        try:
            if save_name is not None:
                app=getattr(self.surfaces,'app',None)
                if app and getattr(app,'profile',None):
                    folder=app.profile.downloads;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
                    self.gtk_file_chooser_set_current_folder(dialog,str(folder).encode())
                self.gtk_file_chooser_set_current_name(dialog, save_name.encode())
                self.gtk_file_chooser_set_do_overwrite_confirmation(dialog, 1)
            if self.gtk_native_dialog_run(dialog)!=-3:return None
            filename=self.gtk_file_chooser_get_filename(dialog)
            try:return Path(C.string_at(filename).decode()) if filename else None
            finally:self.g_free(filename)
        finally:
            self.gtk_native_dialog_destroy(dialog);self.g_object_unref(dialog)

    # ==========================================
    # Function: Select an existing storage directory using the typed native chooser.
    # Method: Parent the system folder picker to the live main window and release its filename.
    # ==========================================
    def choose_folder(self, parent, title, current=None):
        app=getattr(self.surfaces,'app',None)
        parent=getattr(app,'window',None) or parent
        dialog=self.gtk_file_chooser_native_new(title.encode(),parent,2,'选择文件夹'.encode(),'取消'.encode())
        try:
            if current and Path(current).is_dir():self.gtk_file_chooser_set_current_folder(dialog,str(current).encode())
            if self.gtk_native_dialog_run(dialog)!=-3:return None
            filename=self.gtk_file_chooser_get_filename(dialog)
            try:return Path(C.string_at(filename).decode()) if filename else None
            finally:self.g_free(filename)
        finally:
            self.gtk_native_dialog_destroy(dialog);self.g_object_unref(dialog)

    # ==========================================
    # Function: Apply trusted per-avatar style without accumulating global CSS rules.
    # Method: Attach a higher-priority provider directly to one widget's style context.
    # ==========================================
    def style(self,widget,source,provider=None):
        fresh=provider is None
        provider=provider or self.gtk_css_provider_new();encoded=source.encode()
        if not self.gtk_css_provider_load_from_data(provider,encoded,len(encoded),None):
            if fresh:self.g_object_unref(provider)
            raise ValueError('无效的头像样式')
        if fresh:
            self.gtk_style_context_add_provider(self.gtk_widget_get_style_context(widget),provider,601)
            self.g_object_unref(provider)
        return provider

    # ==========================================
    # Function: Scale a bundled icon to the compact navigation rail size.
    # Method: Cache immutable decoded pixels while creating an independent GtkImage for each parent.
    # ==========================================
    def image_file(self,path,size):
        cache=getattr(self,'icon_pixbufs',None)
        if cache is None:cache={};self.icon_pixbufs=cache
        key=(str(path),size)
        if key not in cache:
            pixbuf=self.gdk_pixbuf_new_from_file_at_scale(str(path).encode(),size,size,1,None)
            if not pixbuf:raise ValueError('无法读取应用图标')
            cache[key]=pixbuf
        return self.gtk_image_new_from_pixbuf(cache[key])

    # ==========================================
    # Function: Release application-owned icon pixel references at shutdown.
    # Method: Leave each GtkImage's own reference intact until its widget is destroyed.
    # ==========================================
    def close_icons(self):
        for pixbuf in getattr(self,'icon_pixbufs',{}).values():self.g_object_unref(pixbuf)
        self.icon_pixbufs={}

    # ==========================================
    # Function: Capture the actual native window for verification.
    # Method: Read its GDK drawable and save PNG through the Linux GdkPixbuf API.
    # ==========================================
    def screenshot(self, window, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pixbuf = self.gdk_pixbuf_get_from_window(self.gtk_widget_get_window(window), 0, 0, self.gtk_widget_get_allocated_width(window), self.gtk_widget_get_allocated_height(window))
        if not pixbuf:
            raise RuntimeError('当前显示后端不支持窗口截图；可用 GDK_BACKEND=x11 进行截图测试')
        error = P()
        try:
            if not self.gdk_pixbuf_savev(pixbuf, str(path).encode(), b'png', None, None, C.byref(error)):
                raise RuntimeError('无法保存窗口截图')
        finally:
            if error:
                self.g_error_free(error)
            self.g_object_unref(pixbuf)
