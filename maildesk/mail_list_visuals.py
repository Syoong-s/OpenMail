"""Compact row metadata, avatar bubbles and durable state indicators shared by native mail lists."""
from .ui_actions import ICONS

# ==========================================
# Function: Count unique active RFC messages for admitted rows without hydrating MIME or decoding bodies.
# Method: Batch account-scoped reference components and deduplicate physical folder copies with indexed graph joins.
# ==========================================
def history_counts(store,identities):
    identities=list(dict.fromkeys(identities));result={identity:1 for identity in identities}
    with store.db() as db:
        for start in range(0,len(identities),80):
            page=identities[start:start+80];marks=','.join('?' for _ in page)
            rows=db.execute('''WITH RECURSIVE component(root,account,mid) AS (
                SELECT id,account,message_id FROM messages WHERE id IN ('''+marks+''')
                UNION SELECT c.root,c.account,l.target FROM component c
                JOIN thread_links l ON l.account=c.account AND l.source=c.mid
                UNION SELECT c.root,c.account,l.source FROM component c
                JOIN thread_links l ON l.account=c.account AND l.target=c.mid
                LIMIT 100000)
                SELECT c.root,count(DISTINCT m.message_id) AS count FROM component c
                JOIN messages m ON m.account=c.account AND m.message_id=c.mid AND m.remote_gone=0 GROUP BY c.root''',page).fetchall()
            result.update({row['root']:max(1,row['count']) for row in rows})
    return result

# ==========================================
# Function: Place a compact count bubble on an avatar without reserving a left unread gutter.
# Method: Keep the native avatar as the base and overlay a right/top label or independently clickable unread button.
# ==========================================
def avatar_bubble(g,avatar,count,unread=False,title=''):
    overlay=g.gtk_overlay_new();g.gtk_widget_set_margin_top(avatar,6);g.gtk_container_add(overlay,avatar)
    bubble=g.gtk_button_new_with_label(str(count).encode()) if unread else g.gtk_label_new(str(count).encode())
    context=g.gtk_widget_get_style_context(bubble);g.gtk_style_context_add_class(context,b'avatar-unread-bubble' if unread else b'avatar-history-bubble')
    g.gtk_widget_set_halign(bubble,2);g.gtk_widget_set_valign(bubble,1);g.gtk_overlay_add_overlay(overlay,bubble);g.gtk_overlay_set_overlay_pass_through(overlay,bubble,int(not unread))
    g.gtk_widget_set_tooltip_text(bubble,title.encode() if title else None)
    visible=count>0 if unread else count>1
    g.gtk_widget_set_no_show_all(bubble,int(not visible));g.gtk_widget_set_visible(bubble,int(visible))
    return overlay,bubble

# ==========================================
# Function: Show enabled flags and attachment presence at the trailing edge of an ordinary mail row.
# Method: Omit absent state widgets entirely and use the same yellow assets as the reader's toggled buttons.
# ==========================================
def row_markers(g,item):
    box=g.gtk_box_new(0,4);g.gtk_widget_set_valign(box,3);widgets={}
    for key,title,icon,enabled in [('priority','优先','spark-layout-priority-active',item.get('priority')),('pinned','已置顶','spark-layout-pin-active',item.get('pinned')),('attachments','含附件','mail-attachment',item.get('attachments_count',0))]:
        if not enabled:continue
        image=g.image_file(ICONS/(icon+'.svg'),13);g.gtk_widget_set_tooltip_text(image,title.encode());g.gtk_box_pack_start(box,image,0,0,0);widgets[key]=image
    return box,widgets
