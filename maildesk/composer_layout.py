"""Dedicated native composer surface with bounded inline sizing and compact actions."""
import ctypes as C
from pathlib import Path
from xml.sax.saxutils import escape

# ==========================================
# Function: Fit an inline composer to the actual reader viewport.
# Method: Reserve a visible header/footer and let the body consume remaining space.
# ==========================================
def composer_geometry(viewport,inline):
    height=min(430,max(292,int(viewport or 700)-108)) if inline else -1
    return {'height':height,'body_height':max(110,min(230,height-155)) if inline else 180,'expand':not inline}

# ==========================================
# Function: Measure the space that can actually show an inline reply and its send footer.
# Method: Use the enclosing conversation viewport after allocation, excluding title/toolbars above it.
# ==========================================
def composer_viewport(g,window,reader,inline):
    width=g.gtk_widget_get_allocated_width(reader);height=g.gtk_widget_get_allocated_height(reader)
    if inline:
        scroller=g.gtk_widget_get_ancestor(window,g.gtk_scrolled_window_get_type())
        if scroller:
            visible=g.gtk_widget_get_allocated_height(g.gtk_bin_get_child(scroller))
            if visible>1:height=min(height,visible)
    return width,height

# ==========================================
# Function: Define the dedicated editor independently of generic settings forms.
# Method: Keep native field identifiers while placing recipients above an expanding body and one footer.
# ==========================================
def composer_xml(accounts):
    items=''.join('<item id="'+escape(key)+'">'+escape(label)+'</item>' for key,label in accounts)
    # ==========================================
    # Function: Define one recipient row with optional discoverable disclosure.
    # Method: Use borderless editable fields and hide only empty secondary recipients.
    # ==========================================
    def recipient(key,title,optional=False):
        hidden='<property name="no-show-all">True</property><property name="visible">False</property>' if optional else ''
        return '<child><object class="GtkBox" id="'+key+'_row">'+hidden+'<property name="spacing">8</property><style><class name="composer-recipient"/></style><child><object class="GtkLabel"><property name="label">'+title+'</property><property name="xalign">0</property><style><class name="composer-muted"/></style></object></child><child><object class="GtkEntry" id="'+key+'"><property name="hexpand">True</property><property name="width-chars">8</property><property name="placeholder-text">输入邮箱地址</property></object><packing><property name="expand">True</property><property name="fill">True</property></packing></child></object></child>'
    return '''<interface><object class="GtkBox" id="form"><property name="orientation">vertical</property><property name="spacing">0</property><property name="hexpand">True</property><property name="vexpand">True</property><style><class name="modern-composer"/></style>
<child><object class="GtkBox" id="composer_heading"><property name="spacing">4</property><style><class name="composer-heading"/></style><child><object class="GtkEntry" id="subject"><property name="placeholder-text">主题</property><property name="width-chars">10</property><property name="hexpand">True</property><style><class name="composer-subject"/></style></object><packing><property name="expand">True</property><property name="fill">True</property></packing></child></object></child>
<child><object class="GtkBox" id="recipient_fields"><property name="orientation">vertical</property>'''+recipient('to','收件人')+recipient('cc','抄送',True)+recipient('bcc','密送',True)+'''</object></child>
<child><object class="GtkBox" id="attachments_chips"><property name="orientation">vertical</property><property name="no-show-all">True</property><property name="visible">False</property><style><class name="composer-attachments"/></style></object></child>
<child><object class="GtkScrolledWindow" id="body_scroll"><property name="hscrollbar-policy">never</property><property name="vscrollbar-policy">automatic</property><property name="vexpand">True</property><property name="height-request">180</property><child><object class="GtkTextView" id="body"><property name="wrap-mode">word-char</property><property name="left-margin">16</property><property name="right-margin">16</property><property name="top-margin">12</property><property name="bottom-margin">12</property><property name="pixels-below-lines">4</property><style><class name="composer-body"/></style></object></child></object><packing><property name="expand">True</property><property name="fill">True</property></packing></child>
<child><object class="GtkLabel" id="note"><property name="xalign">0</property><property name="ellipsize">end</property><property name="max-width-chars">20</property><style><class name="composer-note"/></style></object></child>
<child><object class="GtkBox" id="composer_footer"><property name="spacing">2</property><style><class name="composer-footer"/></style></object></child>
<child><object class="GtkBox" id="schedule_state"><property name="no-show-all">True</property><property name="visible">False</property><child><object class="GtkEntry" id="due"/></child><child><object class="GtkEntry" id="followup"/></child></object></child></object>
<object class="GtkPopover" id="account_popover"><child><object class="GtkBox"><property name="margin">10</property><child><object class="GtkComboBoxText" id="account"><items>'''+items+'''</items></object></child></object></child></object></interface>'''

