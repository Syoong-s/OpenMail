"""Embedded inert HTML/Markdown and isolated offline PDF.js readers."""
import ctypes as C
import ctypes.util
import os
from pathlib import Path
from urllib.parse import urlsplit
import subprocess
import uuid
from xml.sax.saxutils import escape
from .gtk_native import P,I,U,S
from .document_content import reader_document
from .message_style import reader_appearance
from .desktop_preferences import resolved_theme
from .mail_images import image_type,image_uri

# ==========================================
# Function: Resolve a native reader runtime without importing Python UI packages.
# Method: Bind a finite C ABI and report missing Linux runtime packages explicitly.
# ==========================================
def library(name, signatures):
    if os.name=='nt':
        from .platform_native import load_library
        module=load_library(name)
        for symbol,signature in signatures.items():
            fn=getattr(module,symbol);fn.restype,fn.argtypes=signature[0],signature[1:]
        return module
    soname=C.util.find_library(name)
    private=os.environ.get('TELEMAIL_READER_ACTIVE','')
    if not soname and private:
        matches=list((Path(private)/'usr/lib/x86_64-linux-gnu').glob('lib'+name+'.so.*'))
        if matches:soname=str(sorted(matches,key=lambda value:len(value.name))[0])
    if not soname:raise RuntimeError('缺少应用内阅读运行库：'+name+'。请按阅读器依赖清单安装 Linux 运行库。')
    module=C.CDLL(soname)
    for symbol,signature in signatures.items():
        fn=getattr(module,symbol);fn.restype,fn.argtypes=signature[0],signature[1:]
    return module

# ==========================================
# Function: Match the public GdkRGBA color structure.
# Method: Pass four doubles to WebKit's native background-color setter.
# ==========================================
class RGBA(C.Structure):
    _fields_=[('red',C.c_double),('green',C.c_double),('blue',C.c_double),('alpha',C.c_double)]

