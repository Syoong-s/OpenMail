"""Docked mail composer with one durable, contact-scoped draft identity."""
import base64
import ctypes as C
import json
from pathlib import Path
import time
import uuid
from .desktop_general import bind,P,I
from .draft_content import has_draft_content
from .local_mail import LOCAL_ACCOUNT
from .mime import MAX_MESSAGE_BYTES

# ==========================================
# Function: Edit real mail in a compact persistent chat footer.
# Method: Own a separate TextBuffer and serialize shared-service draft/outbox operations.
# ==========================================
class ChatComposer:
    # ==========================================
    # Function: Restore one contact's exact saved draft and explicit routing decision.
    # Method: Use a full worker-loaded job; retain all attachment payloads and metadata.
    # ==========================================
    def __init__(self,app,key,route,job=None):
        self.app=app;self.g=g=app.g;self.key=key;self.group='chat-composer';self.busy=False;self.closed=False;self.last_save=time.monotonic();self.snapshot='';self.error='';self.revision=0;self.saved_revision=-1;self.saving=False
        self.expanded=False;self.send_armed=False;self.send_pressed_compact=False;self.animation_source=0;self.animation_started=0;self.body_height=25;self.focus_source=0;self.focus_hold=0;self.deactivated=False;self.body_size_source=0;self.recipient_pickers=[]
        draft=dict(job['draft']) if job else {};self.identity=job['id'] if job else uuid.uuid4().hex
        self.route=json.loads(draft['chat_route']) if draft.get('chat_route') else dict(route)
        self.attachments=list(draft.get('attachments',[]));self.metadata={name:draft.get(name,'') for name in ('in_reply_to','references','reply_source')}
        self.metadata.update({name:draft[name] for name in ('scheduled_at','remind_at','done_after_send','request_receipt') if name in draft})
        if not job:self.metadata.update(in_reply_to=route.get('in_reply_to',''),reply_source=route.get('message',''))
        source=next((item for item in app.chat_items if item['id']==route.get('message')),None)
        if not job and source:
            parsed=source['parsed'];self.metadata['references']=' '.join(parsed.get('references',[])+[parsed.get('message_id','')]).strip()
        self.root=g.gtk_box_new(1,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.root),b'chat-composer')
        self.bubble=g.gtk_box_new(1,4);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.bubble),b'chat-compose-bubble');g.gtk_box_pack_start(self.root,self.bubble,0,1,0)
        self.top_revealer=g.gtk_revealer_new();g.gtk_box_pack_start(self.bubble,self.top_revealer,0,1,0)
        g.gtk_revealer_set_transition_duration(self.top_revealer,180 if getattr(app,'motion',True) else 0)
        top=g.gtk_box_new(0,6);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(top),b'chat-compose-top');g.gtk_container_add(self.top_revealer,top)
        self.account=g.gtk_combo_box_text_new();self.accounts=self.account_choices()
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.account),b'chat-compose-account')
        for identity,title in self.accounts:g.gtk_combo_box_text_append(self.account,identity.encode(),title.encode())
        chosen=(job['account'] if job else route.get('account',''))
        if chosen not in dict(self.accounts):chosen=LOCAL_ACCOUNT if not app.profile.demo else 'demo'
        g.gtk_combo_box_set_active_id(self.account,chosen.encode())
        self.summary=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.summary,0);g.gtk_label_set_ellipsize(self.summary,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.summary),b'chat-compose-summary');g.gtk_box_pack_start(top,self.summary,1,1,0)
        self.action(top,'完整编辑器','composer-expand',self.full_editor)
        self.fields={};self.field_rows={}
        for name,title in [('to','收件人'),('cc','抄送'),('subject','主题')]:
            entry=g.gtk_entry_new();self.fields[name]=entry;g.gtk_style_context_add_class(g.gtk_widget_get_style_context(entry),b'chat-compose-field')
            default=', '.join(route.get(name,[])) if name in ('to','cc') else route.get('subject','')
            if name=='subject' and default and not default.lower().startswith('re:'):default='Re: '+default
            g.text(entry,draft.get(name,default));g.gtk_entry_set_placeholder_text(entry,title.encode())
            row=g.gtk_box_new(0,5);self.field_rows[name]=row;g.gtk_widget_set_no_show_all(row,1);g.gtk_box_pack_start(self.bubble,row,0,1,0);g.gtk_box_pack_start(row,entry,1,1,0)
            if name in ('to','cc'):
                from .recipient_picker import RecipientPicker
                self.recipient_pickers.append(RecipientPicker(self,entry,row))
        self.bcc=draft.get('bcc','');self.html=draft.get('html','')
        if not job and not self.route.get('safe'):
            source=next((item for item in app.chat_items if item['id']==route.get('message')),None)
            if source:
                parsed=source['parsed'];headers=parsed.get('headers',{})
                if not source['outgoing'] and headers.get('reply-to'):g.text(self.fields['to'],headers['reply-to'])
                if source['outgoing']:self.bcc=headers.get('bcc','')
        self.baseline=dict(draft.get('editor_baseline',{}))
        body=draft.get('body','')
        if not job:
            from .desktop_settings import signature_for
            signature=signature_for(app.service.store,chosen)
            body='\n\n-- \n'+signature if signature else ''
            self.baseline={name:g.text(entry) for name,entry in self.fields.items()};self.baseline.update(bcc=self.bcc,body=body)
        self.chips=g.gtk_box_new(1,2);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.chips),b'chat-compose-chips');g.gtk_box_pack_start(self.bubble,self.chips,0,1,0)
        scroll=g.gtk_scrolled_window_new(None,None);self.body_scroll=scroll;g.gtk_scrolled_window_set_policy(scroll,1,1);g.gtk_widget_set_size_request(scroll,-1,25);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(scroll),b'chat-compose-scroll')
        self.body=bind(app,'gtk','gtk_text_view_new',P)();bind(app,'gtk','gtk_text_view_set_wrap_mode',None,P,I)(self.body,3)
        for side in ('left','right'):
            bind(app,'gtk','gtk_text_view_set_'+side+'_margin',None,P,I)(self.body,2)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.body),b'chat-compose-body')
        g.text(self.body,body,view=True);g.gtk_container_add(scroll,self.body)
        body_overlay=g.gtk_overlay_new();g.gtk_container_add(body_overlay,scroll);g.gtk_box_pack_start(self.bubble,body_overlay,0,1,0)
        self.placeholder=g.gtk_label_new('撰写回复…'.encode());g.gtk_label_set_xalign(self.placeholder,0);g.gtk_widget_set_halign(self.placeholder,1);g.gtk_widget_set_valign(self.placeholder,1);g.gtk_widget_set_margin_start(self.placeholder,3);g.gtk_widget_set_margin_top(self.placeholder,2);g.gtk_widget_set_no_show_all(self.placeholder,1)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.placeholder),b'chat-compose-placeholder');g.gtk_overlay_add_overlay(body_overlay,self.placeholder);bind(app,'gtk','gtk_overlay_set_overlay_pass_through',None,P,P,I)(body_overlay,self.placeholder,1)
        from .reply_history import ReplyHistoryView,from_message,validated
        original=next((item for item in app.chat_items if item['id']==self.metadata.get('reply_source')),None)
        self.metadata['reply_history']=validated(draft.get('reply_history')) if job else from_message(original) if original else {}
        self.history_view=ReplyHistoryView(self,self.bubble,self.metadata['reply_history']);self.history_view.set_visible(False)
        footer=g.gtk_box_new(0,7);self.footer=footer;g.gtk_widget_set_no_show_all(footer,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(footer),b'chat-compose-toolbar');g.gtk_box_pack_start(self.bubble,footer,0,1,0)
        self.action(footer,'添加附件','composer-attachment',self.add_attachment)
        self.action(footer,'收件人 / 主题','action-down',self.edit_route)
        self.note=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.note,0);g.gtk_label_set_ellipsize(self.note,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.note),b'chat-compose-note');g.gtk_box_pack_start(footer,self.note,1,1,0)
        g.gtk_box_pack_start(footer,self.account,0,1,0)
        from .sender_choice import SenderChoice
        self.account_choice=SenderChoice(app,self.account,self.body)
        self.send_button=self.action(footer,'发送邮件 · Ctrl+Enter','composer-send',self.send)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.send_button),b'chat-compose-send')
        g.connect(self.send_button,'button-press-event',self.send_press,count=3,group=self.group,returns=True)
        g.connect(self.account,'changed',self.account_changed,group=self.group)
        g.connect(self.body,'key-press-event',self.key_pressed,count=3,group=self.group,returns=True)
        g.connect(self.body,'focus-in-event',self.expand_on_focus,count=3,group=self.group,returns=True)
        g.connect(self.body,'button-press-event',self.expand_on_focus,count=3,group=self.group,returns=True)
        g.connect(self.body_scroll,'button-press-event',self.expand_on_focus,count=3,group=self.group,returns=True)
        self.pointer_gesture=g.gtk_gesture_multi_press_new(app.window);g.gtk_gesture_single_set_button(self.pointer_gesture,0);g.gtk_event_controller_set_propagation_phase(self.pointer_gesture,1)
        g.connect(self.pointer_gesture,'pressed',self.pointer_pressed,types=[P,I,C.c_double,C.c_double,P],group=self.group)
        g.connect(app.window,'set-focus',self.focus_changed,count=3,group=self.group)
        g.connect(app.window,'focus-out-event',self.window_focus_out,count=3,group=self.group,returns=True)
        g.connect(app.window,'focus-in-event',self.window_focus_in,count=3,group=self.group,returns=True)
        g.connect(self.body,'size-allocate',lambda *unused:self.queue_body_size(),count=3,group=self.group)
        g.connect(g.gtk_text_view_get_buffer(self.body),'changed',self.changed,group=self.group)
        for entry in self.fields.values():g.connect(entry,'changed',self.field_changed,group=self.group)
        self.signature_account=chosen;self.signature_managed=not bool(job);self.signature_suffix=self.baseline.get('body','') if not job else ''
        self.refresh_chips();self.update_state();g.gtk_widget_show_all(self.root)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.root),b'chat-compose-collapsed')
        g.gtk_revealer_set_reveal_child(self.top_revealer,0)

    # ==========================================
    # Function: Expand the compact bubble on native pointer or keyboard focus.
    # Method: Preserve the TextBuffer and let GTK dispatch the original input event.
    # ==========================================
    def expand_on_focus(self,*unused):
        self.expand()
        self.send_armed=True
        return False

    # ==========================================
    # Function: Drop editor focus when a pointer lands on nonfocusable workspace background.
    # Method: Observe capture coordinates without claiming input; preserve clicks within owned popups.
    # ==========================================
    def pointer_pressed(self,gesture,count,x,y,data):
        if self.closed or not self.expanded or self.focus_hold:return
        g=self.g;left,top=I(),I()
        if not g.gtk_widget_translate_coordinates(self.root,self.app.window,0,0,C.byref(left),C.byref(top)):return
        if left.value<=x<left.value+g.gtk_widget_get_allocated_width(self.root) and top.value<=y<top.value+g.gtk_widget_get_allocated_height(self.root):return
        surfaces=getattr(g,'surfaces',None)
        if surfaces:
            for key in surfaces.opened:
                state=surfaces.states[key]
                if state['root']!=self.app.window:continue
                frame=state['frame'];px,py=I(),I()
                if g.gtk_widget_translate_coordinates(frame,self.app.window,0,0,C.byref(px),C.byref(py)) and px.value<=x<px.value+g.gtk_widget_get_allocated_width(frame) and py.value<=y<py.value+g.gtk_widget_get_allocated_height(frame):return
        if self.busy and not self.saving:return
        bind(self.app,'gtk','gtk_window_set_focus',None,P,P)(self.app.window,None)
        self.set_expanded(False)

    # ==========================================
    # Function: Remember that a Send press began without reviewed recipient context.
    # Method: Latch before GTK's default focus/activation handlers can expand the bubble.
    # ==========================================
    def send_press(self,*unused):
        self.send_pressed_compact=not self.expanded or not self.send_armed
        return False

    # ==========================================
    # Function: Defer composer collapse until native focus has settled across the entire subtree.
    # Method: Coalesce window focus signals into one owned timeout, including pointer toolbar actions.
    # ==========================================
    def focus_changed(self,*unused):
        if self.closed:return
        if self.focus_source:self.g.g_source_remove(self.focus_source)
        self.focus_callback=C.CFUNCTYPE(I,P)(self.check_focus)
        self.focus_source=self.g.g_timeout_add(100,C.cast(self.focus_callback,P),None)

    # ==========================================
    # Function: Collapse predictably when another application owns the active window.
    # Method: Delay deactivation until dialogs/grabs and composer action callbacks settle.
    # ==========================================
    def window_focus_out(self,*unused):
        self.deactivated=True;self.focus_changed();return False

    # ==========================================
    # Function: Re-evaluate the actual composer descendant when this window becomes active.
    # Method: Clear deactivation state before scheduling the same subtree focus check.
    # ==========================================
    def window_focus_in(self,*unused):
        self.deactivated=False;self.focus_changed();return False

    # ==========================================
    # Function: Expand within the composer and reclaim its added size on departure.
    # Method: Walk native widget ancestry; protect synchronous owned dialogs and explicit sends.
    # ==========================================
    def check_focus(self,*unused):
        self.focus_source=0
        if self.closed or self.focus_hold:return 0
        focus=self.g.gtk_window_get_focus(self.app.window)
        surfaces=self.g.surfaces
        for key in surfaces.opened:
            state=surfaces.states[key];anchor=state.get('anchor')
            if anchor and (anchor==self.root or self.g.gtk_widget_is_ancestor(anchor,self.root)):return 0
        inside=bool(focus and (focus==self.root or self.g.gtk_widget_is_ancestor(focus,self.root)))
        if inside and not self.deactivated:
            self.expand()
            if focus!=self.send_button:self.send_armed=True
        elif not self.busy or self.saving:self.set_expanded(False)
        return 0

    # ==========================================
    # Function: Reveal sender and recipient context before editing or explicit send.
    # Method: Delegate both directions to one reversible, size-only animation owner.
    # ==========================================
    def expand(self):
        self.set_expanded(True)

    # ==========================================
    # Function: Animate compact and expanded composer dimensions without touching authored state.
    # Method: Reverse from the current requested body height and own at most one GLib source.
    # ==========================================
    def set_expanded(self,expanded):
        if self.closed or self.expanded==expanded:return
        self.expanded=expanded;g=self.g
        if not expanded:self.send_armed=False;self.send_pressed_compact=False
        if self.animation_source:g.g_source_remove(self.animation_source);self.animation_source=0
        bubble_context=g.gtk_widget_get_style_context(self.bubble)
        (g.gtk_style_context_add_class if expanded else g.gtk_style_context_remove_class)(bubble_context,b'compose-active')
        context=g.gtk_widget_get_style_context(self.root)
        (g.gtk_style_context_remove_class if expanded else g.gtk_style_context_add_class)(context,b'chat-compose-collapsed')
        if expanded:
            g.gtk_widget_set_no_show_all(self.footer,0);g.gtk_widget_show_all(self.footer);g.gtk_widget_set_no_show_all(self.footer,1)
        else:g.gtk_widget_hide(self.footer)
        self.history_view.set_visible(expanded)
        if not expanded and self.history_view.expanded:self.history_view.toggle()
        if not expanded:
            for widget in self.field_rows.values():g.gtk_widget_hide(widget)
        motion=bool(getattr(self.app,'motion',True));g.gtk_revealer_set_transition_duration(self.top_revealer,180 if motion else 0)
        g.gtk_revealer_set_reveal_child(self.top_revealer,int(expanded));self.update_state()
        self.animation_from=self.body_height;self.animation_target=self.content_height() if expanded else 25
        if not motion:
            self.body_height=self.animation_target;g.gtk_widget_set_size_request(self.body_scroll,-1,self.body_height);return
        self.animation_started=time.monotonic();self.animation_callback=C.CFUNCTYPE(I,P)(self.animate_body)
        self.animation_source=g.g_timeout_add(16,C.cast(self.animation_callback,P),None)

    # ==========================================
    # Function: Advance only this composer's requested body height in either direction.
    # Method: Finish after 180 ms and clear source ownership before native destruction.
    # ==========================================
    def animate_body(self,*unused):
        if self.closed:self.animation_source=0;return 0
        fraction=min(1,(time.monotonic()-self.animation_started)/.18)
        self.body_height=round(self.animation_from+(self.animation_target-self.animation_from)*(1-(1-fraction)**2))
        self.g.gtk_widget_set_size_request(self.body_scroll,-1,self.body_height)
        if fraction>=1:self.animation_source=0;return 0
        return 1

    # ==========================================
    # Function: Measure actual visual text lines, including wrapping, without replacing the native buffer.
    # Method: Read the last GTK layout rectangle and cap the body to a fraction of the window height.
    # ==========================================
    def content_height(self):
        end=(C.c_uint64*16)();rect=(I*4)();buffer=self.g.gtk_text_view_get_buffer(self.body)
        bind(self.app,'gtk','gtk_text_buffer_get_end_iter',None,P,P)(buffer,end)
        bind(self.app,'gtk','gtk_text_view_get_iter_location',None,P,P,P)(self.body,end,rect)
        limit=max(90,min(220,self.g.gtk_widget_get_allocated_height(self.app.window)//3))
        return min(limit,max(25,rect[1]+rect[3]+4))

    # ==========================================
    # Function: Reflow only after GTK has processed text and width changes.
    # Method: Coalesce typing/paste/allocation into a single owned short timeout.
    # ==========================================
    def queue_body_size(self):
        if self.closed or self.body_size_source:return
        self.body_size_callback=C.CFUNCTYPE(I,P)(self.resize_body)
        self.body_size_source=self.g.g_timeout_add(30,C.cast(self.body_size_callback,P),None)

    # ==========================================
    # Function: Grow or shrink the reply body with rendered lines while retaining a scrollable upper bound.
    # Method: Change only its height request; retarget an active expansion animation if necessary.
    # ==========================================
    def resize_body(self,*unused):
        self.body_size_source=0
        if self.closed:return 0
        target=self.content_height() if self.expanded else 25
        if self.animation_source:self.animation_target=target
        elif target!=self.body_height:
            self.body_height=target;self.g.gtk_widget_set_size_request(self.body_scroll,-1,target)
        return 0

    # ==========================================
    # Function: Present all configured senders while retaining account-free draft storage.
    # Method: Keep paused identities selectable; service policy remains authoritative on send.
    # ==========================================
    def account_choices(self):
        return [('demo','演示邮箱')] if self.app.profile.demo else [(a.id,a.email) for a in self.app.service.accounts.values()]+[(LOCAL_ACCOUNT,'本地草稿')]

    # ==========================================
    # Function: Add a compact native icon action with owned callbacks.
    # Method: Route failures through the application's existing guarded action boundary.
    # ==========================================
    def action(self,host,title,icon,callback):
        from .ui_actions import icon_action
        button=self.g.gtk_button_new();icon_action(self.g,button,title,icon,17);self.g.gtk_box_pack_start(host,button,0,0,0)
        self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(button),b'chat-compose-action')
        self.g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=self.group);return button

    # ==========================================
    # Function: Preserve newline entry and require a deliberate send shortcut.
    # Method: Consume only Control+Return and delegate it to the same explicit send action.
    # ==========================================
    def key_pressed(self,widget,event,unused):
        key,state=C.c_uint(),C.c_uint();self.g.gdk_event_get_keyval(event,C.byref(key));self.g.gdk_event_get_state(event,C.byref(state))
        if state.value&4 and key.value in (65293,65421):self.app.run_action(self.send);return True
        return False

    # ==========================================
    # Function: Discard stale rich markup after the plain body is authored.
    # Method: Keep full-editor HTML intact only while its exact text remains unchanged.
    # ==========================================
    def changed(self,*unused):
        self.html='';self.error='';self.revision+=1;self.update_state();self.queue_body_size()

    # ==========================================
    # Function: Mark envelope edits dirty without discarding unchanged rich body markup.
    # Method: Track one revision while retaining HTML until the body itself is edited.
    # ==========================================
    def field_changed(self,*unused):
        self.error='';self.revision+=1;self.update_state()

    # ==========================================
    # Function: Persist explicit removal of this draft's attached original history.
    # Method: Dirty the metadata revision without changing rich authored text, recipients or attachments.
    # ==========================================
    def remove_reply_history(self):
        if self.closed or (self.busy and not self.saving):return False
        self.metadata['reply_history']={};self.snapshot='';self.field_changed();return True

    # ==========================================
    # Function: Apply the selected sender's signature while preserving authored body text.
    # Method: Replace only the exact generated suffix and keep its empty-draft baseline aligned.
    # ==========================================
    def account_changed(self,*unused):
        account=(self.g.gtk_combo_box_get_active_id(self.account) or b'').decode()
        if self.signature_managed and account!=self.signature_account:
            from .desktop_settings import signature_for
            body=self.g.text(self.body,view=True);old=self.signature_suffix;signature=signature_for(self.app.service.store,account);new='\n\n-- \n'+signature if signature else ''
            if not old or body.endswith(old):
                self.g.text(self.body,(body[:-len(old)] if old else body)+new,view=True)
                baseline=self.baseline.get('body','')
                if not old or baseline.endswith(old):self.baseline['body']=(baseline[:-len(old)] if old else baseline)+new
                self.signature_suffix=new
            else:self.signature_managed=False
            self.signature_account=account
        self.field_changed()

    # ==========================================
    # Function: Expose the actual sender and exact visible mail recipients.
    # Method: Keep unsafe inherited routes blocked until reviewed in the full editor.
    # ==========================================
    def update_state(self):
        self.g.gtk_widget_set_visible(self.placeholder,not bool(self.g.text(self.body,view=True)))
        account=(self.g.gtk_combo_box_get_active_id(self.account) or b'').decode();to=self.g.text(self.fields['to']);cc=self.g.text(self.fields['cc'])
        text='To: '+(to or '未选择')+(' · Cc: '+cc if cc else '')+' · '+self.g.text(self.fields['subject'])
        self.g.label(self.summary,text);self.g.gtk_widget_set_tooltip_text(self.summary,text.encode())
        if self.bcc:text+=' · 有密送（完整编辑器核对）';self.g.label(self.summary,text)
        planned=bool(self.metadata.get('scheduled_at') or self.metadata.get('remind_at'))
        if planned:
            plan=('计划 '+str(self.metadata['scheduled_at']) if self.metadata.get('scheduled_at') else '')+(' · 有未回复提醒' if self.metadata.get('remind_at') else '')
            text+=' · '+plan;self.g.label(self.summary,text);self.g.gtk_widget_set_tooltip_text(self.summary,text.encode())
        allowed=self.route.get('safe',False) and not self.bcc and not planned and account in self.app.service.accounts and not self.app.profile.demo and not self.busy
        self.g.gtk_widget_set_sensitive(self.send_button,allowed);self.g.gtk_widget_set_sensitive(self.body,not self.busy or self.saving)
        self.g.label(self.note,self.error or ('已保留发送计划 / 提醒' if planned else '请核对收件人' if not self.route.get('safe') else ''))

    # ==========================================
    # Function: Assemble the complete durable draft with explicit contact provenance.
    # Method: Preserve stable identity, baseline, attachments and route through full-editor handoff.
    # ==========================================
    def payload(self):
        account=(self.g.gtk_combo_box_get_active_id(self.account) or b'').decode()
        return {**{key:self.g.text(widget) for key,widget in self.fields.items()},'account':account,'bcc':self.bcc,'body':self.g.text(self.body,view=True),'html':self.html,'id':self.identity,'attachments':list(self.attachments),'editor_baseline':self.baseline,'chat_key':self.key,'chat_route':json.dumps(self.route,ensure_ascii=False),**self.metadata}

    # ==========================================
    # Function: Save locally at a bounded interval and refuse navigation on failure.
    # Method: Serialize against send; force saves complete before any editor is released.
    # ==========================================
    def autosave(self,force=False):
        if self.closed:return True
        if self.busy:return False
        if self.revision==self.saved_revision:return True
        if not force and time.monotonic()-self.last_save<4:return True
        self.last_save=time.monotonic();payload=self.payload();revision=self.revision
        if payload['account'] not in self.app.service.accounts and not self.app.profile.demo:payload['account']=LOCAL_ACCOUNT
        # ==========================================
        # Function: Validate and persist one immutable draft snapshot away from GTK.
        # Method: Skip all repeated base64/JSON work while the live revision is unchanged.
        # ==========================================
        def operation():
            if has_draft_content(payload):return self.app.service.compose(payload)
            return self.app.service.store.delete_draft(self.identity)
        # ==========================================
        # Function: Commit a successful local snapshot without erasing newer typing.
        # Method: Mark only the captured revision saved and retain the same live TextBuffer.
        # ==========================================
        def saved(result):
            self.busy=False;self.saving=False;self.saved_revision=revision;self.error='';self.update_state()
        # ==========================================
        # Function: Retain authored contents when a background save fails.
        # Method: Leave its revision dirty and refuse navigation until a later save succeeds.
        # ==========================================
        def failed(error):
            self.busy=False;self.saving=False;self.error='草稿未保存：'+str(error);self.update_state();self.app.message(self.error)
        if not force:
            self.busy=True;self.saving=True;self.update_state();self.app.background(operation,saved,failed);return True
        try:operation();saved(None);return True
        except Exception as error:failed(error);return False

    # ==========================================
    # Function: Enqueue exactly one explicit mail send through the existing durable service.
    # Method: Disable repeat submissions and clear authored content only after a queued result.
    # ==========================================
    def send(self):
        if self.busy or self.closed:return
        # Function: Reveal the exact recipients before a compact draft can be sent.
        # Method: Consume this first action without enqueueing or changing the draft.
        if not self.expanded or not self.send_armed or self.send_pressed_compact:
            self.send_pressed_compact=False
            self.expand()
            self.send_armed=True
            return
        # A rapid follow-up during the reveal cannot confirm context still in motion.
        if self.animation_source:return
        payload=self.payload()
        if self.metadata.get('scheduled_at') or self.metadata.get('remind_at'):raise ValueError('已保留发送计划或未回复提醒，请在完整编辑器确认并发送')
        if not self.route.get('safe') or self.bcc:raise ValueError('请先在完整编辑器核对收件人')
        if self.app.profile.demo or payload['account'] not in self.app.service.accounts:raise ValueError('请选择可发送的邮箱账户')
        if not has_draft_content(payload):raise ValueError('请先输入邮件正文或添加附件')
        payload['due']=time.time()+int(self.app.service.store.preference('undo_send_seconds',10));self.busy=True;self.update_state()
        # ==========================================
        # Function: Commit only a confirmed durable enqueue to this live editor.
        # Method: Retain failed content and reset identity only after the service returns queued.
        # ==========================================
        def saved(result):
            self.busy=False
            if result.get('state')!='queued':self.failed(ValueError('邮件尚未进入发送队列'));return
            self.identity=uuid.uuid4().hex;self.attachments=[];self.g.text(self.body,self.baseline.get('body',''),view=True);self.html='';self.snapshot='';self.revision+=1;self.refresh_chips();self.update_state();self.app.message('邮件已排队；可在草稿与发件箱撤销');self.focus_changed();self.app.refresh()
        self.app.background(lambda:self.app.service.compose(payload,send=True),saved,self.failed)

    # ==========================================
    # Function: Keep authored text and attachments after a failed durable operation.
    # Method: Re-enable the existing buffer without replacing its draft identity.
    # ==========================================
    def failed(self,error):
        self.busy=False;self.error='未发送：'+str(error);self.update_state();self.focus_changed();self.app.message(self.error)

    # ==========================================
    # Function: Reveal editable exact recipients and subject in the docked composer.
    # Method: Never infer recipients from a contact title or hidden Bcc membership.
    # ==========================================
    def edit_route(self):
        self.expand()
        shown=not self.g.gtk_widget_get_visible(self.field_rows['to'])
        for row in self.field_rows.values():
            if shown:
                self.g.gtk_widget_set_no_show_all(row,0);self.g.gtk_widget_show_all(row);self.g.gtk_widget_set_no_show_all(row,1)
            else:self.g.gtk_widget_hide(row)

    # ==========================================
    # Function: Add bounded local attachment content to the real outgoing draft.
    # Method: Validate count and aggregate bytes before retaining the encoded payload.
    # ==========================================
    def add_attachment(self):
        if self.busy:return
        self.focus_hold+=1
        try:filename=self.g.choose(self.app.window,'添加附件')
        finally:self.focus_hold-=1;self.deactivated=False;self.focus_changed()
        if not filename:return
        filename=Path(filename);size=filename.stat().st_size
        if len(self.attachments)>=20 or size+sum(len(base64.b64decode(a['base64'])) for a in self.attachments)>MAX_MESSAGE_BYTES:raise ValueError('附件最多 20 个，总大小上限 30 MiB')
        self.attachments.append({'name':filename.name,'base64':base64.b64encode(filename.read_bytes()).decode()});self.refresh_chips();self.snapshot='';self.revision+=1

    # ==========================================
    # Function: Display removable attachment payloads independently of bubble palettes.
    # Method: Rebuild only the small chip list and retain complete base64 data in the model.
    # ==========================================
    def refresh_chips(self):
        self.g.disconnect('chat-chips');self.g.clear(self.chips)
        for index,item in enumerate(self.attachments):
            button=self.g.gtk_button_new_with_label((item['name']+'  ×').encode());self.g.gtk_box_pack_start(self.chips,button,0,1,0)
            self.g.connect(button,'clicked',lambda *unused,i=index:self.remove_attachment(i),group='chat-chips')
        self.g.gtk_widget_show_all(self.chips)

    # ==========================================
    # Function: Remove one explicitly chosen unsent attachment.
    # Method: Retain all remaining payloads and persist the change on the next save.
    # ==========================================
    def remove_attachment(self,index):
        if self.busy:return
        del self.attachments[index];self.snapshot='';self.revision+=1;self.refresh_chips()

    # ==========================================
    # Function: Transfer this same draft identity to the existing complete mail editor.
    # Method: Save first and release the dock only after persistence succeeds.
    # ==========================================
    def full_editor(self):
        if not self.autosave(force=True):return
        payload=self.payload();self.app.chat_handoff=True
        try:self.close();self.app.chat_composer=None;self.app.open_composer(payload)
        finally:self.app.chat_handoff=False

    # ==========================================
    # Function: Release only this footer's widgets and callback groups.
    # Method: Callers must save successfully before destroying the live buffer.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True
        if self.focus_source:self.g.g_source_remove(self.focus_source);self.focus_source=0
        if self.animation_source:self.g.g_source_remove(self.animation_source);self.animation_source=0
        if self.body_size_source:self.g.g_source_remove(self.body_size_source);self.body_size_source=0
        for picker in self.recipient_pickers:picker.close()
        self.history_view.close()
        self.g.disconnect(self.group);self.g.g_object_unref(self.pointer_gesture);self.g.disconnect('chat-chips');self.g.gtk_widget_destroy(self.root)