# ==========================================
# Function: Own a modern native editor without the generic form's nested scroll/grid.
# Method: Reuse Form field and destruction contracts while building a dedicated GTK surface.
# ==========================================
class ComposerLayout:
    # ==========================================
    # Function: Initialize a dedicated editor shell and its stable field registry.
    # Method: Parent one builder-owned root directly into the embedded surface or native dialog.
    # ==========================================
    def init_layout(self,app,fields,accounts,embedded):
        self.app,self.g,self.embedded=app,app.g,embedded;g=self.g
        self.window=g.gtk_box_new(1,0) if embedded else g.gtk_dialog_new()
        self.builder=g.builder(composer_xml(accounts));self.group=f'form-{self.window}';self.closed=False
        self.fields={key:(g.object(self.builder,key),kind) for key,_,kind,_ in fields};self.note=g.object(self.builder,'note')
        from .native_choices import NativeChoice
        self.account_choice=NativeChoice(g,self.fields['account'][0],'发件账户')
        if not hasattr(app,'active_forms'):app.active_forms=[]
        app.active_forms.append(self)
        if getattr(app.options,'self_test',False):app.testing_form=self
        from .desktop_preferences import resolved_theme
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.window),resolved_theme(app).encode())
        root=g.object(self.builder,'form');self.content=root;self.action_area=g.object(self.builder,'composer_footer')
        if embedded:g.gtk_container_add(self.window,root)
        else:
            from .windows_frame import bind_window_frame
            bind_window_frame(app,self.window,self.group)
            g.gtk_window_set_title(self.window,'TeleMail · 新邮件'.encode());g.gtk_window_set_default_size(self.window,900,700)
            g.gtk_window_set_transient_for(self.window,app.window);g.gtk_window_set_application(self.window,app.application)
            g.gtk_container_add(g.gtk_dialog_get_content_area(self.window),root)
        self.layout_height=None;self.layout_scroll_callback=None;self.layout_scroll_timer=0;self.last_viewport=None
        self.layout_size_timer=0;self.layout_size_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.apply_surface_size)
        self.g.connect(app.widget('reader'),'size-allocate',lambda *unused:self.queue_surface_size(),count=3,group=self.group)
        self.g.connect(self.window,'size-allocate',lambda *unused:self.queue_surface_size(),count=3,group=self.group)

    # ==========================================
    # Function: Create one small original icon action with an accessible tooltip.
    # Method: Keep response identifiers and public button attributes stable for semantic tests.
    # ==========================================
    def action_icon(self,parent,title,response,icon):
        g=self.g;button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'composer-icon')
        image=g.image_file(Path(__file__).parent/'desktop_assets'/'icons'/('composer-'+icon+'.svg'),16)
        g.gtk_button_set_image(button,image);g.gtk_button_set_always_show_image(button,1);g.gtk_widget_set_tooltip_text(button,title.encode())
        g.gtk_box_pack_start(parent,button,0,0,0);g.connect(button,'clicked',lambda *unused:self.response(self.window,response,None),group=self.group)
        return button

    # ==========================================
    # Function: Build a single compact toolbar and unobtrusive secondary action popovers.
    # Method: Keep primary writing actions in one row and move infrequent controls behind More.
    # ==========================================
    def setup_actions(self):
        g=self.g;heading=g.object(self.builder,'composer_heading');footer=self.action_area
        self.expand_button=self.action_icon(heading,'展开编辑器 / 返回回复',13,'expand') if self.embedded else None
        self.popout_button=self.action_icon(heading,'在独立窗口撰写 / 返回邮件',15,'popout') if self.embedded else None
        self.close_button=self.action_icon(heading,'关闭并保存草稿',-6,'close')
        self.attachment_button=self.action_icon(footer,'添加附件',3,'attachment')
        self.template_button=self.action_icon(footer,'模板',4,'template')
        self.format_button=g.gtk_menu_button_new();g.gtk_button_set_label(self.format_button,b'Aa');g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.format_button),b'composer-icon');g.gtk_widget_set_tooltip_text(self.format_button,'文字格式'.encode());g.gtk_box_pack_start(footer,self.format_button,0,0,0)
        self.format_popover=self.action_popover(self.format_button,[('加粗',7),('斜体',8),('下划线',9)])
        self.remind_button=self.action_icon(footer,'未回复提醒',12,'reminder')
        self.later_button=self.action_icon(footer,'稍后发送',11,'later')
        self.more_button=g.gtk_menu_button_new();g.gtk_button_set_label(self.more_button,'•••'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.more_button),b'composer-icon');g.gtk_widget_set_tooltip_text(self.more_button,'更多编辑选项'.encode());g.gtk_box_pack_start(footer,self.more_button,0,0,0)
        self.more_popover=self.action_popover(self.more_button,[('保存草稿',1),('抄送 / 密送',14),('插入签名',5),('移除附件',6),('放弃草稿',10)])
        self.account_button=g.gtk_menu_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.account_button),b'composer-account')
        self.account_label=g.gtk_label_new(b'');g.gtk_label_set_ellipsize(self.account_label,3);g.gtk_label_set_max_width_chars(self.account_label,24)
        g.gtk_container_add(self.account_button,self.account_label);g.gtk_menu_button_set_popover(self.account_button,g.object(self.builder,'account_popover'))
        g.gtk_box_pack_start(footer,self.account_button,1,1,4)
        self.send_button=self.action_icon(footer,'发送邮件',2,'send');g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.send_button),b'composer-send')
        self.save_button=self.secondary_buttons[1]
        self.refresh_chips();self.reveal_recipients(False)

    # ==========================================
    # Function: Build secondary controls without growing the editor's main layout.
    # Method: Attach response buttons to native anchored popovers.
    # ==========================================
    def action_popover(self,button,actions):
        g=self.g;popover=g.gtk_popover_new(button);box=g.gtk_box_new(1,2);g.gtk_container_set_border_width(box,8);g.gtk_container_add(popover,box)
        if not hasattr(self,'secondary_buttons'):self.secondary_buttons={}
        for title,response in actions:
            item=g.gtk_button_new_with_label(title.encode());g.gtk_box_pack_start(box,item,0,1,0);self.secondary_buttons[response]=item
            # ==========================================
            # Function: Close the action menu before invoking its native editor command.
            # Method: Capture the exact response and popover at signal creation time.
            # ==========================================
            def activate(*unused,code=response,popup=popover):
                g.gtk_popover_popdown(popup);self.response(self.window,code,None)
            g.connect(item,'clicked',activate,group=self.group)
        g.gtk_widget_show_all(box);g.gtk_menu_button_set_popover(button,popover);return popover

    # ==========================================
    # Function: Reveal secondary recipients only when requested or already populated.
    # Method: Preserve hidden values and recipient completion widgets across all surface changes.
    # ==========================================
    def reveal_recipients(self,explicit=True):
        for key in ('cc','bcc'):
            shown=bool(explicit or self.value(key));row=self.g.object(self.builder,key+'_row')
            self.g.gtk_widget_set_no_show_all(row,not shown);self.g.gtk_widget_set_visible(row,shown)
            if shown:self.g.gtk_widget_show_all(row)
        self.size_surface()

    # ==========================================
    # Function: Render small attachment chips without consuming the message body.
    # Method: Limit the visible chip list to three and expose full removal through More.
    # ==========================================
    def refresh_chips(self):
        g=self.g;host=g.object(self.builder,'attachments_chips');g.clear(host)
        for index,item in enumerate(self.attachments[:3]):
            label=g.gtk_label_new(('↳ '+item['name']).encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,40)
            g.gtk_box_pack_start(host,label,0,1,0)
        if len(self.attachments)>3:g.gtk_box_pack_start(host,g.gtk_label_new(('另有 '+str(len(self.attachments)-3)+' 个附件 · 更多中管理').encode()),0,1,0)
        g.gtk_widget_set_no_show_all(host,not self.attachments);g.gtk_widget_set_visible(host,bool(self.attachments))
        if self.attachments:g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Coalesce allocation notifications without resizing widgets during GTK allocation.
    # Method: Defer one retained callback until the current parent/child allocation pass has returned.
    # ==========================================
    def queue_surface_size(self):
        if self.closed or self.layout_size_timer:return
        self.layout_size_timer=self.g.g_timeout_add(1,C.cast(self.layout_size_callback,C.c_void_p),None)

    # ==========================================
    # Function: Apply the final conversation viewport after native allocation completes.
    # Method: Clear the timer before sizing and refuse work for an already closed editor.
    # ==========================================
    def apply_surface_size(self,*unused):
        self.layout_size_timer=0
        if not self.closed:self.size_surface()
        return 0

    # ==========================================
    # Function: Recompute the reply viewport without wrapping the entire form in another scroller.
    # Method: Keep a useful body allocation and fixed footer while expanded composition fills its parent.
    # ==========================================
    def size_surface(self):
        if self.closed:return
        g=self.g;area=self.app.widget('reader_overlay') if getattr(self,'floating',False) else self.app.widget('reader')
        viewport_size=composer_viewport(g,self.window,area,self.inline)
        viewport=viewport_size[1]
        viewport_changed=viewport_size!=self.last_viewport;self.last_viewport=viewport_size
        if viewport_changed and self.inline and g.gtk_widget_get_parent(self.window):self.scroll_into_view()
        geometry=composer_geometry(viewport,self.inline)
        secondary=sum(bool(g.gtk_widget_get_visible(g.object(self.builder,key+'_row'))) for key in ('cc','bcc'))*32
        attachment_space=min(80,len(getattr(self,'attachments',[]))*20)
        history=getattr(self,'history_view',None);history_space=(218 if history.expanded else 38) if history and history.data else 0
        detached=getattr(self,'detached',False);height=geometry['height']
        self.app.clear_reply_reserve()
        signature=(height,geometry['body_height'],secondary,attachment_space,history_space,viewport_size,self.inline,detached)
        if self.layout_height==signature:return
        self.layout_height=signature
        g.gtk_widget_set_halign(self.window,0);g.gtk_widget_set_valign(self.window,0)
        g.gtk_widget_set_vexpand(self.window,not self.inline)
        g.gtk_widget_set_size_request(self.window,-1,height)
        body=max(60,geometry['body_height']-secondary-attachment_space-history_space) if self.inline else (80 if history and history.expanded else 180)
        g.gtk_widget_set_size_request(g.object(self.builder,'body_scroll'),-1,body)
        context=g.gtk_widget_get_style_context(self.window)
        g.gtk_style_context_remove_class(context,b'floating-reply')
        if self.inline:g.gtk_style_context_add_class(context,b'conversation-reply')
        else:g.gtk_style_context_remove_class(context,b'conversation-reply')

    # ==========================================
    # Function: Bring a newly opened inline reply fully into the conversation viewport.
    # Method: Wait for native allocation, then clamp the enclosing adjustment to the editor rectangle.
    # ==========================================
    def scroll_into_view(self):
        if not self.inline or self.closed or getattr(self,'floating',False):return
        if self.layout_scroll_timer:self.g.g_source_remove(self.layout_scroll_timer)
        # ==========================================
        # Function: Scroll after GTK has assigned the inline editor its actual dimensions.
        # Method: Translate its rectangle into conversation coordinates and clamp the native adjustment.
        # ==========================================
        attempts=[0]
        def reveal(unused):
            if self.closed or not self.inline:self.layout_scroll_timer=0;return 0
            attempts[0]+=1
            g=self.g;scroller=g.gtk_widget_get_ancestor(self.window,g.gtk_scrolled_window_get_type())
            if not scroller:self.layout_scroll_timer=0;return 0
            viewport=g.gtk_bin_get_child(scroller);child=g.gtk_bin_get_child(viewport);x=C.c_int();y=C.c_int()
            if g.gtk_widget_translate_coordinates(self.window,child,0,0,C.byref(x),C.byref(y)):
                adjustment=g.gtk_scrolled_window_get_vadjustment(scroller);height=g.gtk_widget_get_allocated_height(self.window)
                g.gtk_adjustment_clamp_page(adjustment,float(y.value),float(y.value+height))
            if attempts[0]>=10:self.layout_scroll_timer=0;return 0
            return 1
        self.layout_scroll_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(reveal)
        self.layout_scroll_timer=self.g.g_timeout_add(70,C.cast(self.layout_scroll_callback,C.c_void_p),None)
