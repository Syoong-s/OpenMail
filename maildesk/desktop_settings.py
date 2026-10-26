"""Native local settings navigation and account lifecycle, inspired by Spark routes."""
import ctypes as C
from xml.sax.saxutils import escape

from .desktop_forms import Form, form_xml, account_settings, ask_credential
from .local_mail import LOCAL_ACCOUNT
from .inbox_views import MODES as INBOX_MODES

PAGES=[('general','通用'),('accounts','账号'),('contacts','通讯录'),('composer','编辑器'),('templates','模板'),
       ('inbox','收件箱'),('filters','过滤器'),('conversations','对话列表'),('notifications','通知'),('scheduling','计划'),('appearance','外观'),
       ('reading','邮件阅读'),('shortcuts','快捷键'),('privacy','隐私'),('storage','储存空间'),('about','关于')]
DEFAULTS={'theme':'dark','motion':'on','grouping':'smart','notifications':'on','undo':'10',
    'sync_interval':'60','reader_font_size':'14','adapt_dark_html':True,'avatars_mode':'everywhere','mark_read_on_open':True,
    'account_colors_enabled':True,'notify_priority_only':False,'shortcuts_enabled':True,
    'remember_passwords':True,'signature':'','signature_account':'default','default_account':'',
    'inbox_mode_setting':'focused','priority_enabled':True,'priority_limit':'5','gatekeeper_mode':'off',
    'recognition_enabled':True,'group_notification':'category','group_newsletter':'category','group_verification':'category',
    'reply_window_size':'compact','composer_new_window':False,'done_after_reply':False,
    'reply_attachments':'never','suggest_recipients':True,'request_receipt':False,'receipt_notifications':'on',
    'composer_tagline':False,'schedule_morning':'09:00','schedule_evening':'20:00','schedule_today_hours':'2',
    'followup_days':'3','main_action_policy':'close','main_action_unpin':True,'minimize_old_emails':False,
    'thread_new_window':False,'load_remote_images':False,'autodownload_attachments':False,
    'close_to_tray':False,'launch_at_startup':False,'play_send_sound':False,'notification_sound':False,
    'layout_mode':'splitView','mail_list_preview':'expanded','email_preview_lines':'1'}
PAGE_FIELDS={'appearance':['theme','layout_mode','mail_list_preview','email_preview_lines','avatars_mode','account_colors_enabled','motion'],
    'general':['main_action_policy','main_action_unpin','minimize_old_emails','undo','load_remote_images','autodownload_attachments','thread_new_window','launch_at_startup','close_to_tray','sync_interval','play_send_sound','notification_sound'], 'inbox':['grouping','inbox_mode_setting','priority_enabled','priority_limit',
        'gatekeeper_mode','recognition_enabled','group_notification','group_newsletter','group_verification'],
    'reading':['mark_read_on_open','adapt_dark_html','reader_font_size'],
    'composer':['reply_window_size','default_account','composer_new_window','done_after_reply','reply_attachments',
        'suggest_recipients','request_receipt','receipt_notifications','composer_tagline','signature_account','signature'],
    'scheduling':['schedule_morning','schedule_evening','schedule_today_hours','followup_days'],
    'notifications':['notifications','notification_style','notification_preview','notification_duration','toast_duration','notify_priority_only'],'shortcuts':['shortcuts_enabled'],
    'privacy':['remember_passwords'],'storage':['storage_cache','storage_data','storage_downloads']}

# ==========================================
# Function: Build left-navigation settings with independently scrollable native pages.
# Method: Reuse typed Form fields inside a GtkStack/GtkStackSidebar and sticky dialog actions.
# ==========================================
def settings_xml(fields):
    from .settings_appearance import settings_xml as layout
    return layout(fields,PAGES,PAGE_FIELDS)

# ==========================================
# Function: Resolve a default or account-specific signature for the composer.
# Method: Fall back to the existing global signature when no override is saved.
# ==========================================
def signature_for(store, account):
    return store.preference('account_signatures',{}).get(account,store.preference('signature',''))

