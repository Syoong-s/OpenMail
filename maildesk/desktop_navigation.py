"""Full-height in-window navigation surfaces and account-scoped folder commands."""
from pathlib import Path
from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL
from .desktop_folder_navigation import FolderNavigationUI
from .desktop_pinned_navigation import PinnedNavigationUI
from .navigation_hover import NavigationHoverUI
from .account_palette import AccountPaletteUI
from .navigation_drag import NavigationDragUI
import ctypes as C

ICONS=Path(__file__).parent/'desktop_assets/icons'

# ==========================================
# Function: Own floating folder/mailbox panels without creating extra native windows.
# Method: Coordinate toggle buttons, a dismiss backdrop and vertically filling GTK revealers.
# ==========================================
class NavigationUI(FolderNavigationUI,PinnedNavigationUI,NavigationHoverUI,AccountPaletteUI,NavigationDragUI):
    # ==========================================
    # Function: Bind floating navigation once before the main window is shown.
    # Method: Keep panel visibility independent of mailbox refresh and preserve normal keyboard focus.
    # ==========================================
    def initialize_navigation(self):
        g=self.g;self.navigation_panel='';self.navigation_updating=False;self.folder_edit=None;self.folder_popup_groups=set();self.folder_row_widgets={};self.navigation_hover_owner=None;self.navigation_hover_pointer=None
        self.initialize_view_pins()
        from .desktop import VIEWS
        for name,title in [("nav_"+key,value) for key,value in VIEWS.items()]+[('import','导入 EML'),('open_document','打开文件')]:
            self.shrink_navigation_labels(self.widget(name));g.gtk_widget_set_tooltip_text(self.widget(name),title.encode())
        self.folder_capture=g.gtk_gesture_multi_press_new(self.window);g.gtk_gesture_single_set_button(self.folder_capture,0);g.gtk_event_controller_set_propagation_phase(self.folder_capture,1)
        g.connect(self.folder_capture,'pressed',self.folder_pointer_press,count=5,types=[C.c_void_p,C.c_int,C.c_double,C.c_double,C.c_void_p],group='folder-capture')
        g.connect(self.window,'focus-out-event',lambda *unused:(self.cancel_folder_edit(),False)[1],count=3,returns=True)
        for key,button in [('folders_menu','folder_toggle'),('navigation_menu','navigation_toggle')]:
            g.connect(self.widget(button),'toggled',lambda *unused,p=key,b=button:self.navigation_toggled(p,b))
            g.connect(self.widget(key),'notify::child-revealed',lambda widget,*unused:self.navigation_animation_done(widget),count=3)
        g.gtk_widget_add_events(self.widget('navigation_backdrop'),1<<8)
        g.connect(self.widget('navigation_backdrop'),'button-press-event',lambda *unused:(self.close_navigation(),True)[1],count=3,returns=True)
        g.connect(self.widget('workspace_overlay'),'size-allocate',lambda *unused:self.resize_navigation(),count=3)
        self.resize_navigation()

    # ==========================================
    # Function: Let mailbox captions yield to their fixed pin/actions at narrow widths.
    # Method: Traverse native button internals by GTK type and ellipsize labels without touching images or widget identities.
    # ==========================================
    def shrink_navigation_labels(self,widget):
        g=self.g
        if g.g_type_check_instance_is_a(widget,g.gtk_label_get_type()):
            g.gtk_label_set_ellipsize(widget,3);g.gtk_label_set_width_chars(widget,0);g.gtk_label_set_max_width_chars(widget,-1);g.gtk_widget_set_hexpand(widget,1);g.gtk_widget_set_halign(widget,0);return widget
        if not g.g_type_check_instance_is_a(widget,g.gtk_container_get_type()):return
        head=g.gtk_container_get_children(widget);cursor=head
        label=None
        try:
            while cursor:label=self.shrink_navigation_labels(cursor.contents.data) or label;cursor=cursor.contents.next
            if label:
                g.gtk_widget_set_hexpand(widget,1);g.gtk_widget_set_halign(widget,0)
        finally:g.g_list_free(head)
        return label

    # ==========================================
    # Function: Follow the two rail toggles without recursive state changes.
    # Method: Select at most one overlay and close it on a second click.
    # ==========================================
    def navigation_toggled(self,panel,button):
        if self.navigation_updating:return
        if self.g.gtk_toggle_button_get_active(self.widget(button)):self.open_navigation(panel)
        elif self.navigation_panel==panel:self.close_navigation()

    # ==========================================
    # Function: Present a full-height panel next to the fixed rail.
    # Method: Reveal the requested surface and synchronize its native reader occlusion at the same boundary.
    # ==========================================
    def open_navigation(self,panel):
        if panel not in ('folders_menu','navigation_menu'):return
        self.close_navigation(immediate=True);g=self.g;self.navigation_panel=panel;self.navigation_updating=True
        try:
            g.gtk_toggle_button_set_active(self.widget('folder_toggle' if panel=='folders_menu' else 'navigation_toggle'),1)
            target=self.widget(panel);g.gtk_widget_set_no_show_all(target,0);g.gtk_widget_show_all(target);g.gtk_widget_set_no_show_all(target,1)
            # A fullscreen GDK overlay clips native WebView children even when transparent.
            g.gtk_revealer_set_reveal_child(target,1)
            self.resize_navigation()
            sections=getattr(self,'folder_account_sections',{})
            focus=next(iter(sections.values()))['toggle'] if panel=='folders_menu' and sections else self.widget('nav_inbox')
            g.gtk_widget_grab_focus(focus);g.surfaces.reader_layers.sync(self.window)
        finally:self.navigation_updating=False

    # ==========================================
    # Function: Close floating navigation on outside click, Escape or a chosen destination.
    # Method: Hide the backdrop, restore focus and synchronize readers while the closing panel finishes its animation.
    # ==========================================
    def close_navigation(self,immediate=False):
        if not hasattr(self,'navigation_panel'):return
        self.cancel_folder_edit();self.clear_navigation_hover();self.g.surfaces.close_menus()
        g=self.g;previous=self.navigation_panel;self.navigation_updating=True;self.navigation_panel=''
        try:
            for panel,button in [('folders_menu','folder_toggle'),('navigation_menu','navigation_toggle')]:
                g.gtk_toggle_button_set_active(self.widget(button),0);g.gtk_revealer_set_reveal_child(self.widget(panel),0)
                if immediate or not g.gtk_revealer_get_child_revealed(self.widget(panel)):g.gtk_widget_hide(self.widget(panel))
            g.gtk_widget_hide(self.widget('navigation_backdrop'))
            if previous and not immediate:g.gtk_widget_grab_focus(self.widget('folder_toggle' if previous=='folders_menu' else 'navigation_toggle'))
        finally:self.navigation_updating=False
        g.surfaces.reader_layers.sync(self.window)

    # ==========================================
    # Function: Remove an animated closed panel from native hit testing after its transition ends.
    # Method: Hide the completed panel and release its native reader occlusion without a polling delay.
    # ==========================================
    def navigation_animation_done(self,widget):
        if not self.g.gtk_revealer_get_reveal_child(widget):self.g.gtk_widget_hide(widget)
        self.g.surfaces.reader_layers.sync(self.window)

    # ==========================================
    # Function: Keep floating panels aligned to the current rail and respect reduced motion.
    # Method: Let GtkOverlay fill the available height while updating only the horizontal inset and transition.
    # ==========================================
    def resize_navigation(self):
        g=self.g;inset=max(40,g.gtk_widget_get_allocated_width(self.widget('rail')))+6
        for key in ('folders_menu','navigation_menu'):
            g.gtk_widget_set_margin_start(self.widget(key),inset)
            g.gtk_revealer_set_transition_duration(self.widget(key),160 if getattr(self,'motion',True) else 0)
        g.gtk_widget_set_margin_start(self.widget('navigation_backdrop'),max(40,inset-6))
        if getattr(self,'workspace_geometry',None):self.workspace_geometry.fit()

    # ==========================================
    # Function: Create one colored collapsible account section with local add and more actions.
    # Method: Store expansion by stable account identity and keep folder rows inside its own revealer.
    # ==========================================
    def folder_account_section(self,account):
        from .ui_actions import icon_action
        g=self.g;group='folders';host=g.gtk_box_new(1,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(host),b'folder-account')
        event=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(event,0);header=g.gtk_box_new(0,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(header),b'folder-account-row');g.gtk_container_add(event,header);g.gtk_box_pack_start(host,event,0,1,0)
        configured=self.service.accounts.get(account);title=LOCAL_LABEL if account==LOCAL_ACCOUNT else ((configured.title or configured.email) if configured else account)
        toggle=g.gtk_button_new_with_label(title.encode());g.gtk_button_set_alignment(toggle,0,.5);label=g.gtk_bin_get_child(toggle)
        g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_width_chars(label,0);g.gtk_label_set_max_width_chars(label,-1);g.gtk_widget_set_tooltip_text(toggle,title.encode())
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(toggle),b'folder-account-title');g.gtk_box_pack_start(header,toggle,1,1,0)
        tools=g.gtk_box_new(0,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(tools),b'folder-inline-tools');g.gtk_box_pack_start(header,tools,0,0,0)
        add=icon_action(g,g.gtk_button_new(),'新建文件夹 · '+title,'action-add',16);more=g.gtk_menu_button_new();icon_action(g,more,'更多 · '+title,'spark-layout-more',16)
        g.gtk_box_pack_start(tools,self.account_color_button(account,boundary=self.widget('folders_menu')),0,0,0)
        for button in (add,more):g.gtk_box_pack_start(tools,button,0,0,0)
        popup=g.gtk_popover_new(more);menu=g.gtk_box_new(1,3);g.gtk_menu_button_set_popover(more,popup);g.gtk_container_add(popup,menu);g.surfaces.beside(popup,self.widget('folders_menu'))
        g.gtk_container_set_border_width(menu,6)
        g.connect(more,'toggled',lambda *unused:self.populate_folder_popup(menu,popup,account) if g.gtk_toggle_button_get_active(more) else None,group=group)
        g.connect(add,'clicked',lambda *unused:self.run_action(lambda:self.create_account_folder(account)),group=group)
        revealer=g.gtk_revealer_new();g.gtk_box_pack_start(host,revealer,0,1,0);body=g.gtk_box_new(1,2);g.gtk_widget_set_margin_start(body,8);g.gtk_container_add(revealer,body)
        opened=bool(self.service.store.preference('folder_account_expanded',{}).get(account,True));g.gtk_revealer_set_reveal_child(revealer,opened)
        g.gtk_revealer_set_transition_duration(revealer,160 if getattr(self,'motion',True) else 0)
        g.gtk_button_set_image(toggle,g.image_file(ICONS/('conversation-close.svg' if opened else 'conversation-open.svg'),15));g.gtk_button_set_always_show_image(toggle,1);self.refresh_account_heading(account,toggle)
        g.connect(toggle,'clicked',lambda *unused:self.toggle_folder_account(account,revealer,toggle),group=group)
        # Account commands remain permanently visible; folder commands use hover/focus.
        g.gtk_widget_set_opacity(tools,1)
        self.folder_account_sections[account]={'root':host,'body':body,'revealer':revealer,'toggle':toggle,'add':add,'more':more,'popup':popup,'menu':menu}
        g.gtk_box_pack_start(self.widget('folder_tree'),host,0,1,3)
        return body

    # ==========================================
    # Function: Style the live account caption after GtkButton rebuilds its image/label child.
    # Method: Re-resolve the current GtkLabel, restore shrink rules and use bounded Pango markup without leaking CSS providers.
    # ==========================================
    def refresh_account_heading(self,account,button):
        from xml.sax.saxutils import escape
        label=self.shrink_navigation_labels(button)
        if not label:return
        configured=self.service.accounts.get(account);title=LOCAL_LABEL if account==LOCAL_ACCOUNT else ((configured.title or configured.email) if configured else account)
        self.g.gtk_label_set_markup(label,('<span foreground="'+self.identity_colors.account_color(account)+'" weight="600">'+escape(title)+'</span>').encode());self.folder_account_headings[account]=label

    # ==========================================
    # Function: Persist a folder account's disclosure without changing other accounts or folder paths.
    # Method: Update one durable preference and one native chevron/revealer pair.
    # ==========================================
    def toggle_folder_account(self,account,revealer,button):
        opened=not bool(self.g.gtk_revealer_get_reveal_child(revealer));state=dict(self.service.store.preference('folder_account_expanded',{}));state[account]=opened
        self.service.store.set_preference('folder_account_expanded',state);self.g.gtk_revealer_set_reveal_child(revealer,opened)
        self.g.gtk_button_set_image(button,self.g.image_file(ICONS/('conversation-close.svg' if opened else 'conversation-open.svg'),15));self.refresh_account_heading(account,button)

    # ==========================================
    # Function: Start account-root creation inside the existing floating panel.
    # Method: Insert a transient name entry; service creation happens only on Enter.
    # ==========================================
    def create_account_folder(self,account):
        self.begin_folder_edit(account)

    # ==========================================
    # Function: Open the folder manager with the account selected by its own menu.
    # Method: Keep exact account identity without changing the list's current mailbox filter.
    # ==========================================
    def manage_account_folders(self,account):
        from .desktop_folder_manager import manage_folders
        self.close_navigation();return manage_folders(self,account_id=account)

    # ==========================================
    # Function: Open settings from a navigation command with the correct initial section.
    # Method: Close the overlay before entering an existing native settings dialog.
    # ==========================================
    def navigation_settings(self,page):
        from .desktop_settings import settings_dialog
        self.close_navigation();return settings_dialog(self,page)
