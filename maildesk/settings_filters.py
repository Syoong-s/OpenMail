"""Native global/account filter settings, ordered rule cards and explicit preview/run controls."""
import ctypes as C
from . import filter_rules
from .desktop_general import bind,P,I
from .desktop_forms import Form
from .ui_actions import icon_action

FIELD_LABELS=[('sender','发件邮箱'),('domain','发件域名'),('to','收件人'),('cc','抄送'),('subject','主题'),('body','正文'),('header','邮件头'),('attachment_name','附件名称'),('attachment_type','附件类型'),('has_attachment','包含附件'),('size_kb','邮件大小（KiB）'),('category','当前分类'),('smart','智能识别'),('seen','已读'),('starred_contact','星标联系人'),('learned','学习匹配分数')]
CATEGORY_LABELS=[('personal','个人邮件'),('notification','通知'),('newsletter','订阅 / 邮件列表'),('verification','验证码')]
SMART_LABELS=CATEGORY_LABELS+[('invoice','账单 / 发票 / 收据'),('calendar','日历邀请'),('auto_reply','自动回复')]
OP_LABELS=[('contains','包含'),('not_contains','不包含'),('is','等于'),('is_not','不等于'),('starts','开头是'),('ends','结尾是'),('matches','通配符 * ? []')]

# ==========================================
# Function: Add an application-native dropdown with the same ownership as its surrounding form.
# Method: Retain NativeChoice wrappers so pointer, keyboard and close behavior match existing settings.
# ==========================================
def combo(app,form,parent,title,items,active=''):
    g=app.g;widget=g.gtk_combo_box_text_new()
    for value,label in items:g.gtk_combo_box_text_append(widget,str(value).encode(),label.encode())
    g.gtk_combo_box_set_active_id(widget,str(active).encode());g.gtk_box_pack_start(parent,widget,0,0,0)
    from .native_choices import NativeChoice
    form.choices.append(NativeChoice(g,widget,title))
    return widget

# ==========================================
# Function: Read a stable dropdown ID without depending on displayed translated text.
# Method: Copy the borrowed native UTF-8 ID to a normal Python string.
# ==========================================
def active(g,widget):return (g.gtk_combo_box_get_active_id(widget) or b'').decode()

# ==========================================
# Function: Resolve user-facing names for exactly the currently supported filter accounts.
# Method: Keep local/demo mail available without discovering removed credentials from cached folders.
# ==========================================
def account_options(app):
    from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL
    return [(identity,LOCAL_LABEL if identity==LOCAL_ACCOUNT else app.service.accounts[identity].email if identity in app.service.accounts else '演示邮箱') for identity in app.service.filter_accounts()]

