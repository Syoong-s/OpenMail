"""Native folder navigation, message actions and desktop preferences."""
import ctypes as C
import os
from datetime import datetime
from email.utils import getaddresses
import time
from urllib.parse import urlparse
from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL
from .desktop_navigation import NavigationUI

# ==========================================
# Function: Connect personal mail organization to native GTK controls.
# Method: Keep persistent state in the service and widgets on the application thread.
# ==========================================
class OrganizationUI(NavigationUI):
    # ==========================================
    # Function: Bind the expanded mailbox controls and keyboard gestures.
    # Method: Use retained GTK signal callbacks and plain semantic action names.
    # ==========================================
    def bind_organization(self):
        self.header_callback=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_void_p)(self.list_header)
        self.g.gtk_list_box_set_header_func(self.widget('messages'),C.cast(self.header_callback,C.c_void_p),None,None)
        actions={'contacts':self.contacts_dialog,'folders_manage':self.manage_folders,'smart_add':self.smart_folder_dialog,
            'save_search':lambda:self.inbox_menu_action(self.smart_folder_dialog),'selection':self.toggle_selection,'move':self.move_dialog,
            'copy':lambda:self.move_dialog(copy=True),'trash':lambda:self.special_action('trash'),
            'spam':lambda:self.special_action('spam'),'snooze':lambda:self.date_action('snoozed_until'),
            'reminder':lambda:self.date_action('reminder'),'aside':lambda:self.organize_toggle('aside'),
            'done':lambda:self.organize_toggle('done'),'labels':self.labels_dialog,'sender_policy':self.sender_dialog,
            'delete_forever':self.delete_dialog,'preferences':self.preferences,'reply_all':lambda:self.reply_extended('all'),
            'forward':lambda:self.reply_extended('forward'),'copy_markdown':self.copy_markdown,
            'unsubscribe':self.unsubscribe,'print':self.print_mail,'rail_inbox':lambda:self.set_view('inbox'),
            'bulk_seen':lambda:self.perform_bulk('seen',True),'bulk_move':self.move_dialog,
            'bulk_archive':lambda:self.special_action('archive'),'bulk_trash':lambda:self.special_action('trash'),
            'bulk_done':lambda:self.perform_bulk('done',True),'toast_close':lambda:self.g.gtk_revealer_set_reveal_child(self.widget('toast_revealer'),0)}
        for name,callback in actions.items():
            self.g.connect(self.widget(name),'clicked',lambda *unused,fn=callback:self.run_action(fn))
        self.g.connect(self.window,'key-press-event',self.key_pressed,count=3,returns=True)
        icons={'compose':'document-edit-symbolic','nav_inbox':'mail-inbox-symbolic','nav_unread':'mail-unread-symbolic',
            'nav_priority':'starred-symbolic','nav_pinned':'view-pin-symbolic','nav_aside':'folder-symbolic',
            'nav_snoozed':'alarm-symbolic','nav_reminders':'preferences-system-notifications-symbolic',
            'nav_sent':'mail-send-symbolic','nav_drafts':'document-edit-symbolic','nav_archive':'mail-archive-symbolic',
            'nav_trash':'user-trash-symbolic','nav_spam':'mail-mark-junk-symbolic','nav_all':'view-list-symbolic',
            'nav_done':'emblem-ok-symbolic','nav_new_senders':'contact-new-symbolic','nav_blocked':'action-unavailable-symbolic',
            'sync':'view-refresh-symbolic','seen':'mail-mark-read-symbolic','pin':'starred-symbolic',
            'priority':'emblem-important-symbolic','archive':'mail-archive-symbolic','trash':'user-trash-symbolic',
            'reply':'mail-reply-sender-symbolic','reply_all':'mail-reply-all-symbolic','forward':'mail-forward-symbolic'}
        for name in __import__('maildesk.desktop',fromlist=['VIEWS']).VIEWS:self.g.gtk_button_set_alignment(self.widget('nav_'+name),0,0.5)
        icons.update({name:'spark-layout-'+icon for name,icon in {'rail_inbox': 'inbox', 'folder_toggle': 'folder', 'rail_pinned': 'pin', 'rail_sent': 'send', 'rail_trash': 'trash', 'rail_done': 'done', 'navigation_toggle': 'menu', 'contacts': 'contacts', 'preferences': 'preferences', 'settings': 'account', 'done': 'done', 'archive': 'archive', 'trash': 'trash', 'priority': 'priority', 'seen': 'seen', 'pin': 'pin', 'move': 'move', 'snooze': 'snooze', 'more_actions': 'more', 'search_toggle': 'search', 'compose': 'compose', 'sync': 'sync'}.items()})
        icons.update({'nav_aside':'spark-layout-folder','nav_snoozed':'spark-layout-snooze','nav_reminders':'composer-reminder','nav_drafts':'spark-layout-compose','nav_spam':'action-block','nav_all':'inbox-list','nav_new_senders':'settings-gatekeeper','nav_blocked':'action-block'})
        icons.update({'import':'nav-import','open_document':'settings-reading','nav_unread':'spark-layout-seen','nav_priority':'spark-layout-priority','nav_pinned':'spark-layout-pin','nav_sent':'spark-layout-send','nav_trash':'spark-layout-trash','nav_archive':'spark-layout-archive','nav_done':'spark-layout-done','nav_inbox':'spark-layout-inbox'})
        icons.update({'reader_close':'composer-close','search_close':'composer-close','delete_draft':'spark-layout-trash'})
        for name,icon in icons.items():
            from .desktop import ASSETS
            own=ASSETS/'icons'/(icon+'.svg')
            image=self.g.image_file(own,16 if name.startswith('rail_') or name in ('folder_toggle','navigation_toggle','contacts','preferences','settings') else 16) if own.exists() else self.g.gtk_image_new_from_icon_name(icon.encode(),1)
            self.g.gtk_button_set_image(self.widget(name),image)
            self.g.gtk_button_set_always_show_image(self.widget(name),1)
            if name in ('compose','sync','seen','pin','priority','archive','trash','done','move','snooze','more_actions','search_toggle','rail_inbox','folder_toggle','rail_pinned','rail_sent','rail_trash','rail_done','navigation_toggle','contacts','preferences','settings','reader_close','search_close','delete_draft'):
                self.g.gtk_button_set_label(self.widget(name),b'')
        for name in ('import','open_document'):
            self.g.gtk_button_set_alignment(self.widget(name),0,.5);self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.widget(name)),b'nav')
        self.initialize_navigation()
        from .native_choices import NativeChoice
        self.category_choice=NativeChoice(self.g,self.widget('message_category'),'邮件分类')
        from .ui_actions import icon_action
        for name,title,icon in [('selection','选择邮件','action-select'),('bulk_seen','标为已读','spark-layout-seen'),('bulk_move','移动到文件夹','spark-layout-move'),('bulk_archive','归档','spark-layout-archive'),('bulk_trash','移至废纸篓','spark-layout-trash'),('bulk_done','标为完成','spark-layout-done'),('edit_draft','编辑草稿','spark-layout-compose'),('cancel_job','取消计划','composer-close'),('reschedule_job','更改发送时间','composer-later'),('send_job_now','立即发送','composer-send'),('toast_close','关闭提示','composer-close')]:
            icon_action(self.g,self.widget(name),title,icon,14 if name.startswith('bulk_') else 18)

    # ==========================================
    # Function: Render hierarchy, unread badges, favorites and saved searches.
    # Method: Reuse unchanged native rows; rebuild exact account/path hierarchy only when metadata changes.
    # ==========================================
    def refresh_folders(self,rows=None,smart=None):
        if getattr(self,'folder_edit',None):self.folder_refresh_pending=True;return
        g=self.g;account=(g.gtk_combo_box_get_active_id(self.widget('account_filter')) or b'all').decode();rows=self.service.store.list_folders() if rows is None else rows;smart=self.service.store.smart_folders() if smart is None else smart
        accounts=sorted({row['account'] for row in rows}|set(self.service.accounts));colors=self.identity_colors.snapshot(accounts)['colors']
        signature=repr((rows,smart,account,self.folder_account,self.folder_path,colors,getattr(self,'motion',True),[(a.id,a.title,a.email) for a in self.service.accounts.values()]))
        if signature==getattr(self,'folder_tree_signature',None):self.refresh_pinned_navigation();return
        self.clear_navigation_hover();self.folder_buttons={};self.folder_row_widgets={};self.folder_account_headings={};self.folder_account_styles={};self.folder_account_sections={}
        for group in getattr(self,'folder_popup_groups',set()):g.disconnect(group)
        self.folder_popup_groups=set();g.disconnect('folders');g.clear(self.widget('folder_tree'));g.clear(self.widget('smart_tree'))
        for account_id in accounts:
            account_body=self.folder_account_section(account_id);subset=[r for r in rows if r['account']==account_id];nodes={}
            if not subset:
                hint=g.gtk_label_new('尚未同步文件夹'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(hint),b'muted');g.gtk_box_pack_start(account_body,hint,0,1,8)
            for row in subset:
                parts=row['folder'].split(row['delimiter']) if row['delimiter'] else [row['folder']];cursor=nodes
                for depth,part in enumerate(parts):
                    item=cursor.setdefault(part,{'row':None,'children':{},'delimiter':row['delimiter']});cursor=item['children']
                    if depth==len(parts)-1:item['row']=row
            # ==========================================
            # Function: Render delimiter-aware nodes with independent disclosure and hover controls.
            # Method: Represent namespace-only ancestors explicitly without inventing selectable folders.
            # ==========================================
            def render(parent,tree,prefix=()):
                for name,node in sorted(tree.items(),key=lambda item:item[0].casefold()):
                    path=node['delimiter'].join((*prefix,name)) if node['delimiter'] else name
                    row=node['row'] or {'account':account_id,'folder':path,'delimiter':node['delimiter'],'favorite':False,'special':'','color':'','subscribed':True,'selectable':False,'unread':0,'total':0,'virtual':True}
                    key=__import__('json').dumps([account_id,*prefix,name],ensure_ascii=False)
                    children=self.folder_tree_row(parent,row,bool(node['children']),key)
                    if node['children']:render(children,node['children'],(*prefix,name))
            render(account_body,nodes)
        for item in smart:
            if account!='all' and item['account'] and item['account']!=account:continue
            button=g.gtk_button_new_with_label(('⌕ '+item['name']).encode());label=g.gtk_bin_get_child(button);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,20)
            g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'folder-row');g.gtk_widget_set_tooltip_text(button,('条件：'+item['query']).encode())
            g.connect(button,'clicked',lambda *unused,row=item:self.open_smart(row),group='folders');g.gtk_box_pack_start(self.widget('smart_tree'),button,0,1,0)
        self.folder_tree_signature=signature;g.gtk_widget_show_all(self.widget('folder_tree'));g.gtk_widget_show_all(self.widget('smart_tree'));self.refresh_pinned_navigation()

    # ==========================================
    # Function: Open exactly one account's server folder.
    # Method: Clear unrelated filters and preserve full path rather than its display basename.
    # ==========================================
    def open_folder(self, account, path):
        if getattr(self,'local_loader',None):self.local_loader.cancel('read')
        self.pending_read_identity=''
        if not self.close_document():return
        self.focus_group=''
        self.close_navigation()
        self.view,self.folder_account,self.folder_path,self.smart_query='folder',account,path,''
        self.selected='';self.limit=100
        self.rendering=True
        self.g.text(self.widget('search'),'')
        self.g.gtk_combo_box_set_active_id(self.widget('category_filter'),b'all')
        self.rendering=False
        self.g.label(self.widget('view_title'),path.rsplit('/',1)[-1])
        self.refresh()

    # ==========================================
    # Function: Evaluate a saved smart-folder query against all cached folders.
    # Method: Keep its optional account scope separate from the visible account combo.
    # ==========================================
    def open_smart(self, item):
        if not self.close_document():return
        if getattr(self,'local_loader',None):self.local_loader.cancel('read')
        self.pending_read_identity=''
        self.focus_group=''
        self.close_navigation()
        self.view,self.folder_path,self.folder_account,self.smart_query='smart','',item['account'],item['query']
        self.selected='';self.limit=100
        self.rendering=True
        self.g.text(self.widget('search'),'');self.g.gtk_combo_box_set_active_id(self.widget('category_filter'),b'all')
        self.rendering=False
        self.g.label(self.widget('view_title'),item['name']);self.refresh()

    # ==========================================
    # Function: Create/edit/delete a persistent search folder through a native form.
    # Method: Expose the same query grammar used by ordinary mail search.
    # ==========================================
    def smart_folder_dialog(self):
        from .desktop_forms import Form
        items=self.service.store.smart_folders()
        fields=[('existing','智能文件夹','combo',[('new','新建')]+[(r['id'],r['name']) for r in items]),('name','名称','text',[]),('query','搜索条件','text',[]),('account','范围','combo',[('','全部账户')]+[(r['account'],LOCAL_LABEL if r['account']==LOCAL_ACCOUNT else r['account']) for r in self.service.store.list_folders() if r['folder'].upper()=='INBOX'])]
        form=Form(self,'智能文件夹',fields,640)
        form.value('existing','new');form.value('account','');form.value('query',self.g.text(self.widget('search')) or self.smart_query)
        # ==========================================
        # Function: Populate an existing saved query for editing.
        # Method: Select its stable identifier rather than matching user-provided names.
        # ==========================================
        def selected(*unused):
            item=next((r for r in items if r['id']==form.value('existing')),None)
            for key in ('name','query','account'):form.value(key,item[key] if item else '')
        self.g.connect(form.fields['existing'][0],'changed',selected,group=form.group)
        form.button('关闭',-6);form.button('删除定义',2);form.button('保存',1)
        self.g.label(form.note,'例如 has:attachment from:example.com is:unread after:2026-01-01；支持 - 排除。')
        self.g.gtk_widget_show_all(form.window)
        response=self.g.gtk_dialog_run(form.window)
        try:
            if response==1:self.service.store.save_smart_folder(form.value('name'),form.value('query'),form.value('account'),None if form.value('existing')=='new' else form.value('existing'))
            elif response==2 and form.value('existing')!='new':self.service.store.delete_smart_folder(form.value('existing'))
        finally:form.close()
        self.refresh_folders()

    # ==========================================
    # Function: Manage real server folders, subscriptions, favorites and special mappings.
    # Method: Display explicit paths/account and dispatch remote mutations in the worker.
    # ==========================================
    def manage_folders(self):
        from .desktop_folder_manager import manage_folders
        return manage_folders(self)

    # ==========================================
    # Function: Return exact stable IDs for current single or multi selection.
    # Method: Copy GtkListBox's selected row list and release its GLib allocation.
    # ==========================================
    def selected_ids(self):
        if self.contact_mode() and not self.selected:return []
        if not self.multi:return [self.selected] if self.selected and not self.selected.startswith('job:') else []
        rows=self.g.gtk_list_box_get_selected_rows(self.widget('messages'))
        cursor=rows;result=[]
        while cursor:
            identity=self.rows.get(cursor.contents.data,'')
            if identity and not identity.startswith('job:'):result.append(identity)
            cursor=cursor.contents.next
        self.g.g_list_free(rows)
        return result

    # ==========================================
    # Function: Toggle native multiple selection and its animated action bar.
    # Method: Leave ordinary row selection enabled and expose bulk controls explicitly.
    # ==========================================
    def toggle_selection(self):
        if self.contact_mode() and not self.multi:return
        self.multi=not self.multi
        self.g.gtk_list_box_set_selection_mode(self.widget('messages'),3 if self.multi else 1)
        self.g.gtk_revealer_set_reveal_child(self.widget('bulk_revealer'),self.multi)
        self.g.label(self.widget('selection'),'完成选择' if self.multi else '选择',button=True)
        self.message('点击邮件选择多封，Ctrl+A 全选当前列表' if self.multi else '已退出多选')

    # ==========================================
    # Function: Execute one action on the selected messages.
    # Method: Snapshot IDs before dispatch; refresh after confirmed completion.
    # ==========================================
    def perform_bulk(self, action, value=None):
        identities=self.selected_ids()
        if not identities:self.message('请先选择邮件');return
        self.g.gtk_popover_popdown(self.widget('mail_menu'))
        self.background(lambda:self.service.bulk_action(identities,action,value),lambda result:(self.refresh(),self.message(f'已处理 {len(result)} 封邮件')))

    # ==========================================
    # Function: Move selected messages to a configured system folder.
    # Method: Use the account-specific server folder mapping rather than local hiding.
    # ==========================================
    def special_action(self, special):
        if self.selected.startswith('job:'):
            if special=='trash':self.delete_selected_draft()
            return
        if not self.multi and self.selected and not self.selected.startswith('job:'):
            self.quick_action(self.selected,special)
        else:self.perform_bulk(special)

    # ==========================================
    # Function: Choose a folder for move/copy within the source account.
    # Method: Refuse mixed-account selections whose destination would be ambiguous.
    # ==========================================
    def move_dialog(self, copy=False):
        from .desktop_forms import Form
        ids=self.selected_ids()
        if not ids:return
        accounts={self.service.store.get(v)['account'] for v in ids}
        if len(accounts)!=1:raise ValueError('请按账户分别移动或复制邮件')
        rows=[r for r in self.service.store.list_folders(accounts.pop()) if r['selectable']]
        form=Form(self,'复制到' if copy else '移动到',[('folder','目标文件夹','combo',[(r['folder'],r['folder']) for r in rows])],560)
        if rows:form.value('folder',rows[0]['folder'])
        form.button('取消',-6);form.button('复制' if copy else '移动',1)
        self.g.label(form.note,'仅在同一账户内操作；“本地文件夹”的操作仅保存在此电脑。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);path=form.value('folder');form.close()
        if response==1:self.perform_bulk('copy' if copy else 'move',path)

    # ==========================================
    # Function: Schedule/clear a local snooze or follow-up reminder.
    # Method: Convert local user time to a bounded persisted Unix timestamp.
    # ==========================================
    def date_action(self, field):
        from .desktop_forms import Form
        form=Form(self,'稍后处理' if field=='snoozed_until' else '跟进提醒',[('when','本地时间','text',[])],540)
        form.value('when',datetime.fromtimestamp(time.time()+86400).strftime('%Y-%m-%d 09:00'))
        form.button('取消',-6);form.button('清除',2);form.button('设置',1)
        self.g.label(form.note,'例如 2026-10-20 09:00。到期会重新显示并通知；关闭应用后将在下次打开时处理。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);value=form.value('when');form.close()
        if response in (1,2):self.perform_bulk(field,0 if response==2 else datetime.fromisoformat(value).timestamp())

    # ==========================================
    # Function: Toggle temporary set-aside or done status.
    # Method: Derive a uniform selection action from the current message state.
    # ==========================================
    def organize_toggle(self, field):
        if field=='done' and not self.multi:self.quick_action(self.selected,'done')
        elif self.current and not self.selected.startswith('job:'):self.perform_bulk(field,not bool(self.current[field]))

    # ==========================================
    # Function: Add/edit local colored-searchable message tags.
    # Method: Normalize comma-delimited labels and persist them independently of IMAP folders.
    # ==========================================
    def labels_dialog(self):
        from .desktop_forms import Form
        if not self.current or self.selected.startswith('job:'):return
        form=Form(self,'邮件标签',[('labels','逗号分隔','text',[])],540);form.value('labels',', '.join(self.current['labels']))
        form.button('取消',-6);form.button('保存',1)
        self.g.label(form.note,'标签保存在本机，可用 label:标签名 搜索；服务器文件夹请使用“移动到”。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);value=form.value('labels');form.close()
        if response==1:self.perform_bulk('labels',value.replace('，',',').split(','))

    # ==========================================
    # Function: Accept, block or prioritize the selected sender.
    # Method: Persist a policy for this sender and account, applied to future syncs too.
    # ==========================================
    def sender_dialog(self):
        from .desktop_forms import Form
        if not self.current or self.selected.startswith('job:'):return
        form=Form(self,'发件人筛选',[('policy',self.current['sender'],'combo',[('accepted','接受'),('blocked','屏蔽'),('priority','优先'),('new','恢复为新发件人'),('domain:accepted','接受同域名发件人'),('domain:blocked','屏蔽同域名发件人'),('domain:priority','同域名发件人优先')])],620)
        form.value('policy',self.current['sender_policy']);form.button('取消',-6);form.button('保存',1)
        self.g.label(form.note,'屏蔽后从智能收件箱隐藏，可在“已屏蔽”中恢复。此规则保存在本机。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);value=form.value('policy');form.close()
        if response==1:self.perform_bulk('sender_policy',value)

    # ==========================================
    # Function: Confirm irreversible permanent deletion with concrete selection count.
    # Method: Require an explicit user click before UIDPLUS deletion is submitted.
    # ==========================================
    def delete_dialog(self):
        from .desktop_forms import Form
        count=len(self.selected_ids())
        if not count:return
        form=Form(self,'永久删除邮件',[],500);form.button('取消',-6);form.button('永久删除',1)
        self.g.label(form.note,f'将永久删除选中的 {count} 封邮件。服务器操作无法撤销。普通删除请使用废纸篓。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);form.close()
        if response==1:self.perform_bulk('delete')

    # ==========================================
    # Function: Reply to all recipients or forward with original content.
    # Method: Remove own addresses and retain RFC reference chains for replies.
    # ==========================================
    def reply_extended(self, mode, identity=None):
        if not identity and (not self.current or self.selected.startswith('job:')):return
        message=self.service.store.get(identity) if identity else self.current;parsed=message['parsed'];subject=message['subject']
        if mode=='forward':
            body='\n\n---------- 转发邮件 ----------\n发件人: '+parsed['sender']+'\n主题: '+subject+'\n\n'+parsed['body']
            import base64
            from .mime import attachment_content
            from email import policy
            from email.parser import BytesParser
            raw=self.service.store.get(message['id'],raw=True)['raw'];parts=list(BytesParser(policy=policy.default).parsebytes(raw).walk())
            attachments=[{'name':a['name'],'base64':base64.b64encode(attachment_content(parts[a['index']])).decode()} for a in parsed['attachments']]
            self.open_composer({'reply_source':message['id'],'account':message['account'],'subject':'Fwd: '+subject,'body':body,'attachments':attachments});return
        own={a.email.casefold() for a in self.service.accounts.values()}|{'demo@example.com'}
        targets=list(dict.fromkeys(address for _,address in getaddresses([parsed['headers'].get('reply-to',parsed['sender']),parsed['recipients'],parsed['headers'].get('cc','')]) if address and address.casefold() not in own))
        from .reply_options import reply_attachments
        attachments=reply_attachments(self,message)
        if attachments is None:return
        from .reply_history import from_message
        self.open_composer({'reply_history':from_message(message),'reply_source':message['id'],'attachments':attachments,'account':message['account'],'to':', '.join(targets),'subject':subject if subject.lower().startswith('re:') else 'Re: '+subject,'in_reply_to':parsed['message_id'],'references':' '.join(parsed['references']+[parsed['message_id']]),'body':''})

    # ==========================================
    # Function: Copy selected message as readable Markdown.
    # Method: Use the native desktop clipboard without shell commands.
    # ==========================================
    def copy_markdown(self):
        if not self.current or self.selected.startswith('job:'):return
        text='# '+self.current['subject']+'\n\n'+self.current['sender']+'\n\n'+self.current['body']
        clipboard=self.g.gtk_clipboard_get(self.g.gdk_atom_intern_static_string(b'CLIPBOARD'))
        self.g.gtk_clipboard_set_text(clipboard,text.encode(),-1);self.message('已复制 Markdown')

    # ==========================================
    # Function: Offer explicit unsubscribe through a message's advertised mechanism.
    # Method: Show mailto/HTTPS data and require a user click before leaving the client.
    # ==========================================
    def unsubscribe(self):
        from .desktop_forms import Form
        if not self.current or self.selected.startswith('job:'):return
        import re
        header=self.current['parsed']['headers'].get('list-unsubscribe','')
        urls=[v for v in re.findall(r'<([^<>]+)>',header) if urlparse(v).scheme.lower() in ('https','mailto')]
        if not urls:self.message('这封邮件没有可用的 List-Unsubscribe 链接');return
        form=Form(self,'退订',[('url','退订方式','combo',[(v,v) for v in urls])],700);form.value('url',urls[0])
        form.button('取消',-6);form.button('打开退订',1)
        self.g.label(form.note,'将打开发件人提供的退订页面；mailto 会创建一封待确认的草稿。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);url=form.value('url');form.close()
        if response==1:
            if url.startswith('mailto:'):
                from urllib.parse import unquote,parse_qs
                parsed=urlparse(url);query=parse_qs(parsed.query)
                self.open_composer({'account':self.current['account'],'to':unquote(parsed.path),'subject':query.get('subject',['Unsubscribe'])[0],'body':query.get('body',[''])[0]})
            else:
                import subprocess
                from .platform_native import open_uri
                open_uri(url)

    # ==========================================
    # Function: Print the current message using native Linux print/PDF dialogs.
    # Method: Delegate pagination and rendering to the GTK/Pango print adapter.
    # ==========================================
    def print_mail(self):
        if self.current and not self.selected.startswith('job:'):
            from .desktop_print import print_message
            print_message(self,self.current)

    # ==========================================
    # Function: Persist appearance, keyboard and outgoing-mail preferences.
    # Method: Use a native form with values stored in the private application database.
    # ==========================================
    def preferences(self):
        from .desktop_settings import settings_dialog
        self.close_navigation();settings_dialog(self,'general')

    # ==========================================
    # Function: Apply appearance to this process and respect reduced-motion preference.
    # Method: Update client colors and owned native frames while preserving reduced-motion revealer behavior.
    # ==========================================
    def apply_appearance(self):
        from .desktop_preferences import resolved_theme
        dark=resolved_theme(self)=='dark'
        context=self.g.gtk_widget_get_style_context(self.window)
        (self.g.gtk_style_context_add_class if dark else self.g.gtk_style_context_remove_class)(context,b'dark')
        (self.g.gtk_style_context_remove_class if dark else self.g.gtk_style_context_add_class)(context,b'light')
        for form in getattr(self,'active_forms',[]):
            if form.closed:continue
            context_form=self.g.gtk_widget_get_style_context(form.window)
            self.g.gtk_style_context_remove_class(context_form,b'light' if dark else b'dark')
            self.g.gtk_style_context_add_class(context_form,b'dark' if dark else b'light')
        for card in getattr(self,'conversation_cards',{}).values():
            if card.get('reader'):card['reader'].reload()
        self.motion=self.service.store.preference('motion','on')=='on'
        settings=self.g.gtk_widget_get_settings(self.window)
        self.g.g_object_set(settings,b'gtk-application-prefer-dark-theme',int(dark),None)
        self.g.g_object_set(settings,b'gtk-enable-animations',int(self.motion),None)
        from .windows_frame import refresh_window_frames
        refresh_window_frames(self)
        from .appearance_theme import apply as apply_palette
        apply_palette(self)
        self.resize_navigation()
        (self.g.gtk_style_context_remove_class if self.motion else self.g.gtk_style_context_add_class)(context,b'reduced-motion')
        for name in ('folder_revealer','bulk_revealer','toast_revealer'):self.g.gtk_revealer_set_transition_duration(self.widget(name),220 if self.motion else 0)
        self.layout_override=None;self.apply_layout()
        if self.document and hasattr(self.document.engine,'reload'):self.document.engine.reload()

    # ==========================================
    # Function: Route application shortcuts without hijacking text editing.
    # Method: Limit ordinary actions to explicit Control chords and Escape.
    # ==========================================
    def key_pressed(self, window, event, unused):
        key,state=C.c_uint(),C.c_uint()
        if not self.g.gdk_event_get_keyval(event,C.byref(key)):return False
        self.g.gdk_event_get_state(event,C.byref(state))
        control=bool(state.value&4);shift=bool(state.value&1);value=key.value
        if value==65307 and getattr(self,'folder_edit',None):self.cancel_folder_edit();return True
        if value==65307 and getattr(self,'navigation_panel',''):self.close_navigation();return True
        if value==65307 and self.g.gtk_revealer_get_reveal_child(self.widget('search_revealer')):self.show_search(False);return True
        if value==65307 and self.document:self.close_document(preserve_composer=True);return True
        if not self.service.store.preference('shortcuts_enabled',True):return False
        if control and value==44:self.preferences();return True
        if control and value in (102,70) and self.document:return True
        if value==65307 and self.multi:self.toggle_selection();return True
        if not control:return False
        if value in (110,78):self.open_composer();return True
        if value in (102,70):self.show_search(True);return True
        if value in (114,82):self.reply_extended('all') if shift else self.reply();return True
        if value in (97,65) and self.multi:self.g.gtk_list_box_select_all(self.widget('messages'));return True
        return False

    # ==========================================
    # Function: Show a notification settings sample using no real message data.
    # Method: Delegate to the bounded native notification owner.
    # ==========================================
    def preview_notification(self,style='cards',preview=True,duration=8):
        from .desktop_notifications import preview_notification
        preview_notification(self,style,preview,duration)

    # ==========================================
    # Function: Notify about newly synchronized mail and due personal reminders.
    # Method: Filter muted/blocked aliases before all notification styles and acknowledge silent deadlines durably.
    # ==========================================
    def check_notifications(self):
        store=self.service.store
        from .contact_policies import quiet_addresses,allows_notice,allows_message_notice
        from .address_book import own_addresses
        own=own_addresses(store)
        with store.db() as db:quiet=quiet_addresses(db)
        if store.preference('receipt_notifications','on')=='on':
            with store.db() as db:count=db.execute('SELECT count(*) FROM read_receipts').fetchone()[0]
            known_receipts=store.preference('notified_receipt_count',0)
            if count>known_receipts:
                with store.db() as db:recent=db.execute('SELECT recipient FROM read_receipts ORDER BY received DESC LIMIT ?',(count-known_receipts,)).fetchall()
                visible=sum(1 for row in recent if allows_notice(row['recipient'],quiet))
                if visible:self.notify('收到阅读回执',f'{visible} 位收件人返回了显示回执')
            if count!=known_receipts:store.set_preference('notified_receipt_count',count)
        with store.db() as db:
            rows=db.execute('SELECT m.id,m.subject,m.snoozed_until,m.reminder,coalesce(d.raw_from,m.sender) AS raw_from FROM messages m LEFT JOIN message_display d ON d.message=m.id WHERE m.remote_gone=0').fetchall()
        known={r['id'] for r in rows}
        if self.known_messages is not None:
            new={row['id'] for row in rows if row['id'] not in self.known_messages and allows_message_notice(store,row,quiet,own)}
            if store.preference('notify_priority_only',False):
                new={identity for identity in new if store.get(identity)['effective_priority']}
            if new:self.notify('收到新邮件',f'{len(new)} 封新邮件已同步')
        self.known_messages=known
        acknowledged=store.preference('notified_deadlines',{})
        changed=False
        now=time.time()
        for row in rows:
            for key in ('snoozed_until','reminder'):
                deadline=row[key];identity=row['id']+':'+key
                if deadline and deadline<=now and acknowledged.get(identity)!=deadline:
                    if allows_message_notice(store,row,quiet,own):self.notify('稍后邮件已回到收件箱' if key=='snoozed_until' else '邮件跟进提醒',row['subject'])
                    acknowledged[identity]=deadline;changed=True
        if changed:
            store.set_preference('notified_deadlines',dict(list(acknowledged.items())[-500:]))
            self.refresh()

    # ==========================================
    # Function: Deliver a native desktop notice when enabled.
    # Method: Publish a GNotification through the registered GtkApplication.
    # ==========================================
    def notify(self, title, text):
        if self.options.self_test or self.service.store.preference('notifications','on')!='on':return
        style=self.service.store.preference('notification_style','cards')
        if style=='cards':
            from .desktop_notifications import NotificationCards
            if not getattr(self,'notification_cards',None):self.notification_cards=NotificationCards(self)
            shown=self.notification_cards.show(title,text,self.service.store.preference('notification_preview',True),self.service.store.preference('notification_duration',8))
            if shown and self.service.store.preference('notification_sound',False):self.play_system_sound()
            self.message(title+' · '+text);return
        if os.name=='nt':
            tray=getattr(self,'windows_tray',None)
            if tray:tray.notify(title,text)
            self.message(title+' · '+text)
            if self.service.store.preference('notification_sound',False):self.play_system_sound()
            return
        notification=self.g.g_notification_new(title.encode())
        self.g.g_notification_set_body(notification,text.encode())
        self.g.g_application_send_notification(self.application,None,notification)
        self.g.g_object_unref(notification)
        self.message(title+' · '+text)
        if self.service.store.preference('notification_sound',False):self.play_system_sound()

    # ==========================================
    # Function: Browse recent correspondents and manage a personal address book.
    # Method: Merge observed addresses with saved contacts; compose only on explicit selection.
    # ==========================================
    def contacts_dialog(self):
        from .desktop_settings import settings_dialog
        settings_dialog(self,initial='contacts')

    # ==========================================
    # Function: Preview selected cached text attachments in native widgets.
    # Method: Decode only cached MIME bytes; other formats keep an explicit save action.
    # ==========================================
    def preview_attachment(self, identity, attachment):
        from .mime import attachment_content
        from email import policy
        from email.parser import BytesParser
        raw=self.service.store.get(identity,raw=True)['raw'];part=list(BytesParser(policy=policy.default).parsebytes(raw).walk())[attachment['index']]
        data=attachment_content(part)
        return self.show_document(attachment['name'],data,lambda:self.save_attachment(identity,attachment),attachment['type'],identity)

    # ==========================================
    # Function: Preserve a user's folder expansion across sync and navigation.
    # Method: Store a composite account/path key after native expander changes.
    # ==========================================
    def save_expansion(self,widget,key):
        expanded=self.service.store.preference('expanded_folders',{})
        expanded[key]=bool(self.g.gtk_expander_get_expanded(widget))
        self.service.store.set_preference('expanded_folders',expanded)

    # ==========================================
    # Function: Keep visible category/sender headers stable during GTK list updates.
    # Method: Use the documented list-header callback instead of transient manually attached labels.
    # ==========================================
    def list_header(self,row,before,unused):
        group=self.row_groups.get(row)
        if group and group!=self.row_groups.get(before) and self.g.gtk_list_box_row_get_header(row):return
        if group and group!=self.row_groups.get(before):
            identity=self.rows.get(row)
            section=getattr(self,'inbox_sections',{}).get(identity)
            if section:
                header=self.g.gtk_box_new(0,10)
                self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(header),b'section-label')
                unread=sum(not item['seen'] for item in section['items'])
                title=('▸ ' if section['collapsed'] else '▾ ')+section['title']+f"   {len(section['items'])}"+(f" · {unread} 未读" if unread else '')
                button=self.g.gtk_button_new_with_label(title.encode())
                self.g.gtk_button_set_alignment(button,0,0.5)
                self.g.connect(button,'clicked',lambda *unused,key=group:self.toggle_inbox_group(key),group='list-headers')
                self.g.gtk_box_pack_start(header,button,1,1,0)
                definition=self.inboxes.active()
                if definition['mode']=='smart' and section['action']!='none':
                    action=self.g.gtk_button_new_with_label({'seen':'全部已读','done':'全部完成','trash':'移到废纸篓'}[section['action']].encode())
                    self.g.connect(action,'clicked',lambda *unused,key=group:self.inbox_group_action(key),group='list-headers')
                    self.g.gtk_box_pack_start(header,action,0,0,0)
                if definition['mode']=='smart':
                    self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(header),b'card-heading')
                    settings=self.g.gtk_button_new_with_label('⋯'.encode())
                    self.g.connect(settings,'clicked',lambda *unused,key=group:self.inbox_card_dialog(key),group='list-headers')
                    self.g.gtk_box_pack_start(header,settings,0,0,0)
                if len(section['shown'])<len(section['items']):
                    more=self.g.gtk_button_new_with_label('全部'.encode())
                    self.g.connect(more,'clicked',lambda *unused,key=group:self.show_all_cards(key),group='list-headers')
                    self.g.gtk_box_pack_start(header,more,0,0,0)
            else:
                header=self.g.gtk_label_new(group.encode());self.g.gtk_label_set_xalign(header,0)
                self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(header),b'section-label')
            self.g.gtk_widget_show_all(header);self.g.gtk_list_box_row_set_header(row,header)
        else:self.g.gtk_list_box_row_set_header(row,None)
