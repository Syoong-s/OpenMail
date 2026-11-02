"""Concise, state-aware native reader actions using the existing mail controllers."""
from pathlib import Path
import ctypes as C
import time
from .desktop_general import bind,P,I

ICONS=Path(__file__).parent/'desktop_assets/icons'


# ==========================================
# Function: Present the reader's secondary commands as compact icon-labelled groups.
# Method: Reparent existing controllers so keyboard bindings, dialogs and guarded actions remain intact.
# ==========================================
class MailMenuUI:
    # ==========================================
    # Function: Replace the long text menu with a two-column action grid and a collapsed classification area.
    # Method: Preserve button identities/signals, using one stable status indicator per stateful command.
    # ==========================================
    def initialize_mail_menu(self):
        g=self.g;host=g.gtk_bin_get_child(self.widget('mail_menu'));self.mail_menu_entries={}
        definitions=(('aside','暂存','spark-layout-folder'),('spam','垃圾邮件','action-block'),
                     ('reminder','跟进提醒','composer-reminder'),('labels','标签','action-label'),
                     ('copy','复制到…','action-copy'),('sender_policy','发件人','settings-gatekeeper'),
                     ('unsubscribe','退订','action-unsubscribe'),('delete_forever','永久删除','spark-layout-trash'),
                     ('export','导出 EML','action-save'),('copy_markdown','Markdown','file-markdown'),('print','打印 / PDF','action-print'))
        category=g.gtk_widget_get_parent(self.category_choice.button);retained=[self.widget(key) for key,title,icon in definitions]+[category,self.widget('reason')]
        for widget in retained:g.g_object_ref(widget);g.gtk_container_remove(g.gtk_widget_get_parent(widget),widget)
        g.clear(host);g.gtk_container_set_border_width(host,7);bind(self,'gtk','gtk_box_set_spacing',None,P,I)(host,5)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(host),b'reader-menu-content')
        for index,(key,title,icon) in enumerate(definitions):
            if index in (0,4,8):
                heading=g.gtk_label_new(('整理邮件' if index==0 else '邮件操作' if index==4 else '导出与打印').encode());g.gtk_label_set_xalign(heading,0)
                g.gtk_style_context_add_class(g.gtk_widget_get_style_context(heading),b'reader-menu-heading');g.gtk_box_pack_start(host,heading,0,1,0)
            if index%2==0 or index==10:
                line=g.gtk_box_new(0,5);bind(self,'gtk','gtk_box_set_homogeneous',None,P,I)(line,1);g.gtk_box_pack_start(host,line,0,1,0)
            button=self.widget(key);g.clear(button);content=g.gtk_box_new(0,9);g.gtk_container_add(button,content)
            image=g.image_file(ICONS/(icon+'.svg'),16);g.gtk_box_pack_start(content,image,0,0,0)
            label=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(content,label,1,1,0)
            check=g.gtk_label_new(b'');g.gtk_widget_set_size_request(check,12,-1);g.gtk_box_pack_start(content,check,0,0,0)
            context=g.gtk_widget_get_style_context(button);g.gtk_style_context_remove_class(context,b'popover-action');g.gtk_style_context_add_class(context,b'reader-menu-action')
            if key=='delete_forever':g.gtk_style_context_add_class(context,b'reader-menu-danger')
            g.gtk_widget_set_tooltip_text(button,title.encode());g.gtk_box_pack_start(line,button,1,1,0);g.g_object_unref(button)
            self.mail_menu_entries[key]={'button':button,'label':label,'check':check,'image':image}
        expander=bind(self,'gtk','gtk_expander_new',P,C.c_char_p)('分类与识别'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(expander),b'reader-menu-classification')
        box=g.gtk_box_new(1,10);g.gtk_container_add(expander,box)
        for widget in (category,self.widget('reason')):g.gtk_box_pack_start(box,widget,0,1,0);g.g_object_unref(widget)
        g.gtk_label_set_max_width_chars(self.widget('reason'),34);g.gtk_box_pack_start(host,expander,0,1,0)
        g.gtk_widget_show_all(host);state=g.surfaces.states.get(self.widget('mail_menu'))
        if state:state['width']=320
        g.connect(self.widget('more_actions'),'toggled',lambda *unused:self.sync_mail_menu(self.current or {}),group='reader-menu')

    # ==========================================
    # Function: Reflect current mail flags with short stable labels and an explicit selected mark.
    # Method: Reuse existing controls and expose reverse action semantics in tooltips rather than label clutter.
    # ==========================================
    def sync_mail_menu(self,message):
        entries=getattr(self,'mail_menu_entries',{})
        active={'aside':bool(message.get('aside')),'spam':bool(message.get('spam') or message.get('folder_special')=='spam'),
                'reminder':bool(message.get('reminder',0)>time.time()),'labels':bool(message.get('labels'))}
        tips={'aside':'取消暂存，放回收件箱' if active['aside'] else '暂存，稍后处理',
              'spam':'移回收件箱' if active['spam'] else '移到垃圾邮件','reminder':'修改或清除跟进提醒' if active['reminder'] else '设置跟进提醒'}
        for key,entry in entries.items():
            enabled=active.get(key,False);context=self.g.gtk_widget_get_style_context(entry['button'])
            (self.g.gtk_style_context_add_class if enabled else self.g.gtk_style_context_remove_class)(context,b'mail-menu-selected')
            self.g.label(entry['check'],'✓' if enabled else '')
            if key in tips:self.g.gtk_widget_set_tooltip_text(entry['button'],tips[key].encode())

    # ==========================================
    # Function: Make the concise Junk command reversible according to the actual current mail location.
    # Method: Read durable state at activation and dispatch through the existing local-first bulk service.
    # ==========================================
    def toggle_spam(self):
        if not self.selected or self.selected.startswith('job:'):return
        state=self.service.store.state(self.selected)
        self.perform_bulk('inbox' if state['spam'] else 'spam')
