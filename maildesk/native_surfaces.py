"""Same-window rounded menus and editor cards over compatible native controllers."""
import ctypes as C
import sys
import xml.etree.ElementTree as ET
from .native_reader_layers import ReaderLayers

P=C.c_void_p

# ==========================================
# Function: Present native menu/dialog content without OS popover arrows or extra editor windows.
# Method: Preserve hidden GTK controllers while placing owned native frames in a root overlay.
# ==========================================
class NativeSurfaces:
    # ==========================================
    # Function: Retain raw C APIs before installing compatibility dispatchers.
    # Method: Intercept only managed objects and leave independent native windows unchanged.
    # ==========================================
    def __init__(self,g):
        self.g=g;self.app=None;self.states={};self.links={};self.roots={};self.opened=[];self.retired=[];self.choice_proxies={};self.stopping=False;self.reader_layers=ReaderLayers(self)
        names=('gtk_menu_button_new','gtk_menu_button_set_popover','gtk_popover_new','gtk_popover_popup','gtk_popover_popdown','gtk_bin_get_child','gtk_widget_show_all','gtk_widget_show','gtk_widget_hide','gtk_widget_set_visible','gtk_widget_get_visible','gtk_widget_destroy','gtk_window_present','gtk_dialog_run','gtk_dialog_get_content_area','gtk_dialog_add_button','gtk_window_set_default_size','gtk_widget_set_sensitive','gtk_widget_get_style_context','gtk_window_set_title')
        self.orig={name:getattr(g,name) for name in names}
        for name in names:setattr(g,name,getattr(self,name.removeprefix('gtk_')))

    # ==========================================
    # Function: Give menu buttons plain toggle behavior while keeping public builder identifiers.
    # Method: Strip native popover links before construction and bind them through the broker afterward.
    # ==========================================
    def prepare_builder(self,xml):
        root=ET.fromstring(xml);links=[];popovers=[]
        for index,node in enumerate(root.iter('object')):
            if node.get('class')=='GtkPopover' and node.get('id'):popovers.append(node.get('id'))
            if node.get('class')!='GtkMenuButton':continue
            node.set('class','GtkToggleButton')
            if not node.get('id'):node.set('id','surface-button-'+str(index))
            prop=node.find('property[@name="popover"]')
            if prop is not None:links.append((node.get('id'),prop.text));node.remove(prop)
        return ET.tostring(root,encoding='unicode'),(popovers,links)

    # ==========================================
    # Function: Connect newly parsed menu controllers without showing their native popovers.
    # Method: Register references after successful GTK parsing, then connect each toggle identity.
    # ==========================================
    def finish_builder(self,builder,metadata):
        popovers,links=metadata
        for name in popovers:self.register_menu(self.g.object(builder,name),None)
        for button,popover in links:self.menu_button_set_popover(self.g.object(builder,button),self.g.object(builder,popover))

    # ==========================================
    # Function: Attach the broker to the primary desktop after its window exists.
    # Method: Reuse the existing workspace overlay and one input observer per root window.
    # ==========================================
    def attach(self,app):
        self.app=app
        if app.window not in self.roots:self.add_root(app.window,app.widget('workspace_overlay'))

    # ==========================================
    # Function: Keep a disconnected native callback trampoline alive until a later GTK turn.
    # Method: Retire its Python references separately from immediate native handler disconnection.
    # ==========================================
    def retire(self,group):
        callbacks=list(self.g.callbacks.get(group,[]));self.g.disconnect(group)
        if callbacks:self.retired.append(callbacks)

    # ==========================================
    # Function: Observe outside clicks and Escape without taking an exclusive native pointer grab.
    # Method: Use capture-phase gestures and keep each overlay root independently owned.
    # ==========================================
    def add_root(self,window,overlay):
        g=self.g;group='surface-root-'+str(window);gesture=g.gtk_gesture_multi_press_new(window);g.gtk_gesture_single_set_button(gesture,0);g.gtk_event_controller_set_propagation_phase(gesture,1)
        self.roots[window]={'overlay':overlay,'gesture':gesture,'group':group,'layout_source':0,'layout_signature':None,'layout_callback':C.CFUNCTYPE(C.c_int,P)(lambda unused:self.idle_relayout(window))}
        g.connect(gesture,'pressed',lambda widget,count,x,y,data:self.pointer_press(window,x,y),types=[P,C.c_int,C.c_double,C.c_double,P],group=group)
        g.connect(window,'key-press-event',lambda widget,event,data:self.key_press(window,event),count=3,returns=True,group=group)
        g.connect(window,'focus-out-event',lambda *unused:self.focus_out(window),count=3,returns=True,group=group)
        g.connect(overlay,'size-allocate',lambda *unused:self.queue_relayout(window),count=3,group=group)
        g.connect(window,'size-allocate',lambda *unused:self.queue_relayout(window),count=3,group=group)
        g.connect(window,'destroy',lambda *unused:self.remove_root(window),group=group)
        if sys.platform=='win32':
            # ==========================================
            # Function: Refit large open editors when their owner moves to a different monitor.
            # Method: Compare work-area identities and defer layout outside the native configure event.
            # ==========================================
            def monitor_changed(*unused):
                from .windows_display import geometry
                root=self.roots.get(window)
                if not root:return False
                bounds=geometry(g,window)
                if bounds:
                    signature=(bounds.work.left,bounds.work.top,bounds.work.right,bounds.work.bottom)
                    if signature!=root.get('monitor_workarea'):
                        root['monitor_workarea']=signature;self.queue_relayout(window)
                return False
            g.connect(window,'configure-event',monitor_changed,count=3,returns=True,group=group)

    # ==========================================
    # Function: Release a secondary root before its native overlay is destroyed.
    # Method: Dispose its managed surfaces and input observer while native objects remain valid.
    # ==========================================
    def remove_root(self,window):
        root=self.roots.get(window)
        if not root:return
        if root['layout_source']:self.g.g_source_remove(root['layout_source']);root['layout_source']=0
        for key in list(reversed(self.opened)):
            if self.states[key]['root']==window:self.close(key)
        for key,state in list(self.states.items()):
            if state['root']!=window:continue
            anchor=state.get('anchor');current=self.g.gtk_widget_get_toplevel(anchor) if anchor else None
            if state['kind']=='menu' and current!=window and current in self.roots:
                state['root']=current;state['parent']=self.parent_for(anchor)
                if state['frame']:self.move_frame(state['frame'],self.roots[current]['overlay'])
            else:self.dispose(key)
        self.roots.pop(window,None);self.retire(root['group']);self.g.g_object_unref(root['gesture'])

    # ==========================================
    # Function: Locate a menu's own native client root, including a standalone composer.
    # Method: Lazily wrap another window's existing content without changing its controls or model.
    # ==========================================
    def root_for(self,anchor=None):
        g=self.g;window=g.gtk_widget_get_toplevel(anchor) if anchor else (self.app.window if self.app else None)
        if window not in self.roots:
            child=self.orig['gtk_bin_get_child'](window)
            if not child:raise RuntimeError('浮层缺少可用的应用内容区域')
            g.g_object_ref(child);g.gtk_container_remove(window,child);overlay=g.gtk_overlay_new();g.gtk_container_add(overlay,child);g.g_object_unref(child);g.gtk_container_add(window,overlay);self.orig['gtk_widget_show_all'](overlay);self.add_root(window,overlay)
        return window,self.roots[window]['overlay']

    # ==========================================
    # Function: Create one plain native toggle for a broker-owned menu.
    # Method: Avoid GtkMenuButton's internal native popup behavior entirely.
    # ==========================================
    def menu_button_new(self):
        button=self.g.gtk_toggle_button_new();focus=self.g.libs['gtk'].gtk_button_set_focus_on_click;focus.argtypes=[P,C.c_int];focus.restype=None;focus(button,0);return button

    # ==========================================
    # Function: Allocate a hidden GtkPopover as a compatible content controller.
    # Method: Keep native callers' container APIs while recording the visible anchor separately.
    # ==========================================
    def popover_new(self,relative):
        popover=self.orig['gtk_popover_new'](None);self.register_menu(popover,relative);return popover

    # ==========================================
    # Function: Own one native popup controller until its anchor is destroyed.
    # Method: Sink a controller reference and attach a lifetime signal to its anchor.
    # ==========================================
    def register_menu(self,controller,anchor):
        if controller not in self.states:
            self.g.g_object_ref_sink(controller);self.states[controller]={'id':controller,'kind':'menu','anchor':None,'frame':None,'content':None,'root':None,'parent':None,'open':False,'placement':'auto','group':'surface-'+str(controller)}
        state=self.states[controller]
        if anchor and state['anchor']!=anchor:
            state['anchor']=anchor;self.g.connect(anchor,'destroy',lambda *unused,key=controller:self.dispose(key),group=state['group'])
        return state

    # ==========================================
    # Function: Connect a menu toggle to its registered content surface.
    # Method: Preserve the public setter while routing toggles through side-by-side frame ownership.
    # ==========================================
    def menu_button_set_popover(self,button,popover):
        if not popover:
            old=self.links.pop(button,None)
            if old:self.close(old)
            return
        self.register_menu(popover,button);old=self.links.get(button)
        if old==popover:return
        if old:self.close(old)
        self.links[button]=popover;self.g.connect(button,'toggled',lambda *unused:self.toggle_menu(button),group=self.states[popover]['group'])

    # ==========================================
    # Function: Follow a toggle without reopening a surface during recursive dismissal.
    # Method: Compare real toggle state and idempotent managed open state.
    # ==========================================
    def toggle_menu(self,button):
        key=self.links.get(button)
        if key not in self.states:return
        if self.g.gtk_toggle_button_get_active(button):self.show_menu(key)
        else:self.close(key)

    # ==========================================
    # Function: Request an adjacent menu rooted beside a navigation panel.
    # Method: Preserve the panel rectangle as the placement boundary rather than covering its rows.
    # ==========================================
    def beside(self,controller,panel=None):
        state=self.states[controller];state['placement']='side';state['boundary']=panel

    # ==========================================
    # Function: Resolve the nearest visible managed ancestor of a native widget.
    # Method: Walk open frames from top to bottom and use GTK ancestry instead of labels.
    # ==========================================
    def parent_for(self,widget):
        if not widget:return None
        for key in reversed(self.opened):
            state=self.states.get(key)
            if state and state['open'] and state['frame'] and (widget==state['frame'] or self.g.gtk_widget_is_ancestor(widget,state['frame'])):return key
        return None

    # ==========================================
    # Function: Show a rounded flyout and retain only its ancestor branch.
    # Method: Place a child beside its parent and immediately project managed occlusion to native readers.
    # ==========================================
    def show_menu(self,controller):
        if self.stopping:return
        state=self.states.get(controller)
        if not state:return self.orig['gtk_popover_popup'](controller)
        if state['open']:return
        g=self.g;anchor=state.get('anchor')
        if state.get('require_anchor_allocation') and anchor and (not g.gtk_widget_get_mapped(anchor) or g.gtk_widget_get_allocated_width(anchor)<=1 or g.gtk_widget_get_allocated_height(anchor)<=1):
            if not state.get('show_source'):
                # ==========================================
                # Function: Present requested details after their stable Settings anchor is allocated.
                # Method: Bound the delayed retries and let page hide, Escape or disposal cancel ownership.
                # ==========================================
                def retry(unused):
                    if controller not in self.states or self.stopping:state['show_source']=0;return 0
                    current=state.get('anchor')
                    if current and (not g.gtk_widget_get_mapped(current) or g.gtk_widget_get_allocated_width(current)<=1 or g.gtk_widget_get_allocated_height(current)<=1):
                        state['show_attempts']+=1
                        if state['show_attempts']<4:return 1
                        state['show_source']=0;return 0
                    state['show_source']=0;self.show_menu(controller);return 0
                state['show_attempts']=0;state['show_callback']=C.CFUNCTYPE(C.c_int,P)(retry);state['show_source']=g.g_timeout_add(30,C.cast(state['show_callback'],P),None)
            return
        if state.get('show_source'):g.g_source_remove(state['show_source']);state['show_source']=0
        window,overlay=self.root_for(state['anchor']);parent=self.parent_for(state['anchor']);state['parent']=parent;state['root']=window
        keep=self.ancestors(parent)
        for key in list(reversed(self.opened)):
            other=self.states.get(key)
            if other and other['root']==window and other['kind']=='menu' and key not in keep:self.close(key)
        if not state['content']:state['content']=self.orig['gtk_bin_get_child'](controller)
        if not state['content']:return
        if not state['frame']:
            content=state['content'];g.g_object_ref(content);g.gtk_container_remove(controller,content)
            state['frame']=self.make_frame(overlay,'surface-flyout');scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_scrolled_window_set_propagate_natural_height(scroll,1);g.gtk_container_add(scroll,content);g.g_object_unref(content);g.gtk_box_pack_start(state['frame'],scroll,1,1,0);state['scroll']=scroll
            name=g.gtk_widget_get_name(controller)
            if name:g.gtk_widget_set_name(state['frame'],name)
            classes=g.gtk_style_context_list_classes(self.orig['gtk_widget_get_style_context'](controller));cursor=classes
            while cursor:
                g.gtk_style_context_add_class(self.orig['gtk_widget_get_style_context'](state['frame']),C.cast(cursor.contents.data,C.c_char_p).value);cursor=cursor.contents.next
            g.g_list_free(classes)
        else:self.move_frame(state['frame'],overlay)
        state['open']=True;self.opened.append(controller);self.raise_widget(overlay,state['frame']);self.orig['gtk_widget_show_all'](state['frame']);self.position(state)
        anchor=state['anchor']
        if anchor in self.links and not g.gtk_toggle_button_get_active(anchor):g.gtk_toggle_button_set_active(anchor,1)
        self.reader_layers.sync(window)

    # ==========================================
    # Function: Preserve the public native popup entrypoint.
    # Method: Delegate managed menu presentation to the same-window broker.
    # ==========================================
    def popover_popup(self,controller):return self.show_menu(controller)

    # ==========================================
    # Function: Create a common border/shadow surface without a native popover tail.
    # Method: Align a plain GTK box to the overlay origin and style its rounded frame.
    # ==========================================
    def make_frame(self,overlay,css):
        g=self.g;frame=g.gtk_box_new(1,0);g.gtk_widget_set_halign(frame,1);g.gtk_widget_set_valign(frame,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(frame),css.encode());g.gtk_overlay_add_overlay(overlay,frame);return frame

    # ==========================================
    # Function: Move a frame above its existing siblings without losing its native identity.
    # Method: Temporarily retain the widget during overlay remove/reinsert.
    # ==========================================
    def raise_widget(self,overlay,widget):
        g=self.g;g.g_object_ref(widget);g.gtk_container_remove(overlay,widget);g.gtk_overlay_add_overlay(overlay,widget);g.g_object_unref(widget)

    # ==========================================
    # Function: Follow a retained composer menu when its controls move between native windows.
    # Method: Reparent the hidden frame from its actual overlay without rebuilding controller content.
    # ==========================================
    def move_frame(self,frame,overlay):
        g=self.g;parent=g.gtk_widget_get_parent(frame)
        if parent==overlay:return
        g.g_object_ref(frame)
        if parent:g.gtk_container_remove(parent,frame)
        g.gtk_overlay_add_overlay(overlay,frame);g.g_object_unref(frame)

    # ==========================================
    # Function: Return all logical ancestors of a surface.
    # Method: Follow controller identities with cycle protection.
    # ==========================================
    def ancestors(self,key):
        result=set()
        while key in self.states and key not in result:result.add(key);key=self.states[key]['parent']
        return result

    # ==========================================
    # Function: Obtain a widget rectangle in overlay coordinates.
    # Method: Translate native allocations and return an empty rectangle for unavailable anchors.
    # ==========================================
    def rectangle(self,widget,overlay):
        if not widget:return (12,12,0,0)
        x,y=C.c_int(),C.c_int()
        if not self.g.gtk_widget_translate_coordinates(widget,overlay,0,0,C.byref(x),C.byref(y)):return (12,12,0,0)
        return x.value,y.value,self.g.gtk_widget_get_allocated_width(widget),self.g.gtk_widget_get_allocated_height(widget)

    # ==========================================
    # Function: Measure content without feeding previous placement margins back into width.
    # Method: Read preferred dimensions of the inner content, never of its positioned outer frame.
    # ==========================================
    def natural(self,widget):
        low,width,height=C.c_int(),C.c_int(),C.c_int();self.g.gtk_widget_get_preferred_width(widget,C.byref(low),C.byref(width));self.g.gtk_widget_get_preferred_height(widget,C.byref(low),C.byref(height));return width.value,height.value

    # ==========================================
    # Function: Place a root dropdown, adjacent child or centered native editor card.
    # Method: Fit editors to the chosen font and available monitor, then clamp and commit reader exclusions.
    # ==========================================
    def position(self,state):
        if not state['open'] or state['root'] not in self.roots:return
        g=self.g;overlay=self.roots[state['root']]['overlay'];room_w=max(320,g.gtk_widget_get_allocated_width(overlay));room_h=max(240,g.gtk_widget_get_allocated_height(overlay));ox,oy=C.c_int(),C.c_int();g.gtk_widget_translate_coordinates(overlay,state['root'],0,0,C.byref(ox),C.byref(oy));room_w=max(240,min(room_w,g.gtk_widget_get_allocated_width(state['root'])-ox.value));room_h=max(240,min(room_h,g.gtk_widget_get_allocated_height(state['root'])-oy.value));content_w,content_h=self.natural(state['content']);parent=self.states.get(state['parent']);anchor=self.rectangle(state.get('anchor'),overlay)
        dialog=state['kind']=='dialog';factor=max(1,getattr(self.app,'ui_font_size',14)/14) if dialog else 1
        desired=max((state.get('width') or 0)*factor,content_w+18)
        chrome=max(96,sum(self.natural(state[key])[1] for key in ('header','footer') if state.get(key))+24) if dialog else 14
        desired_height=720*factor if state.get('workspace') else content_h+chrome
        if dialog and not state.get('parent') and sys.platform=='win32':
            from .windows_display import fit_dialog
            fit_dialog(self,state,desired,desired_height)
        width=min(max(120,desired),room_w-24)
        adjacent=state.get('placement')=='side' or bool(parent and parent['kind']=='menu')
        if adjacent:
            boundary=parent['frame'] if parent else state.get('boundary') or state.get('anchor');px,py,pw,ph=self.rectangle(boundary,overlay);right=room_w-(px+pw+7)-8;left=px-15
            if state.get('overlay_fallback') and max(right,left)<width:
                x=max(8,min(px+pw-width-12,room_w-width-8))
            elif right>=min(width,200) or right>=left:x=px+pw+7;width=min(width,max(80,right))
            else:width=min(width,max(80,left));x=px-width-7
            y=anchor[1]
        elif dialog:x=(room_w-width)//2;y=24
        else:x=anchor[0];y=anchor[1]+anchor[3]+6
        extra=chrome;max_body=max(80,room_h-extra-24)
        if state['scroll']:g.gtk_scrolled_window_set_max_content_height(state['scroll'],max_body)
        height=min(desired_height,room_h-24) if state.get('workspace') else min(content_h+extra,room_h-20)
        if state.get('placement')=='above':y=max(8,anchor[1]-height-6)
        elif dialog and not adjacent:y=max(12,(room_h-height)//2)
        elif y+height>room_h-8:y=max(8,room_h-height-8)
        if state.get('require_anchor_allocation'):y=max(8,min(y,room_h-height-8))
        x=max(8,min(x,room_w-width-8));g.gtk_widget_set_size_request(state['frame'],int(width),int(height) if state.get('workspace') else -1);g.gtk_widget_set_margin_start(state['frame'],int(x));g.gtk_widget_set_margin_top(state['frame'],int(y))
        state['bounds']=(int(x),int(y),int(width),int(height))
        self.reader_layers.sync(state['root'])

    # ==========================================
    # Function: Refresh open surface placements after root allocation changes.
    # Method: Keep branch order so children follow updated parent geometry.
    # ==========================================
    def relayout(self,window):
        for key in list(self.opened):
            state=self.states.get(key)
            if state and state['root']==window:self.position(state)

    # ==========================================
    # Function: Schedule placement after GTK finishes the current allocation signal.
    # Method: Keep one retained idle source per root so native size_allocate cannot discard newly queued layout requests.
    # ==========================================
    def queue_relayout(self,window):
        root=self.roots.get(window)
        if self.stopping or not root or root['layout_source'] or not self.opened:return
        root['layout_source']=self.g.g_idle_add(C.cast(root['layout_callback'],P),None)

    # ==========================================
    # Function: Commit managed surface geometry and paint after parent allocation unwinds.
    # Method: Commit popup layout and native occlusion once per requested geometry without a repaint loop.
    # ==========================================
    def idle_relayout(self,window):
        root=self.roots.get(window)
        if not root or self.stopping:return 0
        root['layout_source']=0;self.relayout(window);states=[self.states[key] for key in self.opened if key in self.states and self.states[key]['root']==window]
        signature=(self.g.gtk_widget_get_allocated_width(window),self.g.gtk_widget_get_allocated_height(window),tuple((state['id'],state.get('bounds')) for state in states))
        if signature!=root['layout_signature']:
            root['layout_signature']=signature
            self.g.gtk_widget_queue_resize(root['overlay'])
        for state in states:self.g.gtk_widget_queue_draw(state['frame'])
        self.reader_layers.sync(window)
        return 0

    # ==========================================
    # Function: Dismiss one branch while respecting managed dialog cancellation.
    # Method: Close descendants, hide frames and immediately restore native content below the dismissed branch.
    # ==========================================
    def close(self,controller,response=-6):
        state=self.states.get(controller)
        if not state:return
        if state.get('show_source'):self.g.g_source_remove(state['show_source']);state['show_source']=0
        if not state['open']:return
        for key in list(reversed(self.opened)):
            if key!=controller and controller in self.ancestors(self.states[key]['parent']):self.close(key,response)
        state['open']=False
        if controller in self.opened:self.opened.remove(controller)
        if state['frame']:self.orig['gtk_widget_hide'](state['frame'])
        if state.get('backdrop'):self.orig['gtk_widget_hide'](state['backdrop'])
        if state['kind']=='dialog' and state['loops']:self.g.gtk_dialog_response(controller,response)
        anchor=state.get('anchor')
        if anchor in self.links and self.g.gtk_toggle_button_get_active(anchor):self.g.gtk_toggle_button_set_active(anchor,0)
        self.reader_layers.sync(state['root'])
        if state['kind']=='dialog' and sys.platform=='win32':
            from .windows_display import restore_dialog
            restore_dialog(self,state['root'])

    # ==========================================
    # Function: Close ephemeral menus without discarding unrelated settings/editor cards.
    # Method: Dismiss menu roots and their logical children only.
    # ==========================================
    def close_menus(self):
        for key in list(reversed(self.opened)):
            if self.states[key]['kind']=='menu':self.close(key)

    # ==========================================
    # Function: Apply native popup-down semantics to a managed branch.
    # Method: Dispatch unmanaged controllers to GTK unchanged.
    # ==========================================
    def popover_popdown(self,controller):
        if controller in self.states:self.close(controller)
        else:self.orig['gtk_popover_popdown'](controller)

    # ==========================================
    # Function: Expose moved content to existing native popover callers.
    # Method: Return the original child identity after it has moved into an overlay frame.
    # ==========================================
    def bin_get_child(self,widget):
        state=self.states.get(widget)
        return state['content'] if state and state['content'] else self.orig['gtk_bin_get_child'](widget)

    # ==========================================
    # Function: Register a hidden GtkDialog as a same-client editor card.
    # Method: Create independent public content/footer boxes, leaving GTK's private children untouched.
    # ==========================================
    def register_dialog(self,controller,title,width):
        if self.stopping:raise RuntimeError('程序正在退出')
        g=self.g;window,overlay=self.root_for();parent=self.opened[-1] if self.opened else None;state={'id':controller,'kind':'dialog','anchor':None,'frame':self.make_frame(overlay,'surface-editor'),'content':g.gtk_box_new(1,0),'root':window,'parent':parent,'open':False,'placement':'side' if parent and self.states[parent]['kind']=='menu' else 'center','width':width,'group':'surface-'+str(controller),'loops':[],'result':-1}
        if parent:state['anchor']=self.states[parent].get('last_action') or self.states[parent]['frame']
        self.states[controller]=state;frame=state['frame'];header=g.gtk_box_new(0,8);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(header),b'surface-editor-header');label=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(label,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),b'surface-editor-title');g.gtk_box_pack_start(header,label,1,1,0)
        from .ui_actions import icon_action
        close=icon_action(g,g.gtk_button_new(),'关闭','composer-close',16);g.gtk_box_pack_start(header,close,0,0,0);g.connect(close,'clicked',lambda *unused:g.gtk_dialog_response(controller,-6),group=state['group']);g.gtk_box_pack_start(frame,header,0,1,0)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_scrolled_window_set_propagate_natural_height(scroll,1);g.gtk_container_add(scroll,state['content']);g.gtk_box_pack_start(frame,scroll,1,1,0);state['scroll']=scroll;state['title_label']=label
        footer=g.gtk_box_new(0,8);g.gtk_widget_set_halign(footer,2);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(footer),b'surface-editor-footer');g.gtk_box_pack_start(frame,footer,0,1,0);state['footer']=footer;state['header']=header
        if state['placement']!='side':
            backdrop=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(backdrop,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(backdrop),b'surface-dimmer');g.gtk_overlay_add_overlay(overlay,backdrop);state['backdrop']=backdrop;self.raise_widget(overlay,frame)
        g.connect(controller,'response',lambda widget,result,data:self.dialog_response(controller,result),types=[P,C.c_int,P],group=state['group']);return state

    # ==========================================
    # Function: Give settings pages one independent scroller and a stable bounded workspace.
    # Method: Remove the generic editor's outer viewport while retaining its header, sticky footer and controller lifetime.
    # ==========================================
    def settings_workspace(self,controller):
        state=self.states.get(controller)
        if not state or state.get('workspace'):return
        g=self.g;content=state['content'];g.g_object_ref(content);g.gtk_container_remove(g.gtk_widget_get_parent(content),content);g.gtk_widget_destroy(state['scroll']);g.gtk_box_pack_start(state['frame'],content,1,1,0);g.gtk_box_reorder_child(state['frame'],content,1);g.g_object_unref(content);state['scroll']=None;state['workspace']=True

    # ==========================================
    # Function: Reproduce GtkDialog response handling over a hidden native controller.
    # Method: Wake only that dialog's nested loops and leave explicit Form.close ownership intact.
    # ==========================================
    def dialog_response(self,controller,response):
        state=self.states.get(controller)
        if not state:return
        state['result']=response
        for loop in list(state['loops']):self.g.g_main_loop_quit(loop)

    # ==========================================
    # Function: Run a managed editor while continuing GTK and existing desktop timers.
    # Method: Block through a native nested GMainLoop until the real controller emits response.
    # ==========================================
    def dialog_run(self,controller):
        if self.stopping:return -6
        state=self.states.get(controller)
        if not state or state['kind']!='dialog':return self.orig['gtk_dialog_run'](controller)
        self.show_dialog(state);state['result']=-1;loop=self.g.g_main_loop_new(None,0);state['loops'].append(loop)
        try:self.g.g_main_loop_run(loop);return state['result']
        finally:state['loops'].remove(loop);self.g.g_main_loop_unref(loop)

    # ==========================================
    # Function: Present one editor card and its optional modal backdrop.
    # Method: Present the card/backdrop and synchronize occlusion without hiding readers owned by this card.
    # ==========================================
    def show_dialog(self,state):
        if state['open']:self.position(state);return
        state['open']=True;self.opened.append(state['id'])
        overlay=self.roots[state['root']]['overlay']
        if state.get('backdrop'):self.raise_widget(overlay,state['backdrop']);self.orig['gtk_widget_show_all'](state['backdrop'])
        self.raise_widget(overlay,state['frame']);self.orig['gtk_widget_show_all'](state['frame']);self.position(state);self.reader_layers.sync(state['root']);self.queue_relayout(state['root']);self.g.gtk_widget_child_focus(state['content'],0)

    # ==========================================
    # Function: Return the managed editor's public content box.
    # Method: Keep all existing Form builders and native field code compatible.
    # ==========================================
    def dialog_get_content_area(self,controller):
        state=self.states.get(controller)
        return state['content'] if state and state['kind']=='dialog' else self.orig['gtk_dialog_get_content_area'](controller)

    # ==========================================
    # Function: Add a response button to the sticky same-client footer.
    # Method: Emit the native controller's ordinary response signal on activation.
    # ==========================================
    def dialog_add_button(self,controller,title,response):
        state=self.states.get(controller)
        if not state or state['kind']!='dialog':return self.orig['gtk_dialog_add_button'](controller,title,response)
        g=self.g;button=g.gtk_button_new_with_label(title);g.gtk_box_pack_start(state['footer'],button,0,0,0);g.connect(button,'clicked',lambda *unused:g.gtk_dialog_response(controller,response),group=state['group']);return button

    # ==========================================
    # Function: Preserve dialog sizing APIs while controlling the visible card's width.
    # Method: Store requested dimensions and continue setting native controller metadata.
    # ==========================================
    def window_set_default_size(self,window,width,height):
        state=self.states.get(window)
        if state and state['kind']=='dialog':state['width']=width;self.position(state)
        self.orig['gtk_window_set_default_size'](window,width,height)

    # ==========================================
    # Function: Show managed editors or menus through existing widget APIs.
    # Method: Keep ordinary widgets and standalone composer windows on raw GTK behavior.
    # ==========================================
    def widget_show_all(self,widget):
        state=self.states.get(widget)
        if state:
            if state['kind']=='dialog':self.show_dialog(state)
            else:self.show_menu(widget)
        elif widget in self.choice_proxies:self.orig['gtk_widget_show_all'](self.choice_proxies[widget])
        else:self.orig['gtk_widget_show_all'](widget)

    # ==========================================
    # Function: Preserve explicit show operations for managed controllers.
    # Method: Reuse complete managed presentation so the hidden native controller stays hidden.
    # ==========================================
    def widget_show(self,widget):
        if widget in self.states or widget in self.choice_proxies:self.widget_show_all(widget)
        else:self.orig['gtk_widget_show'](widget)

    # ==========================================
    # Function: Hide a managed surface without surfacing its hidden native window.
    # Method: Cancel active nested editor loops and reset menu toggles consistently.
    # ==========================================
    def widget_hide(self,widget):
        if widget in self.states:self.close(widget)
        elif widget in self.choice_proxies:self.orig['gtk_widget_hide'](self.choice_proxies[widget])
        else:self.orig['gtk_widget_hide'](widget)

    # ==========================================
    # Function: Preserve visibility changes for custom controls.
    # Method: Dispatch true/false through their matching managed or raw visibility API.
    # ==========================================
    def widget_set_visible(self,widget,visible):
        if widget in self.states or widget in self.choice_proxies:(self.widget_show if visible else self.widget_hide)(widget)
        else:self.orig['gtk_widget_set_visible'](widget,visible)

    # ==========================================
    # Function: Read the actual visible managed surface state.
    # Method: Avoid reporting the permanently hidden controller's native visibility.
    # ==========================================
    def widget_get_visible(self,widget):
        if widget in self.states:return int(self.states[widget]['open'])
        return self.orig['gtk_widget_get_visible'](self.choice_proxies.get(widget,widget))

    # ==========================================
    # Function: Preserve native sensitivity for value controllers and their visible chips.
    # Method: Set the real field and its mapped display control together.
    # ==========================================
    def widget_set_sensitive(self,widget,sensitive):
        self.orig['gtk_widget_set_sensitive'](widget,sensitive)
        if widget in self.choice_proxies:self.orig['gtk_widget_set_sensitive'](self.choice_proxies[widget],sensitive)
        state=self.states.get(widget)
        if state and state['frame']:self.orig['gtk_widget_set_sensitive'](state['frame'],sensitive)

    # ==========================================
    # Function: Apply existing dialog/popover style code to its visible native frame.
    # Method: Keep ordinary widget contexts unchanged and copy pre-open menu classes on presentation.
    # ==========================================
    def widget_get_style_context(self,widget):
        state=self.states.get(widget)
        return self.orig['gtk_widget_get_style_context'](state['frame'] if state and state['frame'] else widget)

    # ==========================================
    # Function: Keep custom editor headings synchronized with native title changes.
    # Method: Update the hidden controller metadata and its visible header together.
    # ==========================================
    def window_set_title(self,window,title):
        self.orig['gtk_window_set_title'](window,title);state=self.states.get(window)
        if state and state.get('title_label'):self.g.gtk_label_set_text(state['title_label'],title)

    # ==========================================
    # Function: Present existing editor cards through native window-present calls.
    # Method: Preserve ordinary independent window behavior for all other objects.
    # ==========================================
    def window_present(self,window):
        state=self.states.get(window)
        if state and state['kind']=='dialog':self.show_dialog(state)
        else:self.orig['gtk_window_present'](window)

    # ==========================================
    # Function: Destroy managed frames before releasing their hidden controller.
    # Method: Delegate unregistered native objects to GTK unchanged.
    # ==========================================
    def widget_destroy(self,widget):
        if widget in self.states:self.dispose(widget)
        else:self.orig['gtk_widget_destroy'](widget)

    # ==========================================
    # Function: Release a surface and its native lifetime callbacks exactly once.
    # Method: Remove registry ownership before destroying descendants to make recursive disposal harmless.
    # ==========================================
    def dispose(self,key):
        state=self.states.get(key)
        if not state:return
        self.close(key);self.states.pop(key,None)
        for cleanup in state.get('cleanup',[]):cleanup()
        self.retire(state['group'])
        anchor=state.get('anchor')
        if self.links.get(anchor)==key:self.links.pop(anchor,None)
        if state['frame']:self.orig['gtk_widget_destroy'](state['frame'])
        if state.get('backdrop'):self.orig['gtk_widget_destroy'](state['backdrop'])
        self.orig['gtk_widget_destroy'](key)
        if state['kind']=='menu':self.g.g_object_unref(key)

    # ==========================================
    # Function: Close only popup branches outside the pointer's clicked managed frame.
    # Method: Keep ancestor menus visible and allow the underlying clicked widget to act normally.
    # ==========================================
    def pointer_press(self,window,x,y):
        if window not in self.roots:return
        self.g.gtk_style_context_remove_class(self.g.gtk_widget_get_style_context(window),b'keyboard-navigation')
        overlay=self.roots[window]['overlay'];offset=self.rectangle(overlay,window);x-=offset[0];y-=offset[1];hit=None
        for key in reversed(self.opened):
            state=self.states[key]
            if state['root']!=window:continue
            left,top,width,height=self.rectangle(state['frame'],overlay)
            if left<=x<left+width and top<=y<top+height:hit=key;break
            anchor=state.get('anchor')
            if self.links.get(anchor)==key:
                left,top,width,height=self.rectangle(anchor,overlay)
                if left<=x<left+width and top<=y<top+height:hit=key;break
        keep=self.ancestors(hit)
        for key in list(reversed(self.opened)):
            state=self.states[key]
            if state['root']==window and key not in keep and (state['kind']=='menu' or state['placement']=='side'):self.close(key)

    # ==========================================
    # Function: Dismiss the deepest active surface before ordinary application Escape handling.
    # Method: Return true only for an actual same-root Escape dismissal.
    # ==========================================
    def key_press(self,window,event):
        key=C.c_uint()
        if not self.g.gdk_event_get_keyval(event,C.byref(key)):return False
        if key.value in (65289,65056,65361,65362,65363,65364):self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(window),b'keyboard-navigation')
        if key.value!=65307:return False
        for controller,state in reversed(list(self.states.items())):
            anchor=state.get('anchor')
            if state.get('show_source') and anchor and self.g.gtk_widget_get_toplevel(anchor)==window:self.close(controller);return True
        for controller in reversed(self.opened):
            if self.states[controller]['root']==window:self.close(controller);return True
        return False

    # ==========================================
    # Function: Avoid leaving transient menus visible after switching applications.
    # Method: Preserve dialogs and their ancestor menus during browser authorization or app switching.
    # ==========================================
    def focus_out(self,window):
        protected=set()
        for state in self.states.values():
            if state['open'] and state['kind']=='dialog' and state['root']==window:protected.update(self.ancestors(state['parent']))
        for key in list(reversed(self.opened)):
            if self.states[key]['root']==window and self.states[key]['kind']=='menu' and key not in protected:self.close(key)
        return False

    # ==========================================
    # Function: Release retired trampolines after their native event turns have completed.
    # Method: Keep periodic work bounded to current roots and open surfaces only.
    # ==========================================
    def poll(self):self.retired.clear()

    # ==========================================
    # Function: Unwind all managed nested loops before desktop shutdown.
    # Method: Cancel surfaces, then disconnect root observers and release capture gestures.
    # ==========================================
    def shutdown(self):
        if self.stopping:return
        self.stopping=True
        for key in list(reversed(self.opened)):self.close(key)
        for root in self.roots.values():
            if root['layout_source']:self.g.g_source_remove(root['layout_source']);root['layout_source']=0
            self.retire(root['group']);self.g.g_object_unref(root['gesture'])
