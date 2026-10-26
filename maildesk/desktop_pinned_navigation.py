"""Persistent optional rail destinations for real folders and built-in mail views."""
import ctypes as C
from pathlib import Path
from .ui_actions import icon_action

ICONS=Path(__file__).parent/'desktop_assets/icons'
VIEW_ICONS={'unread':'spark-layout-seen','priority':'spark-layout-priority','pinned':'spark-layout-pin','sent':'spark-layout-send','drafts':'spark-layout-compose','archive':'spark-layout-archive','snoozed':'spark-layout-snooze','reminders':'composer-reminder','aside':'spark-layout-folder','done':'spark-layout-done','trash':'spark-layout-trash','spam':'action-block','all':'inbox-list','new_senders':'settings-gatekeeper','blocked':'action-block'}

# ==========================================
# Function: Keep inbox, folders and more-mailboxes fixed while making mail destinations optional.
# Method: Store validated descriptors with account/path identity, separately from mailbox favorites.
# ==========================================
class PinnedNavigationUI:
    # ==========================================
    # Function: Read optional destinations while preserving the previous rail as initial defaults.
    # Method: Validate and deduplicate supported view or account/folder descriptors without writing on read.
    # ==========================================
    def navigation_pins(self):
        raw=self.service.store.preference('pinned_navigation',None)
        if raw is None:raw=[{'kind':'view','view':view} for view in ('pinned','sent','trash','done')]
        if not isinstance(raw,list):return []
        result=[]
        for row in raw:
            if not isinstance(row,dict):continue
            if row.get('kind')=='view' and row.get('view') in VIEW_ICONS:clean={'kind':'view','view':row['view']}
            elif row.get('kind')=='folder' and isinstance(row.get('account'),str) and isinstance(row.get('path'),str):clean={'kind':'folder','account':row['account'],'path':row['path']}
            else:continue
            if clean not in result:result.append(clean)
        return result

    # ==========================================
    # Function: Resolve one exact pin identity.
    # Method: Compare normalized descriptors instead of display labels.
    # ==========================================
    def navigation_is_pinned(self,descriptor):return descriptor in self.navigation_pins()

    # ==========================================
    # Function: Add or remove an optional rail shortcut without changing mailbox state.
    # Method: Persist ordered descriptors and defer row/menu rebuilding until the next main-thread tick.
    # ==========================================
    def toggle_navigation_pin(self,descriptor):
        pins=self.navigation_pins()
        if descriptor in pins:pins.remove(descriptor)
        else:pins.append(dict(descriptor))
        self.service.store.set_preference('pinned_navigation',pins);self.queue_folder_refresh()

    # ==========================================
    # Function: Add hover pin controls beside every optional mailbox destination.
    # Method: Reparent existing native view buttons safely and retain their established click callbacks.
    # ==========================================
    def initialize_view_pins(self):
        g=self.g;self.view_pin_buttons={};self.view_pin_rows={}
        for view in VIEW_ICONS:
            button=self.widget('nav_'+view);parent=g.gtk_widget_get_parent(button);event=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(event,0);line=g.gtk_box_new(0,2);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(line),b'mailbox-item-row');g.gtk_container_add(event,line)
            children=g.gtk_container_get_children(parent);cursor=children;index=0
            while cursor and cursor.contents.data!=button:index+=1;cursor=cursor.contents.next
            g.g_list_free(children);g.g_object_ref(button);g.gtk_container_remove(parent,button);g.gtk_box_pack_start(line,button,1,1,0);g.g_object_unref(button);g.gtk_container_add(parent,event);g.gtk_box_reorder_child(parent,event,index)
            pin=icon_action(g,g.gtk_button_new(),'固定到左侧栏','spark-layout-pin',14);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(pin),b'nav-pin-action');g.gtk_box_pack_start(line,pin,0,0,0);g.gtk_widget_set_opacity(pin,0)
            g.connect(pin,'clicked',lambda *unused,key=view:self.toggle_navigation_pin({'kind':'view','view':key}));self.view_pin_buttons[view]=pin;self.view_pin_rows[view]=line
            g.gtk_widget_add_events(event,(1<<12)|(1<<13))
            for signal in ('enter-notify-event','leave-notify-event'):g.connect(event,signal,lambda *unused,e=event,t=pin,r=line,leave=signal.startswith('leave'):self.navigation_hover(e,t,r,leave=leave),count=3,returns=True)
            for widget in (button,pin):
                g.connect(widget,'focus-in-event',lambda *unused,e=event,t=pin,r=line:self.navigation_hover(e,t,r,keyboard=True),count=3,returns=True)
                g.connect(widget,'focus-out-event',lambda *unused,e=event,t=pin,r=line:self.navigation_hover(e,t,r,leave=True),count=3,returns=True)
        if self.service:self.refresh_pinned_navigation(force=True)

    # ==========================================
    # Function: Rebuild optional rail icons only when their identities or folder metadata change.
    # Method: Keep dynamic shortcuts in their own scrollable host and hide unavailable remote destinations.
    # ==========================================
    def refresh_pinned_navigation(self,force=False):
        from .desktop import VIEWS
        g=self.g;pins=self.navigation_pins();rows=self.service.store.list_folders();lookup={(r['account'],r['folder']):r for r in rows}
        signature=repr((pins,self.service.store.preference('rail_order',None),[(r['account'],r['folder'],r['color'],r['selectable']) for r in rows]))
        if force or signature!=getattr(self,'navigation_pin_signature',None):
            self.navigation_pin_signature=signature;g.disconnect('rail-pins');g.disconnect('rail-drag')
            core={'core:inbox':self.widget('rail_inbox'),'core:folders':self.widget('folder_toggle'),'core:more':self.widget('navigation_toggle'),'core:settings':self.widget('preferences')}
            for widget in core.values():
                g.g_object_ref(widget);parent=g.gtk_widget_get_parent(widget)
                if parent:g.gtk_container_remove(parent,widget)
            g.clear(self.widget('pinned_navigation'));g.clear(self.widget('rail_settings_slot'));self.rail_pin_buttons=[];records={}
            for item in pins:
                row=lookup.get((item.get('account'),item.get('path'))) if item['kind']=='folder' else None
                if item['kind']=='folder' and (not row or not row['selectable']):continue
                title=(item['account']+' / '+item['path']) if row else VIEWS[item['view']]
                icon='spark-layout-folder' if row else VIEW_ICONS[item['view']]
                button=icon_action(g,g.gtk_button_new(),title+' · 拖动排序 / 右键取消固定',icon,16);records[self.rail_key(item)]=button
                if row and row['color']:g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),('folder-'+row['color']).encode())
                g.connect(button,'clicked',lambda *unused,target=dict(item):self.open_navigation_pin(target),group='rail-pins')
                popup=g.gtk_popover_new(button);content=g.gtk_box_new(1,3);g.gtk_container_set_border_width(content,5);g.gtk_container_add(popup,content)
                remove=g.gtk_button_new_with_label('取消固定'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(remove),b'popover-action');g.gtk_box_pack_start(content,remove,0,1,0);g.gtk_widget_show_all(content)
                g.connect(remove,'clicked',lambda *unused,target=dict(item),pop=popup:(g.gtk_popover_popdown(pop),self.toggle_navigation_pin(target)),group='rail-pins')
                g.connect(button,'button-press-event',lambda widget,event,*unused,pop=popup:self.pin_context_press(event,pop),count=3,returns=True,group='rail-pins');self.rail_pin_buttons.append((dict(item),button))
            self.rail_order_keys=self.ordered_rail_keys(list(records));self.rail_widgets={**core,**records};settings_bottom=self.rail_order_keys[-1]=='core:settings'
            for key in self.rail_order_keys:
                host=self.widget('rail_settings_slot') if key=='core:settings' and settings_bottom else self.widget('pinned_navigation');g.gtk_box_pack_start(host,self.rail_widgets[key],0,1,0);self.bind_rail_drag(self.rail_widgets[key],key)
            for widget in core.values():g.g_object_unref(widget)
            scroll=self.widget('pinned_navigation_scroll');g.gtk_widget_set_no_show_all(scroll,0);g.gtk_widget_show_all(scroll);g.gtk_widget_set_no_show_all(scroll,1)
            slot=self.widget('rail_settings_slot');g.gtk_widget_set_no_show_all(slot,0);g.gtk_widget_show_all(slot);g.gtk_widget_set_no_show_all(slot,1);g.gtk_widget_set_visible(slot,settings_bottom)
        inbox_context=g.gtk_widget_get_style_context(self.widget('rail_inbox'))
        (g.gtk_style_context_add_class if self.view=='inbox' else g.gtk_style_context_remove_class)(inbox_context,b'rail-active')
        for view,button in self.view_pin_buttons.items():
            row_context=g.gtk_widget_get_style_context(self.view_pin_rows[view]);(g.gtk_style_context_add_class if self.view==view else g.gtk_style_context_remove_class)(row_context,b'active')
            pinned={'kind':'view','view':view} in pins;context=g.gtk_widget_get_style_context(button)
            (g.gtk_style_context_add_class if pinned else g.gtk_style_context_remove_class)(context,b'pinned');g.gtk_widget_set_tooltip_text(button,('取消固定' if pinned else '固定到左侧栏').encode())
        for item,button in getattr(self,'rail_pin_buttons',[]):
            active=self.view==item.get('view') if item['kind']=='view' else (self.view=='folder' and self.folder_account==item['account'] and self.folder_path==item['path'])
            (g.gtk_style_context_add_class if active else g.gtk_style_context_remove_class)(g.gtk_widget_get_style_context(button),b'rail-active')

    # ==========================================
    # Function: Open a rail destination while retaining its exact account scope.
    # Method: Dispatch to the established folder or built-in view navigation handlers.
    # ==========================================
    def open_navigation_pin(self,item):
        self.cancel_folder_edit()
        if item['kind']=='folder':self.run_action(lambda:self.open_folder(item['account'],item['path']))
        else:self.set_view(item['view'])

    # ==========================================
    # Function: Offer a discoverable context action on optional rail shortcuts.
    # Method: Handle only right-button presses and leave ordinary left-click activation intact.
    # ==========================================
    def pin_context_press(self,event,popup):
        button=C.c_uint()
        if self.g.gdk_event_get_button(event,C.byref(button)) and button.value==3:self.g.gtk_popover_popup(popup);return True
        return False
