"""Independent inbound/outbound contact chat with bounded local projections."""
import ctypes as C
from datetime import datetime
import json
import time
from .desktop_general import bind,P,I
from .contact_conversations import ContactConversations
from .message_style import message_text

# ==========================================
# Function: Read contact job identities from the compact index and unfinished legacy rows.
# Method: Scan old JSON only on a worker while migration is incomplete; hydrate one draft.
# ==========================================
def contact_jobs(db,key,include_draft=False):
    complete=bool(db.execute("SELECT 1 FROM address_migrations WHERE key='navigation-complete'").fetchone())
    indexed=db.execute("SELECT j.id,j.state,j.created,x.preview FROM chat_job_index x JOIN jobs j ON j.id=x.job WHERE x.chat_key=? AND j.state NOT IN ('draft','sent') ORDER BY j.created DESC LIMIT 30",(key,)).fetchall()
    pending=[dict(row) for row in indexed]
    if not complete:
        # The indexed side excludes these rows by identity, so a partially filled index cannot hide them.
        legacy=db.execute("SELECT j.id,j.state,j.created,substr(json_extract(j.draft,'$.body'),1,100) AS preview FROM jobs j LEFT JOIN chat_job_index x ON x.job=j.id WHERE x.job IS NULL AND j.state NOT IN ('draft','sent') AND json_extract(j.draft,'$.chat_key')=? ORDER BY j.created DESC LIMIT 30",(key,)).fetchall()
        pending.extend(dict(row) for row in legacy)
    pending=sorted(pending,key=lambda row:row['created'],reverse=True)[:30]
    items=[{'id':row['id'],'state':row['state'],'draft':{'body':row['preview'] or ''}} for row in pending]
    if not include_draft:return items
    indexed=db.execute("SELECT j.id,j.created FROM chat_job_index x JOIN jobs j ON j.id=x.job WHERE x.chat_key=? AND j.state='draft' ORDER BY j.created DESC LIMIT 1",(key,)).fetchone()
    legacy=None
    if not complete:
        legacy=db.execute("SELECT j.id,j.created FROM jobs j LEFT JOIN chat_job_index x ON x.job=j.id WHERE x.job IS NULL AND j.state='draft' AND json_extract(j.draft,'$.chat_key')=? ORDER BY j.created DESC LIMIT 1",(key,)).fetchone()
    winner=max((row for row in (indexed,legacy) if row),key=lambda row:row['created'],default=None)
    if not winner:return None,items
    row=db.execute('SELECT id,account,draft FROM jobs WHERE id=?',(winner['id'],)).fetchone()
    return {**dict(row),'draft':json.loads(row['draft'])},items

# ==========================================
# Function: Poll compact pending status for one contact.
# Method: Include still-unindexed old jobs until the durable migration marker commits.
# ==========================================
def chat_pending(store,key):
    with store.db() as db:
        db.execute('BEGIN')
        return contact_jobs(db,key)

# ==========================================
# Function: Prepare complete ordinary-mail rich bodies and durable contact jobs off GTK.
# Method: Query exactly five eligible sources with no selection-time index backfill.
# ==========================================
def chat_snapshot(app,core,key,scope,before=None,window=5):
    started=time.monotonic()
    result=core.conversation_messages(key,account=scope,before=before,limit=5,backfill_limit=0,verification_limit=0,content_bytes=8*1024*1024)
    prepared=time.monotonic()
    for item in result['items']:item['rich_body']=app.local_loader.prepare_body(item['id'],item['parsed'])
    result['query_seconds']=prepared-started;result['body_seconds']=time.monotonic()-prepared
    with app.service.store.db() as db:
        db.execute('BEGIN')
        result['draft'],result['pending']=contact_jobs(db,key,include_draft=True)
    from .address_book import sender_detail
    peer=key.removeprefix('contact:person:') if key.startswith('contact:person:') else ''
    latest=result['items'][-1] if result['items'] else {}
    address=latest['peers'][0]['address'] if latest.get('kind')=='direct' and latest.get('peers') else latest['sender'][0]['address'] if latest.get('sender') and not latest.get('outgoing') else ''
    result['person']=sender_detail(app.service.store,address,peer)
    result['prepare_seconds']=time.monotonic()-started
    return result