# ==========================================
# Function: Own an ephemeral embedded HTML view with no remote document resources.
# Method: Block email scripts and render prepared documents through load_html.
# ==========================================
class WebKitHTMLReader:
    # ==========================================
    # Function: Create an embedded WebKitGTK widget and retained navigation policy.
    # Method: Wrap the ephemeral view in a bounded GTK surface and disable scripts before loading content.
    # ==========================================
    def __init__(self,app,group):
        self.app,self.g,self.group=app,app.g,group;self.closed=False
        self.lib=library('webkit2gtk-4.1',{
            'webkit_web_context_new_ephemeral':(P,), 'webkit_web_context_set_sandbox_enabled':(None,P,I),
            'webkit_web_context_add_path_to_sandbox':(None,P,S,I), 'webkit_web_view_new_with_context':(P,P),
            'webkit_web_view_get_settings':(P,P),'webkit_settings_set_enable_javascript':(None,P,I),
            'webkit_settings_set_hardware_acceleration_policy':(None,P,I),'webkit_settings_set_enable_webgl':(None,P,I),
            'webkit_web_view_get_uri':(S,P),'webkit_web_view_get_title':(S,P),'webkit_web_view_is_loading':(I,P),
            'webkit_web_view_load_uri':(None,P,S), 'webkit_web_view_set_background_color':(None,P,P), 'webkit_web_view_load_html':(None,P,S,S),'webkit_web_view_set_zoom_level':(None,P,C.c_double),
            'webkit_web_view_get_find_controller':(P,P),'webkit_find_controller_search':(None,P,S,U,U),
            'webkit_policy_decision_ignore':(None,P),'webkit_navigation_policy_decision_get_navigation_action':(P,P),
            'webkit_navigation_action_get_navigation_type':(I,P),'webkit_navigation_action_get_request':(P,P),
            'webkit_uri_request_get_uri':(S,P),'webkit_web_view_stop_loading':(None,P),
            'webkit_web_view_try_close':(None,P),'webkit_web_view_terminate_web_process':(None,P)})
        context=getattr(app,'reader_web_context',None)
        fresh=not context
        if fresh:
            context=self.lib.webkit_web_context_new_ephemeral();app.reader_web_context=context
        if fresh:
            self.lib.webkit_web_context_set_sandbox_enabled(context,1)
            paths=[Path(__file__).resolve().parent/'desktop_assets/fonts']
            for key in ('TELEMAIL_READER_ACTIVE','FONTCONFIG_FILE'):
                if os.environ.get(key):paths.append(Path(os.environ[key]))
            for path in paths:
                if path.exists():self.lib.webkit_web_context_add_path_to_sandbox(context,str(path.resolve()).encode(),1)
        self.detached_ref=False
        if not self.take_cached_view():
            self.view=self.lib.webkit_web_view_new_with_context(context)
            # External policies bound GTK's natural request; WebKit retains an old viewport size on reuse.
            self.widget=self.g.gtk_scrolled_window_new(None,None)
            self.g.gtk_scrolled_window_set_policy(self.widget,3,3)
            self.g.gtk_container_add(self.widget,self.view)
            app.reader_pool_created=getattr(app,'reader_pool_created',0)+1
        settings=self.lib.webkit_web_view_get_settings(self.view);self.lib.webkit_settings_set_enable_javascript(settings,0)
        from .reader_runtime import reader_software_graphics
        self.software_graphics=reader_software_graphics()
        self.lib.webkit_settings_set_enable_webgl(settings,0)
        if self.software_graphics:self.lib.webkit_settings_set_hardware_acceleration_policy(settings,2)
        self.g.gtk_widget_set_hexpand(self.widget,1)
        self.g.gtk_widget_set_vexpand(self.widget,1)
        self.g.connect(self.view,'decide-policy',self.navigation,count=4,types=[P,P,I,P],returns=True,group=group)
        self.g.connect(self.view,'load-changed',self.loaded,count=3,types=[P,I,P],group=group)
        self.g.connect(self.view,'notify::title',self.title_changed,count=3,group=group)
        self.load_generation=0;self.started_generation=-1;self.expected_uri='about:blank';self.expected_title='';self.document_ready=False;self.pending_image=None;self.image_navigation=False
        self.g.gtk_widget_set_opacity(self.widget,0)
        self.source='';self.zoom=1
        self.lib.webkit_web_view_set_zoom_level(self.view,1)
        self.g.gtk_widget_set_size_request(self.widget,-1,-1)
        self.background()
        self.compact_mail=False;self.content_fit=None

    # ==========================================
    # Function: Fit Linux conversation bubbles to actual browser layout rather than text estimates.
    # Method: Enable isolated host measurements while native markup blocking and mail CSP prevent email scripts.
    # ==========================================
    def enable_compact_layout(self):
        from .webkit_mail_fit import WebKitMailFit
        self.compact_mail=True
        self.g.gtk_widget_set_vexpand(self.widget,0)
        if self.content_fit is None:self.content_fit=WebKitMailFit(self)
        self.content_fit.start()

    # ==========================================
    # Function: Stop a historical body before its containing card is released.
    # Method: Disconnect retained policy callbacks and cancel asynchronous WebKit loading.
    # ==========================================
    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True;self.document_ready=False;self.pending_image=None;self.image_navigation=False
        if getattr(self,'content_fit',None):self.content_fit.close()
        self.lib.webkit_web_view_stop_loading(self.view)
        self.g.disconnect(self.group)
        app=getattr(self,'app',None)
        if app and not getattr(app,'closing',False):
            parking=getattr(app,'reader_parking',None)
            if not parking:
                parking=self.g.gtk_box_new(1,0);self.g.g_object_ref_sink(parking);app.reader_parking=parking
            if self.g.gtk_widget_get_parent(self.widget):self.g.gtk_widget_reparent(self.widget,parking)
            else:self.g.gtk_container_add(parking,self.widget)
            self.attached()
            self.g.gtk_widget_set_opacity(self.widget,0)
            self.source='';self.original=('',False,None)
            self.lib.webkit_web_view_load_html(self.view,b'<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src none"><body></body>',b'about:blank')
            if not hasattr(app,'reader_idle'):app.reader_idle=[]
            app.reader_idle.append(self)

    # ==========================================
    # Function: Borrow an idle renderer without changing its ephemeral security context.
    # Method: Transfer the bounded surface and inner view together through a temporary owned reference.
    # ==========================================
    def take_cached_view(self):
        idle=getattr(self.app,'reader_idle',[])
        if not idle:return False
        previous=idle.pop();self.widget=previous.widget;self.view=previous.view
        self.g.g_object_ref(self.widget);self.detached_ref=True
        self.g.gtk_container_remove(self.app.reader_parking,self.widget)
        self.app.reader_pool_reused=getattr(self.app,'reader_pool_reused',0)+1
        return True

    # ==========================================
    # Function: Complete a borrowed native widget's parent ownership transfer exactly once.
    # Method: Drop only the temporary detached reference after a new container owns the WebView.
    # ==========================================
    def attached(self):
        if getattr(self,'detached_ref',False):
            self.detached_ref=False;self.g.g_object_unref(self.widget)

    # ==========================================
    # Function: Reveal a reused renderer only after its new document has completed loading.
    # Method: Match an inert native document title nonce and ignore stale or closed-owner callbacks.
    # ==========================================
    def loaded(self,widget,event,unused):
        if self.closed:return
        if getattr(self,'image_navigation',False) and self.document_ready:
            self.g.gtk_widget_set_opacity(self.widget,1);return
        title=(self.lib.webkit_web_view_get_title(self.view) or b'').decode()
        if not self.expected_title or title!=self.expected_title:return
        if event==0:
            self.started_generation=self.load_generation;self.g.gtk_widget_set_opacity(self.widget,0)
        elif event==3 and self.source:
            self.document_ready=True;self.g.gtk_widget_set_opacity(self.widget,1)
            pending=getattr(self,'pending_image',None)
            if pending is not None:self.pending_image=None;self.jump_to_image(pending)

    # ==========================================
    # Function: Handle a delayed native title notification after document loading completes.
    # Method: Reveal only the current inert document identity when WebKit has no pending load.
    # ==========================================
    def title_changed(self,widget,parameter,unused):
        if not self.closed and not self.lib.webkit_web_view_is_loading(self.view):self.loaded(widget,3,None)

    # ==========================================
    # Function: Request graceful page closure while retaining its shared sandbox context.
    # Method: Stop local loading and use WebKit's public close handshake only during application shutdown.
    # ==========================================
    def begin_shutdown(self):
        self.close()
        if getattr(self,'shutdown_requested',False):return
        self.shutdown_requested=True
        self.lib.webkit_web_view_try_close(self.view)

    # ==========================================
    # Function: End a still-live owned renderer after the application shutdown grace period.
    # Method: Invoke the public WebKit API while its widgets and shared sandbox context remain valid.
    # ==========================================
    def finish_shutdown(self):
        if getattr(self,'shutdown_terminated',False):return
        self.shutdown_terminated=True
        self.lib.webkit_web_view_terminate_web_process(self.view)

    # ==========================================
    # Function: Block in-view navigation and open explicit web links through the OS.
    # Method: Permit only the initial about document and user-clicked http/mailto targets.
    # ==========================================
    def navigation(self,widget,decision,kind,unused):
        if kind not in (0,1):return False
        action=self.lib.webkit_navigation_policy_decision_get_navigation_action(decision)
        request=self.lib.webkit_navigation_action_get_request(action)
        uri=(self.lib.webkit_uri_request_get_uri(request) or b'').decode()
        if uri in ('about:blank','',getattr(self,'expected_uri','')) or uri.startswith('about:blank#mail-image-'):return False
        self.lib.webkit_policy_decision_ignore(decision)
        if self.lib.webkit_navigation_action_get_navigation_type(action)==0 and urlsplit(uri).scheme.lower() in ('http','https','mailto'):
            if urlsplit(uri).scheme.lower()=='mailto':self.app.run_action(lambda:self.app.open_mailto(uri))
            else:
                from .platform_native import open_uri
                open_uri(uri)
        return True

    # ==========================================
    # Function: Load an offline HTML or Markdown document.
    # Method: Sanitize before invoking the native renderer and retain testable source.
    # ==========================================
    def load(self,source,markdown=False,images=None,force=False):
        self.original=(source,markdown,images)
        self.background()
        store=self.app.service.store
        prepared=reader_document(source,markdown,resolved_theme(self.app)=='dark',images,
            adapt_dark=False if getattr(self,'preserve_document_style',False) else store.preference('adapt_dark_html',True),font_size=store.preference('reader_font_size',14),remote_images=store.preference('load_remote_images',False),appearance=reader_appearance(self))
        if not force and prepared==self.source:return
        if self.content_fit:self.content_fit.height=None
        self.source=prepared;self.load_generation+=1;self.started_generation=-1;self.document_ready=False;self.pending_image=None;self.image_navigation=False
        self.expected_title='TeleMail reader '+uuid.uuid4().hex
        rendered=self.source.replace('<head>','<head><title>'+self.expected_title+'</title>',1)
        self.g.gtk_widget_set_opacity(self.widget,0)
        self.lib.webkit_web_view_load_html(self.view,rendered.encode(),b'about:blank')

    # ==========================================
    # Function: Repaint a document after theme or privacy preferences change.
    # Method: Reuse the original inert input and current settings without losing image content.
    # ==========================================
    def reload(self):
        if hasattr(self,'original'):self.load(*self.original,force=True)

    # ==========================================
    # Function: Reveal a cached image at its original position in the mail document.
    # Method: Navigate to the document-local image anchor without evaluating script or fetching URLs.
    # ==========================================
    def jump_to_image(self,index):
        if not self.document_ready:self.pending_image=int(index);return
        self.image_navigation=True
        self.lib.webkit_web_view_load_uri(self.view,('about:blank#mail-image-'+str(int(index))).encode())

    # ==========================================
    # Function: Keep the renderer surface dark during asynchronous page loads.
    # Method: Set the public WebKit background color before loading the document.
    # ==========================================
    def background(self):
        dark=resolved_theme(self.app)=='dark'
        palette=reader_appearance(self)
        color=RGBA(*(int(palette['surface'][i:i+2],16)/255 for i in (1,3,5)),1) if palette else (RGBA(39/255,41/255,44/255,1) if dark else RGBA(1,1,1,1))
        self.lib.webkit_web_view_set_background_color(self.view,C.byref(color))

    # ==========================================
    # Function: Search rendered text within the current document.
    # Method: Use WebKit's case-insensitive, wrap-around native find controller.
    # ==========================================
    def find(self,text):
        controller=self.lib.webkit_web_view_get_find_controller(self.view)
        self.lib.webkit_find_controller_search(controller,text.encode(),1|16,1000)

    # ==========================================
    # Function: Scale the embedded document without changing saved mail.
    # Method: Bound native zoom between fifty and three hundred percent.
    # ==========================================
    def scale(self,factor):
        self.zoom=min(3,max(.5,self.zoom*factor));self.lib.webkit_web_view_set_zoom_level(self.view,self.zoom)

