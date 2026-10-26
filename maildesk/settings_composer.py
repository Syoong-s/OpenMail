"""Native per-account automatic CC/BCC and shared schedule preference validation."""
from .desktop_forms import Form
from .settings_inbox import account_choices
from .composer_options import validated_addresses

# ==========================================
# Function: Edit per-account automatic copy rules used by the delivery service.
# Method: Validate recipient syntax, persist mode/enabled/address values and reload on selection.
# ==========================================
def auto_copy_settings(app):
    choices=account_choices(app);store=app.service.store
    form=Form(app,'自动抄送 / 密送',[('account','发送账号','combo',choices),('enabled','启用','check',[]),
        ('mode','发送方式','combo',[('cc','抄送 CC'),('bcc','密送 BCC')]),('addresses','收件地址','text',[])],680)
    form.button('关闭',-6);form.button('保存此账号',1)
    # ==========================================
    # Function: Populate the selected account rule without changing other accounts.
    # Method: Reload a single validated mapping entry on each selection change.
    # ==========================================
    def selected(*unused):
        value=store.preference('auto_copy',{}).get(form.value('account'),{})
        form.value('enabled',value.get('enabled',False));form.value('mode',value.get('mode','bcc'));form.value('addresses',value.get('addresses',''))
    app.g.connect(form.fields['account'][0],'changed',selected,group=form.group);form.value('account',choices[0][0])
    app.g.label(form.note,'每次发送时应用此规则。相同收件地址会去重；密送地址不会写入可见邮件头。')
    app.g.gtk_widget_show_all(form.window)
    try:
        while app.g.gtk_dialog_run(form.window)==1:
            try:
                values=validated_addresses(form.value('addresses'))
                if form.value('enabled') and not values:raise ValueError('启用自动抄送/密送时请填写地址')
                mapping=store.preference('auto_copy',{});mapping[form.value('account')]={'enabled':form.value('enabled'),'mode':form.value('mode'),'addresses':', '.join(values)}
                store.set_preference('auto_copy',mapping);app.g.label(form.note,'已保存此账号的自动抄送 / 密送设置')
            except ValueError as error:app.g.label(form.note,str(error))
    finally:form.close()
