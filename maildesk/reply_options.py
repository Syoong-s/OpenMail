"""Native reply attachment policy with explicit always/never/ask behavior."""
from .i18n import text as _tr
import base64
from email import policy
from email.parser import BytesParser
from .mime import attachment_content

# ==========================================
# Function: Choose whether a reply includes the original cached attachments.
# Method: Respect the editor policy and use a real native confirmation for Ask Every Time.
# ==========================================
def reply_attachments(app, message):
    items=message['parsed']['attachments']
    mode=app.service.store.preference('reply_attachments','never')
    if not items or mode=='never':return []
    if mode=='ask':
        from .desktop_forms import Form
        form=Form(app,_tr('回复包含附件'),[],520);form.button(_tr('取消回复'),-6);form.button(_tr('不包含附件'),2);form.button(_tr('包含附件'),1)
        app.g.label(form.note,_tr('原邮件有 {0} 个附件，是否附在这次回复中？').format(len(items)))
        app.g.gtk_widget_show_all(form.window);response=app.g.gtk_dialog_run(form.window);form.close()
        if response not in (1,2):return None
        if response==2:return []
    raw=app.service.store.get(message['id'],raw=True)['raw']
    parts=list(BytesParser(policy=policy.default).parsebytes(raw).walk())
    return [{'name':item['name'],'base64':base64.b64encode(attachment_content(parts[item['index']])).decode()} for item in items]
