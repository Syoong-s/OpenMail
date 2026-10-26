"""Native Windows WebView2 reader embedded in independently owned child surfaces aligned with GTK widgets."""
import ctypes as C
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
import uuid
from .document_content import reader_document
from .message_style import reader_appearance
from .desktop_preferences import resolved_theme
from .gtk_native import P,I,U,S
from .platform_native import runtime_root,profile_homes,open_uri
from .reader_fit import MEASURE_MAIL,fitted_height

# ==========================================
# Function: Bind the small application-owned browser bridge lazily.
# Method: Load a private DLL and declare pointer-safe cdecl ABI signatures.
# ==========================================
def bridge():
    library=C.CDLL(str(runtime_root()/'bin/maildesk-webview.dll'))
    signatures={'md_webview_create':(P,P,C.c_wchar_p,C.c_wchar_p),
        'md_webview_load':(None,P,C.c_wchar_p,I),'md_webview_resize':(None,P,I),
        'md_webview_query':(U,P,C.c_wchar_p),'md_webview_result':(I,P,U,C.c_wchar_p,I),
        'md_webview_viewport':(None,P,I,I,I,I,I,I,I),
        'md_webview_position':(None,P,I,I,I,I,I,I),'md_webview_overlay':(None,P,I,I,I,I),
        'md_webview_window':(P,P),'md_webview_exclusions':(None,P,P,I),
        'md_webview_status':(I,P),'md_webview_link':(I,P,C.c_wchar_p,I),
        'md_webview_zoom':(None,P,C.c_double),'md_webview_script':(None,P,C.c_wchar_p),
        'md_webview_wheel':(C.c_double,P),'md_webview_metrics':(U,I),'md_webview_key':(U,P),'md_webview_close':(None,P),'md_webview_shutdown':(None,),'md_webview_drained':(I,),'md_webview_finish':(None,)}
    for name,signature in signatures.items():
        fn=getattr(library,name);fn.restype,fn.argtypes=signature[0],signature[1:]
    return library