# ==========================================
# Function: Expose all supported local settings and mailbox connections in one dialog.
# Method: Persist actual preferences and route account actions to existing native forms.
# ==========================================
def settings_dialog(app, initial='general', contact=None):
    existing=getattr(app,'settings_form',None)
    if existing and not existing.closed:
        app.g.gtk_stack_set_visible_child_name(app.g.object(existing.builder,'settings_stack'),initial.encode())
        if contact:existing.contacts_page.open_person(contact)
        app.g.gtk_window_present(existing.window);return
    store,g=app.service.store,app.g
    choices=[(a.id,a.title or a.email) for a in app.service.accounts.values()]
    if app.profile.demo:choices=[('demo','demo@example.com')]
    fields=[('theme','外观','combo',[('dark','深色'),('light','浅色'),('system','跟随系统')]),
        ('motion','动态效果','combo',[('on','启用'),('off','减少动态')]),
        ('grouping','邮件分组','combo',[('smart','智能分类'),('sender','发件人'),('domain','域名'),('none','按时间')]),
        ('inbox_mode_setting','默认收件箱视图','combo',list(INBOX_MODES.items())),
        ('notifications','桌面通知','combo',[('on','启用'),('off','关闭')]),
        ('notify_priority_only','只通知优先邮件','check',[]),('undo','撤销发送窗口','combo',[(str(v),str(v)+' 秒') for v in (0,5,10,15,20,30,60)]),
        ('sync_interval','同步间隔','combo',[(str(v),title) for v,title in [(30,'30 秒'),(60,'1 分钟'),(300,'5 分钟'),(900,'15 分钟')]]),
        ('default_account','默认发件账号','combo',[('','上次使用')]+choices),
        ('account_colors_enabled','账户外圈颜色','check',[]),
        ('avatars_mode','发件人头像','combo',[('everywhere','列表和阅读区'),('reader','仅阅读区'),('list','仅邮件列表'),('none','隐藏')]),
        ('mark_read_on_open','打开邮件时自动标为已读','check',[]),('adapt_dark_html','深色文字适配','check',[]),('reader_font_size','阅读字号','combo',[(str(v),str(v)+' px') for v in (14,16,18,20)]),
        ('signature_account','签名适用账号','combo',[('default','默认签名')]+choices),('signature','签名','body',[]),
        ('shortcuts_enabled','启用应用快捷键','check',[]),('remember_passwords','默认记住成功登录','check',[]),
        ('priority_enabled','优先邮件置于顶端','check',[]),('priority_limit','收件箱内优先邮件','combo',[(str(v),'全部邮件' if not v else str(v)+' 封') for v in (3,5,10,0)]),
        ('gatekeeper_mode','信使 · 新发件人','combo',[('explicit','进入收件箱前筛选'),('inThread','在邮件内筛选'),('off','不审阅（接受全部）')]),
        ('recognition_enabled','自动邮件识别','check',[]),
        ('group_notification','通知邮件组别','combo',[(v,t) for v,t in [('category','按类别'),('sender','按发件人'),('domain','按域名'),('account','按账号'),('none','不分组')]]),
        ('group_verification','验证码邮件组别','combo',[(v,t) for v,t in [('category','按类别'),('sender','按发件人'),('domain','按域名'),('account','按账号'),('none','不分组')]]),
        ('group_newsletter','动态 / 订阅组别','combo',[(v,t) for v,t in [('category','按类别'),('sender','按发件人'),('domain','按域名'),('account','按账号'),('none','不分组')]]),
        ('reply_window_size','回复或转发窗口','combo',[('compact','紧凑视图'),('full','全屏')]),
        ('composer_new_window','始终在新窗口打开编辑器','check',[]),('done_after_reply','回复或转发后标为完成','check',[]),
        ('reply_attachments','回复包含附件','combo',[('never','从不包含'),('always','总是包含'),('ask','每次询问')]),
        ('suggest_recipients','自动建议收件人','check',[]),('request_receipt','阅读状态 · 请求邮件回执','check',[]),
        ('receipt_notifications','收到阅读回执时通知','combo',[('on','所有收件人'),('off','无')]),('composer_tagline','显示 Sent with TeleMail','check',[]),
        ('schedule_morning','上午预设时间','text',[]),('schedule_evening','晚上预设时间','text',[]),
        ('schedule_today_hours','今天稍后','combo',[(str(v),'+'+str(v)+' 小时') for v in (1,2,3,4)]),
        ('followup_days','未回复提醒默认间隔','combo',[(str(v),str(v)+' 天') for v in (1,2,3,7)])]
    fields += [('notification_style','通知样式','combo',[('cards','TeleMail 卡片'),('system','系统通知')]),('notification_preview','显示通知内容预览','check',[]),('notification_duration','卡片停留时间（秒）','range',(3,60,1)),('toast_duration','底部操作通知停留时间（秒）','range',(1,60,1))]
    fields += [('main_action_policy','归档或删除后','combo',[('next','打开下一封邮件'),('previous','打开上一封邮件'),('close','返回邮件列表')]),
        ('main_action_unpin','归档时从置顶列表移除','check',[]),('minimize_old_emails','折叠历史邮件','check',[]),
        ('load_remote_images','加载远程图片','check',[]),('autodownload_attachments','自动缓存附件','check',[]),
        ('thread_new_window','全屏布局在新窗口打开邮件串','check',[]),('launch_at_startup','开机启动','check',[]),
        ('close_to_tray','关闭窗口后留在系统托盘','check',[]),('play_send_sound','邮件发送成功时播放系统声音','check',[]),
        ('notification_sound','收到通知时播放系统声音','check',[]),
        ('layout_mode','布局','combo',[('fullScreen','全屏视图'),('splitView','分屏视图'),('switchInsideInbox','在收件箱中切换')]),
        ('mail_list_preview','全屏列表预览','combo',[('compact','紧凑'),('expanded','展开')]),
        ('email_preview_lines','分屏正文预览','combo',[(str(v),'隐藏' if not v else str(v)+' 行') for v in range(4)])]
    from .scheduling import PRESETS
    fields += [('preset_'+key,label,'check',[]) for key,label in PRESETS]
    PAGE_FIELDS['scheduling']=['schedule_morning','schedule_evening','schedule_today_hours','followup_days']+['preset_'+key for key,_ in PRESETS]
    from .appearance_settings import FIELDS as APPEARANCE_FIELDS
    fields+=APPEARANCE_FIELDS
    from .storage_settings import FIELDS as STORAGE_FIELDS
    fields+=STORAGE_FIELDS
    PAGE_FIELDS['storage']=[field[0] for field in STORAGE_FIELDS]
    fields=[(key,title,'switch' if kind=='check' else kind,options) for key,title,kind,options in fields]
    PAGE_FIELDS['appearance']=['theme']+[item[0] for item in APPEARANCE_FIELDS]+['layout_mode','mail_list_preview','email_preview_lines','avatars_mode','account_colors_enabled','motion']
    form=Form(app,'TeleMail · 设置',fields,1050,layout=settings_xml(fields))
    from .ui_actions import icon_action
    app.settings_form=form;form.page_buttons={};form.account_buttons={}
    from .settings_conversations import ConversationFolderSettings
    form.conversations_page=ConversationFolderSettings(app,form)
    from .storage_settings import bind_storage_settings,storage_plan,retention_values
    bind_storage_settings(app,form)
    for key,default in DEFAULTS.items():
        pref={'undo':'undo_send_seconds','inbox_mode_setting':'unused_inbox_mode'}.get(key,key)
        value=app.inboxes.active()['mode'] if key=='inbox_mode_setting' else store.preference(pref,default)
        form.value(key,value)
    enabled=store.preference('schedule_enabled',[key for key,_ in PRESETS])
    for key,_ in PRESETS:form.value('preset_'+key,key in enabled)
    form.value('notification_style',store.preference('notification_style','cards'));form.value('notification_preview',store.preference('notification_preview',True));form.value('notification_duration',store.preference('notification_duration',8));form.value('toast_duration',store.preference('toast_duration',7))
    from .appearance_settings import AppearanceSettings
    appearance_editor=AppearanceSettings(app,form)
    from .desktop_install import set_autostart,default_mail_client
    from pathlib import Path
    import os
    startup_path=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'autostart/org.telemail.Desktop.desktop'
    form.value('launch_at_startup',startup_path.is_file())
    startup_before=startup_path.is_file()
    if os.name=='nt':
        from .windows_integration import startup_enabled
        startup_before=startup_enabled()
        form.value('launch_at_startup',startup_before)
    tray_available=app.tray_available()
    if not tray_available:
        form.value('close_to_tray',False);g.gtk_widget_set_sensitive(form.fields['close_to_tray'][0],0)
    stack=g.object(form.builder,'settings_stack')
    # ==========================================
    # Function: Keep original line-icon navigation synchronized with the active settings page.
    # Method: Route section buttons to GtkStack and apply selected-state color to one button.
    # ==========================================
    def nav_changed(*unused):
        active=(g.gtk_stack_get_visible_child_name(stack) or b'').decode()
        contacts=getattr(form,'contacts_page',None)
        if active!='contacts' and contacts:contacts.page_hidden()
        child=g.gtk_stack_get_visible_child(stack)
        if child:g.gtk_widget_queue_resize(child);g.gtk_widget_queue_draw(child)
        g.gtk_widget_queue_resize(stack);g.gtk_widget_queue_draw(stack)
        for key,_ in PAGES:
            context=g.gtk_widget_get_style_context(g.object(form.builder,'settings_nav_'+key))
            (g.gtk_style_context_add_class if active==key else g.gtk_style_context_remove_class)(context,b'active')
    for key,_ in PAGES:
        g.connect(g.object(form.builder,'settings_nav_'+key),'clicked',lambda *unused,page=key:g.gtk_stack_set_visible_child_name(stack,page.encode()),group=form.group)
    g.connect(stack,'notify::visible-child-name',nav_changed,count=3,group=form.group)
    g.connect(stack,'size-allocate',lambda *unused:g.gtk_widget_queue_draw(stack),count=3,group=form.group)
    nav_changed()
    signatures=dict(store.preference('account_signatures',{}));current_signature=['default']
    g.label(form.note,'设置仅保存在此客户端。账号、通讯录开关和过滤器操作立即生效；其他选项点击“保存”后生效。')
    form.button('取消',-6)
    save=form.button('保存',1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(save),b'suggested-action')

    # ==========================================
    # Function: Add a settings action with dialog-owned signal lifetime.
    # Method: Keep callbacks attached to the parent form and catch native boundary errors.
    # ==========================================
    def action(page,key,title,callback):
        button=g.gtk_button_new();form.page_buttons[key]=button
        from .settings_appearance import ICONS
        content=g.gtk_box_new(0,10);g.gtk_container_add(button,content);g.gtk_box_pack_start(content,g.image_file(ICONS/('settings-'+page+'.svg'),16),0,0,0)
        label=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(content,label,1,1,0);g.gtk_box_pack_start(content,g.image_file(ICONS/'action-next.svg',12),0,0,0);g.gtk_widget_set_tooltip_text(button,title.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'settings-link')
        g.connect(button,'clicked',lambda *unused:app.run_action(callback),group=form.group)
        g.gtk_box_pack_start(g.object(form.builder,'page_'+page),button,0,1,0)
        return button

    # ==========================================
    # Function: Rebuild the account cards without changing downloaded messages.
    # Method: Show connection/persistence states and explicit per-account operations.
    # ==========================================
    def render_accounts():
        if form.closed:return
        host=g.object(form.builder,'page_accounts');g.disconnect('settings-accounts');g.clear(host)
        form.account_buttons={};form.account_labels={}
        configured=list(app.profile.accounts()) if not app.profile.demo else []
        if not configured:
            text='演示邮箱 · 真实账号请在普通窗口管理' if app.profile.demo else '尚未添加邮箱。添加后将在这里显示连接和登录状态。'
            g.gtk_box_pack_start(host,g.gtk_label_new(text.encode()),0,1,4)
        for account in configured:
            paused=store.preference('paused_accounts',[]);status=app.service.status['accounts'].get(account.id,{})
            state='同步已暂停' if account.id in paused else '已连接' if status.get('ok') else '同步失败' if status else '尚未连接'
            card=g.gtk_box_new(1,7);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(card),b'account-card')
            caption=(account.title or account.email)+'\n'+account.email+' · '+state+' · '+app.profile.credential_state(account)
            if account.id in app.profile.credential_errors:caption+='\n'+app.profile.credential_errors[account.id]
            label=g.gtk_label_new(caption.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_line_wrap(label,1)
            form.account_labels[account.id]=label
            account_header=g.gtk_box_new(0,12);g.gtk_box_pack_start(account_header,label,1,1,0);g.gtk_box_pack_start(account_header,app.account_color_button(account.id,group='settings-accounts'),0,0,0);g.gtk_box_pack_start(card,account_header,0,1,3);buttons=g.gtk_box_new(0,5)
            operations=[('edit','编辑服务器',lambda a=account:edit_account(a.id)),
                ('login','更新登录',lambda a=account:login(a)),('pause','恢复同步' if account.id in paused else '暂停同步',lambda a=account:pause(a)),
                ('forget','忘记凭据',lambda a=account:forget(a)),('remove','移除账号',lambda a=account:remove(a))]
            for key,title,callback in operations:
                button=g.gtk_button_new_with_label(title.encode());form.account_buttons[(account.id,key)]=button
                icon_action(g,button,title,{'edit':'folder-edit','login':'settings-privacy','pause':'spark-layout-sync','forget':'settings-privacy','remove':'spark-layout-trash'}[key])
                g.connect(button,'clicked',lambda *unused,fn=callback:app.run_action(fn),group='settings-accounts')
                g.gtk_box_pack_start(buttons,button,0,1,0)
            g.gtk_box_pack_start(card,buttons,0,1,0);g.gtk_box_pack_start(host,card,0,1,6)
        action('accounts','add_account','＋ 添加邮箱账号',lambda:edit_account('new'))
        g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Refresh connection and saved-login state while the account page is open.
    # Method: Update existing labels on the GTK thread without rebuilding card buttons.
    # ==========================================
    def refresh_status(unused):
        if form.closed:return 0
        paused=store.preference('paused_accounts',[])
        try:configured=app.profile.accounts()
        except (ValueError,OSError):
            g.label(form.note,'账号配置暂时无法读取，请重新打开设置');return 1
        for account in configured:
            label=form.account_labels.get(account.id)
            if not label:continue
            status=app.service.status['accounts'].get(account.id,{})
            state='同步已暂停' if account.id in paused else '已连接' if status.get('ok') else '同步失败' if status else '正在连接'
            caption=(account.title or account.email)+'\n'+account.email+' · '+state+' · '+app.profile.credential_state(account)
            if account.id in app.profile.credential_errors:caption+='\n'+app.profile.credential_errors[account.id]
            g.label(label,caption)
        return 1

    # ==========================================
    # Function: Add or edit a mailbox from the account settings page.
    # Method: Reuse validated masked forms then rebuild the cards.
    # ==========================================
    def edit_account(identity):
        account_settings(app,identity);render_accounts()

    # ==========================================
    # Function: Replace one saved login without exposing its existing value.
    # Method: Always present a masked entry and stage replacement until provider success.
    # ==========================================
    def login(account):
        from .desktop_signin import account_signin
        account_signin(app,account);render_accounts()

    # ==========================================
    # Function: Pause or resume automatic synchronization for exactly one account.
    # Method: Persist a local polling exclusion without deleting connection settings.
    # ==========================================
    def pause(account):
        paused=set(store.preference('paused_accounts',[]))
        paused.discard(account.id) if account.id in paused else paused.add(account.id)
        store.set_preference('paused_accounts',sorted(paused));app.request_sync();render_accounts()

    # ==========================================
    # Function: Forget a saved login only after an explicit local action.
    # Method: Clear the vault/session and refresh credential status while retaining mail.
    # ==========================================
    def forget(account):
        app.profile.forget_credential(account);render_accounts();app.message('已忘记本机凭据；下载的邮件保留')

    # ==========================================
    # Function: Remove the selected account connection after a concrete confirmation.
    # Method: Preserve downloaded mail and stop pending delivery through the absent account.
    # ==========================================
    def remove(account):
        confirm=Form(app,'移除账号',[],520);confirm.button('取消',-6);confirm.button('移除账号',1)
        g.label(confirm.note,'移除 '+account.email+' 的连接和保存凭据。已下载邮件和本地草稿保留。')
        g.gtk_widget_show_all(confirm.window);response=g.gtk_dialog_run(confirm.window);confirm.close()
        if response==1:
            app.apply_accounts(app.profile.remove_account(account))
            store.set_preference('paused_accounts',[value for value in store.preference('paused_accounts',[]) if value!=account.id])
            if store.preference('default_account','')==account.id:store.set_preference('default_account','')
            render_accounts()

    # ==========================================
    # Function: Keep unsaved per-account signature edits while switching the selector.
    # Method: Stage values in dialog memory and commit only on Save.
    # ==========================================
    def signature_changed(*unused):
        signatures[current_signature[0]]=form.value('signature')
        current_signature[0]=form.value('signature_account') or 'default'
        form.value('signature',signatures.get(current_signature[0],store.preference('signature','') if current_signature[0]=='default' else ''))

    # ==========================================
    # Function: Show first-class template cards with edit/duplicate/order/delete actions.
    # Method: Rebuild only native cards after a durable template operation.
    # ==========================================
    def render_templates():
        host=g.object(form.builder,'page_templates');g.disconnect('settings-templates');g.clear(host);form.template_buttons={}
        for template in store.templates():
            card=g.gtk_box_new(1,7);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(card),b'account-card')
            label=g.gtk_label_new((template['name']+'\n'+template['subject']+'\n'+' '.join(template['body'].split())[:90]).encode())
            g.gtk_label_set_xalign(label,0);g.gtk_label_set_line_wrap(label,1);g.gtk_box_pack_start(card,label,0,1,3)
            buttons=g.gtk_box_new(0,5)
            for operation,title in [('edit','编辑'),('duplicate','复制'),('up','上移'),('down','下移'),('delete','删除')]:
                button=g.gtk_button_new_with_label(title.encode());form.template_buttons[(template['id'],operation)]=button
                icon_action(g,button,title,{'edit':'folder-edit','duplicate':'action-copy','up':'action-up','down':'action-down','delete':'spark-layout-trash'}[operation])
                g.connect(button,'clicked',lambda *unused,identity=template['id'],op=operation:template_action(identity,op),group='settings-templates')
                g.gtk_box_pack_start(buttons,button,0,1,0)
            g.gtk_box_pack_start(card,buttons,0,1,0);g.gtk_box_pack_start(host,card,0,1,5)
        action('templates','new_template','新建模板',lambda:template_action('new','edit'))
        g.gtk_widget_show_all(host)
    # ==========================================
    # Function: Apply one template action while retaining original messages and drafts.
    # Method: Reuse validated edit dialogs and independent store order/duplicate operations.
    # ==========================================
    def template_action(identity,operation):
        if operation=='edit':template_settings(app,identity)
        elif operation=='delete':store.delete_template(identity)
        else:store.arrange_template(identity,operation)
        render_templates()
    render_accounts();render_templates()
    g.connect(form.fields['signature_account'][0],'changed',signature_changed,group=form.group)
    from .settings_contacts import ContactsPage
    form.contacts_page=ContactsPage(app,form)
    from .settings_filters import FilterPage
    form.filters_page=FilterPage(app,form)
    if contact:form.contacts_page.open_person(contact)
    action('general','default_mail_client','设为默认邮件应用',lambda:(default_mail_client(),app.message('请在 Windows 默认应用中选择 TeleMail；邮件链接只会打开草稿' if os.name=='nt' else 'TeleMail 已设为 mailto 默认应用；邮件链接只会打开草稿')) )
    action('appearance','appearance_reset','恢复默认外观',appearance_editor.reset)
    action('notifications','notification_demo','预览通知样式',lambda:app.preview_notification(form.value('notification_style'),form.value('notification_preview'),int(form.value('notification_duration'))))
    action('appearance','labels_appearance','标签显示选项',lambda:label_settings(app))
    action('inbox','inbox_views','收件箱视图设置',app.inbox_dialog)
    action('inbox','folder_settings','文件夹与智能文件夹',app.manage_folders)
    action('composer','templates','管理邮件模板',lambda:(template_settings(app),render_templates()))
    from .settings_composer import auto_copy_settings
    from .settings_inbox import policy_settings,gatekeeper_settings
    action('composer','auto_copy','自动抄送 / 密送',lambda:auto_copy_settings(app))
    action('composer','schedule_options','稍后发送与提醒预设',lambda:g.gtk_stack_set_visible_child_name(stack,b'scheduling'))
    action('inbox','priority_people','优先发件人',lambda:policy_settings(app,True))
    action('inbox','gatekeeper_rules','信使 · 接受与屏蔽',lambda:gatekeeper_settings(app))
    action('inbox','recognition_rules','邮件识别规则',lambda:policy_settings(app))
    g.label(g.object(form.builder,'note_composer'),'阅读状态使用标准邮件回执，不插入跟踪像素；收件客户端可拒绝回执，因此不保证获得已读结果。回复后完成仅在投递确认后生效。')
    g.label(g.object(form.builder,'note_scheduling'),'预设仅在本机保存。关闭客户端期间不投递，下次启动处理已到期计划。')
    g.label(g.object(form.builder,'note_inbox'),'信使在本机筛选新发件人，不移动或删除服务商邮件。自动识别区分个人、通知和订阅；手工修正与域名规则优先。')
    g.label(g.object(form.builder,'note_reading'),'附件收纳在正文底部的一行入口，点击展开。图片保留在正文原位置。HTML/Markdown 使用阅读字号；PDF 保持原始排版。')
    g.label(g.object(form.builder,'note_general'),'远程图片默认阻止，开启后发件人服务器可获知加载请求；脚本与本地文件仍被阻止。完整 MIME 已随邮件同步，自动缓存将附件另存到本机私有目录，不再次联网。'+('当前桌面没有可恢复的系统托盘，因此已禁用关闭到托盘。' if not tray_available else '托盘右键可恢复或明确退出。')+('开机启动仅为当前 Windows 用户注册；无需 WSL。' if os.name=='nt' else '开机启动遵循 Linux 桌面会话，WSLg 不会代替 Windows 启动 WSL。'))
    g.label(g.object(form.builder,'note_appearance'),'全屏视图在邮件列表和邮件串之间切换；分屏同时显示两栏；收件箱切换保留选中邮件。全屏紧凑/展开及分屏正文行数分别生效。标签选项控制本地标签和系统文件夹标识，不同步 Gmail 标签。')
    g.label(g.object(form.builder,'note_shortcuts'),'Ctrl+N 写邮件\nCtrl+F 搜索\nCtrl+R 回复\nCtrl+Shift+R 全部回复\nCtrl+A 多选时全选\nEsc 返回邮件 / 退出多选\nCtrl+, 打开设置')
    g.label(g.object(form.builder,'note_privacy'),('邮件、草稿、设置均在本机。远程图片默认阻止，邮件脚本始终禁用。密码使用 Windows DPAPI 当前用户保护，并与账号设置绑定；同一 Windows 用户的进程仍可读取。取消默认记住只影响未来登录；已有凭据在账号页逐个忘记。' if os.name=='nt' else '邮件、草稿、设置均在本机。远程图片与脚本默认阻止。密码使用 AES-256-GCM 加密，设备密钥以 0600 权限单独保存；同一 Linux 用户或 root 可访问密钥。取消默认记住只影响未来登录；已有凭据在账号页逐个忘记。'))
    from . import __version__
    g.label(g.object(form.builder,'note_about'),'TeleMail '+__version__+('\nWindows 11 x64 · GTK / WebView2 / Poppler' if os.name=='nt' else '\nLinux amd64 · GTK / WebKitGTK / Poppler')+'\n本地邮件客户端，无应用云端服务。')
    g.gtk_widget_show_all(form.window)
    g.gtk_stack_set_visible_child_name(g.object(form.builder,'settings_stack'),initial.encode())
    status_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(refresh_status)
    status_timer=g.g_timeout_add(1000,C.cast(status_callback,C.c_void_p),None)
    migration_plan=None
    while True:
        response=g.gtk_dialog_run(form.window)
        if response!=1:break
        try:
            from datetime import datetime
            appearance_editor.values()
            for field in ('schedule_morning','schedule_evening'):datetime.strptime(form.value(field),'%H:%M')
            retention_values(form)
            migration_plan=storage_plan(app,form)
            form.conversations_page.value()
            if form.value('inbox_mode_setting') not in INBOX_MODES:raise ValueError('请选择有效的收件箱视图')
            if form.value('launch_at_startup')!=startup_before:set_autostart(form.value('launch_at_startup'))
            break
        except (ValueError,OSError) as error:g.label(form.note,str(error) if not isinstance(error,ValueError) or 'time data' not in str(error) else '预设时间请填写 HH:MM，例如 09:00')
    try:
        if response==1:
            from .mail_retention import save_policy
            save_policy(store,*retention_values(form))
            scope_changed=form.conversations_page.save()
            if scope_changed:app.chat_folder_scope_changed()
            appearance_editor.save()
            for key in ('notification_style','notification_preview'):store.set_preference(key,form.value(key))
            store.set_preference('notification_duration',int(form.value('notification_duration')));store.set_preference('toast_duration',int(form.value('toast_duration')))
            changed_recognition=store.preference('recognition_enabled',True)!=form.value('recognition_enabled')
            changed_priority=store.preference('priority_limit',5)!=int(form.value('priority_limit'))
            for key in ('theme','motion','grouping','notifications','default_account','avatars_mode','adapt_dark_html','mark_read_on_open',
                        'account_colors_enabled','notify_priority_only','shortcuts_enabled','remember_passwords','priority_enabled','gatekeeper_mode',
                        'recognition_enabled','group_notification','group_newsletter','group_verification','reply_window_size','composer_new_window','done_after_reply',
                        'reply_attachments','suggest_recipients','request_receipt','receipt_notifications','composer_tagline','schedule_morning','schedule_evening',
                        'main_action_policy','main_action_unpin','minimize_old_emails','thread_new_window','load_remote_images',
                        'autodownload_attachments','close_to_tray','launch_at_startup','play_send_sound','notification_sound',
                        'layout_mode','mail_list_preview','email_preview_lines'):
                store.set_preference(key,form.value(key))
            for key,pref in [('undo','undo_send_seconds'),('sync_interval','sync_interval'),('reader_font_size','reader_font_size'),('priority_limit','priority_limit'),('schedule_today_hours','schedule_today_hours'),('followup_days','followup_days')]:
                store.set_preference(pref,int(form.value(key)))
            store.set_preference('schedule_enabled',[key for key,_ in PRESETS if form.value('preset_'+key)])
            if changed_priority:
                for view in app.inboxes.all():
                    view.get('cards',{}).get('priority',{}).pop('limit',None);app.inboxes.save(view)
            if changed_recognition:app.background(store.reclassify,lambda result:app.refresh())
            signatures[current_signature[0]]=form.value('signature')
            store.set_preference('signature',signatures.pop('default',store.preference('signature','')))
            store.set_preference('account_signatures',signatures)
            mode=form.value('inbox_mode_setting')
            active=app.inboxes.active()
            target=active if active['mode']==mode else next((row for row in app.inboxes.all() if row['mode']==mode),None)
            if not target:
                target=app.inboxes.definition(mode);app.inboxes.save(target)
            store.set_preference('active_inbox_view',target['id']);app.fill_inbox_modes()
            app.service.interval=store.preference('sync_interval',60)
            app.apply_appearance();app.refresh();app.message('设置已保存')
            if store.preference('autodownload_attachments',False):
                from .desktop_preferences import cached_attachments
                app.background(lambda:cached_attachments(store),lambda count:app.message('已缓存 '+str(count)+' 个附件'))
    finally:
        form.conversations_page.close();form.contacts_page.close();form.filters_page.close();appearance_editor.close();g.g_source_remove(status_timer);g.disconnect('settings-accounts');g.disconnect('settings-templates');g.disconnect(form.group+'-contacts-rows');form.close();app.settings_form=None
    if response==1 and migration_plan is not None:app.request_storage_migration(migration_plan)

