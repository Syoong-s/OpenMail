"""Compact sender-composition summaries and stable per-message quick actions."""
from pathlib import Path

# ==========================================
# Function: Bound ordinary row widgets while keeping every category summary reachable.
# Method: Apply pagination only to individual rows and retain complete summary objects.
# ==========================================
def focused_render_items(sections,limit):
    result=[];remaining=limit;more=False
    for section in sections:
        if section.get('summary'):
            result.append({'_summary':section,'account':''});continue
        values=section['shown'][:1] if section['collapsed'] else section['shown']
        result.extend(values[:remaining]);more=more or len(values)>remaining
        remaining=max(0,remaining-len(values))
    return result,more

# ==========================================
# Function: Add focused summary navigation and stable mail action controls.
# Method: Render native GTK rows backed by complete scoped membership snapshots.
# ==========================================
class FocusUI:
    # ==========================================
    # Function: Open a complete group as a paginated sublist.
    # Method: Retain the active view and account filters while replacing only list composition.
    # ==========================================
    def open_focus_group(self,key):
        if not self.close_document():return
        self.focus_group=key;self.limit=100;self.refresh()

    # ==========================================
    # Function: Return from a group sublist to its compact summaries.
    # Method: Clear the transient group key without changing stored view definitions.
    # ==========================================
    def close_focus_group(self,*unused):
        self.focus_group='';self.limit=100;self.refresh()

    # ==========================================
    # Function: Render a single horizontal category composition row.
    # Method: Make the complete title, avatar and sender surface one native navigation button.
    # ==========================================
    def summary_row(self,section):
        g=self.g;row=g.gtk_list_box_row_new();box=g.gtk_box_new(1,6);line=g.gtk_box_new(0,7)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(row),b'focus-summary')
        button=g.gtk_button_new();title=g.gtk_label_new((section['title']+f"   {len(section['items'])}"+(f" · {section['unread']} 未读" if section['unread'] else '')+'  ›').encode())
        g.gtk_label_set_xalign(title,0);g.gtk_box_pack_start(box,title,0,1,0)
        g.connect(button,'clicked',lambda *unused,key=section['key']:self.open_focus_group(key),group='list-headers')
        for item in section['recent_senders']:
            avatar=g.gtk_label_new((item.get('sender_name') or item['sender'])[:1].upper().encode())
            g.gtk_style_context_add_class(g.gtk_widget_get_style_context(avatar),b'summary-avatar')
            self.apply_avatar(avatar,item['sender'],item['account'],getattr(self,'list_avatar_state',None))
            g.gtk_box_pack_start(line,avatar,0,0,0)
        names='、'.join(item.get('sender_name') or item['sender'].split('@')[0] for item in section['recent_senders'])
        label=g.gtk_label_new(names.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),b'mail-preview');g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,22)
        g.gtk_box_pack_start(line,label,1,1,0);g.gtk_box_pack_start(box,line,0,1,0)
        g.gtk_container_add(button,box);g.gtk_container_add(row,button);g.gtk_container_add(self.widget('messages'),row);g.gtk_list_box_row_set_selectable(row,0)
        self.summary_rows[section['key']]={'row':row,'button':button,'section':section}
        return row

    # ==========================================
    # Function: Construct the three compact left-side actions for one message.
    # Method: Capture the durable identity independently of current GTK selection.
    # ==========================================
    def row_actions(self,identity,item=None):
        g=self.g;box=g.gtk_box_new(1,0);buttons={};item=item or {}
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(box),b'row-action-column')
        for action,title,icon in [('done','完成','done'),('seen','已读 / 未读','seen'),('trash','移到废纸篓','trash')]:
            button=g.gtk_button_new();g.gtk_button_set_image(button,g.image_file(Path(__file__).parent/'desktop_assets/icons'/('spark-layout-'+icon+'.svg'),12));g.gtk_button_set_always_show_image(button,1)
            g.gtk_widget_set_tooltip_text(button,title.encode());g.gtk_widget_set_size_request(button,14,17)
            g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'row-quick-action')
            if action=='seen' and not item.get('seen',True):
                g.gtk_button_set_image(button,None);g.gtk_button_set_label(button,'●'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'unread-action');g.gtk_widget_set_tooltip_text(button,'标为已读'.encode())
            g.connect(button,'clicked',lambda *unused,target=identity,code=action:self.run_action(lambda:self.quick_action(target,code)),group='list-headers')
            g.gtk_box_pack_start(box,button,0,0,0);buttons[action]=button
        self.quick_buttons[identity]=buttons
        return box

    # ==========================================
    # Function: Execute a mail action and finish navigation only after confirmed success.
    # Method: Snapshot pre-action neighbors, apply service semantics and preserve selection on errors.
    # ==========================================
    def quick_action(self,identity,action):
        if not identity or identity.startswith('job:'):return
        message=self.service.store.get(identity);ids=[item['id'] for item in self.items]
        policy=self.service.store.preference('main_action_policy','close');target=''
        if identity in ids:
            index=ids.index(identity);offset=1 if policy=='next' else -1
            if policy in ('next','previous') and 0<=index+offset<len(ids):target=ids[index+offset]
        selected=self.selected;finishing=action in ('done','trash','archive')
        # ==========================================
        # Function: Mutate exactly the captured mail and optional pin state.
        # Method: Delegate read/trash/provider archive to shared services and retain ordinary safe trash.
        # ==========================================
        def operation():
            unpin=finishing and bool(message['pinned']) and self.service.store.preference('main_action_unpin',True)
            if unpin and action in ('trash','archive'):self.service.update(identity,{'pinned':False})
            if action=='seen':result=self.service.update(identity,{'seen':not bool(message['seen'])})
            elif action=='done':result=self.service.store.organize(identity,done=not bool(message['done']))
            else:result=self.service.bulk_action([identity],action)
            if unpin and action=='done':self.service.update(identity,{'pinned':False})
            return result
        # ==========================================
        # Function: Apply precomputed finishing navigation without overriding a newer user selection.
        # Method: Close or move only when the acted message remains selected and the save boundary succeeds.
        # ==========================================
        def success(result):
            following=False
            if finishing and self.selected==identity and selected==identity:
                if not self.close_document():self.refresh();return
                self.selected=target;following=bool(target)
            self.refresh()
            if following and self.selected!=target:
                self.layout_override=None;self.read(target)
        self.background(operation,success)