# ==========================================
# Function: Keep the complete Linux reader public contract on native Windows.
# Method: Align an owned child HWND with a virtual GTK drawing area without competing for GTK clipping.
# ==========================================
class HTMLReader:
    # ==========================================
    # Function: Allocate only a lightweight GTK surface until the mail is visible.
    # Method: Defer browser creation until realize and register only weak floating-layer ownership.
    # ==========================================
    def __init__(self,app,group):
        self.app,self.g,self.group=app,app.g,group;self.closed=False;self.handle=None
        self.lib=getattr(app,'windows_webview_bridge',None)
        if not self.lib:self.lib=app.windows_webview_bridge=bridge()
        self.widget=self.g.gtk_drawing_area_new();self.source='';self.original=('',False,None)
        self.zoom=1;self.document_ready=False;self.pending_image=None;self.detached_ref=False
        self.load_generation=0;self.started_generation=-1;self.expected_title='';self.expected_uri='about:blank';self.image_navigation=False
        self.g.gtk_widget_set_hexpand(self.widget,1);self.g.gtk_widget_set_vexpand(self.widget,1)
        self.g.connect(self.widget,'realize',self.realized,group=group)
        self.g.connect(self.widget,'unrealize',self.unrealized,group=group)
        self.g.connect(self.widget,'size-allocate',self.allocated,count=3,group=group)
        self.g.connect(self.widget,'map',self.mapped,group=group)
        self.g.connect(self.widget,'unmap',self.unmapped,group=group)
        self.g.connect(self.widget,'draw',self.draw,count=3,returns=True,group=group)
        self.geometry_adjustments=set()
        layers=getattr(getattr(self.g,'surfaces',None),'reader_layers',None)
        if layers:layers.readers.add(self)
        self.timer=0;self.timer_callback=None;self.failed=False
        self.compact_mail=False;self.fit_query=0;self.fit_generation=-1;self.fit_next=0;self.fit_height=None
        app.reader_pool_created=getattr(app,'reader_pool_created',0)+1

    # ==========================================
    # Function: Create an owned browser child under the current GTK top-level.
    # Method: Keep the drawing area virtual so GTK never rewrites the browser host region.
    # ==========================================
    def realized(self,*unused):
        if self.closed or self.handle or not self.source:return
        gdk=self.g.libs['gdk'];native=gdk.gdk_win32_window_get_handle;native.argtypes=[P];native.restype=P
        window=self.g.gtk_widget_get_window(self.g.gtk_widget_get_toplevel(self.widget))
        if not window:raise RuntimeError('无法创建应用内阅读区域')
        hwnd=native(window)
        from .storage_paths import active_cache
        profile=active_cache()/'webview2'
        # Controllers are required to use Edge InPrivate mode; no mail cookies/history are persisted.
        profile.mkdir(parents=True,exist_ok=True)
        self.handle=self.lib.md_webview_create(hwnd,str(profile),str(runtime_root()/'bin/WebView2Loader.dll'))
        if not self.handle:raise RuntimeError('无法初始化 Windows WebView2 阅读器')
        self.lib.md_webview_zoom(self.handle,self.zoom)
        if self.source:self.lib.md_webview_load(self.handle,self.rendered_document(),int(self.remote))
        self.timer_callback=C.CFUNCTYPE(I,P)(self.poll)
        self.timer=self.g.g_timeout_add(40,C.cast(self.timer_callback,P),None)
        scroller=self.g.gtk_widget_get_ancestor(self.widget,self.g.gtk_scrolled_window_get_type())
        if scroller:
            adjustment=self.g.gtk_scrolled_window_get_vadjustment(scroller)
            if adjustment not in self.geometry_adjustments:
                self.geometry_adjustments.add(adjustment);self.g.connect(adjustment,'value-changed',self.allocated,group=self.group)
        self.allocated()

    # ==========================================
    # Function: Release a controller before GTK destroys or reparents its native HWND.
    # Method: Retain the prepared document and zoom so the next realize recreates safely.
    # ==========================================
    def unrealized(self,*unused):
        if self.timer:self.g.g_source_remove(self.timer);self.timer=0
        if self.handle:self.lib.md_webview_close(self.handle);self.handle=None
        self.document_ready=False
        self.fit_query=0;self.fit_next=0

    # ==========================================
    # Function: Match browser pixels to the native GTK child allocation.
    # Method: Read physical HWND bounds and synchronize mapped visibility without mixing DPI units.
    # ==========================================
    def allocated(self,*unused):
        if self.handle and not self.closed:self.sync_native_viewport()

    # ==========================================
    # Function: Reveal a browser only when GTK maps its entire ancestor chain.
    # Method: Respect card collapse, hidden tabs, and reader stack transitions.
    # ==========================================
    def mapped(self,*unused):
        if self.handle and not self.closed:self.sync_native_viewport()

    # ==========================================
    # Function: Hide a native browser when the enclosing GTK card disappears.
    # Method: Avoid a child HWND painting through collapsed history or another panel.
    # ==========================================
    def unmapped(self,*unused):
        if self.handle:self.lib.md_webview_resize(self.handle,0)

    # ==========================================
    # Function: Keep each native mail surface clipped to its enclosing GTK viewport.
    # Method: Commit placement, viewport intersection, circular button cutout and all higher GTK surface exclusions.
    # ==========================================
    def sync_native_viewport(self):
        g=self.g;width=g.gtk_widget_get_allocated_width(self.widget);height=g.gtk_widget_get_allocated_height(self.widget)
        root=g.gtk_widget_get_toplevel(self.widget);x,y=I(),I()
        g.gtk_widget_translate_coordinates(self.widget,root,0,0,C.byref(x),C.byref(y))
        self.lib.md_webview_position(self.handle,x.value,y.value,width,height,g.gtk_widget_get_allocated_width(root),g.gtk_widget_get_allocated_height(root))
        cut=(0,0,0,0);arrow=getattr(self.app,'chat_bottom',None);layers=getattr(getattr(g,'surfaces',None),'reader_layers',None)
        if arrow and g.gtk_widget_get_mapped(arrow.button) and g.gtk_widget_get_toplevel(arrow.button)==root and not (layers and layers.has_owner(self.widget,root)):
            bx,by=I(),I()
            if g.gtk_widget_translate_coordinates(arrow.button,self.widget,0,0,C.byref(bx),C.byref(by)):
                right=bx.value+g.gtk_widget_get_allocated_width(arrow.button);bottom=by.value+g.gtk_widget_get_allocated_height(arrow.button)
                if bx.value<width and by.value<height and right>0 and bottom>0:cut=(bx.value-4,by.value-4,right+4,bottom+4)
        self.lib.md_webview_overlay(self.handle,*cut)
        rects=layers.rectangles(self.widget,root) if layers else ()
        coordinates=(I*(len(rects)*4))(*(value for rect in rects for value in rect))
        self.lib.md_webview_exclusions(self.handle,C.cast(coordinates,P),len(rects))
        left,top,right,bottom=0,0,width,height
        scroller=g.gtk_widget_get_ancestor(self.widget,g.gtk_scrolled_window_get_type())
        if scroller:
            x,y=I(),I()
            if g.gtk_widget_translate_coordinates(self.widget,scroller,0,0,C.byref(x),C.byref(y)):
                left=max(0,-x.value);top=max(0,-y.value)
                right=min(width,g.gtk_widget_get_allocated_width(scroller)-x.value)
                bottom=min(height,g.gtk_widget_get_allocated_height(scroller)-y.value)
        self.lib.md_webview_viewport(self.handle,left,top,right,bottom,width,height,int(bool(g.gtk_widget_get_mapped(self.widget))))

    # ==========================================
    # Function: Synchronize native mail surfaces before GTK paints the surrounding card.
    # Method: Observe the draw signal without consuming it or scheduling another redraw.
    # ==========================================
    def draw(self,*unused):
        if self.handle and not self.closed:self.sync_native_viewport()
        return False

    # ==========================================
    # Function: Resolve asynchronous browser readiness and user-clicked external links.
    # Method: Sync native parent movement and poll state on the GTK loop without nested message pumps.
    # ==========================================
    def poll(self,*unused):
        if self.closed or not self.handle:return 0
        self.sync_native_viewport()
        status=self.lib.md_webview_status(self.handle)
        if status<0 and not self.failed:
            self.failed=True;self.app.message('Windows 阅读器无法启动，请检查 Microsoft Edge WebView2 Runtime（错误 '+hex(status&0xffffffff)+'）')
        self.document_ready=status==1
        if self.document_ready and getattr(self,'compact_mail',False):self.poll_content_fit()
        if self.document_ready and self.pending_image is not None:
            index=self.pending_image;self.pending_image=None;self.jump_to_image(index)
        wheel=self.lib.md_webview_wheel(self.handle)
        if wheel:self.scroll_parent(wheel)
        link=C.create_unicode_buffer(8192)
        key=self.lib.md_webview_key(self.handle)
        if key:self.app.run_action(lambda:self.shortcut(key))
        if self.closed or not self.handle:return 0
        if self.lib.md_webview_link(self.handle,link,len(link)):
            uri=link.value
            if urlsplit(uri).hostname=='maildesk.invalid':return 1
            if urlsplit(uri).scheme.lower()=='mailto':self.app.run_action(lambda:self.app.open_mailto(uri))
            else:self.app.run_action(lambda:open_uri(uri))
        return 1

    # ==========================================
    # Function: Fit email leaves to their rendered content while document tabs keep their full viewport.
    # Method: Enable a bounded asynchronous host measurement only for conversation-owned readers.
    # ==========================================
    def enable_compact_layout(self):
        self.compact_mail=True;self.fit_next=0
        self.g.gtk_widget_set_vexpand(self.widget,0)

    # ==========================================
    # Function: Remove estimated empty height after actual fonts, images and line wrapping settle.
    # Method: Poll one generation-bound native query, validate its title and update logical height only on change.
    # ==========================================
    def poll_content_fit(self):
        now=time.monotonic()
        if self.fit_query:
            result=C.create_unicode_buffer(2048);status=self.lib.md_webview_result(self.handle,self.fit_query,result,len(result))
            if not status:return
            self.fit_query=0
            if status>0 and self.fit_generation==self.load_generation:
                try:measurement=json.loads(result.value)
                except (ValueError,TypeError):measurement=None
                if isinstance(measurement,dict) and measurement.get('title')==self.expected_title:
                    height=fitted_height(measurement,self.g.gtk_widget_get_allocated_height(self.widget))
                    if height and (self.fit_height is None or abs(height-self.fit_height)>2):
                        self.fit_height=height;self.g.gtk_widget_set_size_request(self.widget,-1,height)
                        self.lib.md_webview_script(self.handle,"document.documentElement.style.overflowY='"+('hidden' if height<5000 else 'auto')+"'")
            self.fit_next=now+.5
        elif now>=self.fit_next and self.g.gtk_widget_get_allocated_height(self.widget)>=8:
            self.fit_generation=self.load_generation;self.fit_query=self.lib.md_webview_query(self.handle,MEASURE_MAIL)
            if not self.fit_query:self.fit_next=now+1

    # ==========================================
    # Function: Continue a user's boundary wheel gesture in the enclosing conversation.
    # Method: Clamp the GTK adjustment and cancel automatic reveal only for manual scrolling.
    # ==========================================
    def scroll_parent(self,delta):
        g=self.g;scroller=g.gtk_widget_get_ancestor(self.widget,g.gtk_scrolled_window_get_type())
        if not scroller:return
        gtk=g.libs['gtk'];adjustment=g.gtk_scrolled_window_get_vadjustment(scroller)
        for name in ('gtk_adjustment_get_value','gtk_adjustment_get_upper','gtk_adjustment_get_page_size'):
            fn=getattr(gtk,name);fn.restype=C.c_double;fn.argtypes=[P]
        setter=gtk.gtk_adjustment_set_value;setter.restype=None;setter.argtypes=[P,C.c_double]
        maximum=max(0,gtk.gtk_adjustment_get_upper(adjustment)-gtk.gtk_adjustment_get_page_size(adjustment))
        value=gtk.gtk_adjustment_get_value(adjustment)
        self.app.pending_conversation_reveal=None
        bottom=getattr(self.app,'chat_bottom',None)
        if bottom and g.gtk_widget_is_ancestor(self.widget,self.app.chat_timeline):bottom.user_scroll()
        setter(adjustment,min(maximum,max(0,value+delta)))

    # ==========================================
    # Function: Preserve application shortcuts while keyboard focus is inside HTML content.
    # Method: Route only the same explicit commands as the main GTK key handler.
    # ==========================================
    def shortcut(self,encoded):
        if encoded==0x40000:
            if getattr(self.app,'navigation_panel',''):self.app.close_navigation()
            return
        key=encoded&0xffff;control=bool(encoded&0x10000);shift=bool(encoded&0x20000);app=self.app
        if key==27 and self.g.gtk_revealer_get_reveal_child(app.widget('search_revealer')):app.show_search(False);return
        if key==27 and app.document:app.close_document(preserve_composer=True);return
        if key==65 and control:
            if app.multi and app.service.store.preference('shortcuts_enabled',True):self.g.gtk_list_box_select_all(app.widget('messages'))
            elif self.handle:self.lib.md_webview_script(self.handle,'document.execCommand("selectAll")')
            return
        if not app.service.store.preference('shortcuts_enabled',True):return
        if key==27 and app.multi:app.toggle_selection();return
        if not control:return
        if key==188:app.preferences()
        elif key==78:app.open_composer()
        elif key==70:
            if not app.document:app.show_search(True)
        elif key==82:app.reply_extended('all') if shift else app.reply()

    # ==========================================
    # Function: Prepare the same inert, themed document used by the Linux reader.
    # Method: Preserve CSP, remote-image consent, CID data and exact quote-leaf provenance.
    # ==========================================
    def load(self,source,markdown=False,images=None,force=False):
        self.original=(source,markdown,images);store=self.app.service.store
        self.remote=bool(store.preference('load_remote_images',False))
        prepared=reader_document(source,markdown,resolved_theme(self.app)=='dark',images,
            adapt_dark=False if getattr(self,'preserve_document_style',False) else store.preference('adapt_dark_html',True),font_size=store.preference('reader_font_size',14),remote_images=self.remote,appearance=reader_appearance(self))
        if not force and prepared==self.source:return
        self.source=prepared;self.load_generation+=1;self.document_ready=False;self.failed=False;self.pending_image=None
        self.fit_query=0;self.fit_next=0;self.fit_height=None
        self.expected_title='TeleMail reader '+uuid.uuid4().hex
        if self.handle:self.lib.md_webview_load(self.handle,self.rendered_document(),int(self.remote))
        elif self.g.gtk_widget_get_window(self.widget):self.realized()

    # ==========================================
    # Function: Supply the current title-identified document only while the native call needs it.
    # Method: Regenerate from the retained sanitized source instead of retaining a third large string.
    # ==========================================
    def rendered_document(self):
        return self.source.replace('<head>','<head><title>'+self.expected_title+'</title>',1)

    # ==========================================
    # Function: Reload theme and image permissions from immutable original input.
    # Method: Keep current cached MIME bytes and HTML sanitization boundaries unchanged.
    # ==========================================
    def reload(self):self.load(*self.original,force=True)

    # ==========================================
    # Function: Acknowledge the widget parent handoff used by shared reader callers.
    # Method: Windows creates one owned GTK drawing area and needs no detached reference.
    # ==========================================
    def attached(self):pass

    # ==========================================
    # Function: Scroll to an exact image anchor within the current inert document.
    # Method: Execute a host-owned numeric-only operation while email scripts stay disabled.
    # ==========================================
    def jump_to_image(self,index):
        index=max(0,int(index))
        if not self.document_ready:self.pending_image=index;return
        self.image_navigation=True
        self.lib.md_webview_script(self.handle,"document.getElementById('mail-image-"+str(index)+"')?.scrollIntoView({block:'center'})")

    # ==========================================
    # Function: Find visible text using a safely JSON-encoded search literal.
    # Method: Invoke only the browser's built-in find primitive, never document-supplied code.
    # ==========================================
    def find(self,text):
        if self.handle:self.lib.md_webview_script(self.handle,'window.find('+json.dumps(str(text))+',false,false,true)')

    # ==========================================
    # Function: Scale the current in-pane document without changing its source.
    # Method: Apply the same fifty-to-three-hundred-percent limits as Linux.
    # ==========================================
    def scale(self,factor):
        self.zoom=min(3,max(.5,self.zoom*factor))
        if self.handle:self.lib.md_webview_zoom(self.handle,self.zoom)

    # ==========================================
    # Function: Keep compatibility with reader theme repaint callers.
    # Method: Actual page colors are already enforced by the shared prepared document.
    # ==========================================
    def background(self):pass

    # ==========================================
    # Function: Close the native controller and every retained GTK callback exactly once.
    # Method: Remove polling, native ownership and weak layer registration before releasing the widget callbacks.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True;self.document_ready=False
        if self.timer:self.g.g_source_remove(self.timer);self.timer=0
        if self.handle:self.lib.md_webview_close(self.handle);self.handle=None
        self.g.disconnect(self.group);self.source='';self.original=('',False,None)
        layers=getattr(getattr(self.g,'surfaces',None),'reader_layers',None)
        if layers:layers.readers.discard(self)

    # ==========================================
    # Function: Cooperate with the application's bounded reader shutdown sequence.
    # Method: WebView2 controller Close is synchronous and does not require Linux process discovery.
    # ==========================================
    def begin_shutdown(self):self.close()

    # ==========================================
    # Function: Complete the cross-platform reader shutdown contract.
    # Method: Native controllers have already closed during the first shutdown phase.
    # ==========================================
    def finish_shutdown(self):self.close()