HTMLReader=WebKitHTMLReader
if os.name=='nt':
    from .windows_reader import HTMLReader

from .pdf_reader import PDFReader

# ==========================================
# Function: Decode local text documents without changing their original saved bytes.
# Method: Accept Unicode BOMs and common HTML declarations, then UTF-8/GB18030 fallbacks.
# ==========================================
def document_text(data):
    import re
    if data.startswith((b'\xff\xfe',b'\xfe\xff')):return data.decode('utf-16',errors='replace')
    match=re.search(br'charset\s*=\s*["\']?([A-Za-z0-9_-]+)',data[:4096],re.I)
    encodings=([match.group(1).decode('ascii')] if match else [])+['utf-8-sig','gb18030']
    for encoding in encodings:
        if encoding.lower().replace('_','-') not in ('utf-8','utf-8-sig','gb18030','gbk','gb2312','big5','windows-1252','iso-8859-1'):continue
        try:return data.decode(encoding)
        except (UnicodeDecodeError,LookupError):continue
    return data.decode('utf-8',errors='replace')

# ==========================================
# Function: Render one active file beneath the shared workspace tab strip.
# Method: Keep format-specific engines isolated; inactive tabs retain bytes rather than browser controllers.
# ==========================================
class DocumentPanel:
    # ==========================================
    # Function: Create one bounded document model and engine offscreen.
    # Method: Reuse native PDF and inert HTML readers while retaining file pages/source for local navigation.
    # ==========================================
    def __init__(self,app,name,data,on_save=None,media_type='',origin_id='',prepared=None):
        from .file_previews import preview
        self.app,self.g=app,app.g;self.group='document-'+str(id(self));self.engine=None;self.closed=False;self.name=name;self.origin_id=origin_id
        self.model=prepared if prepared is not None else preview(name,data,media_type)
        if Path(name).suffix.lower() in ('.tif','.tiff','.ico'):
            from .file_previews import native_raster,Preview
            self.model=Preview('image',[('图片','<figure><img src="'+native_raster(self.g,data)+'" alt="本机图片"></figure>')])
        self.preview_kind=self.model.kind;self.text_source=self.model.source;self.page_index=0;self.source_mode=False
        self.root=self.g.gtk_box_new(1,0);self.g.g_object_ref_sink(self.root);self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.root),b'document-panel')
        self.scroll=self.g.gtk_scrolled_window_new(None,None);self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.scroll),b'document-canvas');self.g.gtk_widget_set_hexpand(self.scroll,1);self.g.gtk_widget_set_vexpand(self.scroll,1);self.g.gtk_box_pack_start(self.root,self.scroll,1,1,0)
        self.toolbar=self.g.gtk_box_new(0,4);self.g.gtk_widget_set_halign(self.toolbar,3);self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.toolbar),b'document-controls');self.g.gtk_box_pack_start(self.root,self.toolbar,0,1,0)
        try:
            self.engine=PDFReader(app,data,self.group,self.update_page) if self.preview_kind=='pdf' else HTMLReader(app,self.group)
            if self.preview_kind!='pdf':self.engine.preserve_document_style=self.model.preserve_style;self.load_page()
            self.g.gtk_container_add(self.scroll,self.engine.widget)
            if isinstance(self.engine,HTMLReader):self.engine.attached()
            if self.preview_kind=='pdf' or len(self.model.pages)>1:
                self.previous_button=self.add_button('上一页','action-back',lambda:self.set_page(-1));self.next_button=self.add_button('下一页','action-next',lambda:self.set_page(1))
            self.page_label=self.g.gtk_label_new(b'');self.g.gtk_label_set_ellipsize(self.page_label,3);self.g.gtk_label_set_max_width_chars(self.page_label,22);self.g.gtk_box_pack_start(self.toolbar,self.page_label,0,0,2)
            self.zoom_out_button=self.add_button('缩小','action-zoom-out',lambda:self.engine.scale(1/1.2));self.zoom_in_button=self.add_button('放大','action-zoom-in',lambda:self.engine.scale(1.2))
            if self.preview_kind=='pdf':
                self.fit_button=self.add_button('适合宽度','action-fit',lambda:self.engine.fit(self.g.gtk_widget_get_allocated_width(self.scroll)))
                self.search_entry=self.g.gtk_entry_new();self.g.gtk_entry_set_width_chars(self.search_entry,12);self.g.gtk_entry_set_max_length(self.search_entry,2048)
                self.g.gtk_entry_set_placeholder_text(self.search_entry,'搜索 PDF'.encode());self.g.gtk_widget_set_tooltip_text(self.search_entry,'输入文字并按回车搜索；再次回车查找下一处'.encode())
                self.g.gtk_box_pack_start(self.toolbar,self.search_entry,0,0,4)
                self.g.connect(self.search_entry,'activate',lambda *unused:self.engine.find((self.g.gtk_entry_get_text(self.search_entry) or b'').decode()),group=self.group)
            self.initial_fit=False;self.update_page()
            if self.preview_kind=='pdf':self.g.connect(self.scroll,'size-allocate',lambda *unused:self.fit_initial_pdf(),count=3,group=self.group)
        except Exception:self.close(False);raise

    # ==========================================
    # Function: Load the current sheet/slide or source view in the same native controller.
    # Method: Sanitize generated markup through the shared reader before displaying it.
    # ==========================================
    def load_page(self):
        import html
        source='<pre><code>'+html.escape(self.text_source)+'</code></pre>' if self.source_mode else self.model.pages[self.page_index][1]
        self.engine.load(source,self.preview_kind=='markdown' and not self.source_mode)

    # ==========================================
    # Function: Toggle source only for formats with textual source.
    # Method: Preserve current document page/zoom and avoid exposing binary Office XML as editable code.
    # ==========================================
    def toggle_source(self):
        if not self.text_source:return
        self.source_mode=not self.source_mode;self.load_page()

    # ==========================================
    # Function: Navigate PDF pages or generated workbook/slide pages.
    # Method: Keep one live native engine and reset the file viewport to the next part.
    # ==========================================
    def set_page(self,delta):
        if self.preview_kind=='pdf':self.engine.turn_page(delta)
        else:self.page_index=max(0,min(len(self.model.pages)-1,self.page_index+delta));self.load_page()
        self.update_page()

    # ==========================================
    # Function: Build one compact retained file action.
    # Method: Use shared original icons and route native callback failures through application status.
    # ==========================================
    def add_button(self,title,icon,callback):
        from .ui_actions import icon_action
        button=icon_action(self.g,self.g.gtk_button_new(),title,icon);self.g.gtk_box_pack_start(self.toolbar,button,0,0,0);self.g.connect(button,'clicked',lambda *unused:self.app.run_action(lambda:(callback(),self.update_page())),group=self.group);return button

    # ==========================================
    # Function: Synchronize compact part/zoom labels and boundary controls.
    # Method: Reflect the actual PDF index or generated sheet/slide title.
    # ==========================================
    def update_page(self):
        if not hasattr(self,'page_label'):return
        pdf=self.preview_kind=='pdf';index=self.engine.index if pdf else self.page_index;count=self.engine.count if pdf else len(self.model.pages)
        title=(f'{index+1} / {count}' if count else (self.engine.error or 'PDF 正在加载…')) if pdf else self.model.pages[index][0]
        self.g.label(self.page_label,title+f' · {getattr(self.engine,"zoom",1):.0%}');self.g.gtk_widget_set_tooltip_text(self.page_label,title.encode())
        if hasattr(self,'previous_button'):self.g.gtk_widget_set_sensitive(self.previous_button,index>0);self.g.gtk_widget_set_sensitive(self.next_button,index+1<count)

    # ==========================================
    # Function: Fit an opened PDF after the document canvas receives its real width.
    # Method: Apply once; subsequent manual zoom remains stable during window resizing.
    # ==========================================
    def fit_initial_pdf(self):
        width=self.g.gtk_widget_get_allocated_width(self.scroll)
        if not self.closed and not self.initial_fit and width>40:self.initial_fit=True;self.engine.fit(width)

    # ==========================================
    # Function: Dispose the active file engine and native callbacks exactly once.
    # Method: Release child renderers before native widgets; workspace owns column/tab closure.
    # ==========================================
    def close(self,return_mail=False):
        if self.closed:return
        self.closed=True
        if self.engine:self.engine.close()
        self.g.surfaces.retire(self.group);self.g.gtk_widget_destroy(self.root);self.g.g_object_unref(self.root)