# ==========================================
# Function: Present contact mail separately from the existing RFC-card reader.
# Method: Keep synthetic contact identities outside every message mutation path.
# ==========================================
class ContactChatUI:
    # ==========================================
    # Function: Create an independent stack page and its owned docked editor host.
    # Method: Create independent timeline sections and a scoped shared rich-body surface.
    # ==========================================
    def initialize_chat(self):
        g=self.g;previous_page=g.gtk_stack_get_visible_child_name(self.widget('reader_stack')) or b'mail'
        self.selected_chat='';self.chat_composer=None;self.chat_source_return=None;self.chat_read_pending=set();self.chat_items=[];self.chat_before=None;self.chat_due=0;self.chat_scope='';self.chat_loading=False;self.chat_render_source=0;self.chat_scroll_pending=None;self.chat_window_before=None;self.chat_native_labels=[];self.chat_width=0;self.chat_editor_width=0;self.chat_load_error='';self.chat_force_bottom=False;self.chat_anchor=None;self.chat_latest_id='';self.chat_jobs_due=0;self.chat_pending_items=[];self.chat_bubbles=[];self.chat_has_more=False;self.chat_metrics={};self.chat_retired_readers=[];self.chat_refresh_pending=False;self.chat_request=None
        from .chat_rich_surface import ChatRichSurface
        self.chat_surface=ChatRichSurface(self)
        root=g.gtk_box_new(1,0);self.chat_root=root;g.gtk_widget_set_name(root,b'contact_chat')
        self.chat_person_header=self.create_person_header(root,True)
        g.gtk_widget_set_no_show_all(self.chat_person_header['root'],1);g.gtk_widget_hide(self.chat_person_header['root'])
        self.chat_title=self.chat_person_header['name'];self.chat_aliases=self.chat_person_header['aliases']
        self.mail_person_header=self.create_person_header(self.widget('mail_surface'),False)
        g.gtk_box_reorder_child(self.widget('mail_surface'),self.mail_person_header['root'],1)
        g.gtk_widget_set_no_show_all(self.mail_person_header['root'],1);g.gtk_widget_hide(self.mail_person_header['root'])
        self.chat_scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(self.chat_scroll,2,1)
        overlay=g.gtk_overlay_new();g.gtk_container_add(overlay,self.chat_scroll);g.gtk_box_pack_start(root,overlay,1,1,0)
        from .chat_bottom_button import ChatBottomButton
        self.chat_bottom=ChatBottomButton(self,overlay)
        self.chat_timeline=g.gtk_box_new(1,14);g.gtk_widget_set_margin_top(self.chat_timeline,16);g.gtk_widget_set_margin_bottom(self.chat_timeline,20);g.gtk_container_add(self.chat_scroll,self.chat_timeline)
        self.chat_paging=g.gtk_box_new(0,4);g.gtk_widget_set_halign(self.chat_paging,3);g.gtk_box_pack_start(self.chat_timeline,self.chat_paging,0,1,0)
        self.chat_older_button=self.chat_action(self.chat_paging,'加载更早的五封邮件','action-up',self.chat_older,'chat-static')
        self.chat_latest_button=self.chat_action(self.chat_paging,'回到最新邮件','action-down',self.chat_latest,'chat-static')
        self.chat_messages_host=g.gtk_box_new(1,14);g.gtk_box_pack_start(self.chat_timeline,self.chat_messages_host,0,1,0)
        self.chat_pending_host=g.gtk_box_new(1,6);g.gtk_box_pack_start(self.chat_timeline,self.chat_pending_host,0,1,0)
        g.connect(self.chat_timeline,'size-allocate',self.chat_resize,count=3,group='chat-static')
        self.chat_editor_host=g.gtk_box_new(1,0);g.gtk_box_pack_start(root,self.chat_editor_host,0,1,0)
        g.connect(self.chat_editor_host,'size-allocate',self.chat_resize,count=3,group='chat-static')
        bind(self,'gtk','gtk_stack_add_named',None,P,P,C.c_char_p)(self.widget('reader_stack'),root,b'chat');g.gtk_widget_show_all(root)
        if previous_page==b'mail':g.gtk_widget_show(self.widget('mail_surface'))
        g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),previous_page)

    # ==========================================
    # Function: Present one compact person identity above a bounded alias viewport.
    # Method: Reuse native avatars and icon actions, reserving at most 70 pixels for wrapped aliases.
    # ==========================================
    def create_person_header(self,host,chat):
        g=self.g;root=g.gtk_box_new(0,12);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(root),b'chat-header');g.gtk_box_pack_start(host,root,0,1,0)
        avatar=g.gtk_label_new(b'?');g.gtk_style_context_add_class(g.gtk_widget_get_style_context(avatar),b'person-header-avatar');g.gtk_widget_set_valign(avatar,1);g.gtk_box_pack_start(root,avatar,0,0,0)
        text=g.gtk_box_new(1,2);g.gtk_box_pack_start(root,text,1,1,0)
        name=g.gtk_label_new('选择一个联系人'.encode());g.gtk_label_set_xalign(name,0);g.gtk_label_set_ellipsize(name,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(name),b'person-header-name');g.gtk_box_pack_start(text,name,0,1,0)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_scrolled_window_set_propagate_natural_height(scroll,1);g.gtk_scrolled_window_set_max_content_height(scroll,49)
        aliases=g.gtk_label_new(b'');g.gtk_label_set_xalign(aliases,0);g.gtk_label_set_line_wrap(aliases,1);bind(self,'gtk','gtk_label_set_line_wrap_mode',None,P,I)(aliases,2);g.gtk_label_set_selectable(aliases,1);g.gtk_label_set_max_width_chars(aliases,36);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(aliases),b'person-header-aliases');g.gtk_container_add(scroll,aliases);g.gtk_box_pack_start(text,scroll,0,1,0)
        settings=self.chat_action(root,'当前联系人设置','settings-general',self.chat_contact_settings,'chat-static') if chat else None
        self.chat_action(root,'关闭对话' if chat else '关闭邮件','composer-close',self.close_mail,'chat-static')
        return {'root':root,'name':name,'aliases':aliases,'avatar':avatar,'scroll':scroll,'settings':settings}

    # ==========================================
    # Function: Show every saved sender alias from the current worker snapshot.
    # Method: Retain original sender fallback, keep foreign recipients out, and update the existing widgets.
    # ==========================================
    def update_person_header(self,header,detail,name='',account=''):
        addresses=detail.get('addresses',[]);title=detail.get('name') or name or (addresses[0] if addresses else '未知发件人')
        self.g.label(header['name'],title);self.g.label(header['avatar'],title[:1].upper());self.g.label(header['aliases'],' · '.join(addresses))
        self.g.gtk_widget_set_tooltip_text(header['aliases'],'\n'.join(addresses).encode())
        self.apply_avatar(header['avatar'],addresses[0] if addresses else '',account)
        self.g.gtk_widget_set_no_show_all(header['root'],0);self.g.gtk_widget_show_all(header['root']);self.g.gtk_widget_set_no_show_all(header['root'],1)

    # ==========================================
    # Function: Resolve contact mode only in the inbox's unrestricted contact view.
    # Method: Folder, focus-group and ordinary mail modes retain their existing renderer.
    # ==========================================
    def contact_mode(self):
        return bool(getattr(self,'inboxes',None) and self.view=='inbox' and not self.folder_path and not self.focus_group and self.inboxes.active()['mode']=='conversations')

    # ==========================================
    # Function: Rebuild immutable own-account projection scope after account changes.
    # Method: Pass every configured account and the explicit synthetic demo identity.
    # ==========================================
    def contact_core(self):
        signature=tuple(sorted((a.id,a.email) for a in self.service.accounts.values()))+(('demo','demo@example.com'),) if self.profile.demo else tuple(sorted((a.id,a.email) for a in self.service.accounts.values()))
        if getattr(self,'contact_signature',None)!=signature:
            self.contact_signature=signature;self.contacts=ContactConversations(self.service.store,list(self.service.accounts.values()),extra_own=('demo@example.com',) if self.profile.demo else ())
        return self.contacts

    # ==========================================
    # Function: Add one compact action with a clearly owned callback lifetime.
    # Method: Use the existing icon assets and guarded native action dispatcher.
    # ==========================================
    def chat_action(self,host,title,icon,callback,group='chat-bubbles'):
        from .ui_actions import icon_action
        button=self.g.gtk_button_new();icon_action(self.g,button,title,icon,16);self.g.gtk_box_pack_start(host,button,0,0,0)
        self.g.connect(button,'clicked',lambda *unused:self.run_action(callback),group=group);return button

    # ==========================================
    # Function: Render participant rows in short native batches.
    # Method: Reserve a left unread gutter, retain contact identities and suppress bulk mail actions.
    # ==========================================
    def render_contacts(self,projection):
        g=self.g;self.items=projection['items'];self.total=projection['total']
        previous_scope=self.chat_scope;self.chat_scope=projection['scope'];self.rendering=True
        if getattr(self,'chat_source_return',None) and previous_scope!=self.chat_scope:
            if not self.chat_discard_return():return
        if previous_scope!=self.chat_scope and self.selected_chat and not self.leave_chat():return
        self.last_chat_account_filter=(g.gtk_combo_box_get_active_id(self.widget('account_filter')) or b'all').decode()
        self.refresh_folders(projection['folders'],projection['smart']);g.disconnect('list-headers');g.clear(self.widget('messages'));self.rows={};self.row_groups={};self.summary_rows={};self.quick_buttons={};self.group_members={};self.inbox_sections={};self.collapsed_rows=set();self.row_avatar_styles={};self.row_avatars={};self.chat_unread_markers={};self.chat_contact_titles={}
        if self.multi:self.toggle_selection()
        g.gtk_widget_hide(self.widget('selection'))
        for name in ('focus_back','gatekeeper_inbox','category_filter'):g.gtk_widget_hide(self.widget(name))
        from .conversation_folders import load as folder_scope
        selected_folders=folder_scope(self.service.store)
        self.g.label(self.widget('view_subtitle'),'跨主题 · '+('已选 '+str(len(selected_folders['folders']))+' 个文件夹' if selected_folders['mode']=='custom' else '收件与已发送邮件'))
        avatar_state=self.identity_colors.snapshot([row['account'] for row in self.items])
        has_pinned=any(item.get('contact_pinned') for item in self.items);self.chat_contact_avatars={}
        for index,item in enumerate(self.items):
            row=g.gtk_list_box_row_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(row),b'contact-item-row');box=g.gtk_box_new(0,7);g.gtk_widget_set_margin_top(box,13);g.gtk_widget_set_margin_bottom(box,13);g.gtk_widget_set_margin_start(box,0);g.gtk_widget_set_margin_end(box,8)
            pin=bool(item.get('contact_pinned'));unread=item['unread_count'];visible_unread=bool(unread and not item.get('muted'))
            if has_pinned:self.row_groups[row]='置顶联系人' if pin else '联系人'
            identity_box=g.gtk_box_new(0,2);g.gtk_box_pack_start(box,identity_box,0,0,0)
            avatar=g.gtk_label_new(item['contact_name'][:1].upper().encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(avatar),b'mail-avatar')
            g.gtk_widget_set_valign(avatar,3)
            sender=item['contact_address'];self.apply_avatar(avatar,sender,item['account'],avatar_state);self.chat_contact_avatars[item['key']]=avatar
            from .mail_list_visuals import avatar_bubble
            avatar_host,marker=avatar_bubble(g,avatar,unread if visible_unread else 0,unread=True,title='将当前对话范围内的邮件设为已读 · '+str(unread)+' 封未读')
            g.gtk_style_context_add_class(g.gtk_widget_get_style_context(marker),b'chat-unread-marker');g.gtk_widget_set_sensitive(marker,bool(visible_unread and item['key'] not in self.chat_read_pending));g.gtk_box_pack_start(identity_box,avatar_host,0,0,0);self.chat_unread_markers[item['key']]=marker
            g.connect(marker,'clicked',lambda *unused,key=item['key']:self.chat_mark_all_read(key),group='list-headers')
            text=g.gtk_box_new(1,5);g.gtk_box_pack_start(box,text,1,1,0)
            title=item['title']+('  ·  免打扰' if item.get('muted') else '  ·  '+str(unread)+' 未读' if unread else '')
            latest=item['latest_author']+'：'+(item['preview'] or '(无文字正文)')
            for value,css in [(title,'mail-sender'),(latest,'mail-preview'),(datetime.fromtimestamp(item['timestamp']).strftime('%m-%d %H:%M')+' · '+str(item['count'])+' 封邮件','mail-preview')]:
                label=g.gtk_label_new(' '.join(value.split()).encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,40);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),css.encode());g.gtk_box_pack_start(text,label,0,1,0)
                if css=='mail-sender':self.chat_contact_titles[item['key']]=label
            tooltip='发件人：'+(item['latest_author_address'] or '未知')+'\n可见参与者：'+(', '.join(peer['address'] for peer in item['peers']) or '无')
            g.gtk_widget_set_tooltip_text(box,tooltip.encode());g.gtk_container_add(row,box);self.rows[row]='contact:'+item['key'];g.gtk_container_add(self.widget('messages'),row);g.gtk_widget_show_all(row)
            if index%8==7:self.rendering=False;yield;self.rendering=True
        chosen=next((row for row,identity in self.rows.items() if identity=='contact:'+self.selected_chat),None)
        if chosen:g.gtk_list_box_select_row(self.widget('messages'),chosen)
        self.rendering=False;self.render_has_more=len(self.items)<self.total;g.gtk_widget_set_visible(self.widget('more'),self.render_has_more);g.label(self.widget('count'),str(self.total)+' 个对话')
        self.contact_progress(projection['indexing'])
        if self.selected_chat and chosen:self.read_chat(self.selected_chat,refresh=True)
        elif self.selected_chat:self.leave_chat()
        if not self.selected_chat and not self.selected and not (self.composer and not self.composer.closed):self.show_chat_page()
        self.apply_layout()

    # ==========================================
    # Function: Continue useful bounded backfill while exposing terminal unresolved verification.
    # Method: Inspect count, byte admission and persistent-error signals to prevent retry spinning.
    # ==========================================
    def contact_progress(self,indexing):
        if indexing.get('foreground_snapshot'):return
        self.chat_due=0
        remaining=indexing.get('remaining',0);pending=indexing.get('verification_remaining',0);minimum=indexing.get('verification_min_bytes') or 0
        useful=remaining>0 or indexing.get('membership_remaining',0)>0 or pending>0 and minimum<=64*1024*1024
        progress=indexing.get('processed',0)+indexing.get('verification_processed',0)+indexing.get('membership_processed',0)
        if useful and (progress or minimum>indexing.get('verification_byte_budget',0)):
            self.chat_verify_budget=min(64*1024*1024,max(32*1024*1024,minimum));self.chat_due=time.monotonic()+.25
            self.g.label(self.widget('view_subtitle'),f'正在整理联系人 · 元数据 {indexing.get("indexed",0)}/{indexing.get("total",0)} · 待核对 {pending}')
        elif indexing.get('incomplete'):
            self.g.label(self.widget('view_subtitle'),'部分副本尚未验证，已分别显示 · 可稍后刷新')

    # ==========================================
    # Function: Keep background indexing, docked drafts and final scroll allocation progressing.
    # Method: Reuse the application tick instead of adding unowned repeating timers.
    # ==========================================
    def chat_tick(self):
        if self.chat_composer and not self.chat_composer.closed:self.chat_composer.autosave()
        elif self.selected_chat and self.contact_mode() and not self.chat_loading and not self.chat_load_error and not (self.composer and not self.composer.closed):self.read_chat(self.selected_chat,refresh=True)
        if self.chat_due and time.monotonic()>=self.chat_due:
            self.chat_due=0
            if self.contact_mode():self.refresh()
        if self.selected_chat and self.chat_jobs_due and time.monotonic()>=self.chat_jobs_due and not self.chat_loading and not (self.composer and not self.composer.closed):
            key=self.selected_chat;self.chat_jobs_due=float('inf')
            # ==========================================
            # Function: Apply live queued/sending/error status only to its still-selected contact.
            # Method: Rebuild native pending chrome only when compact status actually changes.
            # ==========================================
            def jobs_ready(items):
                if self.selected_chat!=key:return
                self.chat_jobs_due=time.monotonic()+2
                if items!=self.chat_pending_items:
                    self.chat_pending_items=items;self.render_chat_pending(items)
            self.local_loader.request('chat-jobs',lambda:chat_pending(self.service.store,key),jobs_ready)
        pending=self.chat_scroll_pending
        if pending and time.monotonic()>=pending[0]:
            adjustment=self.g.gtk_scrolled_window_get_vadjustment(self.chat_scroll);upper=bind(self,'gtk','gtk_adjustment_get_upper',C.c_double,P)(adjustment);page=bind(self,'gtk','gtk_adjustment_get_page_size',C.c_double,P)(adjustment)
            if pending[1]=='bottom':
                latest=self.chat_bubbles[-1]['root'] if self.chat_bubbles else None
                allocated=bool(latest and self.g.gtk_widget_get_mapped(latest) and self.g.gtk_widget_get_allocated_height(latest)>1 and page>1)
                if not allocated and time.monotonic()<pending[0]+3:return
            value=upper-page if pending[1]=='bottom' else pending[2]+max(0,upper-pending[3]) if pending[1]=='older' else pending[2]
            if pending[1]!='bottom' and self.chat_anchor:
                entry=next((entry for entry in self.chat_bubbles if entry['origin']==self.chat_anchor[0]),None)
                if entry:
                    x,y=I(),I();self.g.gtk_widget_translate_coordinates(entry['root'],self.chat_timeline,0,0,C.byref(x),C.byref(y));value=y.value+self.chat_anchor[1]
            bind(self,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(adjustment,max(0,value));self.chat_scroll_pending=None
        if not self.chat_scroll_pending:
            self.chat_bottom.follow();self.chat_surface.tick()
        self.chat_bottom.update()

    # ==========================================
    # Function: Select a contact through a latest-only local read channel.
    # Method: Save before navigation and preserve the same docked buffer on passive refresh.
    # ==========================================
    def read_chat(self,key,refresh=False,older=False):
        if self.closing:return
        context=getattr(self,'chat_source_return',None)
        if context:
            if key==context['key']:self.chat_resume_original();return
            if not self.chat_discard_return():return
        if refresh and self.chat_loading:
            if key==self.selected_chat:self.chat_refresh_pending=True
            return
        changed=key!=self.selected_chat
        if changed:self.chat_refresh_pending=False
        if changed and not refresh:
            from .reader_handoff import navigation_handoff
            handoff=navigation_handoff(self)
            if handoff:handoff.begin()
        if not refresh and changed and not self.close_document():return
        if self.composer and not self.composer.closed:return
        if not refresh:
            self.local_loader.cancel('read');self.pending_read_identity=''
            if changed:
                self.clear_conversation();self.selected='';self.current=None;self.chat_items=[];self.chat_window_before=None;self.chat_force_bottom=True
        self.selected_chat=key
        chosen=next((row for row,identity in self.rows.items() if identity=='contact:'+key),None)
        if chosen:
            self.rendering=True;self.g.gtk_list_box_select_row(self.widget('messages'),chosen);self.rendering=False
            if not refresh:self.g.gtk_widget_grab_focus(chosen)
        self.show_chat_page();core=self.contact_core();scope=self.chat_scope;before=self.chat_before if older else self.chat_window_before;window=5
        self.chat_loading=True;self.chat_refresh_pending=False;self.chat_request=(key,scope,older);self.chat_load_error='';self.g.gtk_widget_set_sensitive(self.chat_older_button,0);requested=time.monotonic()
        item=next((row for row in self.items if row.get('key')==key),None)
        self.g.label(self.chat_title,item['title'] if item else '邮件对话')
        if changed:self.g.label(self.chat_aliases,'');self.g.label(self.chat_person_header['avatar'],'…')
        # ==========================================
        # Function: Apply only the still-selected contact's complete local snapshot.
        # Method: Keep an existing editor untouched and replace only the bounded timeline model.
        # ==========================================
        def ready(result):
            with self.service.store.preference_snapshot():
                if self.selected_chat!=key or self.chat_scope!=scope or not self.contact_mode():return
                if self.chat_refresh_pending:
                    self.chat_loading=False;self.chat_refresh_pending=False;self.read_chat(key,refresh=True,older=older);return
                self.chat_loading=False;self.chat_load_error='';self.contact_progress(result['indexing']);old=self.chat_items
                incoming=result['items'];old_ids={entry['id'] for entry in old}
                if older:self.chat_items=incoming+old
                elif old and any(entry['id'] in old_ids for entry in incoming):
                    replacements={entry['id']:entry for entry in incoming};merged={entry['id']:replacements.get(entry['id'],entry) for entry in old};merged.update(replacements)
                    self.chat_items=sorted(merged.values(),key=lambda entry:(entry['timestamp'],entry['id']))
                else:self.chat_items=incoming
                retained=0;cut=len(self.chat_items)
                for position,entry in enumerate(self.chat_items):
                    retained+=entry['rich_body'].get('_bytes',0)
                    if position>=5 and (position>=120 or retained>24*1024*1024):cut=position;break
                if cut<len(self.chat_items):
                    boundary=self.chat_items[cut];self.chat_window_before=[boundary['timestamp'],boundary['id']];self.chat_items=self.chat_items[:cut]
                if older or not old or not any(entry['id'] in old_ids for entry in incoming):
                    self.chat_before=result['before'];self.chat_has_more=result['has_more']
                self.chat_metrics={'query_seconds':result['query_seconds'],'body_seconds':result['body_seconds'],'prepare_seconds':result['prepare_seconds'],'ready_seconds':time.monotonic()-requested,'page_count':len(incoming),'loaded_count':len(self.chat_items),'index_processed':result['indexing'].get('processed',0),'verification_processed':result['indexing'].get('verification_processed',0)}
                item=next((row for row in self.items if row.get('key')==key),None)
                self.chat_latest_id=item['latest_id'] if item else result['items'][-1]['id'] if result['items'] and not self.chat_window_before else self.chat_latest_id
                heading=(item['title'] if item else '邮件对话')
                self.update_person_header(self.chat_person_header,result['person'],heading,item['account'] if item else '')
                if item:self.g.gtk_widget_set_tooltip_text(self.chat_title,(heading+'\n最新邮件发件人：'+(item['latest_author_address'] or '未知')+'\n会话地址：'+(', '.join(peer['address'] for peer in item['peers']) or '无')).encode())
                if not self.chat_composer:
                    route=self.chat_items[-1]['route'] if self.chat_items else item['route'] if item else {'safe':False}
                    from .chat_composer import ChatComposer
                    self.chat_composer=ChatComposer(self,key,route,result['draft']);self.g.gtk_box_pack_start(self.chat_editor_host,self.chat_composer.root,0,1,0)
                    self.chat_editor_width=0;self.chat_resize()
                self.chat_pending_items=result['pending'];self.chat_jobs_due=time.monotonic()+2
                self.render_chat_timeline(result['pending'],older)
                ids=[identity for message in result['items'] for identity in message['copy_ids'] if any(not location['seen'] for location in message['locations'])]
                if ids and self.service.store.preference('mark_read_on_open',True):self.background(lambda:[self.service.mark_opened(identity) for identity in ids])
                self.apply_layout()
        self.local_loader.request('chat',lambda:chat_snapshot(self,core,key,scope,before,window),ready)

    # ==========================================
    # Function: Consume one coalesced refresh after its earlier local snapshot fails.
    # Method: Check the selected identity and scope, then clear intent before submitting one successor.
    # ==========================================
    def chat_snapshot_failed(self):
        request=self.chat_request
        if not self.chat_refresh_pending or not request:return
        self.chat_refresh_pending=False
        key,scope,older=request
        if self.closing or self.selected_chat!=key or self.chat_scope!=scope or not self.contact_mode():return
        self.read_chat(key,refresh=True,older=older)

    # ==========================================
    # Function: Select the independent chat page without exposing ordinary mail actions.
    # Method: Keep the RFC toolbar confined to its existing sibling stack page.
    # ==========================================
    def show_chat_page(self):
        self.set_reader_state(False);self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'chat');self.g.gtk_widget_show_all(self.chat_root)
        self.g.gtk_widget_set_visible(self.chat_person_header['root'],bool(self.selected_chat))

    # ==========================================
    # Function: Save and release the selected contact before a real navigation change.
    # Method: Refuse busy/failed saves, invalidate local work and destroy owned callbacks only afterward.
    # ==========================================
    def leave_chat(self):
        if getattr(self,'chat_handoff',False):return True
        editor=getattr(self,'chat_composer',None)
        if editor and not editor.autosave(force=True):return False
        if editor:editor.close();self.chat_composer=None
        if getattr(self,'local_loader',None):self.local_loader.cancel('chat');self.local_loader.cancel('chat-jobs')
        self.cancel_chat_render();self.g.disconnect('chat-bubbles');self.selected_chat='';self.chat_items=[];self.chat_before=None;self.chat_due=0;self.chat_loading=False;self.chat_refresh_pending=False;self.chat_request=None;self.chat_load_error='';self.chat_window_before=None;self.chat_jobs_due=0;self.chat_pending_items=[]
        if getattr(self,'chat_timeline',None):
            self.clear_chat_cards();self.g.disconnect('chat-pending');self.g.clear(self.chat_pending_host);self.g.label(self.chat_title,'选择一个联系人');self.g.label(self.chat_aliases,'');self.g.label(self.chat_person_header['avatar'],'?')
        self.g.gtk_widget_hide(self.chat_person_header['root']);self.chat_bottom.update()
        self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'mail');return True

    # ==========================================
    # Function: Load another bounded chronological page on explicit request.
    # Method: Follow the core cursor even when byte admission returns fewer messages than requested.
    # ==========================================
    def chat_older(self):
        self.chat_bottom.user_scroll()
        if self.selected_chat and self.chat_before and not self.chat_loading:self.read_chat(self.selected_chat,refresh=True,older=True)

    # ==========================================
    # Function: Return from a bounded older window to the newest cached mail.
    # Method: Reset only timeline pagination while retaining the same docked draft.
    # ==========================================
    def chat_latest(self):
        if self.chat_loading:return
        self.chat_bottom.following=True;self.chat_window_before=None;self.chat_items=[];self.chat_force_bottom=True;self.read_chat(self.selected_chat,refresh=True)

    # ==========================================
    # Function: Release contact-owned source cards without touching the normal mail registry.
    # Method: Drop callbacks and reader references before native widget destruction.
    # ==========================================
    def clear_chat_cards(self):
        cards=list(self.chat_surface.conversation_cards.values());self.chat_surface.conversation_cards={};self.chat_bubbles=[];self.chat_native_labels=[]
        for card in cards:
            if getattr(self,'reader_handoff',None):self.reader_handoff.prepare(card,self.g.gtk_widget_get_parent(card.get('timeline_host',card['root'])))
            self.chat_surface.release_card_readers(card);self.g.disconnect(card['group']);self.g.disconnect('history-body-'+card['origin'])
        self.g.clear(self.chat_messages_host)

    # ==========================================
    # Function: Update only pending-job chrome when outbox polling changes.
    # Method: Keep every source root, browser, disclosure state and footer buffer intact.
    # ==========================================
    def render_chat_pending(self,pending):
        g=self.g;g.disconnect('chat-pending');g.clear(self.chat_pending_host)
        for job in pending:
            state={'queued':'排队 · 可在发件箱撤销','sending':'发送中','failed':'发送失败','partial':'部分接受','uncertain':'结果待确认'}.get(job['state'],job['state'])
            button=g.gtk_button_new_with_label((state+' · '+job['draft'].get('body','')[:100]+'  ↗').encode());g.gtk_label_set_ellipsize(g.gtk_bin_get_child(button),3);g.gtk_box_pack_start(self.chat_pending_host,button,0,1,0);g.connect(button,'clicked',lambda *unused:self.set_view('drafts'),group='chat-pending')
        g.gtk_widget_show_all(self.chat_pending_host)

    # ==========================================
    # Function: Incrementally prepend five rich messages and preserve existing native body state.
    # Method: Reconcile exact source IDs, retaining roots and measured leaves for unchanged sources.
    # ==========================================
    def render_chat_timeline(self,pending,older=False):
        g=self.g;adjustment=g.gtk_scrolled_window_get_vadjustment(self.chat_scroll)
        value=bind(self,'gtk','gtk_adjustment_get_value',C.c_double,P)(adjustment);upper=bind(self,'gtk','gtk_adjustment_get_upper',C.c_double,P)(adjustment);page=bind(self,'gtk','gtk_adjustment_get_page_size',C.c_double,P)(adjustment)
        bottom=self.chat_force_bottom or self.chat_bottom.following;self.chat_force_bottom=False;self.chat_anchor=None
        if not bottom:
            for entry in self.chat_bubbles:
                x,y=I(),I();g.gtk_widget_translate_coordinates(entry['root'],self.chat_timeline,0,0,C.byref(x),C.byref(y))
                if y.value+g.gtk_widget_get_allocated_height(entry['root'])>=value:self.chat_anchor=(entry['origin'],value-y.value);break
        existing={entry['origin']:entry for entry in self.chat_bubbles};keep={item['id'] for item in self.chat_items};surface=self.chat_surface
        for origin in list(surface.conversation_cards):
            if origin not in keep:
                card=surface.conversation_cards.pop(origin);surface.release_card_readers(card);g.disconnect(card['group']);g.disconnect('history-body-'+origin);g.destroy_tree(existing[origin]['root'])
        self.chat_bubbles=[]
        for index,item in enumerate(self.chat_items):
            entry=existing.get(item['id'])
            if entry:
                entry['item']=item;surface.conversation_cards[item['id']]['metadata'].update(seen=item['seen'])
            else:entry=self.chat_bubble(item)
            self.chat_bubbles.append(entry);g.gtk_box_reorder_child(self.chat_messages_host,entry['root'],index)
        self.render_chat_pending(pending);self.chat_width=0;self.chat_resize();g.gtk_widget_show_all(self.chat_messages_host)
        for card in surface.conversation_cards.values():
            g.gtk_widget_set_no_show_all(card['history_host'],not card['history_visible']);g.gtk_widget_set_visible(card['history_host'],card['history_visible'])
            surface.show_card_history(card,card['history_visible'])
        g.gtk_widget_set_no_show_all(self.chat_older_button,not self.chat_has_more);g.gtk_widget_set_visible(self.chat_older_button,self.chat_has_more);g.gtk_widget_set_sensitive(self.chat_older_button,not self.chat_loading)
        g.gtk_widget_set_no_show_all(self.chat_latest_button,not bool(self.chat_window_before));g.gtk_widget_set_visible(self.chat_latest_button,bool(self.chat_window_before))
        self.chat_scroll_pending=(time.monotonic()+.12,'older' if older else 'bottom' if bottom else 'same',value,upper)

    # ==========================================
    # Function: Put the complete ordinary source renderer in a directional contact row.
    # Method: Supply admitted metadata and immutable body models to the isolated common renderer.
    # ==========================================
    def chat_bubble(self,item):
        g=self.g;surface=self.chat_surface;parsed=item['parsed'];sender=', '.join(person.get('name') or person['address'] for person in item['sender'])
        metadata={**item,'sender':item['sender'][0]['address'] if item['sender'] else '',
                  'sender_name':sender,'recipients':(parsed.get('headers') or {}).get('to',parsed.get('recipients',''))}
        card=surface.create_conversation_card(metadata);card.update(item['rich_body']);surface.conversation_cards[item['id']]=card
        row=g.gtk_box_new(0,8);bubble=card['timeline_host'];avatar=card['avatar']
        g.gtk_widget_reparent(avatar,row);g.gtk_widget_set_valign(avatar,1)
        if item['outgoing']:g.gtk_box_pack_start(row,bubble,1,1,0);g.gtk_box_reorder_child(row,avatar,1)
        else:g.gtk_box_pack_start(row,bubble,1,1,0)
        g.gtk_widget_set_hexpand(bubble,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(card['root']),b'chat-bubble')
        g.gtk_box_pack_start(self.chat_messages_host,row,0,1,0);surface.toggle_conversation_card(item['id'],True);g.gtk_widget_show_all(row)
        return {'root':row,'bubble':bubble,'own':item['outgoing'],'origin':item['id'],'card':card,'item':item}

    # ==========================================
    # Function: Add native selectable text with explicit shared bubble contrast.
    # Method: Wrap at a bounded reading width and avoid applying foreground to independent surfaces.
    # ==========================================
    def chat_text(self,host,text,css):
        g=self.g;label=message_text(g,g.gtk_label_new(text.encode()));g.gtk_label_set_xalign(label,0);g.gtk_label_set_line_wrap(label,1);bind(self,'gtk','gtk_label_set_line_wrap_mode',None,P,I)(label,2);g.gtk_label_set_max_width_chars(label,64);g.gtk_label_set_selectable(label,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),css.encode());g.gtk_box_pack_start(host,label,0,1,0);self.chat_native_labels.append(label);return label

    # ==========================================
    # Function: Advance one short native timeline batch and finalize scrolling after allocation.
    # Method: Own one idle source and retain callback references until removed.
    # ==========================================
    def chat_render_batch(self,unused=None):
        try:next(self.chat_render);return 1
        except StopIteration:
            self.chat_render_source=0;self.chat_width=0;self.chat_resize();mode,value,upper=self.chat_scroll_after
            self.chat_scroll_pending=(time.monotonic()+.12,mode,value,upper)
            return 0
        except Exception as error:self.chat_render_source=0;self.show_error(error);return 0

    # ==========================================
    # Function: Keep message bubbles and the input aligned in a centered reading column.
    # Method: Recalculate native margins only when their respective hosts change width.
    # ==========================================
    def chat_resize(self,*unused):
        width=self.g.gtk_widget_get_allocated_width(self.chat_timeline)
        if width>=2 and width!=self.chat_width:
            self.chat_width=width;margin=max(18,(width-700)//2+18)
            for bubble in getattr(self,'chat_bubbles',[]):
                self.g.gtk_widget_set_margin_start(bubble['root'],margin+(28 if bubble['own'] else 0));self.g.gtk_widget_set_margin_end(bubble['root'],margin+(0 if bubble['own'] else 28))
        editor_width=self.g.gtk_widget_get_allocated_width(self.chat_editor_host)
        if editor_width>=2 and editor_width!=self.chat_editor_width:
            self.chat_editor_width=editor_width;margin=max(12,(editor_width-700)//2)
            if self.chat_composer:
                self.g.gtk_widget_set_margin_start(self.chat_composer.root,margin)
                self.g.gtk_widget_set_margin_end(self.chat_composer.root,margin)

    # ==========================================
    # Function: Cancel obsolete timeline construction before destroying its widgets.
    # Method: Remove only this page's retained idle source and drop its generator.
    # ==========================================
    def cancel_chat_render(self):
        if getattr(self,'chat_render_source',0):self.g.g_source_remove(self.chat_render_source);self.chat_render_source=0
        renderer=getattr(self,'chat_render',None)
        if renderer:renderer.close();self.chat_render=None
        self.chat_scroll_pending=None

    # ==========================================
    # Function: Point the dock at one explicit message's exact safe route.
    # Method: Preserve authored draft content by refusing route replacement until empty.
    # ==========================================
    def chat_reply(self,item):
        editor=self.chat_composer
        if not editor:return
        from .draft_content import has_draft_content
        if has_draft_content(editor.payload()):self.message('已有未发送草稿；请先发送或在完整编辑器保存');return
        if not editor.autosave(force=True):return
        editor.close();self.chat_composer=None
        from .chat_composer import ChatComposer
        self.chat_composer=ChatComposer(self,self.selected_chat,item['route']);self.g.gtk_box_pack_start(self.chat_editor_host,self.chat_composer.root,0,1,0);self.chat_editor_width=0;self.chat_resize();self.g.gtk_widget_grab_focus(self.chat_composer.body)

    # ==========================================
    # Function: Open the latest message in the original complete RFC reader.
    # Method: Preserve the docked draft before switching to the sibling stack page.
    # ==========================================
    def chat_open_latest(self):
        if self.chat_latest_id:self.chat_open_original(self.chat_latest_id)

    # ==========================================
    # Function: Open an original source while retaining the exact bounded chat and its live draft.
    # Method: Suspend worker updates and remember the clicked bubble's offset without rebuilding its widgets.
    # ==========================================
    def chat_open_original(self,identity):
        if not self.selected_chat or self.chat_source_return:return
        self.chat_bottom.user_scroll()
        if self.chat_composer and not self.chat_composer.autosave(force=True):return
        if not self.close_document(preserve_composer=True):return
        g=self.g;adjustment=g.gtk_scrolled_window_get_vadjustment(self.chat_scroll);value=bind(self,'gtk','gtk_adjustment_get_value',C.c_double,P)(adjustment)
        card=next((entry for entry in self.chat_bubbles if entry['origin']==identity),None);x,y=I(),I()
        if card:g.gtk_widget_translate_coordinates(card['root'],self.chat_timeline,0,0,C.byref(x),C.byref(y))
        self.chat_source_return={'key':self.selected_chat,'source':identity,'value':value,'anchor':(identity,value-y.value) if card else None,'scope':self.chat_scope}
        self.local_loader.cancel('chat');self.local_loader.cancel('chat-jobs');self.chat_loading=False;self.chat_request=None;self.chat_refresh_pending=False;self.selected_chat=''
        self.rendering=True;g.gtk_list_box_unselect_all(self.widget('messages'));self.rendering=False
        g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'mail');self.read(identity)

    # ==========================================
    # Function: Restore the contact and exact bubble position after closing the original-mail reader.
    # Method: Save any original-mail reply, clear only the ordinary reader and reuse the suspended timeline/buffer.
    # ==========================================
    def chat_resume_original(self):
        context=self.chat_source_return
        if not context or not self.close_document():return False
        self.thread_window_dismissed=self.selected;self.close_thread_window();self.clear_reader();self.chat_source_return=None
        self.selected_chat=context['key']
        if context.get('reload_scope'):
            if not any(item.get('key')==self.selected_chat for item in self.items):return self.leave_chat()
            self.chat_anchor=None;self.chat_scroll_pending=None;self.chat_force_bottom=True;self.chat_bottom.following=True;self.read_chat(self.selected_chat,refresh=True)
        else:self.chat_anchor=context['anchor'];self.chat_scroll_pending=(time.monotonic()+.05,'restore',context['value'],0);self.chat_due=time.monotonic()+2;self.show_chat_page()
        chosen=next((row for row,identity in self.rows.items() if identity=='contact:'+self.selected_chat),None)
        if chosen:self.rendering=True;self.g.gtk_list_box_select_row(self.widget('messages'),chosen);self.rendering=False
        self.layout_override=False;self.apply_layout();return True

    # ==========================================
    # Function: Release a suspended contact when the user starts unrelated navigation.
    # Method: Reuse the ordinary autosaving close boundary before invalidating the return context.
    # ==========================================
    def chat_discard_return(self):
        context=self.chat_source_return
        if not context:return True
        self.selected_chat=context['key']
        if not self.leave_chat():self.selected_chat='';return False
        self.chat_source_return=None;return True

    # ==========================================
    # Function: Open the selected contact's saved settings directly from the chat header.
    # Method: Use the stable saved person identity and existing Settings contacts drawer.
    # ==========================================
    def chat_contact_settings(self):
        item=next((item for item in self.items if item['key']==self.selected_chat),None)
        from .settings_contacts import contact_details_dialog
        contact_details_dialog(self,item.get('person_id') if item else None)

    # ==========================================
    # Function: Remove stale cached cards when saved folder scope changes without losing authored draft text.
    # Method: Cancel old snapshots, clear only source state and let the subsequent list refresh reconcile the selected contact.
    # ==========================================
    def chat_folder_scope_changed(self):
        if self.chat_source_return:self.chat_source_return['reload_scope']=True
        self.local_loader.cancel('chat');self.cancel_chat_render();self.chat_loading=False;self.chat_refresh_pending=False;self.chat_request=None
        self.chat_items=[];self.chat_before=None;self.chat_window_before=None;self.chat_anchor=None;self.chat_force_bottom=True;self.chat_bottom.following=bool(self.selected_chat)
        self.clear_chat_cards()

    # ==========================================
    # Function: Mark the selected scope of cached mail for the clicked contact read without selecting its row.
    # Method: Resolve every account/source copy off GTK and atomically queue existing remote read intents.
    # ==========================================
    def chat_mark_all_read(self,key):
        if key in self.chat_read_pending:return
        core=self.contact_core();self.chat_read_pending.add(key);button=self.chat_unread_markers.get(key)
        if button:self.g.gtk_widget_set_sensitive(button,0)
        # ==========================================
        # Function: Commit exact physical copies and detect mail that arrived during the operation.
        # Method: Read the selected contact twice around the transaction without touching unrelated index work.
        # ==========================================
        def operation():
            sources=core.unread_sources(key);count=self.service.store.mark_contact_opened(sources,remote=not self.service.demo)
            return count,sources,bool(core.unread_sources(key))
        # ==========================================
        # Function: Reflect durable read completion immediately in the existing contact row.
        # Method: Update its marker/title and visible copy flags before a deferred count refresh, preserving navigation.
        # ==========================================
        def ready(result):
            count,sources,remaining=result;self.chat_read_pending.discard(key)
            if self.closing:return
            visible=self.contact_mode() and 'contact:'+key in self.rows.values()
            item=next((item for item in self.items if item.get('key')==key),None)
            marker=self.chat_unread_markers.get(key) if visible else None
            if marker:
                self.g.gtk_widget_set_sensitive(marker,bool(remaining and item and not item.get('muted')))
                if not remaining:self.g.label(marker,'',button=True);self.g.gtk_widget_set_tooltip_text(marker,None);self.g.gtk_widget_set_no_show_all(marker,1);self.g.gtk_widget_hide(marker)
            if item and visible and not remaining:
                item.update(unread_count=0,seen=True)
                title=self.chat_contact_titles.get(key)
                if title:self.g.label(title,item['title']+('  ·  免打扰' if item.get('muted') else ''))
            identities={source['id'] for source in sources}
            for item in self.chat_items:
                for copy in item.get('locations',[]):
                    if copy['id'] in identities:copy['seen']=True
                if item.get('copy_ids') and set(item['copy_ids'])<=identities:item['seen']=True
            self.chat_due=time.monotonic()+.5;self.message('已将 '+str(count)+' 封邮件设为已读')
        # ==========================================
        # Function: Restore a retryable read marker after a local write failure.
        # Method: Leave cached unread state untouched and report through the existing application boundary.
        # ==========================================
        def failed(error):
            self.chat_read_pending.discard(key)
            if self.closing:return
            visible=self.contact_mode() and 'contact:'+key in self.rows.values()
            marker=self.chat_unread_markers.get(key) if visible else None
            if marker:
                item=next((item for item in self.items if item.get('key')==key),None)
                self.g.gtk_widget_set_sensitive(marker,bool(item and item.get('unread_count') and not item.get('muted')))
            self.show_error(error)
        self.local_loader.action(operation,ready,failed)
