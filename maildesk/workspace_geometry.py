"""Resizable mailbox/navigation/preview geometry with bounded durable widths."""
import ctypes as C
import time

P=C.c_void_p
NAV_MIN,NAV_MAX=128,960

# ==========================================
# Function: Clamp persisted pixel widths without trusting imported preference types.
# Method: Fall back to measured-layout defaults and bound every requested native allocation.
# ==========================================
def bounded(value,default,low,high):
    try:return min(high,max(low,int(value)))
    except (ValueError,TypeError,OverflowError):return min(high,max(low,default))

# ==========================================
# Function: Coordinate native splitters and navigation edge handles.
# Method: Preserve mail widgets while independently resizing an optional third document column.
# ==========================================
class WorkspaceGeometry:
    # ==========================================
    # Function: Restore main/preview widths after the local service is ready.
    # Method: Connect allocations/positions once and defer preference writes until dragging settles.
    # ==========================================
    def __init__(self,app):
        self.app,self.g=app,app.g;self.pending={};self.changed_at=0;self.updating=False;self.preview_open=False;self.preview_growth={};self.resize_anchor=None;self.layout_source=0;self.layout_callback=C.CFUNCTYPE(C.c_int,P)(self.idle_fit);self.nav={};self.dragging=False
        store=app.service.store;self.list_width=bounded(store.preference('mail_list_width',340),340,220,720);self.preview_width=bounded(store.preference('document_panel_width',400),400,280,20000)
        self.g.gtk_paned_set_position(app.widget('mail_split'),self.list_width)
        for key in ('mail_split','document_split'):
            self.g.connect(app.widget(key),'notify::position',lambda *unused,name=key:self.position_changed(name),count=3,group='workspace-geometry')
        self.g.connect(app.widget('document_split'),'size-allocate',lambda *unused:self.fit(),count=3,group='workspace-geometry')
        from .windows_frame import WindowResize
        self.window_resize=WindowResize(app)
        for key in ('folders_menu','navigation_menu'):self.add_navigation_handle(key)
        self.split_drag='';self.split_start=0;self.split_gesture=self.g.gtk_gesture_drag_new(app.widget('workspace_overlay'));self.g.gtk_gesture_single_set_button(self.split_gesture,1);self.g.gtk_event_controller_set_propagation_phase(self.split_gesture,1)
        self.g.connect(self.split_gesture,'drag-begin',lambda widget,x,y,data:self.split_begin(x,y),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        self.g.connect(self.split_gesture,'drag-update',lambda widget,x,y,data:self.split_update(x),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        self.g.connect(self.split_gesture,'drag-end',lambda *unused:self.split_end(),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        self.reading_inset=-1;self.reading_pending=True;self.g.connect(self.g.gtk_widget_get_parent(app.widget('conversation_host')),'size-allocate',lambda *unused:setattr(self,'reading_pending',True),count=3,group='workspace-geometry')
        self.fit()

    # ==========================================
    # Function: Give each one-pixel divider a wider invisible mouse target.
    # Method: Claim capture-phase drags only within four pixels of a visible pane boundary, leaving content and navigation clicks untouched.
    # ==========================================
    def split_begin(self,x,y):
        g=self.g;overlay=self.app.widget('workspace_overlay');self.split_drag=''
        if not getattr(self.app,'navigation_panel','') and not g.surfaces.opened:
            for key in ('document_split','mail_split'):
                if key=='document_split' and not self.preview_open:continue
                if key=='mail_split' and not all(g.gtk_widget_get_visible(self.app.widget(child)) for child in ('listpane','reader')):continue
                widget=self.app.widget(key);cx,cy=C.c_int(),C.c_int()
                if g.gtk_widget_translate_coordinates(widget,overlay,g.gtk_paned_get_position(widget),0,C.byref(cx),C.byref(cy)) and abs(x-cx.value)<=4 and cy.value<=y<cy.value+g.gtk_widget_get_allocated_height(widget):self.split_drag=key;self.split_start=g.gtk_paned_get_position(widget);break
        g.gtk_gesture_set_state(self.split_gesture,1 if self.split_drag else 2);self.dragging=bool(self.split_drag)

    # ==========================================
    # Function: Move a pane boundary using the native drag's horizontal offset.
    # Method: Let GTK enforce child minima and reuse debounced position preferences.
    # ==========================================
    def split_update(self,offset):
        if self.split_drag:self.g.gtk_paned_set_position(self.app.widget(self.split_drag),int(self.split_start+offset))

    # ==========================================
    # Function: End a divider drag without writing on every pointer motion.
    # Method: Release only transient gesture state; the shared tick persists settled widths.
    # ==========================================
    def split_end(self):self.split_drag='';self.dragging=False

    # ==========================================
    # Function: Embed a visible resize edge beside the existing floating navigation surface.
    # Method: Pack the internally scrolling surface directly so its rows receive the true width and keep trailing tools inside the native minimum.
    # ==========================================
    def add_navigation_handle(self,key):
        g=self.g;panel=self.app.widget(key);surface=g.gtk_bin_get_child(panel);g.g_object_ref(surface);g.gtk_container_remove(panel,surface);wrapper=g.gtk_box_new(0,0);g.gtk_widget_set_hexpand(wrapper,0);g.gtk_container_add(panel,wrapper);g.gtk_widget_set_size_request(surface,-1,-1);clip=surface;g.gtk_box_pack_start(wrapper,surface,1,1,0);g.g_object_unref(surface)
        edge=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(edge,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(edge),b'navigation-resize-edge');g.gtk_widget_set_size_request(edge,8,-1);g.gtk_widget_set_tooltip_text(edge,'拖动调整侧栏宽度'.encode());g.gtk_box_pack_start(wrapper,edge,0,0,0)
        gesture=g.gtk_gesture_drag_new(edge);g.gtk_gesture_single_set_button(gesture,1);g.gtk_gesture_single_set_touch_only(gesture,0);g.gtk_event_controller_set_propagation_phase(gesture,1)
        self.nav[key]={'wrapper':wrapper,'surface':surface,'edge':edge,'clip':clip,'gesture':gesture,'width':bounded(self.app.service.store.preference(key+'_width',300),300,NAV_MIN,NAV_MAX),'start':300,'pointer_start':0,'active':False,'applied':None}
        g.connect(gesture,'drag-begin',lambda widget,x,y,data,name=key:self.nav_begin(name),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        g.connect(gesture,'drag-update',lambda widget,x,y,data,name=key:self.nav_update(name,x),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        g.connect(gesture,'cancel',lambda *unused,name=key:self.nav_end(name),count=3,group='workspace-geometry')
        g.connect(gesture,'drag-end',lambda widget,x,y,data,name=key:self.nav_end(name),types=[P,C.c_double,C.c_double,P],group='workspace-geometry')
        g.connect(surface,'size-allocate',lambda *unused:self.fit(),count=3,group='workspace-geometry')
        g.connect(edge,'realize',lambda *unused,w=edge:self.resize_cursor(w),group='workspace-geometry');self.set_nav_width(key,self.nav[key]['width'])

    # ==========================================
    # Function: Show a horizontal-resize pointer over the native handle.
    # Method: Create and release one standard GDK cursor for the realized edge window.
    # ==========================================
    def resize_cursor(self,widget):
        gdk=self.g.libs['gdk'];display=gdk.gdk_display_get_default;display.restype=P;display.argtypes=[];cursor=gdk.gdk_cursor_new_from_name;cursor.restype=P;cursor.argtypes=[P,C.c_char_p];value=cursor(display(),b'col-resize')
        if value:
            setter=gdk.gdk_window_set_cursor;setter.restype=None;setter.argtypes=[P,P];setter(self.g.gtk_widget_get_window(widget),value);self.g.g_object_unref(value)

    # ==========================================
    # Function: Start a navigation resize using its actual allocated width.
    # Method: Retain one actual width and root-pointer baseline; a moving edge never becomes the coordinate origin.
    # ==========================================
    def nav_begin(self,key):
        self.dragging=True;self.app.cancel_folder_edit();record=self.nav[key];self.g.gtk_gesture_set_state(record['gesture'],1);record['start']=self.g.gtk_widget_get_allocated_width(record['wrapper']);record['pointer_start']=self.nav_pointer(key);record['active']=True

    # ==========================================
    # Function: Follow the pointer in stable screen coordinates while the edge moves.
    # Method: Ignore the moving-widget-local offset and coalesce the resulting target into the retained idle layout.
    # ==========================================
    def nav_update(self,key,offset):
        record=self.nav[key]
        if record['active']:self.set_nav_width(key,record['start']+self.nav_pointer(key)-record['pointer_start'])

    # ==========================================
    # Function: Commit an explicitly resized navigation width.
    # Method: Keep each floating panel's width independent and local.
    # ==========================================
    def nav_end(self,key):
        record=self.nav[key]
        if not record['active']:return
        record['active']=False;self.dragging=False;self.defer(key+'_width',record['width'])

    # ==========================================
    # Function: Read the latest native drag event without depending on the edge's moving origin.
    # Method: Use GDK root coordinates in logical units, with the unmoving main-window pointer as fallback.
    # ==========================================
    def nav_pointer(self,key):
        event=self.g.gtk_gesture_get_last_event(self.nav[key]['gesture'],None);x,y=C.c_double(),C.c_double()
        if event and self.g.gdk_event_get_root_coords(event,C.byref(x),C.byref(y)):return x.value
        px,py=C.c_int(),C.c_int();self.g.gtk_widget_get_pointer(self.app.window,C.byref(px),C.byref(py));return px.value

    # ==========================================
    # Function: Bound a panel against both the expanded range and current window.
    # Method: Keep128–960 logical-pixel targets, reserve rail/outside space and apply each changed request outside GTK motion/allocation callbacks.
    # ==========================================
    def set_nav_width(self,key,width):
        available=self.g.gtk_widget_get_allocated_width(self.app.widget('workspace_overlay'));maximum=min(NAV_MAX,max(NAV_MIN,available-120)) if available>1 else NAV_MAX;record=self.nav[key];record['width']=bounded(width,300,NAV_MIN,maximum)
        if not self.updating:self.fit();return
        if record['applied']==record['width']:return
        record['applied']=record['width'];context=self.g.gtk_widget_get_style_context(record['surface'])
        (self.g.gtk_style_context_add_class if record['width']<168 else self.g.gtk_style_context_remove_class)(context,b'navigation-compact')
        self.g.gtk_widget_set_size_request(record['wrapper'],record['width'],-1)

    # ==========================================
    # Function: Reveal a ready document beside the persistent mail/list split.
    # Method: Keep reader_stack on its current mail/composer child and allocate only the new column.
    # ==========================================
    def show_preview(self):
        fresh=not self.preview_open;self.preview_open=True
        if fresh:
            from .window_workspace import attachment_width,expand_for_attachment
            requested=attachment_width(self.app.service.store.preference('attachment_open_width',700))
            old_width=self.g.gtk_widget_get_allocated_width(self.app.widget('document_split'));mail=self.g.gtk_widget_get_allocated_width(self.app.widget('reader'));self.preview_growth={}
            enabled=bool(self.app.service.store.preference('attachment_auto_expand',True));added=expand_for_attachment(self.app,requested,self.preview_growth) if enabled else 0
            self.preview_width=requested;available=max(540,old_width+added-self.list_width-2)
            # Anchor at the post-growth size: the new width belongs to the file column.
            self.resize_anchor=(available,bounded(mail,400,260,min(750,max(260,available-280))))
        host=self.app.widget('document_host');self.g.gtk_widget_set_no_show_all(host,0);self.g.gtk_widget_show_all(host);self.g.gtk_widget_set_no_show_all(host,1);self.fit()

    # ==========================================
    # Function: Hide the independent file column without resetting the mail reader.
    # Method: Allow the original split to reclaim its full width.
    # ==========================================
    def hide_preview(self):
        receipt=self.preview_growth;self.preview_growth={};self.preview_open=False;self.resize_anchor=None;self.g.gtk_widget_hide(self.app.widget('document_host'))
        from .window_workspace import restore_after_attachment
        restore_after_attachment(self.app,receipt);self.fit()

    # ==========================================
    # Function: Fit split widths to the actual root allocation without forcing window growth.
    # Method: Share growth between mail/file panes until the700px content cap; retain a stable anchor through native reallocations.
    # ==========================================
    def fit(self):
        if self.updating or self.app.closing or self.layout_source:return
        self.layout_source=self.g.g_idle_add(C.cast(self.layout_callback,P),None)

    # ==========================================
    # Function: Apply one coalesced layout after GTK finishes allocating the current frame.
    # Method: Leave allocation signal handlers before setting paned positions so queued resizes cannot be swallowed.
    # ==========================================
    def idle_fit(self,unused=None):
        self.layout_source=0
        if not self.app.closing:self.apply_fit()
        return 0

    # ==========================================
    # Function: Allocate the anchored mail/file widths from the current usable workspace.
    # Method: Keep programmatic position notifications separate from explicit divider drags.
    # ==========================================
    def apply_fit(self):
        if self.updating or self.app.closing:return
        self.updating=True
        try:
            outer=self.app.widget('document_split');width=self.g.gtk_widget_get_allocated_width(outer)
            if width>1:
                if self.preview_open:
                    from .window_workspace import settle_expansion
                    settle_expansion(self.app,self.preview_growth)
                    minimum=C.c_int();natural=C.c_int();self.g.gtk_widget_get_preferred_width(self.app.widget('reader'),C.byref(minimum),C.byref(natural));reader_min=max(260,minimum.value)
                    self.g.gtk_widget_get_preferred_width(self.app.widget('listpane'),C.byref(minimum),C.byref(natural));list_min=max(220,minimum.value)
                    position=bounded(self.list_width,340,list_min,max(list_min,width-reader_min-282));available=max(reader_min+280,width-position-2)
                    if self.resize_anchor is None:self.resize_anchor=(available,bounded(available-self.preview_width,400,reader_min,max(reader_min,750)))
                    total,mail=self.resize_anchor;mail=bounded(round(mail+(available-total)/2),400,reader_min,min(max(reader_min,750),max(reader_min,available-280)))
                    self.g.gtk_paned_set_position(outer,position+1+mail)
                else:position=bounded(self.list_width,340,220,max(220,width-260))
                self.g.gtk_paned_set_position(self.app.widget('mail_split'),position)
            for key in self.nav:self.set_nav_width(key,self.nav[key]['width'])
        finally:self.updating=False

    # ==========================================
    # Function: Center a bounded mail timeline inside its actual scrolling viewport.
    # Method: Update margins only when allocation changes; automatic horizontal policy avoids inflating the window minimum.
    # ==========================================
    def fit_reading(self):
        host=self.app.widget('conversation_host');parent=self.g.gtk_widget_get_parent(host)
        width=self.g.gtk_widget_get_allocated_width(parent) if parent else 0
        if width<=1:return
        extra=max(0,width-740);inset=(20+extra//2,20+extra-extra//2)
        if inset==self.reading_inset:return
        self.reading_inset=inset;self.g.gtk_widget_set_margin_start(host,inset[0]);self.g.gtk_widget_set_margin_end(host,inset[1])

    # ==========================================
    # Function: Capture a native splitter change after initial/programmatic allocation.
    # Method: Accept explicit divider gestures only, preventing allocator notifications from rewriting the resize anchor.
    # ==========================================
    def position_changed(self,key):
        if self.updating or self.app.closing or self.split_drag!=key:return
        outer=self.app.widget('document_split');width=self.g.gtk_widget_get_allocated_width(outer)
        if width<=1:return
        position=self.g.gtk_paned_get_position(self.app.widget(key))
        if key=='mail_split':self.list_width=bounded(position,340,220,720);self.defer('mail_list_width',self.list_width)
        if self.preview_open:
            available=max(540,width-self.list_width-2);mail=bounded(self.g.gtk_paned_get_position(outer)-self.list_width-1,400,260,750)
            self.resize_anchor=(available,mail);self.preview_width=max(280,available-mail);self.defer('document_panel_width',self.preview_width)

    # ==========================================
    # Function: Coalesce durable width changes instead of writing on every mouse motion.
    # Method: Use the existing desktop tick and a half-second idle deadline.
    # ==========================================
    def defer(self,key,value):self.pending[key]=value;self.changed_at=time.monotonic()

    # ==========================================
    # Function: Flush a settled geometry change from the existing main-thread timer.
    # Method: Bound work to the small pending width dictionary.
    # ==========================================
    def tick(self,force=False):
        if self.reading_pending and not self.app.closing:self.reading_pending=False;self.fit_reading()
        if not self.pending or (not force and time.monotonic()-self.changed_at<.5):return
        for key,value in self.pending.items():self.app.service.store.set_preference(key,value)
        self.pending.clear()

    # ==========================================
    # Function: Release owned gestures and pending geometry at application shutdown.
    # Method: Persist only queued explicit changes and retire callbacks before native widgets disappear.
    # ==========================================
    def close(self):
        if self.layout_source:self.g.g_source_remove(self.layout_source);self.layout_source=0
        self.tick(force=True);self.g.surfaces.retire('workspace-geometry')
        for record in self.nav.values():self.g.g_object_unref(record['gesture'])
        self.nav={};self.g.g_object_unref(self.split_gesture);self.window_resize.close()