# ==========================================
# Function: Present global/account rules and guarded manual processing in the actual Settings workspace.
# Method: Reuse the production service and native editor while keeping preview and mutation visibly separate.
# ==========================================
class FilterPage:
    # ==========================================
    # Function: Build scope, ordered rule list, manual folder selectors and audit summary.
    # Method: Own widgets through the parent form and defer database/protocol work to existing application workers.
    # ==========================================
    def __init__(self,app,form):
        self.app=app;self.form=form;self.g=g=app.g;self.store=app.service.store;self.plan=None;self.busy=False;self.items={};self.buttons={};self.cards={};self.card_views={};self.expanded=set();self.closed=False
        host=g.object(form.builder,'page_filters');self.host=host
        toolbar=g.gtk_box_new(0,7);g.gtk_box_pack_start(host,toolbar,0,1,4)
        self.scope=combo(app,form,toolbar,'过滤器范围',[('','全局过滤器'),*account_options(app)])
        self.add=self.button(toolbar,'新建过滤器','action-add',self.edit)
        self.rows=g.gtk_box_new(1,7);g.gtk_box_pack_start(host,self.rows,0,1,5)
        from .filter_manual import ManualRunPanel
        self.manual=ManualRunPanel(self,host,account_options(app))
        actions=g.gtk_box_new(0,6);g.gtk_box_pack_start(host,actions,0,1,3)
        self.preview_button=self.button(actions,'预览匹配邮件','spark-layout-seen',self.preview)
        self.run_button=self.button(actions,'运行当前预览中的移动','composer-send',self.run)
        self.cancel_button=self.button(actions,'停止后续过滤器移动','composer-close',self.cancel)
        self.preview_label=g.gtk_label_new('尚未预览。自动过滤只执行一次；账号规则先于全局，首条匹配后停止。'.encode());g.gtk_label_set_xalign(self.preview_label,0);g.gtk_label_set_line_wrap(self.preview_label,1);g.gtk_box_pack_start(host,self.preview_label,0,1,6)
        self.history=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.history,0);g.gtk_label_set_line_wrap(self.history,1);g.gtk_box_pack_start(host,self.history,0,1,8)
        for label in (self.preview_label,self.history):bind(app,'gtk','gtk_label_set_line_wrap_mode',None,P,I)(label,2)
        g.connect(self.scope,'changed',lambda *unused:self.render(),group=form.group)
        g.connect(self.run_account,'changed',lambda *unused:self.account_changed(),group=form.group)
        for widget in (self.run_folder,self.run_rule):g.connect(widget,'changed',lambda *unused:self.invalidate(),group=form.group)
        g.connect(self.subfolders,'notify::active',lambda *unused:self.invalidate(),count=3,group=form.group)
        self.render();self.controls()

    # ==========================================
    # Function: Attach a compact labeled-by-tooltip icon action.
    # Method: Route every callback through the application's native error boundary and form-owned signals.
    # ==========================================
    def button(self,parent,title,icon,callback):
        g=self.g;button=g.gtk_button_new();icon_action(g,button,title,icon);g.gtk_box_pack_start(parent,button,0,0,0);g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=self.form.group);return button

    # ==========================================
    # Function: Keep execution unavailable until a matching preview is present.
    # Method: Disable editing/preview while this page is preparing or running work and expose cancellation only during a run.
    # ==========================================
    def controls(self):
        for widget in (self.add,self.scope,self.run_account,self.run_folder,self.run_rule,self.subfolders,self.preview_button,self.rows):self.g.gtk_widget_set_sensitive(widget,not self.busy)
        self.g.gtk_widget_set_sensitive(self.subfolders,not self.busy and bool(active(self.g,self.run_account) and active(self.g,self.run_folder)))
        self.g.gtk_widget_set_sensitive(self.run_button,not self.busy and bool(self.plan and self.plan['entries']))
        self.g.gtk_widget_set_sensitive(self.cancel_button,bool(self.app.service.status.get('filters',{}).get('running')))
        self.manual.sync()

    # ==========================================
    # Function: Invalidate a prepared manual snapshot when its visible source or rule selector changes.
    # Method: Require another preview before the mutation button becomes active.
    # ==========================================
    def invalidate(self):self.plan=None;self.controls()

    # ==========================================
    # Function: Populate only the selected account's actual selectable source folders.
    # Method: Keep all-account runs unambiguous and preserve paths as dropdown IDs.
    # ==========================================
    def account_changed(self):
        g=self.g;g.gtk_combo_box_text_remove_all(self.run_folder);g.gtk_combo_box_text_append(self.run_folder,b'','所有文件夹'.encode());account=active(g,self.run_account)
        if account:
            for row in self.store.list_folders(account):
                if row['selectable']:g.gtk_combo_box_text_append(self.run_folder,row['folder'].encode(),row['folder'].encode())
        g.gtk_combo_box_set_active_id(self.run_folder,b'');self.invalidate()

    # ==========================================
    # Function: Refresh ordered rule cards without changing any mail or training data.
    # Method: Rebuild owned collapsible views while preserving only this Settings session's disclosure state.
    # ==========================================
    def render(self):
        if self.closed or self.form.closed:return
        g=self.g;group=self.form.group+'-filter-rows';g.disconnect(group);g.clear(self.rows);scope=active(g,self.scope);items=filter_rules.rules(self.store);self.items={rule['id']:rule for rule in items};self.cards={};self.buttons={}
        from .filter_cards import FilterCard
        from .identity_colors import IdentityColors
        names=dict(account_options(self.app));snapshot=IdentityColors(self.store).snapshot(names);colors=snapshot['colors'] if snapshot['enabled'] else {};self.card_views={};self.expanded.intersection_update(self.items)
        for rule in items:
            if rule['account']!=scope:continue
            view=FilterCard(self,rule,names,colors,group);self.card_views[rule['id']]=view;self.cards[rule['id']]=view.box;g.gtk_box_pack_start(self.rows,view.box,0,1,0)
        if not any(rule['account']==scope for rule in items):g.gtk_box_pack_start(self.rows,g.gtk_label_new('还没有过滤器，点击 ＋ 新建。'.encode()),0,1,8)
        selected=active(g,self.run_rule);g.gtk_combo_box_text_remove_all(self.run_rule);g.gtk_combo_box_text_append(self.run_rule,b'','全部启用的过滤器'.encode())
        for rule in items:g.gtk_combo_box_text_append(self.run_rule,rule['id'].encode(),(('全局' if not rule['account'] else names.get(rule['account'],rule['account']))+' · '+rule['name']).encode())
        g.gtk_combo_box_set_active_id(self.run_rule,selected.encode() if selected in self.items else b'')
        self.log_summary();g.gtk_widget_show_all(self.rows);self.invalidate()

    # ==========================================
    # Function: Save an explicit enabled toggle immediately without retroactive execution.
    # Method: Read the native slider, persist through the service and preserve independent disclosure state.
    # ==========================================
    def toggle(self,identity,widget):
        rule=self.items[identity]|{'enabled':bool(self.g.gtk_switch_get_active(widget))};self.busy=True;self.controls();self.app.background(lambda:self.app.service.save_filter(rule),lambda unused:self.saved(),self.failed)

    # ==========================================
    # Function: Open the structured editor for the selected scope or saved rule.
    # Method: Keep the editor inside the same application and refresh only after a successful durable save.
    # ==========================================
    def edit(self,identity=None):
        from .filter_editor import FilterEditor
        editor=FilterEditor(self.app,self.items.get(identity) if identity else None,active(self.g,self.scope));self.editor=editor
        if editor.run():self.saved()

    # ==========================================
    # Function: Dispatch rule-local ordering, editing, duplication, learning or deletion.
    # Method: Keep model training explicit and let ordinary rule edits retain their own validation boundary.
    # ==========================================
    def operation(self,identity,operation):
        if operation=='edit':return self.edit(identity)
        if operation=='learn':return self.learn(identity)
        if operation=='delete':
            form=Form(self.app,'删除过滤器',[],440);self.g.label(form.note,'仅删除规则和学习样本；已经移动的邮件保留。');form.button('取消',-6);form.button('删除',1);self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);form.close()
            if response!=1:return
        self.busy=True;self.controls();self.app.background(lambda:filter_rules.arrange(self.store,identity,operation),lambda unused:self.saved(),self.failed)

    # ==========================================
    # Function: Acknowledge a durable rule change while the page still owns its widgets.
    # Method: Rebuild the cards and leave old mail unchanged until the user previews and runs it.
    # ==========================================
    def saved(self):
        self.busy=False
        if self.closed or self.form.closed:return
        self.render();self.g.label(self.preview_label,'过滤器已保存。已有邮件请先预览，再手动运行。')

    # ==========================================
    # Function: Report worker failure without presenting a stale preview as executable.
    # Method: Preserve the normal application error boundary and release only page-owned busy state.
    # ==========================================
    def failed(self,error):
        self.busy=False
        if not self.closed and not self.form.closed:self.controls();self.g.label(self.preview_label,str(error));self.log_summary()
        if not self.app.closing:self.app.show_error(error)

    # ==========================================
    # Function: Prepare a nonmutating manual plan over the visible cached-mail scope.
    # Method: Run the shared matcher off GTK and show source, destination and matching reason before enabling execution.
    # ==========================================
    def preview(self):
        account=active(self.g,self.run_account);folder=active(self.g,self.run_folder);rule=active(self.g,self.run_rule);children=bool(self.g.gtk_switch_get_active(self.subfolders));self.busy=True;self.plan=None;self.controls();self.g.label(self.preview_label,'正在预览已缓存邮件…')
        self.app.background(lambda:self.app.service.preview_filters(account,folder,children,rule),self.preview_ready,self.failed)

    # ==========================================
    # Function: Present a concrete bounded manual plan without moving a source.
    # Method: Show counts, representative identities/paths and explicit truncation or ambiguous-result skips.
    # ==========================================
    def preview_ready(self,plan):
        self.busy=False
        if self.closed or self.form.closed:return
        self.plan=plan;text='已检查 '+str(plan['scanned'])+' 封 · 将移动 '+str(len(plan['entries']))+' 封 · 已在目标 '+str(plan['unchanged'])+' 封'
        if plan['uncertain']:text+=' · '+str(plan['uncertain'])+' 封移动结果待核对，已跳过'
        if plan['truncated']:text+='\n本次最多1000封；完成后再次预览可继续。'
        for entry in plan['entries'][:8]:text+='\n'+entry['subject'][:60]+' · '+entry['folder']+' → '+entry['destination']+'\n  '+entry['name']+'：'+entry['reason'][:120]
        self.g.label(self.preview_label,text);self.controls()

    # ==========================================
    # Function: Run only the reviewed prepared snapshot after the user explicitly clicks the execution action.
    # Method: Let the service invalidate changed rules and recheck source generations before moving.
    # ==========================================
    def run(self):
        if not self.plan:return
        plan=self.plan;self.plan=None;self.busy=True;self.controls();self.g.gtk_widget_set_sensitive(self.cancel_button,1);self.g.label(self.preview_label,'正在运行预览中的移动…');self.app.background(lambda:self.app.service.run_filter_plan(plan),self.run_ready,self.failed)

    # ==========================================
    # Function: Show exact manual results after provider confirmation and refresh the mailbox.
    # Method: Keep failed/uncertain counts explicit and require a fresh preview before another run.
    # ==========================================
    def run_ready(self,result):
        self.busy=False
        if not self.app.closing:self.app.refresh()
        if self.closed or self.form.closed:return
        self.g.label(self.preview_label,('已停止 · ' if result['cancelled'] else '运行完成 · ')+'移动 '+str(result['moved'])+' 封 · 失败 / 待核对 '+str(result['failed'])+' 封 · 跳过 '+str(result['skipped'])+' 封');self.controls();self.log_summary()

    # ==========================================
    # Function: Cancel future manual moves without interrupting an in-flight provider mutation.
    # Method: Set the service's explicit cancellation flag and retain already confirmed results.
    # ==========================================
    def cancel(self):self.app.service.filter_cancel_event.set();self.g.label(self.preview_label,'正在停止后续移动；当前操作完成后停止。')

    # ==========================================
    # Function: Learn a rule's account-specific style from explicitly selected cached examples.
    # Method: Require an account choice, then train locally without modifying any message or enabling a rule automatically.
    # ==========================================
    def learn(self,identity):
        rule=self.items[identity];options=[(account,label) for account,label in account_options(self.app) if account in rule['destinations']]
        if not options:raise ValueError('请先设置目标文件夹')
        selected=rule['account'] or active(self.g,self.run_account);selected=selected if selected in dict(options) else options[0][0]
        form=Form(self.app,'学习目标文件夹的邮件特征',[('account','训练账号','combo',options)],560);self.learning_form=form;form.value('account',selected);self.g.label(form.note,'仅使用本机缓存：目标文件夹作为正例，其他文件夹作为反例，至少各5封。不会移动邮件或上传内容。学习后请使用“学习匹配分数”条件，并先预览。');form.button('取消',-6);form.button('开始学习',1);self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);account=form.value('account');form.close()
        if response!=1:return
        self.busy=True;self.controls();self.app.background(lambda:self.app.service.train_filter(identity,account),self.learned,self.failed)

    # ==========================================
    # Function: Report sample coverage and invalidate previews derived from an older model.
    # Method: Keep learned-score thresholds visible in the structured rule editor rather than silently adding a condition.
    # ==========================================
    def learned(self,result):
        self.busy=False
        if self.closed or self.form.closed:return
        self.invalidate();self.g.label(self.preview_label,'学习完成：目标示例 '+str(result['positive'])+' 封，其他示例 '+str(result['negative'])+' 封。请用“学习匹配分数”条件，并先预览验证。')

    # ==========================================
    # Function: Show recent successes and actionable failures without duplicating message bodies.
    # Method: Render the last six bounded audit entries with source/target and the saved explanation.
    # ==========================================
    def log_summary(self):
        with self.store.db() as db:rows=db.execute('SELECT * FROM mail_filter_log ORDER BY id DESC LIMIT 6').fetchall()
        names={'moved':'已移动','failed':'失败','uncertain':'待核对','moving':'正在移动','unchanged':'已在目标'}
        self.g.label(self.history,'最近运行记录'+''.join('\n'+names.get(row['state'],row['state'])+' · '+row['source']+' → '+row['target']+' · '+row['detail'][:100] for row in rows))

    # ==========================================
    # Function: Release page-specific callbacks when Settings closes.
    # Method: Let explicitly started backend work finish without writing to destroyed GTK widgets.
    # ==========================================
    def close(self):self.closed=True;self.g.disconnect(self.form.group+'-filter-rows')
