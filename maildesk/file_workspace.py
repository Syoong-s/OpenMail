"""Tabbed offline attachment workspace with one active native renderer."""
import hashlib
from pathlib import Path
from .ui_actions import icon_action
from .attachment_cards import file_kind

# ==========================================
# Function: Retain bounded file tabs independently from the selected mail.
# Method: Share one native content host and release inactive reader engines to bound browser memory.
# ==========================================
class DocumentWorkspace:
    # ==========================================
    # Function: Create the tab strip, breadcrumb action row and reusable content host.
    # Method: Keep chrome in the existing right column and avoid native floating windows.
    # ==========================================
    def __init__(self,app):
        self.app,self.g=app,app.g;g=self.g;self.group='files-'+str(id(self));self.tabs={};self.active_key=None;self.panel=None;self.closed=False;self.tab_widgets={}
        self.root=g.gtk_box_new(1,0);g.g_object_ref_sink(self.root);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.root),b'file-workspace')
        self.tabs_row=g.gtk_box_new(0,2);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.tabs_row),b'file-tabs');g.gtk_box_pack_start(self.root,self.tabs_row,0,1,0)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,1,2);g.gtk_widget_set_size_request(scroll,40,38);g.gtk_box_pack_start(self.tabs_row,scroll,1,1,0);self.tab_host=g.gtk_box_new(0,0);g.gtk_container_add(scroll,self.tab_host)
        self.add_action(self.tabs_row,'打开本地文件','action-add',lambda:app.open_document());self.add_action(self.tabs_row,'关闭文件栏','composer-close',self.close)
        self.pathbar=g.gtk_box_new(0,5);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.pathbar),b'file-pathbar');g.gtk_box_pack_start(self.root,self.pathbar,0,1,0)
        self.breadcrumb=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.breadcrumb,0);g.gtk_label_set_ellipsize(self.breadcrumb,3);g.gtk_label_set_max_width_chars(self.breadcrumb,30);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.breadcrumb),b'file-breadcrumb');g.gtk_box_pack_start(self.pathbar,self.breadcrumb,1,1,0)
        self.source_button=self.add_action(self.pathbar,'查看源码 / 返回预览','action-code',self.toggle_source);self.save_button=self.add_action(self.pathbar,'保存原始文件','action-save',self.save)
        self.content=g.gtk_box_new(1,0);g.gtk_widget_set_vexpand(self.content,1);g.gtk_box_pack_start(self.root,self.content,1,1,0)

    # ==========================================
    # Function: Expose the active renderer to the existing shutdown/theme lifecycle.
    # Method: Forward a borrowed reference rather than retaining inactive engines.
    # ==========================================
    @property
    def engine(self):return self.panel.engine if self.panel else None

    # ==========================================
    # Function: Expose the active source message for existing mail-selection guards.
    # Method: Preserve the exact origin identity associated with each attachment tab.
    # ==========================================
    @property
    def origin_id(self):return self.tabs[self.active_key]['origin'] if self.active_key in self.tabs else ''

    # ==========================================
    # Function: Expose the active format to native preview diagnostics and callers.
    # Method: Delegate without keeping duplicate document models.
    # ==========================================
    @property
    def preview_kind(self):return self.panel.preview_kind if self.panel else ''

    # ==========================================
    # Function: Construct a compact shared chrome action.
    # Method: Retain callbacks under the workspace group and propagate failures through application status.
    # ==========================================
    def add_action(self,host,title,icon,callback):
        button=icon_action(self.g,self.g.gtk_button_new(),title,icon,16);self.g.gtk_box_pack_start(host,button,0,0,0);self.g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=self.group);return button

    # ==========================================
    # Function: Add or focus one exact attachment without duplicating an already open tab.
    # Method: Hash bounded bytes with name/origin and reject memory growth beyond eight files or60MiB.
    # ==========================================
    def open(self,name,data,on_save=None,media_type='',origin_id='',prepared=None):
        if len(data)>30*1024*1024:raise ValueError('文件超过30 MiB')
        key=(origin_id,name,hashlib.sha256(data).hexdigest())
        if key in self.tabs:self.activate(key);return self
        if len(self.tabs)>=8 or sum(len(t['data']) for t in self.tabs.values())+len(data)>60*1024*1024:raise ValueError('最多打开8个文件、合计60 MiB；请先关闭不需要的标签')
        from .document_reader import DocumentPanel
        panel=DocumentPanel(self.app,name,data,on_save,media_type,origin_id,prepared)
        self.tabs[key]={'name':name,'data':data,'save':on_save,'type':media_type,'origin':origin_id,'prepared':prepared};self.install(key,panel);return self

    # ==========================================
    # Function: Switch to a retained file using a newly constructed active reader.
    # Method: Build before replacing the current renderer so invalid files never discard the working preview.
    # ==========================================
    def activate(self,key):
        if key==self.active_key or key not in self.tabs:return
        from .document_reader import DocumentPanel
        tab=self.tabs[key];panel=DocumentPanel(self.app,tab['name'],tab['data'],tab['save'],tab['type'],tab['origin'],tab.get('prepared'));self.install(key,panel)

    # ==========================================
    # Function: Install the active reader and synchronize tab chrome.
    # Method: Close the previous engine before packing the next native child and expose source only when meaningful.
    # ==========================================
    def install(self,key,panel):
        if self.panel:self.panel.close(False)
        self.panel=panel;self.active_key=key;self.g.gtk_box_pack_start(self.content,panel.root,1,1,0);self.g.gtk_widget_show_all(panel.root);tab=self.tabs[key];self.g.label(self.breadcrumb,('邮件附件' if tab['origin'] else '本地文件')+' › '+tab['name']);self.g.gtk_widget_set_tooltip_text(self.breadcrumb,tab['name'].encode());self.g.gtk_widget_set_sensitive(self.source_button,bool(panel.text_source));self.redraw_tabs()

    # ==========================================
    # Function: Render one horizontal row of bounded filename tabs with local close icons.
    # Method: Retire old tab callbacks safely before rebuilding original native icon/label controls.
    # ==========================================
    def redraw_tabs(self):
        g=self.g;group=self.group+'-tabs';g.surfaces.retire(group);g.clear(self.tab_host);self.tab_widgets={}
        for key,tab in self.tabs.items():
            row=g.gtk_box_new(0,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(row),b'file-tab')
            if key==self.active_key:g.gtk_style_context_add_class(g.gtk_widget_get_style_context(row),b'active')
            button=g.gtk_button_new();line=g.gtk_box_new(0,6);g.gtk_container_add(button,line);g.gtk_box_pack_start(line,g.image_file(Path(__file__).parent/'desktop_assets/icons'/('file-'+file_kind(tab['name'],tab['type'])+'.svg'),14),0,0,0)
            label=g.gtk_label_new(tab['name'].encode());g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,18);g.gtk_box_pack_start(line,label,1,1,0);g.gtk_widget_set_tooltip_text(button,tab['name'].encode());g.gtk_box_pack_start(row,button,1,1,0)
            close=icon_action(g,g.gtk_button_new(),'关闭 '+tab['name'],'composer-close',12);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(close),b'file-tab-close');g.gtk_box_pack_start(row,close,0,0,0);g.gtk_box_pack_start(self.tab_host,row,0,0,0)
            g.connect(button,'clicked',lambda *unused,k=key:self.app.run_action(lambda:self.activate(k)),group=group);g.connect(close,'clicked',lambda *unused,k=key:self.app.run_action(lambda:self.close_tab(k)),group=group);self.tab_widgets[key]={'row':row,'button':button,'close':close}
        g.gtk_widget_show_all(self.tab_host)

    # ==========================================
    # Function: Close a single file tab and select its neighboring retained file.
    # Method: Keep mail/composer widgets untouched and hide the file column only after the last tab closes.
    # ==========================================
    def close_tab(self,key):
        if key not in self.tabs:return
        if len(self.tabs)==1:self.close();return
        if key==self.active_key:
            keys=list(self.tabs);index=keys.index(key);self.activate(keys[index+1] if index+1<len(keys) else keys[index-1])
        del self.tabs[key];self.redraw_tabs()

    # ==========================================
    # Function: Switch between source and rendered preview for text-backed formats.
    # Method: Reuse the current reader and retain its format/page state.
    # ==========================================
    def toggle_source(self):
        if self.panel:self.panel.toggle_source();self.g.gtk_widget_set_tooltip_text(self.source_button,('返回预览' if self.panel.source_mode else '查看源码').encode())

    # ==========================================
    # Function: Save the exact original file bytes on explicit user action.
    # Method: Preserve the existing attachment save callback or ask for a local destination.
    # ==========================================
    def save(self):
        tab=self.tabs[self.active_key]
        if tab['save']:return tab['save']()
        path=self.g.choose(self.app.window,'保存原始文件',tab['name'])
        if path:Path(path).write_bytes(tab['data'])

    # ==========================================
    # Function: Release the complete file column during explicit close/navigation/shutdown.
    # Method: Close one active engine, retire tab/chrome callbacks and clear retained bytes once.
    # ==========================================
    def close(self,return_mail=True):
        if self.closed:return
        self.closed=True;self.app.document_request_serial=getattr(self.app,'document_request_serial',0)+1
        if self.panel:self.panel.close(False);self.panel=None
        self.g.surfaces.retire(self.group+'-tabs');self.g.surfaces.retire(self.group);self.g.gtk_widget_destroy(self.root);self.g.g_object_unref(self.root);self.tabs.clear();self.tab_widgets.clear()
        if getattr(self.app,'document',None) is self:self.app.document=None
        if return_mail:
            if getattr(self.app,'workspace_geometry',None):self.app.workspace_geometry.hide_preview()
            else:self.g.gtk_widget_hide(self.app.widget('document_host'))
            if not self.app.closing and hasattr(self.app,'apply_layout'):self.app.apply_layout()
