"""Modern native provider picker and explicit, verified account sign-in wizard."""
import ctypes as C
from dataclasses import asdict
import queue
import threading
import uuid

from .account_login import (PROVIDERS, LoginError, browser_authorize, decode_oauth,
                            detect_provider, import_google_client, oauth_provider, verify_login)
from .config import Account
from .credentials import identity, session_secret
from .desktop_forms import Form,form_xml

CSS=b'''
.signin-dialog { background:#181b23; color:#e9edf5; }
.signin-shell { padding:8px; }
.signin-title { font-size:24px; font-weight:700; }
.signin-subtitle { color:#a3adbd; font-size:13px; }
.signin-card { background:#242936; border:1px solid #333b4a; border-radius:14px; padding:18px; }
.signin-card:hover { background:#30384a; border-color:#649bff; }
.signin-card.signin-selected { background:#253a59; border-color:#6eacff; }
.signin-card label { font-size:15px; }
.signin-dialog entry { border-radius:8px; min-height:30px; background:#232834; color:#f0f3fa; }
.signin-dialog button { border-radius:9px; min-height:28px; }
.signin-dialog .suggested-action { background:#4387f4; color:white; border:0; }
.signin-verified { color:#7bc9a0; font-weight:600; }
.signin-status { padding:10px; border-radius:10px; background:#222834; }
.signin-dialog.light { background:#f6f8fc; color:#202938; }
.signin-dialog.light entry { background:white; color:#202938; }
.signin-dialog.light .signin-card, .signin-dialog.light .signin-status { background:#e9eef7; color:#202938; }
'''

