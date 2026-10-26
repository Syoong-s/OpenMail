"""Native inbox view selection, creation, settings and group actions."""
from .inbox_views import InboxViews, MODES

# ==========================================
# Function: Connect durable inbox layouts to GTK controls.
# Method: Use ordinary native widgets and the existing mail service for mutations.
# ==========================================
class InboxUI:
    # ==========================================
    # Function: Initialize views and connect selection and configuration controls.
    # Method: Rebuild the native selector with stable stored identifiers.
    # ==========================================
    def initialize_inbox(self):
        self.inboxes=InboxViews(self.service.store)
        self.group_members={}
        self.g.connect(self.widget('inbox_mode'),'changed',self.inbox_changed)
        for name,fn in [('view_settings',lambda:self.inbox_menu_action(lambda:self.navigation_settings('inbox'))),('open_document',self.open_document)]:
            self.g.connect(self.widget(name),'clicked',lambda *unused,callback=fn:self.run_action(callback))
        self.g.connect(self.widget('focus_back'),'clicked',self.close_focus_group)
        from .ui_actions import icon_action
        icon_action(self.g,self.widget('focus_back'),'返回聚焦列表','action-back',16)
        self.g.gtk_box_pack_start(self.widget('view_toggle_content'),self.g.image_file(__import__('pathlib').Path(__file__).parent/'desktop_assets/icons/action-down.svg',14),0,0,0)
        self.g.gtk_widget_set_tooltip_text(self.widget('view_toggle'),'切换收件箱视图'.encode())
        for name,title,icon in [('view_settings','视图设置','settings-inbox'),('reclassify','重新归类','settings-classification'),('save_search','保存搜索','folder-favorite')]:
            icon_action(self.g,self.widget(name),title,icon,16)
        self.fill_inbox_modes()

    # ==========================================
    # Function: Populate the saved inbox selector without recursive change callbacks.
    # Method: Keep saved view identities in the hidden selector and show three illustrated mode tiles.
    # ==========================================
    def fill_inbox_modes(self):
        from pathlib import Path
        self.inbox_filling=True;g=self.g;active=self.inboxes.active()['id'];rows=self.inboxes.all()
        combo=self.widget('inbox_mode');g.gtk_combo_box_text_remove_all(combo)
        for row in rows:g.gtk_combo_box_text_append(combo,row['id'].encode(),row['name'].encode())
        g.gtk_combo_box_set_active_id(combo,active.encode());self.inbox_filling=False
        g.disconnect('inbox-view-choices');host=self.widget('inbox_view_choices');g.clear(host);self.inbox_view_buttons={}
        current=self.inboxes.active()
        from .desktop_general import bind,P,I
        bind(self,'gtk','gtk_orientable_set_orientation',None,P,I)(host,1)
        tile_row=None
        for index,(mode,title) in enumerate(MODES.items()):
            if index%2==0:
                tile_row=g.gtk_box_new(0,10);g.gtk_box_pack_start(host,tile_row,0,1,0)
            row=current if current['mode']==mode else next((item for item in rows if item['mode']==mode),None)
            button=g.gtk_button_new();g.gtk_widget_set_size_request(button,156,-1)
            content=g.gtk_box_new(1,7);g.gtk_container_add(button,content)
            g.gtk_box_pack_start(content,g.image_file(Path(__file__).parent/'desktop_assets/icons'/('inbox-preview-'+mode+'.svg'),150),0,1,0)
            label=g.gtk_label_new(title.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),b'inbox-mode-title');g.gtk_box_pack_start(content,label,0,1,0)
            caption=g.gtk_label_new(('Contact Mail' if mode=='conversations' else 'Classic Inbox' if mode=='classic' else 'Smart Inbox').encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(caption),b'inbox-mode-caption');g.gtk_box_pack_start(content,caption,0,1,0)
            g.gtk_widget_set_tooltip_text(button,((row['name']+' · ') if row else '').encode()+{'focused':'按重要程度和类别归组','smart':'先处理未读邮件','classic':'所有邮件按时间排列','conversations':'按联系人跨主题阅读和撰写邮件'}[mode].encode())
            context=g.gtk_widget_get_style_context(button);g.gtk_style_context_add_class(context,b'inbox-view-choice')
            if current['mode']==mode:g.gtk_style_context_add_class(context,b'active')
            g.connect(button,'clicked',lambda *unused,choice=mode:self.run_action(lambda:self.select_inbox_mode(choice)),group='inbox-view-choices');g.gtk_box_pack_start(tile_row,button,1,1,0);self.inbox_view_buttons[row['id'] if row else 'mode:'+mode]=button
        g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Select a real inbox mode while retaining existing view customization.
    # Method: Reuse the active or first saved matching definition; create only a missing mode on explicit click.
    # ==========================================
    def select_inbox_mode(self,mode):
        current=self.inboxes.active()
        target=current if current['mode']==mode else next((row for row in self.inboxes.all() if row['mode']==mode),None)
        if target is None:
            target=self.inboxes.save(self.inboxes.definition(mode));self.fill_inbox_modes()
        self.select_inbox_view(target['id'])

    # ==========================================
    # Function: Select a saved inbox view from a preview tile.
    # Method: Retain the hidden combo controller and close its native menu immediately.
    # ==========================================
    def select_inbox_view(self,identity):
        self.g.gtk_popover_popdown(self.widget('views_menu'));self.g.gtk_combo_box_set_active_id(self.widget('inbox_mode'),identity.encode())

    # ==========================================
    # Function: Dismiss inbox options before executing its chosen action.
    # Method: Keep modal forms and background commands outside the menu's focus grab.
    # ==========================================
    def inbox_menu_action(self,callback):
        self.g.gtk_popover_popdown(self.widget('views_menu'));return callback()

    # ==========================================
    # Function: Activate one saved inbox layout.
    # Method: Persist selection and reset pagination through the standard navigation action.
    # ==========================================
    def inbox_changed(self,*unused):
        if getattr(self,'inbox_filling',True):return
        identity=(self.g.gtk_combo_box_get_active_id(self.widget('inbox_mode')) or b'').decode()
        if identity:
            previous=self.inboxes.active()['id']
            if not self.close_document():
                self.inbox_filling=True;self.g.gtk_combo_box_set_active_id(self.widget('inbox_mode'),previous.encode());self.inbox_filling=False;return
            self.service.store.set_preference('active_inbox_view',identity)
            for key,button in getattr(self,'inbox_view_buttons',{}).items():
                context=self.g.gtk_widget_get_style_context(button)
                (self.g.gtk_style_context_add_class if key==identity else self.g.gtk_style_context_remove_class)(context,b'active')
            self.set_view('inbox')

    # ==========================================
    # Function: Create or edit an inbox view using native controls.
    # Method: Expose the mode, account scope and actual card settings in one durable form.
    # ==========================================
    def inbox_dialog(self, create=False):
        from .desktop_forms import Form
        value=self.inboxes.definition(create if isinstance(create,str) else 'focused') if create else self.inboxes.active()
        fields=[('name','视图名称','text',[]),('mode','收件箱视图','combo',list(MODES.items())),
                ('grouping','分组方式','combo',[('category','类别'),('sender','发件人'),('domain','域名'),('account','账户')]),
                ('limit','卡片显示邮件','combo',[('3','3 封'),('5','5 封'),('10','10 封'),('0','全部邮件')]),
                ('action','整组快捷操作','combo',[('none','无操作'),('seen','标为已读'),('done','完成'),('trash','移到废纸篓')]),
                ('disabled','隐藏分组（逗号分隔）','text',[])]
        account_choices=self.inbox_account_choices()
        fields+=self.inbox_account_fields(account_choices)
        form=Form(self,'增加收件箱视图' if create else '收件箱视图设置',fields,740)
        for key in form.fields:
            if key=='account_scope' or key.startswith('scope_account_'):continue
            current=value.get(key,'')
            form.value(key,','.join(current) if isinstance(current,list) else str(current))
        self.fill_inbox_account_fields(form,value['accounts'],account_choices)
        self.g.label(form.note,'聚焦列表：按重要程度和类别归组。未读卡片：分组展示未读，已读另列。简洁列表：按时间排列。\n分组标识：priority、personal、verification、notification、newsletter、pinned、seen。')
        form.button('取消',-6)
        if not create:
            form.button('删除此视图',2)
            form.button('恢复全部卡片',3)
        form.button('保存并使用',1)
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window)
        try:
            if response==1:
                for key in form.fields:
                    if key=='account_scope' or key.startswith('scope_account_'):continue
                    text=form.value(key)
                    value[key]=[v.strip() for v in text.split(',') if v.strip()] if key in ('accounts','disabled') else text
                value['accounts']=self.read_inbox_account_fields(form,account_choices)
                self.inboxes.save(value);self.service.store.set_preference('active_inbox_view',value['id'])
            elif response==2:self.inboxes.delete(value['id'])
            elif response==3:value['cards']={};value['disabled']=[];self.inboxes.save(value)
            else:return
            self.fill_inbox_modes();self.set_view('inbox')
        finally:form.close()

    # ==========================================
    # Function: Persist expansion state for a single group.
    # Method: Toggle the group key only in the active view, then rebuild its projection.
    # ==========================================
    def toggle_inbox_group(self,key):
        value=self.inboxes.active();collapsed=value['collapsed']
        if key in collapsed:collapsed.remove(key)
        else:collapsed.append(key)
        self.inboxes.save(value);self.refresh()

    # ==========================================
    # Function: Apply the configured action to every cached message in a card.
    # Method: Snapshot identities before asynchronous work and reuse service bulk semantics.
    # ==========================================
    def inbox_group_action(self,key):
        definition=self.inboxes.active()
        action=definition.get('cards',{}).get(key.split(':',1)[0],{}).get('action',definition['action'])
        account=(self.g.gtk_combo_box_get_active_id(self.widget('account_filter')) or b'all').decode()
        if action=='none':return
        # ==========================================
        # Function: Process a complete cached card without blocking native rendering.
        # Method: Resolve its full scoped membership before invoking service bulk operations.
        # ==========================================
        def operation():
            identities=self.inboxes.group_identities(key,definition,'' if account=='all' else account)
            return self.service.bulk_action(identities,action,True if action in ('seen','done') else None)
        self.background(operation,lambda result:(self.refresh(),self.message(f'已处理 {len(result)} 封邮件')))

    # ==========================================
    # Function: Open a local document inside a native application window.
    # Method: Read bounded local bytes and dispatch by format without launching a browser.
    # ==========================================
    def open_document(self):
        self.close_navigation()
        from pathlib import Path
        target=self.g.choose(self.window,'打开图片或文档')
        if target:
            path=Path(target)
            if path.stat().st_size>30*1024*1024:raise ValueError('文档超过 30 MiB')
            self.close_navigation()
            self.show_document(path.name,path.read_bytes(),origin_id=self.selected)

    # ==========================================
    # Function: Expand card item limits without changing the mail cache.
    # Method: Save the all-items choice in the current view definition.
    # ==========================================
    def show_all_cards(self,key=None):
        value=self.inboxes.active()
        if key:value.setdefault('cards',{}).setdefault(key.split(':',1)[0],{})['limit']=0
        else:value['limit']=0
        self.inboxes.save(value);self.refresh()

    # ==========================================
    # Function: Toggle search from the compact toolbar or explicitly reveal it for a shortcut.
    # Method: Clear hidden filters on close and restore keyboard focus to the message list.
    # ==========================================
    def show_search(self,opened=None):
        if opened is None:opened=not bool(self.g.gtk_revealer_get_reveal_child(self.widget('search_revealer')))
        self.g.gtk_revealer_set_reveal_child(self.widget('search_revealer'),opened)
        if opened:self.close_navigation();self.g.gtk_widget_grab_focus(self.widget('search'))
        else:
            self.g.text(self.widget('search'),'')
            self.g.gtk_widget_grab_focus(self.widget('messages'))

    # ==========================================
    # Function: Embed a real HTML renderer when its Linux runtime is present.
    # Method: Retain the plain-text model for accessibility and unavailable-runtime diagnostics.
    # ==========================================
    def initialize_reader(self):
        from .document_reader import HTMLReader
        self.html_reader=None;self.reader_runtime_error=''
        try:
            self.html_reader=HTMLReader(self,'html-reader')
        except RuntimeError as error:
            self.reader_runtime_error=str(error);return
        children=self.g.gtk_container_get_children(self.widget('body_host'))
        if children:
            fallback=children.contents.data
            self.g.gtk_widget_set_no_show_all(fallback,1);self.g.gtk_widget_hide(fallback)
        self.g.g_list_free(children)
        self.legacy_html_reader=self.html_reader
        self.g.gtk_box_pack_start(self.widget('body_host'),self.html_reader.widget,1,1,0);self.html_reader.attached()

    # ==========================================
    # Function: Offer the three inbox layouts as distinct native preview tiles.
    # Method: Choose a mode first, then configure the new persistent view.
    # ==========================================
    def choose_inbox_mode(self):
        from .desktop_forms import Form
        form=Form(self,'增加收件箱视图',[],800)
        choices=self.g.gtk_box_new(0,16);selected=[]
        descriptions={'focused':'━ ━ ━\n▸ 通知\n▸ 动态\n\n按重要程度归组',
                      'smart':'▣ 个人  3\n▣ 通知  5\n▣ 动态  2\n\n先处理未读邮件',
                      'classic':'━ ━ ━\n━ ━ ━\n━ ━ ━\n\n所有邮件按时间排列',
                      'conversations':'◉ 联系人\n  ▰ 收件\n    ▰ 已发送\n\n按联系人跨主题对话'}
        for mode,title in MODES.items():
            button=self.g.gtk_button_new_with_label((title+'\n\n'+descriptions[mode]).encode())
            self.g.gtk_widget_set_size_request(button,220,220)
            self.g.gtk_box_pack_start(choices,button,1,1,0)
            self.g.connect(button,'clicked',lambda *unused,key=mode:(selected.append(key),self.g.gtk_dialog_response(form.window,1)),group=form.group)
        self.g.gtk_box_pack_start(self.g.gtk_dialog_get_content_area(form.window),choices,1,1,20)
        self.g.label(form.note,'为同一个收件箱增加不同视图；邮件和文件夹保持原样。')
        form.button('取消',-6);self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);form.close()
        if response==1 and selected:self.inbox_dialog(selected[0])

    # ==========================================
    # Function: Configure one unread card without altering the other cards.
    # Method: Persist enabled, grouping, account scope, count and action overrides per category.
    # ==========================================
    def inbox_card_dialog(self,key):
        from .desktop_forms import Form
        from .inbox_views import TITLES
        value=self.inboxes.active();base=key.split(':',1)[0];card=value.get('cards',{}).get(base,{})
        fields=[('enabled','显示此卡片','combo',[('yes','显示'),('no','隐藏')]),
            ('grouping','卡片分组','combo',[('category','合并'),('sender','按发件人'),('domain','按域名'),('account','按账户')]),
            ('limit','显示邮件数量','combo',[('3','3 封'),('5','5 封'),('10','10 封'),('0','全部')]),
            ('action','整组快捷操作','combo',[('none','无操作'),('seen','标为已读'),('done','完成'),('trash','移到废纸篓')]),
            ]
        account_choices=self.inbox_account_choices();fields+=self.inbox_account_fields(account_choices)
        form=Form(self,TITLES.get(base,base)+' · 卡片设置',fields,700)
        form.value('enabled','yes' if card.get('enabled',True) else 'no')
        for field in ('grouping','limit','action'):form.value(field,str(card.get(field,value[field])))
        self.fill_inbox_account_fields(form,card.get('accounts',[]),account_choices)
        self.g.label(form.note,'设置仅适用于此类卡片。可选择适用账户；隐藏后可在视图设置中恢复。')
        form.button('取消',-6);form.button('保存',1);self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window)
        try:
            if response==1:
                card={'enabled':form.value('enabled')=='yes','grouping':form.value('grouping'),'limit':int(form.value('limit')),'action':form.value('action'),
                      'accounts':self.read_inbox_account_fields(form,account_choices)}
                value.setdefault('cards',{})[base]=card;self.inboxes.save(value);self.refresh()
        finally:form.close()

    # ==========================================
    # Function: Describe available mail accounts for native scope selection.
    # Method: Use display addresses while keeping provider identities inside the model.
    # ==========================================
    def inbox_account_choices(self):
        from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL
        if self.profile.demo:return [('demo','演示邮箱')]
        return [(account.id,account.email) for account in self.service.accounts.values()]+[(LOCAL_ACCOUNT,LOCAL_LABEL)]

    # ==========================================
    # Function: Build checkboxes for explicit multi-account view scopes.
    # Method: Offer all accounts, including future additions, or a chosen set.
    # ==========================================
    def inbox_account_fields(self,choices):
        return [('account_scope','适用账户','combo',[('all','所有账户'),('chosen','仅选中的账户')])]+[
            ('scope_account_'+str(index),label,'check',[]) for index,(_,label) in enumerate(choices)]

    # ==========================================
    # Function: Populate account scope widgets from persisted identities.
    # Method: Preserve an all-accounts scope as an explicit selector value.
    # ==========================================
    def fill_inbox_account_fields(self,form,selected,choices):
        form.value('account_scope','chosen' if selected else 'all')
        for index,(identity,_) in enumerate(choices):form.value('scope_account_'+str(index),not selected or identity in selected)

    # ==========================================
    # Function: Validate the account selection before saving a view or card.
    # Method: Require at least one checked account when an explicit scope is chosen.
    # ==========================================
    def read_inbox_account_fields(self,form,choices):
        if form.value('account_scope')=='all':return []
        selected=[identity for index,(identity,_) in enumerate(choices) if form.value('scope_account_'+str(index))]
        if not selected:raise ValueError('请选择至少一个账户')
        return selected

    # ==========================================
    # Function: Open one file in an independent right-hand reader column.
    # Method: Build the preview before replacing an older file, preserving mail and composer widgets.
    # ==========================================
    def show_document(self,name,data,on_save=None,media_type='',origin_id='',prepared=None):
        from .file_workspace import DocumentWorkspace
        from pathlib import Path
        self.document_request_serial=getattr(self,'document_request_serial',0)+1;serial=self.document_request_serial
        if prepared is None and (Path(name).suffix.lower() in ('.doc','.rtf') or media_type.split(';')[0] in ('application/msword','application/rtf','text/rtf')):
            from .file_previews import preview
            self.message('正在读取 Word 文档…')
            self.background(lambda:preview(name,data,media_type),lambda model:self.show_document(name,data,on_save,media_type,origin_id,model) if not self.closing and serial==self.document_request_serial else None,lambda error:self.message(str(error)) if not self.closing and serial==self.document_request_serial else None);return None
        workspace=self.document if isinstance(self.document,DocumentWorkspace) else DocumentWorkspace(self)
        try:workspace.open(name,data,on_save,media_type,origin_id,prepared)
        except Exception:
            if workspace is not self.document:workspace.close(False)
            raise
        if getattr(self,'thread_window',None):self.close_thread_window(preserve_composer=True)
        if workspace is not self.document:
            if self.document:self.document.close(False)
            self.document=workspace;self.g.gtk_box_pack_start(self.widget('document_host'),workspace.root,1,1,0)
        self.g.gtk_widget_show_all(workspace.root)
        if getattr(self,'workspace_geometry',None):self.workspace_geometry.show_preview()
        else:self.g.gtk_widget_show(self.widget('document_host'))
        if hasattr(self,'apply_layout'):self.apply_layout()
        return workspace

    # ==========================================
    # Function: Close a file independently or retain the existing guarded navigation contract.
    # Method: Explicit file dismissal preserves the composer; mailbox navigation still saves/refuses busy drafts.
    # ==========================================
    def close_document(self,preserve_composer=False):
        if not preserve_composer and getattr(self,'selected_chat','') and not self.leave_chat():return False
        if not preserve_composer and self.composer and self.composer.embedded and not getattr(self.composer,'detached',False):
            if self.composer.busy:return False
            self.composer.on_delete()
            if self.composer and not self.composer.closed:return False
        self.document_request_serial=getattr(self,'document_request_serial',0)+1
        if self.document:self.document.close()
        return True

    # ==========================================
    # Function: Apply sender fill and independent account outline to one avatar.
    # Method: Use a widget-local validated CSS provider, retaining no global per-sender rules.
    # ==========================================
    def apply_avatar(self,widget,sender,account,state=None):
        value=self.identity_colors.style(sender,account,state)
        header=widget==self.widget('sender_avatar')
        provider=self.g.style(widget,'label { background-color: '+value['background']+'; color: #ffffff; border: 2px solid '+value['border']+'; }',getattr(self,'header_avatar_provider',None) if header else None)
        if header:self.header_avatar_provider=provider
        self.g.gtk_widget_set_tooltip_text(widget,(sender+' · '+account).encode())
        return provider

    # ==========================================
    # Function: Choose a persistent outline color for each configured mail account.
    # Method: Present readable account labels and a fixed validated color palette.
    # ==========================================
    def account_colors_dialog(self):
        from .desktop_forms import Form
        from .identity_colors import ACCOUNT_PALETTE
        choices=self.inbox_account_choices()
        names=('蓝色','橙色','绿色','紫色','玫红','青色','金色','灰蓝')
        colors=list(zip(ACCOUNT_PALETTE,names))
        existing=self.service.store.preference('account_colors',{})
        colors += [(color,'自定义 '+color) for color in dict.fromkeys(existing.values()) if color not in ACCOUNT_PALETTE]
        form=Form(self,'账户配色',[('account','邮箱账户','combo',choices),('color','头像外圈','combo',colors)],580)
        # ==========================================
        # Function: Display the selected account's current outline color.
        # Method: Resolve stable assignments without altering sender backgrounds.
        # ==========================================
        def changed(*unused):
            account=form.value('account')
            if account:form.value('color',self.identity_colors.account_color(account))
        self.g.connect(form.fields['account'][0],'changed',changed,group=form.group)
        form.value('account',choices[0][0]);changed()
        self.g.label(form.note,'头像底色区分发件人，外圈颜色区分收到邮件的账户。颜色保存在本机。')
        form.button('取消',-6);form.button('保存',1);self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window)
        try:
            if response==1:self.identity_colors.set_account_color(form.value('account'),form.value('color'));self.refresh()
        finally:form.close()
