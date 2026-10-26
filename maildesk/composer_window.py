"""Native standalone/embedded composer, local scheduling and personal editing policies."""
import base64
import ctypes as C
from datetime import datetime
from pathlib import Path
import time
import uuid
import json
import sqlite3
from .desktop_forms import Form,form_xml
from .mime import MAX_MESSAGE_BYTES
from .local_mail import LOCAL_ACCOUNT
from .composer_layout import ComposerLayout

# ==========================================
# Function: Compose, reply or edit a draft in a standalone native dialog.
# Method: Keep a stable draft identity and call the shared mail service directly.
# ==========================================
class Composer(ComposerLayout,Form):
    # ==========================================
    # Function: Create the full native message editor.
    # Method: Populate account and text fields, retain attachments and reply headers.
    # ==========================================
    def __init__(self, app, draft=None):
        draft = draft or {}
        accounts = [('demo','demo@example.com')] if app.profile.demo else [(a.id,a.email) for a in app.service.accounts.values()]+[(LOCAL_ACCOUNT,'本地草稿（未选择发件账户）')]
        fields = [('account','发件账户','combo',accounts)]
        fields += [(key,label,'text',[]) for key,label in [('to','收件人'),('cc','抄送'),('bcc','密送'),('subject','主题')]]
        fields += [('body','正文','body',[]),('due','发送计划','text',[]),('followup','未回复提醒','text',[])]
        embedded=not app.service.store.preference('composer_new_window',False)
        self.inline=embedded and bool(draft.get('reply_source')) and app.service.store.preference('reply_window_size','compact')=='compact'
        self.floating=False;self.detached=False;self.surface_window=None;self.inline_card=None
        if embedded and not app.close_document():raise ValueError('请先保存当前草稿')
        self.init_layout(app,fields,accounts,embedded)
        self.identity = draft.get('id') or uuid.uuid4().hex
        self.attachments = list(draft.get('attachments', []))
        self.reply = {key: draft.get(key,'') for key in ('in_reply_to','references','reply_source','chat_key','chat_route')}
        self.reply.update({key:draft[key] for key in ('done_after_send','request_receipt') if key in draft})
        self.busy = False
        self.last_autosave=time.monotonic()
        self.last_snapshot=''
        for key in ('to','cc','bcc','subject','body'):
            self.value(key, draft.get(key,''))
        preferred=app.service.store.preference('default_account','') or app.service.store.preference('last_from_account','')
        self.value('account', draft.get('account') or (preferred if preferred in dict(accounts) else accounts[0][0] if accounts else ''))
        self.signature_account=self.value('account');self.applied_signature='';self.signature_managed=not bool(draft.get('id'))
        if not draft.get('id'):
            from .desktop_settings import signature_for
            signature=signature_for(app.service.store,self.value('account'))
            if signature:self.value('body',self.value('body')+'\n\n-- \n'+signature)
            self.applied_signature=signature
        from .richtext import NativeRichText
        self.rich=NativeRichText(self.g,self.fields['body'][0])
        if draft.get('html'):self.rich.load_html(draft['html'])
        self.editor_baseline=dict(draft.get('editor_baseline',{}))
        if not draft.get('id'):
            self.editor_baseline={key:self.value(key) if draft.get('reply_source') else ('\n\n-- \n'+self.applied_signature if key=='body' and self.applied_signature else '') for key in ('to','cc','bcc','subject','body')}
        self.value('due',draft.get('scheduled_at',''))
        if draft.get('remind_at'):self.value('followup',datetime.fromtimestamp(draft['remind_at']).isoformat(timespec='minutes'))
        self.completions=[]
        if app.service.store.preference('suggest_recipients',True):
            from .composer_completion import RecipientCompletion
            self.completions=[RecipientCompletion(self,self.fields[key][0]) for key in ('to','cc','bcc')]
        self.g.gtk_entry_set_placeholder_text(self.fields['due'][0], '可选，例如 2026-10-20 14:30（本地时间）'.encode())
        self.g.label(self.note, '附件：' + '、'.join(a['name'] for a in self.attachments) if self.attachments else '草稿保存在本机。演示模式禁止外发。' if app.profile.demo else '草稿保存在本机；定时发送要求应用保持运行。')
        from .reply_history import ReplyHistoryView,validated
        self.reply['reply_history']=validated(draft.get('reply_history'))
        self.history_view=ReplyHistoryView(self,self.content,self.reply['reply_history']);self.g.gtk_box_reorder_child(self.content,self.history_view.root,4)
        self.setup_actions()
        from .recipient_picker import RecipientPicker
        self.recipient_pickers=[RecipientPicker(self,self.fields[key][0],self.g.object(self.builder,key+'_row')) for key in ('to','cc','bcc')]
        self.account_changed()
        self.g.connect(self.fields['account'][0],'changed',self.account_changed,group=self.group)
        if not embedded:
            self.g.connect(self.window, 'response', self.response, count=3, group=self.group, types=(C.c_void_p,C.c_int,C.c_void_p))
            self.g.connect(self.window, 'delete-event', self.on_delete, count=3, group=self.group, returns=True)
        self.restore_window=False
        if embedded:
            card=getattr(app,'conversation_cards',{}).get(draft.get('reply_source'))
            self.inline=bool(self.inline and card)
            self.floating=False
            if self.inline:self.g.gtk_box_pack_start(card['reply_host'],self.window,0,1,0)
            else:self.g.gtk_box_pack_start(app.widget('composer_host'),self.window,1,1,0)
            self.g.gtk_stack_set_visible_child_name(app.widget('reader_stack'),b'mail' if self.inline else b'composer')
        if draft.get('reply_source') and app.service.store.preference('reply_window_size','compact')=='full':
            target=app.window if embedded else self.window
            self.restore_window=embedded and not self.g.gtk_window_is_maximized(target)
            self.g.gtk_window_maximize(target)
        if not embedded and not draft.get('reply_source'):self.g.gtk_window_maximize(self.window)
        self.g.gtk_widget_show_all(self.window)
        self.size_surface();self.scroll_into_view();app.composer=self;app.update_reply_draft_cards()
        self.set_draft_state('saved' if draft.get('id') else 'dirty','本机草稿 · 已保存' if draft.get('id') else '正在撰写 · 草稿仅保存在本机')
        for key in ('account','to','cc','bcc','subject','due','followup'):
            self.g.connect(self.fields[key][0],'changed',self.draft_changed,group=self.group)
        self.g.connect(self.g.gtk_text_view_get_buffer(self.fields['body'][0]),'changed',self.draft_changed,group=self.group)

    # ==========================================
    # Function: Release editor widgets and restore an embedded full-screen reply layout.
    # Method: Return the right pane to mail and undo only maximization initiated here.
    # ==========================================
    def close(self):
        if self.closed:return
        if self.layout_scroll_timer:self.g.g_source_remove(self.layout_scroll_timer);self.layout_scroll_timer=0
        if getattr(self,'layout_size_timer',0):self.g.g_source_remove(self.layout_size_timer);self.layout_size_timer=0
        if self.restore_window:self.g.gtk_window_unmaximize(self.app.window)
        surface=self.surface_window;self.surface_window=None
        for picker in self.recipient_pickers:picker.close()
        self.history_view.close()
        super().close()
        if surface:self.g.gtk_widget_destroy(surface)
        self.app.clear_reply_reserve()
        self.app.update_reply_draft_cards()
        self.app.apply_layout()

    # ==========================================
    # Function: Expand or return the same inline editor without serializing its live buffer.
    # Method: Reparent one GTK form, retaining rich text, attachments, draft identity and callbacks.
    # ==========================================
    def toggle_surface(self):
        if not self.embedded:return
        if self.detached:self.attach_surface();return
        card=getattr(self.app,'conversation_cards',{}).get(self.reply.get('reply_source'))
        self.inline=bool(not self.inline and card)
        self.floating=False
        self.reparent_surface(card['reply_host'] if self.inline else self.app.widget('composer_host'))
        self.g.gtk_stack_set_visible_child_name(self.app.widget('reader_stack'),b'mail' if self.inline else b'composer')
        self.g.gtk_widget_show_all(self.window);self.app.apply_layout();self.size_surface();self.scroll_into_view()
        self.app.update_reply_draft_cards()

    # ==========================================
    # Function: Transfer one live editor between a box, overlay and native independent window.
    # Method: Hold a temporary strong reference while removing and adding its existing widget.
    # ==========================================
    def reparent_surface(self,parent,overlay=False):
        g=self.g;g.g_object_ref(self.window);current=g.gtk_widget_get_parent(self.window)
        if current:g.gtk_container_remove(current,self.window)
        if overlay:g.gtk_overlay_add_overlay(parent,self.window)
        else:g.gtk_container_add(parent,self.window)
        g.g_object_unref(self.window)

    # ==========================================
    # Function: Pop the same reply draft into an independently focusable native window.
    # Method: Reparent its exact form and TextBuffer rather than serializing a second draft.
    # ==========================================
    def detach_surface(self):
        if not self.embedded:return
        if self.detached:self.g.gtk_window_present(self.surface_window);return
        self.detached=True;self.floating=False;self.inline=False;g=self.g
        self.surface_window=g.gtk_window_new(0)
        from .windows_frame import bind_window_frame
        bind_window_frame(self.app,self.surface_window,self.group)
        g.gtk_window_set_title(self.surface_window,('TeleMail · '+(self.value('subject') or '撰写邮件')).encode())
        g.gtk_window_set_default_size(self.surface_window,760,640);g.gtk_window_set_application(self.surface_window,self.app.application)
        from .desktop_preferences import resolved_theme
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.surface_window),resolved_theme(self.app).encode())
        g.connect(self.surface_window,'delete-event',self.on_delete,count=3,group=self.group,returns=True)
        self.reparent_surface(self.surface_window);self.app.clear_reply_reserve()
        g.gtk_stack_set_visible_child_name(self.app.widget('reader_stack'),b'mail')
        self.size_surface();g.gtk_widget_show_all(self.surface_window);g.gtk_window_present(self.surface_window)
        self.app.update_reply_draft_cards();self.app.apply_layout()

    # ==========================================
    # Function: Return an independent editor directly beneath its original conversation message.
    # Method: Transfer the same live form before destroying only the now-empty native window.
    # ==========================================
    def attach_surface(self):
        if not self.detached:return
        source=self.reply.get('reply_source');card=getattr(self.app,'conversation_cards',{}).get(source)
        self.detached=False;self.inline=bool(card);self.floating=False
        surface=self.surface_window;self.surface_window=None
        self.reparent_surface(card['reply_host'] if self.inline else self.app.widget('composer_host'))
        self.g.gtk_widget_destroy(surface)
        self.g.gtk_stack_set_visible_child_name(self.app.widget('reader_stack'),b'mail' if self.inline else b'composer')
        self.g.gtk_widget_show_all(self.window);self.size_surface();self.scroll_into_view();self.app.update_reply_draft_cards();self.app.apply_layout()

    # ==========================================
    # Function: Close an unsent native editor safely.
    # Method: Ignore close while a submission is pending and otherwise release the form.
    # ==========================================
    def on_delete(self, *unused):
        if not self.busy:
            if self.autosave(force=True) is False:return True
            self.close()
            self.app.composer = None
        return True

    # ==========================================
    # Function: Handle native editor response buttons.
    # Method: Validate attachments and schedule shared service mutations off the UI thread.
    # ==========================================
    def response(self, window, response, unused):
        response = int(response or 0)
        if self.busy:
            return
        if response not in (1,2,3,4,5,6,7,8,9,10,11,12,13,14,15):
            self.on_delete()
            return
        if response==13:self.toggle_surface();return
        if response==14:self.reveal_recipients();return
        if response==15:
            self.attach_surface() if self.detached else self.detach_surface();return
        if response in (11,12):
            from .scheduling import choose_schedule
            field='due' if response==11 else 'followup'
            current=self.value(field)
            if response==12 and not current:
                from datetime import timedelta
                try:base=datetime.fromisoformat(self.value('due'))
                except ValueError:base=datetime.now()
                current=(base+timedelta(days=self.app.service.store.preference('followup_days',3))).isoformat(timespec='minutes')
            value=choose_schedule(self.app,'稍后发送' if response==11 else '未回复提醒',current)
            if value is not None:self.value(field,value)
            if response==11 and value:self.response(window,2,unused)
            return
        if response==10:
            self.discard();return
        if response in (7,8,9):
            self.rich.toggle({7:'bold',8:'italic',9:'underline'}[response]);self.draft_changed();return
        if response==4:
            self.template_dialog();return
        if response==5:
            from .desktop_settings import signature_for
            signature=signature_for(self.app.service.store,self.value('account'))
            if signature:self.rich.replace_suffix('','\n\n-- \n'+signature)
            return
        if response==6:
            self.remove_attachment();return
        if response == 3:
            filename = self.g.choose(self.app.window if self.embedded else self.window, '添加附件')
            if filename:
                if filename.stat().st_size > MAX_MESSAGE_BYTES or len(self.attachments) >= 20:
                    self.g.label(self.note, '附件最多 20 个，单封邮件总大小上限 30 MiB')
                    return
                self.attachments.append({'name': filename.name, 'base64': base64.b64encode(filename.read_bytes()).decode()})
                self.refresh_chips();self.size_surface();self.draft_changed()
            return
        try:
            payload = {key:self.value(key) for key in ('account','to','cc','bcc','subject','body')}
            payload['html']=self.rich.html()
            payload.update({'id':self.identity, 'attachments':self.attachments,'editor_baseline':self.editor_baseline, **self.reply})
            if response==1:
                from .draft_content import has_draft_content
                if not has_draft_content(payload):
                    self.app.service.store.delete_draft(self.identity);self.close();self.app.composer=None;self.app.refresh();return
            if response==2:
                payload['due']=time.time()+int(self.app.service.store.preference('undo_send_seconds',10))
            from .scheduling import schedule_timestamp
            payload['scheduled_at']=self.value('due').strip()
            if payload['scheduled_at'] and response==2:payload['due']=schedule_timestamp(payload['scheduled_at'])
            if self.value('followup').strip():payload['remind_at']=schedule_timestamp(self.value('followup'))
            self.busy = True
            self.g.gtk_widget_set_sensitive(self.save_button, 0)
            self.g.gtk_widget_set_sensitive(self.send_button, 0)
            self.app.background(lambda:self.app.service.compose(payload, send=response == 2), self.saved, self.failed)
        except (ValueError, OSError) as error:
            self.failed(error)

    # ==========================================
    # Function: Commit the editor result to the visible desktop state.
    # Method: Close only after the durable draft/outbox operation succeeds.
    # ==========================================
    def saved(self, result):
        self.busy = False
        self.close()
        self.app.composer = None
        self.app.message('邮件已排队，可在“草稿 / 发件箱”中撤销发送' if result['state'] == 'queued' else '草稿已保存')
        self.app.refresh()

    # ==========================================
    # Function: Keep a failed editor open for correction.
    # Method: Re-enable buttons and display the bounded service error.
    # ==========================================
    def failed(self, error):
        self.busy = False
        if not self.closed:
            self.g.gtk_widget_set_sensitive(self.save_button, 1)
            self.account_changed()
            self.set_draft_state('error',str(error))

    # ==========================================
    # Function: Select an attachment for removal before saving or sending.
    # Method: Remove exactly one indexed payload from the current editor state.
    # ==========================================
    def remove_attachment(self):
        if not self.attachments:
            self.g.label(self.note,'没有附件');return
        form=Form(self.app,'移除附件',[('attachment','附件','combo',[(str(i),a['name']) for i,a in enumerate(self.attachments)])],540)
        form.value('attachment','0');form.button('取消',-6);form.button('移除',1)
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);index=form.value('attachment');form.close()
        if response==1:
            del self.attachments[int(index)]
            self.refresh_chips();self.size_surface();self.draft_changed()

    # ==========================================
    # Function: Apply/save/edit/delete reusable personal composer templates.
    # Method: Keep template definitions separate from drafts and never send on application.
    # ==========================================
    def template_dialog(self):
        templates=self.app.service.store.templates()
        form=Form(self.app,'邮件模板',[('template','选择模板','combo',[('new','保存当前邮件为新模板')]+[(r['id'],r['name']) for r in templates]),('name','模板名称','text',[])],620)
        form.value('template','new');form.value('name',self.value('subject'))
        form.button('关闭',-6);form.button('删除',3);form.button('保存当前内容',2);form.button('应用模板',1)
        self.g.label(form.note,'保存会使用当前编辑器的主题和正文；应用模板会替换主题和正文。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);identity=form.value('template');name=form.value('name');form.close()
        if response==1:
            item=next((r for r in templates if r['id']==identity),None)
            if item:
                from .composer_options import render_template
                account=self.app.service.accounts.get(self.value('account'))
                values={'name':account.display_name if account else '', 'email':account.email if account else '',
                    'date':datetime.now().strftime('%Y-%m-%d'),'recipient':self.value('to')}
                content,missing=render_template(item,values)
                if missing:
                    variables=Form(self.app,'填写模板变量',[('var'+str(i),name,'text',[]) for i,name in enumerate(missing)],620)
                    variables.button('取消',-6);variables.button('应用模板',1);self.g.gtk_widget_show_all(variables.window)
                    answer=self.g.gtk_dialog_run(variables.window)
                    if answer==1:values.update({name:variables.value('var'+str(i)) for i,name in enumerate(missing)})
                    variables.close()
                    if answer!=1:return
                    content,_=render_template(item,values)
                self.value('subject',content['subject']);self.value('body',content['body']);self.signature_managed=False
        elif response==2:
            self.app.service.store.save_template(name,self.value('subject'),self.value('body'),None if identity=='new' else identity)
        elif response==3 and identity!='new':self.app.service.store.delete_template(identity)

    # ==========================================
    # Function: Expose the durable state of the single live draft in its native editor.
    # Method: Change status only on an edit or a confirmed local persistence outcome.
    # ==========================================
    def set_draft_state(self,state,message):
        self.draft_state=state;self.g.label(self.note,message)

    # ==========================================
    # Function: Mark unsaved field and body changes without saving every keystroke.
    # Method: Reuse the bounded autosave timer and retain errors until the user makes another edit.
    # ==========================================
    def draft_changed(self,*unused):
        if not self.closed and not self.busy:self.set_draft_state('dirty','正在撰写 · 等待保存到本机')

    # ==========================================
    # Function: Persist removal of the attached history from the full editor's draft.
    # Method: Save an explicit empty history while retaining the original reply linkage and authored content.
    # ==========================================
    def remove_reply_history(self):
        if self.closed or self.busy:return False
        self.reply['reply_history']={};self.last_snapshot='';self.draft_changed();return True

    # ==========================================
    # Function: Persist changed unsent editor contents automatically and on close.
    # Method: Save locally at a bounded interval using the same stable draft identifier.
    # ==========================================
    def autosave(self,force=False):
        if self.busy:return False
        if self.closed or (not force and time.monotonic()-self.last_autosave<4):return True
        self.last_autosave=time.monotonic()
        payload={key:self.value(key) for key in ('account','to','cc','bcc','subject','body')}
        payload.update({'id':self.identity,'attachments':self.attachments,'html':self.rich.html(),'scheduled_at':self.value('due'),'editor_baseline':self.editor_baseline,**self.reply})
        from .draft_content import has_draft_content
        if not has_draft_content(payload):
            try:self.app.service.store.delete_draft(self.identity)
            except (ValueError,OSError,sqlite3.Error) as error:self.set_draft_state('error','空白草稿清理未完成：'+str(error));return False
            self.last_snapshot='';self.set_draft_state('empty','空白草稿不会保存')
            self.app.update_reply_draft_cards();return True
        if self.value('followup').strip():
            try:payload['remind_at']=datetime.fromisoformat(self.value('followup')).timestamp()
            except ValueError:pass
        snapshot=json.dumps(payload,sort_keys=True)
        if snapshot==self.last_snapshot:
            self.set_draft_state('saved','已保存到本机');return True
        try:
            self.app.service.compose(payload)
            self.last_snapshot=snapshot
            self.set_draft_state('saved','已保存到本机 · '+datetime.now().strftime('%H:%M:%S'))
            self.app.update_reply_draft_cards()
            return True
        except (ValueError,OSError,sqlite3.Error) as error:
            self.set_draft_state('error','自动保存未完成：'+str(error))
            return False

    # ==========================================
    # Function: Discard an unsent draft after an explicit native confirmation.
    # Method: Keep the editor open on cancellation and remove only its stable draft ID.
    # ==========================================
    def discard(self):
        form=Form(self.app,'放弃草稿',[],480);form.button('保留',-6);form.button('放弃草稿',1)
        self.g.label(form.note,'将删除当前未发送的草稿内容。')
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window);form.close()
        if response==1:
            self.app.service.store.delete_draft(self.identity);self.close();self.app.composer=None;self.app.refresh()

    # ==========================================
    # Function: Enable sending only for a real configured provider account.
    # Method: Local drafts remain editable offline; account changes update native controls.
    # ==========================================
    def account_changed(self,*unused):
        if hasattr(self,'rich') and self.value('account')!=self.signature_account and self.signature_managed:
            from .desktop_settings import signature_for
            new=signature_for(self.app.service.store,self.value('account'))
            old_suffix='\n\n-- \n'+self.applied_signature if self.applied_signature else '';new_suffix='\n\n-- \n'+new if new else ''
            self.signature_managed=self.rich.replace_suffix(old_suffix,new_suffix)
            baseline=self.editor_baseline.get('body','')
            if self.signature_managed and (not old_suffix or baseline.endswith(old_suffix)):self.editor_baseline['body']=(baseline[:-len(old_suffix)] if old_suffix else baseline)+new_suffix
            self.applied_signature=new;self.signature_account=self.value('account')
        if hasattr(self,'account_label'):
            account=next((a for a in self.app.service.accounts.values() if a.id==self.value('account')),None)
            self.g.label(self.account_label,account.email if account else '演示账户' if self.app.profile.demo else '选择发件账户')
        allowed=not self.app.profile.demo and self.value('account') in self.app.service.accounts and not self.busy
        self.g.gtk_widget_set_sensitive(self.send_button,int(allowed))
        self.g.gtk_widget_set_sensitive(self.later_button,int(allowed))
        if self.value('account')==LOCAL_ACCOUNT:
            self.g.label(self.note,'本地草稿保存在此电脑。发送前请添加并选择邮箱账户。')