# ==========================================
# Function: Produce the wizard's native provider and state pages.
# Method: Build GtkStack children with compact cards, real entries and progress rows.
# ==========================================
def signin_xml(fields):
    from xml.sax.saxutils import escape
    rows=''
    for key,title,subtitle in [('gmail','Gmail','使用 Google 浏览器安全登录'),('outlook','Outlook / Hotmail','Microsoft 个人邮箱'),
                                ('microsoft365','Microsoft 365','工作或学校邮箱'),('other','其他邮箱','IMAP / SMTP · 密码或授权码')]:
        mark={'gmail':'G','outlook':'O','microsoft365':'M','other':'@'}[key]
        rows+=f'''<child><object class="GtkButton" id="provider_{key}"><style><class name="signin-card"/></style><child><object class="GtkBox"><property name="spacing">16</property><child><object class="GtkLabel"><property name="label">{mark}</property><property name="width-request">32</property><style><class name="signin-title"/></style></object></child><child><object class="GtkBox"><property name="orientation">vertical</property><property name="spacing">5</property><child><object class="GtkLabel"><property name="label">{escape(title)}</property><property name="xalign">0</property></object></child><child><object class="GtkLabel"><property name="label">{escape(subtitle)}</property><property name="xalign">0</property><style><class name="signin-subtitle"/></style></object></child></object></child><child><object class="GtkImage"><property name="icon-name">go-next-symbolic</property><property name="halign">end</property><property name="hexpand">True</property></object></child></object></child></object></child>'''
    # Separate identity fields from server and OAuth configuration without nesting a body editor.
    basic=[item for item in fields if item[0] in ('email','title','display_name','method','secret','remember')]
    advanced=[item for item in fields if item[0] not in {item[0] for item in basic}]
    basic_xml=form_xml(basic).removeprefix('<interface>').removesuffix('</interface>').replace('id="form"','id="basic_fields"').replace('id="note"','id="identity_note"')
    advanced_xml=form_xml(advanced).removeprefix('<interface>').removesuffix('</interface>').replace('id="form"','id="advanced_fields"').replace('id="note"','id="advanced_note"')
    return '''<interface><object class="GtkBox" id="form"><property name="orientation">vertical</property><property name="spacing">14</property><property name="margin">22</property><style><class name="signin-shell"/></style>
      <child><object class="GtkLabel" id="heading"><property name="label">连接你的邮箱</property><property name="xalign">0</property><style><class name="signin-title"/></style></object></child>
      <child><object class="GtkLabel" id="subtitle"><property name="label">选择服务商，在提供商确认授权后连接收件与发件服务。</property><property name="wrap">True</property><property name="xalign">0</property><style><class name="signin-subtitle"/></style></object></child>
      <child><object class="GtkStack" id="signin_stack"><property name="transition-type">slide-left-right</property><property name="transition-duration">180</property><property name="homogeneous">False</property>
        <child><object class="GtkBox" id="providers"><property name="orientation">vertical</property><property name="spacing">10</property>'''+rows+'''</object><packing><property name="name">providers</property></packing></child>
        <child><object class="GtkScrolledWindow"><property name="height-request">420</property><property name="hscrollbar-policy">never</property><child><object class="GtkBox"><property name="orientation">vertical</property><property name="spacing">6</property>'''+'<child>'+basic_xml+'</child>'+'''<child><object class="GtkLabel" id="method_note"><property name="wrap">True</property><property name="xalign">0</property><property name="margin">8</property><style><class name="signin-subtitle"/></style></object></child>
        <child><object class="GtkBox" id="oauth_configuration"><property name="orientation">vertical</property><property name="spacing">6</property><child><object class="GtkLabel"><property name="label">浏览器登录应用配置</property><property name="xalign">0</property></object></child><child><object class="GtkLabel" id="oauth_note"><property name="wrap">True</property><property name="xalign">0</property><style><class name="signin-subtitle"/></style></object></child><child><object class="GtkButton" id="import_google"><property name="label">导入 Google 桌面客户端 JSON…</property></object></child></object></child>
        <child><object class="GtkExpander" id="advanced"><property name="label">高级设置 · 服务器与 OAuth Client ID</property><child>'''+advanced_xml+'''</child></object></child></object></child></object><packing><property name="name">details</property></packing></child>
        <child><object class="GtkBox" id="checking"><property name="orientation">vertical</property><property name="spacing">16</property><property name="margin-top">24</property><property name="margin-bottom">24</property><child><object class="GtkSpinner" id="spinner"><property name="height-request">36</property></object></child><child><object class="GtkLabel" id="browser_status"><property name="label">准备安全连接</property><property name="wrap">True</property></object></child><child><object class="GtkLabel" id="imap_status"><property name="label">○  收件服务 · 等待验证</property><style><class name="signin-status"/></style></object></child><child><object class="GtkLabel" id="smtp_status"><property name="label">○  发件服务 · 等待验证</property><style><class name="signin-status"/></style></object></child></object><packing><property name="name">checking</property></packing></child>
        <child><object class="GtkBox" id="success"><property name="orientation">vertical</property><property name="spacing">14</property><property name="margin-top">28</property><property name="margin-bottom">28</property><child><object class="GtkImage" id="verified_symbol"><property name="icon-name">object-select-symbolic</property><property name="pixel-size">48</property><style><class name="signin-verified"/></style></object></child><child><object class="GtkLabel" id="success_title"><property name="label">邮箱已验证</property><style><class name="signin-title"/></style></object></child><child><object class="GtkLabel" id="verified_identity"><property name="wrap">True</property><property name="selectable">True</property></object></child><child><object class="GtkLabel" id="success_note"><property name="label">点击“完成添加”后才会保存此账户并开始同步。</property><property name="wrap">True</property><style><class name="signin-subtitle"/></style></object></child></object><packing><property name="name">success</property></packing></child>
      </object></child><child><object class="GtkLabel" id="note"><property name="wrap">True</property><property name="xalign">0</property><style><class name="signin-subtitle"/></style></object></child></object></interface>'''

