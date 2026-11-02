"""Local priority identities, Gatekeeper policies and category-rule settings."""
from .i18n import text as _tr, join_text as _join_ui
from .desktop_forms import Form
from .local_mail import LOCAL_ACCOUNT

# ==========================================
# Function: Offer configured and cached account identities for local policy management.
# Method: Preserve editable rules even after an account is disconnected.
# ==========================================
def account_choices(app):
    choices={account.id:account.title or account.email for account in app.service.accounts.values()}
    with app.service.store.db() as db:
        for row in db.execute('SELECT DISTINCT account FROM messages'):choices.setdefault(row[0],row[0])
    if app.profile.demo:choices.setdefault('demo','demo@example.com')
    choices.setdefault(LOCAL_ACCOUNT,_tr('本地邮件'))
    return list(choices.items())

# ==========================================
# Function: Manage account-scoped priority people/domains and mail classification corrections.
# Method: Edit a durable rule, reclassify uncategorized overrides and expose readable current rules.
# ==========================================
def policy_settings(app, priority=False):
    choices=account_choices(app)
    fields=[('account',_tr('邮箱账号'),'combo',choices),('sender',_tr('发件人 / @域名'),'text',[])]
    if priority:fields.append(('enabled',_tr('设为优先发件人'),'check',[]))
    else:fields.append(('category',_tr('识别为'),'combo',[('personal',_tr('个人邮件')),('notification',_tr('通知')),('verification',_tr('验证码')),('newsletter',_tr('订阅 / 动态')),('remove',_tr('移除识别规则'))]))
    form=Form(app,_tr('优先发件人') if priority else _tr('邮件识别规则'),fields,690)
    form.button(_tr('关闭'),-6);form.button(_tr('保存规则'),1)
    form.value('account',choices[0][0]);form.value('enabled',True) if priority else form.value('category','personal')
    # ==========================================
    # Function: Show current sender and domain rules without accessing account secrets.
    # Method: Read the existing local account scope whenever its selector changes.
    # ==========================================
    def show(*unused):
        account=form.value('account')
        values=app.service.store.priority_senders(account) if priority else [sender+' → '+category for sender,category in app.service.store.sender_rules(account).items()]
        app.g.label(form.note,_tr('当前规则：\n')+(_join_ui('\n',(values[:30])) if values else _tr('暂无规则'))+_tr('\n可输入完整邮箱或 @example.com；规则仅作用于选择的账号。'))
    app.g.connect(form.fields['account'][0],'changed',show,group=form.group);show()
    app.g.gtk_widget_show_all(form.window)
    try:
        while app.g.gtk_dialog_run(form.window)==1:
            try:
                if priority:app.service.store.set_priority_sender(form.value('account'),form.value('sender'),form.value('enabled'))
                else:app.service.store.category_rule(form.value('account'),form.value('sender'),form.value('category'));app.service.store.reclassify()
                app.refresh();show();form.value('sender','')
            except ValueError as error:app.g.label(form.note,str(error))
    finally:form.close()

# ==========================================
# Function: Manage accepted/blocked sender or domain rules outside a selected mail.
# Method: Update only local filtering state; never delete or move provider messages.
# ==========================================
def gatekeeper_settings(app):
    from .composer_options import rule_sender
    fields=[('account',_tr('邮箱账号'),'combo',account_choices(app)),('sender',_tr('发件人 / @域名'),'text',[]),
        ('policy',_tr('处理方式'),'combo',[('accepted',_tr('接受')),('blocked',_tr('屏蔽')),('new',_tr('恢复待审阅'))])]
    form=Form(app,_tr('信使 · 发件人管理'),fields,690);form.button(_tr('关闭'),-6);form.button(_tr('保存'),1)
    form.value('account',account_choices(app)[0][0]);form.value('policy','accepted')
    # ==========================================
    # Function: List persisted sender/domain accept and block decisions for the selected account.
    # Method: Render bounded plain text with no remote mailbox mutations.
    # ==========================================
    def show(*unused):
        with app.service.store.db() as db:rows=db.execute('SELECT sender,policy FROM sender_policy WHERE account=? ORDER BY sender',(form.value('account'),)).fetchall()
        app.g.label(form.note,_join_ui('\n',((row['sender']+' · '+{'accepted':_tr('已接受'),'blocked':_tr('已屏蔽'),'new':_tr('待审阅'),'priority':_tr('优先')}.get(row['policy'],row['policy']) for row in rows[:30]))) or _tr('暂无决策。可为某个邮箱或整个 @域名设置接受/屏蔽。'))
    app.g.connect(form.fields['account'][0],'changed',show,group=form.group);show();app.g.gtk_widget_show_all(form.window)
    try:
        while app.g.gtk_dialog_run(form.window)==1:
            try:
                sender=rule_sender(form.value('sender'))
                with app.service.store.db() as db:db.execute('INSERT INTO sender_policy VALUES(?,?,?) ON CONFLICT(account,sender) DO UPDATE SET policy=excluded.policy',(form.value('account'),sender,form.value('policy')))
                app.refresh();show();form.value('sender','')
            except ValueError as error:app.g.label(form.note,str(error))
    finally:form.close()
