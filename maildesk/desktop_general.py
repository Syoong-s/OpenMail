"""User-scoped native system integration and native appearance/lifecycle helpers."""
import ctypes as C
import os
from pathlib import Path
from .gtk_native import P,I,S
from .desktop_preferences import parse_mailto,resolved_theme

# ==========================================
# Function: Bind an optional native system API without adding dependencies.
# Method: Reuse loaded runtime libraries with explicit public C signatures.
# ==========================================
def bind(app,library,name,result,*arguments):
    function=getattr(app.g.libs[library],name);function.restype=result;function.argtypes=arguments
    return function

# ==========================================
# Function: Integrate general and appearance preferences with the native desktop.
# Method: Keep optional tray/startup actions user-controlled and preserve access when unsupported.
# ==========================================
class GeneralUI:
    # ==========================================
    # Function: Initialize desktop appearance observers and recoverable tray behavior.
    # Method: Observe GNOME color-scheme when available; detect a real tray host before hiding.
    # ==========================================
    def initialize_general(self):
        self.system_theme='dark';self.system_settings=None;self.tray_icon=None;self.layout_override=None
        self.sent_sound_known=None
        self.refresh_system_theme()
        settings=self.g.gtk_widget_get_settings(self.window)
        self.g.connect(settings,'notify::gtk-theme-name',lambda *unused:self.system_theme_changed(),count=3,group='general')
        gtk=self.g.libs['gtk']
        if os.name=='nt':
            from .windows_tray import WindowsTray
            self.windows_tray=WindowsTray(self)
        if os.name!='nt' and self.legacy_tray_supported() and all(hasattr(gtk,name) for name in ('gtk_status_icon_new_from_file','gtk_status_icon_is_embedded')):
            self.tray_icon=bind(self,'gtk','gtk_status_icon_new_from_file',P,S)(str(Path(__file__).parent/'desktop_assets/icon.svg').encode())
            bind(self,'gtk','gtk_status_icon_set_tooltip_text',None,P,S)(self.tray_icon,'TeleMail · 点击恢复；右键显示恢复和退出菜单'.encode())
            bind(self,'gtk','gtk_status_icon_set_visible',None,P,I)(self.tray_icon,1)
            self.g.connect(self.tray_icon,'activate',lambda *unused:self.restore_window(),group='general')
            self.g.connect(self.tray_icon,'popup-menu',self.tray_popup,count=4,types=[P,C.c_uint,C.c_uint,P],group='general')
            self.g.connect(self.tray_icon,'notify::embedded',lambda *unused:self.tray_host_changed(),count=3,group='general')
        # Native back/toggle controls remain available when a single-pane layout hides the list.
        self.layout_button=self.g.gtk_button_new_with_label('切换邮件 / 列表'.encode())
        self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.layout_button),b'quiet')
        bind(self,'gtk','gtk_header_bar_pack_end',None,P,P)(self.widget('header'),self.layout_button)
        self.g.connect(self.layout_button,'clicked',lambda *unused:self.toggle_layout(),group='general')
        self.apply_layout()

    # ==========================================
    # Function: Avoid GTK's X11-only legacy tray widget on a native Wayland display.
    # Method: Test the active GdkDisplay GType before constructing any GtkStatusIcon.
    # ==========================================
    def legacy_tray_supported(self):
        if os.name=='nt':return True
        gdk=self.g.libs['gdk']
        if not hasattr(gdk,'gdk_x11_display_get_type'):return False
        display=bind(self,'gdk','gdk_display_get_default',P)()
        if not display:return False
        display_type=bind(self,'gdk','gdk_x11_display_get_type',C.c_size_t)()
        return bool(bind(self,'object','g_type_check_instance_is_a',I,P,C.c_size_t)(display,display_type))

    # ==========================================
    # Function: Read the desktop color preference without changing system settings.
    # Method: Check schema availability before constructing GSettings and use GTK theme name as fallback.
    # ==========================================
    def refresh_system_theme(self):
        if os.name=='nt':
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                    light=winreg.QueryValueEx(key,'AppsUseLightTheme')[0]
                self.system_theme='light' if light else 'dark'
            except OSError:self.system_theme='dark'
            return
        if getattr(self,'system_settings',None):
            pointer=bind(self,'gio','g_settings_get_string',P,P,S)(self.system_settings,b'color-scheme')
            scheme=C.string_at(pointer).decode() if pointer else '';self.g.g_free(pointer)
            self.system_theme='light' if scheme=='prefer-light' else 'dark' if scheme=='prefer-dark' else self.gtk_system_theme()
            return
        source=bind(self,'gio','g_settings_schema_source_get_default',P)()
        schema=bind(self,'gio','g_settings_schema_source_lookup',P,P,S,I)(source,b'org.gnome.desktop.interface',1) if source else None
        if schema:
            try:
                if bind(self,'gio','g_settings_schema_has_key',I,P,S)(schema,b'color-scheme'):
                    self.system_settings=bind(self,'gio','g_settings_new_full',P,P,P,S)(schema,None,None)
                    self.g.connect(self.system_settings,'changed::color-scheme',lambda *unused:self.system_theme_changed(),count=3,group='general')
            finally:bind(self,'gio','g_settings_schema_unref',None,P)(schema)
        if self.system_settings:self.refresh_system_theme()
        else:self.system_theme=self.gtk_system_theme()

    # ==========================================
    # Function: Derive a fallback system color from the selected GTK desktop theme.
    # Method: Read an allocated string through GObject; avoid the app-owned prefer-dark property.
    # ==========================================
    def gtk_system_theme(self):
        pointer=P();function=self.g.libs['object'].g_object_get
        function.restype=None;function.argtypes=[P,S,P,P]
        function(self.g.gtk_widget_get_settings(self.window),b'gtk-theme-name',C.byref(pointer),None)
        name=C.string_at(pointer).decode().lower() if pointer else ''
        self.g.g_free(pointer)
        return 'dark' if not name or 'dark' in name else 'light'

    # ==========================================
    # Function: Repaint a system-following application when desktop colors change.
    # Method: Keep explicit dark/light preferences stable and update rendered content on the GTK thread.
    # ==========================================
    def system_theme_changed(self):
        self.refresh_system_theme()
        if self.service and self.service.store.preference('theme','dark')=='system':
            self.apply_appearance()
            self.refresh()
            if self.document and hasattr(self.document.engine,'reload'):self.document.engine.reload()

    # ==========================================
    # Function: Detect a functioning notification-area host.
    # Method: Query embedding rather than assuming a tray exists under Wayland or WSLg.
    # ==========================================
    def tray_available(self):
        if os.name=='nt':return bool(getattr(self,'windows_tray',None) and self.windows_tray.available)
        return bool(getattr(self,'tray_icon',None) and bind(self,'gtk','gtk_status_icon_is_embedded',I,P)(self.tray_icon))

    # ==========================================
    # Function: Preserve access if the desktop tray disappears while TeleMail is hidden.
    # Method: Restore the primary native window whenever its only recovery affordance is lost.
    # ==========================================
    def tray_host_changed(self):
        if self.window and not self.tray_available() and not self.g.gtk_widget_get_visible(self.window):self.restore_window()

    # ==========================================
    # Function: Restore the primary window from the tray or a new activation.
    # Method: Show and present the existing application window without duplicating services.
    # ==========================================
    def restore_window(self):
        self.g.gtk_widget_show(self.window);self.apply_layout();self.g.gtk_window_present(self.window)

    # ==========================================
    # Function: Provide discoverable restore and explicit quit actions on the tray icon.
    # Method: Use a standard native GTK menu and retained callbacks, never a hidden-only process.
    # ==========================================
    def tray_popup(self,icon,button,timestamp,unused):
        old=getattr(self,'tray_menu',None)
        self.g.disconnect('tray-menu')
        if old:self.g.gtk_widget_destroy(old)
        menu=bind(self,'gtk','gtk_menu_new',P)();self.tray_menu=menu
        for title,callback in [('打开 TeleMail',self.restore_window),('退出 TeleMail',lambda:self.on_delete(force=True))]:
            item=bind(self,'gtk','gtk_menu_item_new_with_label',P,S)(title.encode())
            bind(self,'gtk','gtk_menu_shell_append',None,P,P)(menu,item)
            self.g.connect(item,'activate',lambda *unused,fn=callback:fn(),group='tray-menu')
        self.g.gtk_widget_show_all(menu)
        bind(self,'gtk','gtk_menu_popup',None,P,P,P,P,P,C.c_uint,C.c_uint)(menu,None,None,None,None,button,timestamp)

    # ==========================================
    # Function: Apply split, full-list or inbox-toggle viewing layouts.
    # Method: Hide one existing native pane while preserving its widgets and list scroll position.
    # ==========================================
    def apply_layout(self):
        if not self.service:return
        self.ensure_thread_window()
        mode=self.service.store.preference('layout_mode','splitView')
        active=bool(self.selected) or bool(getattr(self,'selected_chat','')) or bool(self.composer and self.composer.embedded and not getattr(self.composer,'detached',False))
        show_reader=self.layout_override if mode!='splitView' and self.layout_override is not None else active
        fullcompose=bool(self.composer and self.composer.embedded and not getattr(self.composer,'inline',False) and not getattr(self.composer,'detached',False))
        preview_open=bool(getattr(self,'workspace_geometry',None) and self.workspace_geometry.preview_open)
        split=(mode=='splitView' or preview_open) and not fullcompose
        if fullcompose:show_reader=True
        separate=bool(getattr(self,'thread_window',None))
        self.g.gtk_widget_set_visible(self.widget('listpane'),separate or split or not show_reader)
        self.g.gtk_widget_set_visible(self.widget('reader'),separate or split or show_reader)
        if getattr(self,'layout_button',None):
            self.g.gtk_widget_set_visible(self.layout_button,not split)
            self.g.label(self.layout_button,'← 返回邮件列表' if show_reader else '显示选中邮件',button=True)
            self.g.gtk_widget_set_sensitive(self.layout_button,active or show_reader)

    # ==========================================
    # Function: Toggle a single-pane mailbox between its list and active reader.
    # Method: Change a transient view override without resetting selection or saved layout preference.
    # ==========================================
    def toggle_layout(self):
        reader=bool(self.g.gtk_widget_get_visible(self.widget('reader')))
        self.layout_override=not reader
        self.apply_layout()

    # ==========================================
    # Function: Open an explicit safe mailto link as an unsent composer.
    # Method: Preserve an existing nonempty draft rather than replacing it without review.
    # ==========================================
    def open_mailto(self,uri):
        if getattr(self,'closing',False):return
        draft=parse_mailto(uri)
        if self.composer and not self.composer.closed:
            self.open_composer();self.message('已有邮件正在编辑；请先保存或关闭，再打开邮件链接');return
        self.open_composer(draft);self.apply_layout()

    # ==========================================
    # Function: Receive unique-instance OS mailto activation requests.
    # Method: Decode GFiles through the public GIO API and validate each URI before opening a draft.
    # ==========================================
    def open_files(self,application,files,count,hint,unused):
        if getattr(self,'closing',False):return
        self.activate()
        for index in range(min(count,8)):
            pointer=bind(self,'gio','g_file_get_uri',P,P)(files[index])
            uri=C.string_at(pointer).decode() if pointer else '';self.g.g_free(pointer)
            self.run_action(lambda value=uri:self.open_mailto(value))

    # ==========================================
    # Function: Play an optional native desktop sound after confirmed local events.
    # Method: Use the current GDK display bell and leave all sounds off unless selected.
    # ==========================================
    def play_system_sound(self):
        if getattr(self.options,'self_test',False):return
        display=bind(self,'gdk','gdk_display_get_default',P)()
        if display:bind(self,'gdk','gdk_display_beep',None,P)(display)

    # ==========================================
    # Function: Observe confirmed send transitions without playing sounds for historical jobs.
    # Method: Snapshot sent identities on first poll and play once for newly confirmed deliveries.
    # ==========================================
    def check_send_sound(self):
        with self.service.store.db() as db:known={row[0] for row in db.execute("SELECT id FROM jobs WHERE state='sent'")}
        if self.sent_sound_known is not None and known-self.sent_sound_known and self.service.store.preference('play_send_sound',False):self.play_system_sound()
        self.sent_sound_known=known

    # ==========================================
    # Function: Release optional system references at native application shutdown.
    # Method: Disconnect callbacks before unref so no settings/tray signal can use a closing window.
    # ==========================================
    def close_general(self,release_readers=True):
        if getattr(self,'notification_cards',None):self.notification_cards.close();self.notification_cards=None
        self.g.disconnect('general');self.g.disconnect('tray-menu')
        if getattr(self,'windows_tray',None):self.windows_tray.close();self.windows_tray=None
        if release_readers and getattr(self,'windows_webview_bridge',None):self.windows_webview_bridge.md_webview_shutdown()
        for key in ('tray_icon','system_settings'):
            value=getattr(self,key,None)
            if value:self.g.g_object_unref(value);setattr(self,key,None)
        if getattr(self,'tray_menu',None):self.g.gtk_widget_destroy(self.tray_menu);self.tray_menu=None
        if release_readers and getattr(self,'reader_web_context',None):self.g.g_object_unref(self.reader_web_context);self.reader_web_context=None