# ==========================================
# Function: Own one cancellable native sign-in attempt and explicit final commit.
# Method: Queue worker progress onto a retained GTK timer; never commit from a worker.
# ==========================================
class SignInWizard(Form):
    # ==========================================
    # Function: Construct provider cards and an isolated candidate form.
    # Method: Preserve existing account identity while keeping typed secrets private.
    # ==========================================
    def __init__(self,app,account=None,allow_metadata=False):
        self.previous=account;self.provider=detect_provider(account.email,account) if account else 'other'
        self.allow_metadata=allow_metadata
        self.stage='providers';self.generation=0;self.cancel_event=threading.Event();self.events=queue.Queue()
        self.receipt=None;self.candidate=None;self.candidate_secret='';self.result=None;self.metadata_only=False
        fields=[('email','邮箱地址','text',[]),('title','账号名称','text',[]),('display_name','发件人名称','text',[]),
                ('method','登录方式','combo',[]),('secret','密码 / 授权码','secret',[]),('remember','在本机记住登录','check',[]),
                ('username','登录用户名','text',[]),('imap_host','IMAP 服务器','text',[]),('imap_port','IMAP 端口','text',[]),
                ('imap_security','IMAP 加密','combo',[('ssl','SSL / TLS'),('starttls','STARTTLS')]),
                ('smtp_host','SMTP 服务器','text',[]),('smtp_port','SMTP 端口','text',[]),
                ('smtp_security','SMTP 加密','combo',[('ssl','SSL / TLS'),('starttls','STARTTLS')]),
                ('folders','同步文件夹','text',[]),('sent_folder','已发送文件夹','text',[]),
                ('client_id','OAuth Client ID','text',[]),('client_secret','Google 客户端密钥','secret',[])]
        super().__init__(app,'添加邮箱 · TeleMail',fields,620,layout=signin_xml(fields))
        self.stack=self.g.object(self.builder,'signin_stack')
        self.back_button=self.button('返回',2);self.cancel_button=self.button('取消',-6);self.next_button=self.button('继续',1)
        self.provider_buttons={key:self.g.object(self.builder,'provider_'+key) for key in PROVIDERS}
        context=self.g.gtk_widget_get_style_context(self.window);self.g.gtk_style_context_add_class(context,b'signin-dialog')
        context=self.g.gtk_widget_get_style_context(self.next_button);self.g.gtk_style_context_add_class(context,b'suggested-action')
        self.css=self.g.gtk_css_provider_new();self.g.gtk_css_provider_load_from_data(self.css,CSS,-1,None)
        self.g.gtk_style_context_add_provider_for_screen(self.g.gdk_screen_get_default(),self.css,610)
        for key,button in self.provider_buttons.items():
            self.g.connect(button,'clicked',lambda *unused,key=key:self.choose_provider(key),group=self.group)
        self.g.connect(self.fields['method'][0],'changed',lambda *unused:self.update_method(),group=self.group)
        self.g.connect(self.g.object(self.builder,'import_google'),'clicked',lambda *unused:self.import_google(),group=self.group)
        self.value('remember',app.service.store.preference('remember_passwords',True))
        self.timer_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.poll)
        self.timer=self.g.g_timeout_add(80,C.cast(self.timer_callback,C.c_void_p),None)
        app.signin_wizard=self
        if account:self.choose_provider(self.provider,existing=True)
        else:self.show_stage('providers')

    # ==========================================
    # Function: Move between provider, details, verification and confirmation pages.
    # Method: Set visible native stack child and meaningful action button state.
    # ==========================================
    def show_stage(self,stage):
        self.stage=stage;self.g.gtk_stack_set_visible_child_name(self.stack,stage.encode())
        self.g.gtk_widget_set_sensitive(self.back_button,stage in ('details','success'))
        self.g.gtk_widget_set_sensitive(self.next_button,stage in ('details','success'))
        action=('保存更改' if self.metadata_only else '确认登录' if self.previous else '完成添加') if stage=='success' else '连接邮箱'
        self.g.gtk_button_set_label(self.next_button,action.encode())
        if stage=='success':
            self.g.label(self.g.object(self.builder,'success_note'),
                         '确认后保存资料，保留已有登录。' if self.metadata_only else
                         '点击“'+action+'”后才会保存已验证的登录并开始同步。')
        titles={'providers':'连接你的邮箱','details':PROVIDERS[self.provider]['name'],'checking':'正在验证邮箱','success':'准备就绪'}
        self.g.label(self.g.object(self.builder,'heading'),titles[stage])
        if stage=='checking':self.g.gtk_spinner_start(self.g.object(self.builder,'spinner'))
        else:self.g.gtk_spinner_stop(self.g.object(self.builder,'spinner'))

    # ==========================================
    # Function: Fill public provider defaults without copying any existing secret.
    # Method: Retain custom account connection values for existing account updates.
    # ==========================================
    def choose_provider(self,provider,existing=False):
        self.provider=provider;values=asdict(self.previous) if existing and self.previous else PROVIDERS[provider]
        for key in ('email','title','display_name','username','imap_host','imap_port','imap_security','smtp_host','smtp_port','smtp_security','sent_folder'):
            self.value(key,str(values.get(key,'')))
        self.value('folders',', '.join(values.get('folders',['INBOX'])))
        self.value('secret','');self.value('client_id','');self.value('client_secret','')
        combo=self.fields['method'][0];self.g.gtk_combo_box_text_remove_all(combo)
        methods=([('browser','通过 Google 浏览器确认登录'),('password','应用专用密码 / 授权码')] if provider=='gmail' else
                 [('browser','通过 Microsoft 浏览器确认登录')] if provider in ('outlook','microsoft365') else
                 [('password','密码 / 邮箱授权码'),('token','已有 OAuth2 访问令牌')])
        for key,title in methods:self.g.gtk_combo_box_text_append(combo,key.encode(),title.encode())
        selected='browser' if provider!='other' else 'password'
        if existing and self.previous and self.previous.auth=='password' and provider in ('gmail','other'):selected='password'
        if existing and self.previous and self.previous.auth=='oauth2':
            bundle=decode_oauth(session_secret(self.previous))
            if bundle:
                self.value('client_id',bundle['client_id']);self.value('client_secret',bundle.get('client_secret',''))
            elif provider=='other':selected='token'
        self.value('method',selected);self.update_method()
        self.show_stage('details');self.g.gtk_expander_set_expanded(self.g.object(self.builder,'advanced'),provider=='other')
        self.g.label(self.note,'凭据不会在验证及最终确认前写入账号或凭据文件。')

    # ==========================================
    # Function: Show applicable credentials and explain authentic browser configuration.
    # Method: Keep provider policy explicit and reveal configuration when unavailable.
    # ==========================================
    def update_method(self):
        method=self.value('method');browser=method=='browser'
        parent=self.g.gtk_widget_get_parent(self.fields['secret'][0])
        self.g.gtk_widget_set_visible(parent,not browser)
        self.g.gtk_widget_set_no_show_all(parent,browser)
        configuration=self.g.object(self.builder,'oauth_configuration')
        self.g.gtk_widget_set_visible(configuration,browser);self.g.gtk_widget_set_no_show_all(configuration,not browser)
        import_button=self.g.object(self.builder,'import_google')
        self.g.gtk_widget_set_visible(import_button,browser and self.provider=='gmail')
        self.g.gtk_widget_set_no_show_all(import_button,not(browser and self.provider=='gmail'))
        for key in ('client_id','client_secret'):
            row=self.g.gtk_widget_get_parent(self.fields[key][0]);visible=browser and (key=='client_id' or self.provider=='gmail')
            self.g.gtk_widget_set_visible(row,visible);self.g.gtk_widget_set_no_show_all(row,not visible)
        note=('将打开系统浏览器，在 Google / Microsoft 页面确认授权。TeleMail 不读取网站登录密码。' if browser else
              'Gmail 请开启两步验证并创建应用专用密码；普通 Google 密码无法用于 IMAP。' if self.provider=='gmail' else
              '密码仅用于加密的 IMAP / SMTP 认证；优先使用邮箱提供商的授权码。' if method=='password' else
              '手动访问令牌兼容模式：不含刷新授权，令牌到期后需要重新登录。')
        self.g.label(self.g.object(self.builder,'method_note'),note)
        self.g.label(self.g.object(self.builder,'oauth_note'),'此本地应用未内置公共 OAuth 注册。请导入自己的 Google 桌面客户端，或填写 Microsoft 公共客户端 ID（启用 http://localhost/oauth/callback 桌面回调，端口动态）。未配置时无法浏览器登录。')

    # ==========================================
    # Function: Load a user-selected Google installed-client registration privately.
    # Method: Use the native file chooser and keep client secrets only in this form.
    # ==========================================
    def import_google(self):
        native=self.g.gtk_file_chooser_native_new('导入 Google 桌面客户端 JSON'.encode(),self.window,0,'导入'.encode(),'取消'.encode())
        try:
            if self.g.gtk_native_dialog_run(native)!=-3:return
            pointer=self.g.gtk_file_chooser_get_filename(native)
            if not pointer:return
            try:path=C.string_at(pointer).decode()
            finally:self.g.g_free(pointer)
            values=import_google_client(path)
            self.value('client_id',values['client_id']);self.value('client_secret',values['client_secret'])
            self.g.label(self.note,'已载入桌面应用配置。连接后将在浏览器中请求你的授权。')
        except Exception:self.g.label(self.note,'无法读取 Google 桌面应用配置，请检查 JSON 文件。')
        finally:self.g.gtk_native_dialog_destroy(native)

    # ==========================================
    # Function: Validate the complete candidate without persisting or staging its secret.
    # Method: Keep an existing immutable account ID and generate IDs only for additions.
    # ==========================================
    def read_candidate(self):
        values=asdict(self.previous) if self.previous else {'id':'mail-'+uuid.uuid4().hex[:10]}
        for key in ('email','title','display_name','username','imap_host','smtp_host','imap_security','smtp_security','sent_folder'):
            values[key]=self.value(key).strip()
        values['imap_port']=int(self.value('imap_port'));values['smtp_port']=int(self.value('smtp_port'))
        values['folders']=tuple(value.strip() for value in self.value('folders').split(',') if value.strip())
        values['auth']='password' if self.value('method')=='password' else 'oauth2'
        values.setdefault('secret_env','TELEMAIL_'+values['id'].replace('-','_').upper())
        candidate=Account(**values)
        if any(item.id!=candidate.id and item.email.casefold()==candidate.email.casefold() for item in self.app.profile.accounts()):
            raise LoginError('这个邮箱已经添加，请在账号设置中更新原账号的登录')
        return candidate

    # ==========================================
    # Function: Start bounded browser/transport verification outside GTK's main thread.
    # Method: Tag queued events with the attempt generation so stale results cannot commit.
    # ==========================================
    def begin(self):
        try:
            candidate=self.read_candidate();method=self.value('method');secret=self.value('secret');self.candidate_method=method
            self.metadata_only=bool(self.allow_metadata and self.previous and identity(self.previous)==identity(candidate) and not secret and method!='browser')
            if self.metadata_only:
                # No changed connection or credential: edit metadata while retaining trusted login.
                self.candidate=candidate;self.receipt=None
                self.g.label(self.g.object(self.builder,'success_title'),'更新账户资料')
                self.g.label(self.g.object(self.builder,'verified_identity'),candidate.email+'\n连接设置未变，将保留原有登录。')
                self.show_stage('success');return
            client_id=self.value('client_id').strip();client_secret=self.value('client_secret')
            authority=oauth_provider(self.provider)
            if method=='browser':
                from .account_login import validate_client
                validate_client(authority,client_id,client_secret)
            elif not secret:raise LoginError('请填写密码或邮箱授权码')
        except (ValueError,TypeError):
            self.g.label(self.note,'请检查邮箱、服务器和端口；浏览器登录需要有效的 OAuth Client ID。')
            if self.value('method')=='browser':self.g.gtk_expander_set_expanded(self.g.object(self.builder,'advanced'),1)
            return
        self.generation+=1;generation=self.generation;self.cancel_event=threading.Event();cancel=self.cancel_event
        self.candidate=candidate;self.receipt=None;self.candidate_secret=''
        for key,title in [('browser_status','准备安全连接'),('imap_status','○  收件服务 · 等待验证'),('smtp_status','○  发件服务 · 等待验证')]:self.g.label(self.g.object(self.builder,key),title)
        self.g.label(self.note,'可随时取消；只有两项验证都成功并点击完成才会保存。');self.show_stage('checking')
        # ==========================================
        # Function: Publish only safe stage names and validated results to the UI.
        # Method: Keep network calls and authorization secrets entirely in the worker.
        # ==========================================
        def work():
            try:
                progress=lambda stage,status:self.events.put((generation,'progress',(stage,status)))
                value=browser_authorize(authority,client_id,candidate.email,client_secret,cancel,progress=progress) if method=='browser' else secret
                receipt=verify_login(candidate,value,cancel,progress)
                self.events.put((generation,'success',(receipt,value)))
            except LoginError as error:self.events.put((generation,'error',str(error)))
            except Exception:self.events.put((generation,'error','连接验证未完成，请检查网络、服务器与认证设置后重试。'))
        threading.Thread(target=work,name='maildesk-sign-in',daemon=True).start()

    # ==========================================
    # Function: Apply worker events on the GTK thread without accepting stale attempts.
    # Method: Drain a bounded queue and display only safe fixed status messages.
    # ==========================================
    def poll(self,*unused):
        if self.closed:return 0
        for unused in range(32):
            try:generation,kind,value=self.events.get_nowait()
            except queue.Empty:break
            if generation!=self.generation or self.cancel_event.is_set():continue
            if kind=='progress':
                stage,status=value
                if stage=='browser':self.g.label(self.g.object(self.builder,'browser_status'),'请在浏览器中登录并确认授权，然后返回此窗口')
                else:
                    title='收件服务' if stage=='imap' else '发件服务'
                    self.g.label(self.g.object(self.builder,stage+'_status'),('✓  ' if status=='verified' else '◌  ')+title+(' · 已验证' if status=='verified' else ' · 正在连接'))
            elif kind=='error':
                self.show_stage('details');self.g.label(self.note,value+' 未保存账户或新凭据。')
            elif kind=='success':
                self.receipt,self.candidate_secret=value
                self.value('secret','')
                self.g.label(self.g.object(self.builder,'success_title'),'邮箱已验证')
                account=self.candidate
                description=('OAuth2 浏览器授权' if self.candidate_method=='browser' else
                             'OAuth2 访问令牌认证' if account.auth=='oauth2' else 'TLS 加密密码认证')
                self.g.label(self.g.object(self.builder,'verified_identity'),account.email+'\n登录身份：'+account.login_name+'\n✓ IMAP · '+account.imap_host+'\n✓ SMTP · '+account.smtp_host+'\n'+description)
                self.show_stage('success');self.g.label(self.note,'尚未保存。请确认以上账户身份与服务器后完成登录。')
        return 1

    # ==========================================
    # Function: Require a deliberate native confirmation before local persistence.
    # Method: Commit the matched verification receipt, then update the running service.
    # ==========================================
    def confirm(self):
        if self.stage!='success' or not self.candidate:return False
        try:
            if self.metadata_only:
                saved=self.app.profile.save_account(asdict(self.candidate))
            else:
                if not self.receipt or self.cancel_event.is_set():return False
                saved=self.app.profile.commit_verified_login(self.candidate,self.candidate_secret,self.receipt,self.value('remember'))
            self.result=self.candidate;self.app.apply_accounts(saved);return True
        except Exception:
            self.g.label(self.note,'本机账户保存失败，未替换已有登录。请检查目录权限或重新验证。');return False

    # ==========================================
    # Function: Run native responses while keeping asynchronous verification interactive.
    # Method: Leave the dialog open for retries and require the final success response.
    # ==========================================
    def run(self):
        self.g.gtk_widget_show_all(self.window);self.update_method();self.show_stage(self.stage)
        while not self.closed:
            response=self.g.gtk_dialog_run(self.window)
            if response in (-6,-4,-1):break
            if response==2:
                self.generation+=1;self.cancel_event.set();self.receipt=None;self.candidate_secret=''
                self.show_stage('details' if self.stage=='success' else 'providers')
            elif response==1:
                if self.stage=='success':
                    if self.confirm():break
                elif self.stage=='details':self.begin()
        result=self.result;self.close();return result

    # ==========================================
    # Function: Cancel work before disconnecting and releasing native widgets.
    # Method: Invalidate callbacks, remove the timer and clear candidate secrets.
    # ==========================================
    def close(self):
        if self.closed:return
        self.cancel_event.set();self.generation+=1;self.candidate_secret='';self.receipt=None
        if self.timer:self.g.g_source_remove(self.timer);self.timer=0
        if getattr(self.app,'signin_wizard',None) is self:self.app.signin_wizard=None
        super().close()
        self.g.gtk_style_context_remove_provider_for_screen(self.g.gdk_screen_get_default(),self.css)
        self.g.g_object_unref(self.css)

# ==========================================
# Function: Open the same verified workflow for initial, added and replacement accounts.
# Method: Keep demo accounts read-only and return only a confirmed account result.
# ==========================================
def account_signin(app,account=None,allow_metadata=False):
    if app.profile.demo:
        app.message('演示模式不能修改真实账户。请打开普通 TeleMail 窗口。');return None
    return SignInWizard(app,account,allow_metadata=allow_metadata).run()