# ==========================================
# Function: Manage personal templates directly from settings without opening a composer.
# Method: Reuse the durable template store and preserve text until an explicit save/delete.
# ==========================================
def template_settings(app, selected_id='new'):
    rows={row['id']:row for row in app.service.store.templates()}
    fields=[('template','模板','combo',[('new','新模板')]+[(key,row['name']) for key,row in rows.items()]),
        ('name','模板名称','text',[]),('subject','邮件主题','text',[]),('body','内容','body',[])]
    form=Form(app,'邮件模板',fields,700);form.button('关闭',-6);form.button('删除',2);form.button('保存',1)
    # ==========================================
    # Function: Populate the selected stored template in plain native fields.
    # Method: Load only after selection; saved templates remain unchanged until Save.
    # ==========================================
    def selected(*unused):
        row=rows.get(form.value('template'),{})
        for key in ('name','subject','body'):form.value(key,row.get(key,''))
    app.g.connect(form.fields['template'][0],'changed',selected,group=form.group);form.value('template',selected_id if selected_id in rows else 'new')
    app.g.label(form.note,'支持 {{name}}、{{email}}、{{date}} 和自定义 {{variable}} 占位符；应用时填写。')
    app.g.gtk_widget_show_all(form.window);response=app.g.gtk_dialog_run(form.window)
    try:
        if response==1:app.service.store.save_template(form.value('name'),form.value('subject'),form.value('body'),None if form.value('template')=='new' else form.value('template'))
        elif response==2 and form.value('template')!='new':app.service.store.delete_template(form.value('template'))
    finally:form.close()

# ==========================================
# Function: Control local user labels and system-folder marks in each mail surface.
# Method: Persist three independent switches; no provider-specific label synchronization is implied.
# ==========================================
def label_settings(app):
    keys=[('labels_list','在邮件列表中显示标签'),('labels_reader','在邮件视图中显示标签'),('labels_system','显示系统文件夹标签')]
    form=Form(app,'标签',[ (key,title,'switch',[]) for key,title in keys ],620)
    for key,_ in keys:form.value(key,app.service.store.preference(key,key!='labels_system'))
    app.g.label(form.note,'适用于本机标签与文件夹标记。此设置只改变显示，不修改服务器邮件或 Gmail 标签。')
    form.button('关闭',-6);form.button('保存',1);app.g.gtk_widget_show_all(form.window)
    try:
        if app.g.gtk_dialog_run(form.window)==1:
            for key,_ in keys:app.service.store.set_preference(key,form.value(key))
            app.refresh()
    finally:form.close()
