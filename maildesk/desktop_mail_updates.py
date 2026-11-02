"""Small local state updates that preserve native list rows and rich mail readers."""
from .ui_actions import state_action
from collections import OrderedDict
import ctypes as C

ROW_WIDGETS=('quick_buttons','row_status','row_history_badges','row_avatar_styles','row_avatars',
             'chat_unread_markers','chat_contact_titles','chat_contact_avatars')


# ==========================================
# Function: Patch local mailbox state without recreating unaffected native controls.
# Method: Admit stable row sets; use the existing renderer when membership/order actually grows.
# ==========================================
class MailUpdatesUI:
    # ==========================================
    # Function: Retain reusable native rows across membership or ordering changes.
    # Method: Hold one explicit GTK reference while rebuilding only changed row contents and headers.
    # ==========================================
    def retain_mail_rows(self):
        self.g.disconnect('list-section-headers')
        self.g.gtk_list_box_set_header_func(self.widget('messages'),None,None,None)
        self.list_reusable_rows=getattr(self,'mail_row_cache',OrderedDict());self.mail_row_cache=OrderedDict()
        for row,identity in self.rows.items():
            signature=getattr(self,'list_row_signatures',{}).get(identity)
            if signature is None or identity.startswith('job:'):continue
            entry={'row':row,'signature':signature,'group':self.row_groups.get(row)}
            for name in ROW_WIDGETS:
                entry[name]=getattr(self,name,{}).get(identity.removeprefix('contact:') if name.startswith('chat_') else identity)
            self.g.g_object_ref(row);self.g.gtk_container_remove(self.widget('messages'),row)
            self.g.gtk_list_box_row_set_header(row,None)
            self.list_reusable_rows[identity]=entry

    # ==========================================
    # Function: Keep a bounded native row cache for fast folder returns and release evicted controls.
    # Method: Retain at most 200 detached rows; balance every explicit reference on eviction or shutdown.
    # ==========================================
    def release_mail_rows(self,discard=False):
        cached=getattr(self,'mail_row_cache',OrderedDict())
        cached.update(getattr(self,'list_reusable_rows',{}));self.list_reusable_rows={}
        while cached and (discard or len(cached)>200):
            identity,entry=cached.popitem(last=False)
            self.g.disconnect('list-row-'+identity);self.g.gtk_widget_destroy(entry['row']);self.g.g_object_unref(entry['row'])
        self.mail_row_cache=cached

    # ==========================================
    # Function: Restore an unchanged native row at its new list position.
    # Method: Compare complete visual inputs and transfer retained controls back to the live registries.
    # ==========================================
    def reuse_mail_row(self,identity,signature):
        entry=self.list_reusable_rows.pop(identity,None)
        if entry is None:return False
        row=entry['row']
        if entry['signature']!=signature:
            self.g.disconnect('list-row-'+identity);self.g.gtk_widget_destroy(row);self.g.g_object_unref(row);return False
        self.rows[row]=identity
        if entry['group'] is not None:self.row_groups[row]=entry['group']
        for name in ROW_WIDGETS:
            if entry[name] is not None:getattr(self,name)[identity.removeprefix('contact:') if name.startswith('chat_') else identity]=entry[name]
        self.g.gtk_container_add(self.widget('messages'),row);self.g.g_object_unref(row)
        self.g.gtk_widget_show_all(row)
        self.mail_rows_reused=getattr(self,'mail_rows_reused',0)+1
        return True

    # ==========================================
    # Function: Restore group headers after a coherent native row update.
    # Method: Re-enable the retained callback once instead of recomputing headers on each removal.
    # ==========================================
    def restore_mail_headers(self):
        self.g.gtk_list_box_set_header_func(self.widget('messages'),C.cast(self.header_callback,C.c_void_p),None,None)

    # ==========================================
    # Function: Identify the visible mailbox independently of its selected message.
    # Method: Include view preferences and filters so rows are never reused across unrelated scopes.
    # ==========================================
    def mail_list_context(self):
        from .desktop_preferences import row_presentation
        store=self.service.store
        with store.preference_snapshot():
            presentation=(row_presentation(store),*[store.preference(key) for key in ('grouping','avatars_mode','account_colors','account_colors_enabled')])
            return (self.view,self.folder_account,self.folder_path,self.smart_query,self.focus_group,
                    self.g.text(self.widget('search')),self.g.gtk_combo_box_get_active_id(self.widget('category_filter')),
                    self.g.gtk_combo_box_get_active_id(self.widget('account_filter')),repr(self.inboxes.active()),repr(presentation))

    # ==========================================
    # Function: Apply changed read counts, removals and summary membership in place.
    # Method: Require a completed matching context and compare row identities before touching GTK.
    # ==========================================
    def patch_mail_projection(self,projection):
        if getattr(self,'rendered_mail_context',None)!=self.mail_list_context():return False
        if getattr(self,'list_renderer',None) or self.view=='drafts':return False
        if projection.get('contacts'):
            if [r.get('key') for r in self.items]!=[r.get('key') for r in projection['items']]:return False
            # Titles/latest message changes still need normal row construction.
            ignored={'unread_count','seen'}
            if any({k:v for k,v in a.items() if k not in ignored}!={k:v for k,v in b.items() if k not in ignored} for a,b in zip(self.items,projection['items'])):return False
            self.items=projection['items'];self.update_contact_badges()
            self.refresh_folders(projection['folders'],projection['smart'])
            if self.selected_chat:self.read_chat(self.selected_chat,refresh=True)
            return True
        rows=projection['items'];sections=projection.get('sections');render_rows=rows;has_more=False
        if sections is not None:
            if self.focus_group:render_rows=next((s['items'][:self.limit] for s in sections if s['key']==self.focus_group),[])
            else:
                from .desktop_focus import focused_render_items
                render_rows,has_more=focused_render_items(sections,self.limit)
        summaries={r['_summary']['key']:r['_summary'] for r in render_rows if '_summary' in r}
        if set(summaries)!=set(getattr(self,'summary_rows',{})):return False
        incoming={r['id']:r for r in render_rows if '_summary' not in r}
        grouped={row['id']:section for section in sections or [] if not section.get('summary') for row in section['shown']} if not self.focus_group else {}
        if any(grouped.get(identity,{}).get('key')!=self.inbox_sections.get(identity,{}).get('key') for identity in incoming):return False
        old={r['id']:r for r in self.items};old_order=list(self.rows.values())
        if [i for i in old_order if i in incoming]!=list(incoming):return False
        ignored={'seen','done','archived'}
        for identity,item in incoming.items():
            if identity not in old:return False
            if {k:v for k,v in item.items() if k not in ignored}!={k:v for k,v in old[identity].items() if k not in ignored}:return False
        self.rendering=True
        try:
            for row,identity in list(self.rows.items()):
                if identity not in incoming:
                    self.rows.pop(row);self.row_groups.pop(row,None);self.quick_buttons.pop(identity,None);self.g.disconnect('list-row-'+identity);self.g.gtk_widget_destroy(row)
                else:
                    buttons=self.quick_buttons.get(identity,{})
                    if buttons and incoming[identity].get('seen')!=old[identity].get('seen'):
                        self.update_quick_buttons(identity,incoming[identity])
            self.items=list(rows);self.total=projection['total']
            if self.focus_group:
                self.items=next((list(s['items']) for s in sections if s['key']==self.focus_group),[]);self.total=len(self.items)
            if sections is not None:
                self.group_members={s['key']:[r['id'] for r in s['items']] for s in sections};self.inbox_sections=grouped
                self.g.disconnect('list-section-headers');self.g.gtk_list_box_set_header_func(self.widget('messages'),None,None,None)
                for row in self.rows:self.g.gtk_list_box_row_set_header(row,None)
                self.restore_mail_headers()
            self.g.label(self.widget('count'),str(self.total)+' 封邮件')
            self.g.gtk_widget_set_visible(self.widget('more'),len(incoming)<self.total if sections is None or self.focus_group else has_more)
            self.refresh_folders(projection['folders'],projection['smart'])
        finally:self.rendering=False
        return True

    # ==========================================
    # Function: Update one mail row's compact state controls immediately.
    # Method: Reuse its action widgets and refresh only state icons and tooltips.
    # ==========================================
    def update_quick_buttons(self,identity,message):
        buttons=getattr(self,'quick_buttons',{}).get(identity,{})
        for key in ('seen','done'):
            if key not in buttons:continue
            active=bool(message.get(key) or key=='done' and message.get('archived'))
            state_action(self.g,buttons[key],('标为未读' if active else '标为已读') if key=='seen' else ('移回收件箱' if active else '完成并归档'),'spark-layout-'+key,active,12)
            if key=='seen':
                context=self.g.gtk_widget_get_style_context(buttons[key])
                (self.g.gtk_style_context_remove_class if active else self.g.gtk_style_context_add_class)(context,b'unread-action')
                if not active:self.g.gtk_button_set_image(buttons[key],None);self.g.gtk_button_set_label(buttons[key],'●'.encode())

    # ==========================================
    # Function: Reflect committed contact read counts without waiting for provider polling.
    # Method: Change only the avatar badge and title of existing rows.
    # ==========================================
    def update_contact_badges(self):
        for item in self.items:
            key=item.get('key');badge=getattr(self,'chat_unread_markers',{}).get(key)
            if not badge:continue
            count=item['unread_count'];visible=bool(count and not item.get('muted'))
            self.g.label(badge,str(count),button=True);self.g.gtk_widget_set_sensitive(badge,visible)
            self.g.gtk_widget_set_no_show_all(badge,not visible);self.g.gtk_widget_set_visible(badge,visible)
            title=getattr(self,'chat_contact_titles',{}).get(key)
            if title:self.g.label(title,item['title']+('  ·  免打扰' if item.get('muted') else '  ·  '+str(count)+' 未读' if count else ''))

    # ==========================================
    # Function: Remove an unavailable ordinary-mail card without disturbing other loaded bodies.
    # Method: Clear the selected reader or release only the exact passive source tree and callbacks.
    # ==========================================
    def discard_mail_card(self,identity):
        if getattr(self,'selected_chat',''):return
        if self.current and self.current['id']==identity and self.selected==identity:self.clear_reader();return
        card=getattr(self,'conversation_cards',{}).pop(identity,None)
        if card:
            self.release_card_readers(card)
            for group in (card['group'],'reply-drafts-'+identity,'history-body-'+identity):self.g.disconnect(group)
            self.g.gtk_widget_destroy(card.get('timeline_host',card['root']));self.conversation_signature=None

    # ==========================================
    # Function: Reconcile committed local actions into visible controls and scoped queries.
    # Method: Update state-only chrome; ask workers for fresh membership without reloading rich bodies.
    # ==========================================
    def mail_changed(self,identities=()):
        store=self.service.store
        for identity in identities:
            try:message=store.state(identity)
            except KeyError:self.discard_mail_card(identity);continue
            in_destination=self.view=='folder' and self.folder_account==message['account'] and self.folder_path==message['folder']
            removed=not in_destination and (message['trashed'] or message['spam'] or message['remote_gone'] or self.view=='inbox' and message['archived'])
            if removed:self.discard_mail_card(identity)
            self.update_quick_buttons(identity,message)
            for surface in (self,getattr(self,'chat_surface',None)):
                card=getattr(surface,'conversation_cards',{}).get(identity) if surface else None
                if card:
                    card['metadata'].update({key:message[key] for key in ('seen','done','pinned','archived','folder')})
                    surface.update_card_actions(card)
            if self.current and self.current.get('id')==identity:
                self.current.update({key:message[key] for key in ('seen','done','pinned','archived','folder')})
                for key in ('seen','done','pin','archive'):
                    active=bool(message[{'pin':'pinned','archive':'archived'}.get(key,key)])
                    state_action(self.g,self.widget(key),('标为未读' if active else '标为已读') if key=='seen' else ('移回收件箱' if active else '完成并归档') if key in ('done','archive') else ('取消置顶' if active else '置顶'),'spark-layout-'+key,active)
        self.refresh()
