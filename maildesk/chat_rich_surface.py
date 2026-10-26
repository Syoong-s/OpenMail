"""Scoped ordinary-mail renderer with viewport-owned engines for contact bubbles."""
import ctypes as C
import os
import re
import time
from .desktop_conversation import ConversationUI
from .quoted_history import fragment_text
from .message_style import message_text

# ==========================================
# Function: Share complete mail rendering without borrowing the ordinary reader's selection or registry.
# Method: Keep card/disclosure state here and give native readers the actual application owner.
# ==========================================
class ChatRichSurface(ConversationUI):
    # ==========================================
    # Function: Own only contact card state and deferred rich leaves.
    # Method: Forward services and native APIs while retaining a separate conversation registry.
    # ==========================================
    def __init__(self,app):
        self.reader_owner=app;self.conversation_cards={};self.conversation_focus='';self.leaves=[];self.max_live=8;self.peak_live=0;self.hydrated=0;self.evicted=0;self.html_reader=None

    # ==========================================
    # Function: Resolve shared helpers without redirecting application state writes.
    # Method: Read unowned attributes from the actual application; renderer writes stay scoped.
    # ==========================================
    def __getattr__(self,name):return getattr(self.reader_owner,name)

    # ==========================================
    # Function: Route source replies through the durable dock and existing full editor.
    # Method: Use exact source IDs and preserve the contact draft before editor navigation.
    # ==========================================
    def reply_message(self,identity,mode='reply'):
        app=self.reader_owner;item=next((item for item in app.chat_items if item['id']==identity),None)
        if mode=='reply' and item:app.chat_reply(item)
        elif app.leave_chat():app.reply_extended(mode,identity)

    # ==========================================
    # Function: Keep original source actions available inside each rich bubble.
    # Method: Add a distinct envelope action to the shared row using the card's owned callback group.
    # ==========================================
    def create_conversation_card(self,row):
        card=super().create_conversation_card(row)
        parent=self.g.gtk_widget_get_parent(card['history_button'])
        card['original_button']=self.conversation_icon(parent,'打开原邮件','original-mail',lambda:self.reader_owner.chat_open_original(row['id']),card['group'])
        return card

    # ==========================================
    # Function: Never decode MIME from a native contact callback.
    # Method: Admit only worker-prepared cards to the shared body renderer.
    # ==========================================
    def load_conversation_body(self,card):
        if card.get('history_model'):super().load_conversation_body(card)

    # ==========================================
    # Function: Show real plain mail natively and reserve rich mail's formatted layout without a text flash.
    # Method: Use a quiet skeleton until the browser DOM is ready; never overlay an unformatted copy of rich mail.
    # ==========================================
    def history_leaf(self,card,source,parent,readers,images):
        g=self.g;text=fragment_text(source) or '(无文字正文)'
        plain=not card.get('details_parsed',{}).get('html') and not images and not re.search(r'(?:https?://|mailto:|www\.|<a\b|<(?:img|svg|video|audio|iframe)\b)',source,re.I)
        if plain:
            label=self.text_label(text,parent);card['native_text_leaves']=card.get('native_text_leaves',0)+1;g.gtk_widget_show(label);return
        host=g.gtk_box_new(1,0);g.gtk_widget_set_hexpand(host,1);g.gtk_box_pack_start(parent,host,0,1,0)
        overlay=g.gtk_overlay_new();engine=g.gtk_box_new(1,0);g.gtk_widget_set_size_request(engine,-1,150);g.gtk_container_add(overlay,engine);g.gtk_box_pack_start(host,overlay,0,1,0)
        preview=g.gtk_box_new(1,10);g.gtk_widget_set_valign(preview,1);g.gtk_widget_set_halign(preview,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(preview),b'mail-loading')
        for width in (210,280,170):
            line=g.gtk_box_new(0,0);g.gtk_widget_set_size_request(line,width,7);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(line),b'mail-loading-line');g.gtk_box_pack_start(preview,line,0,0,0)
        g.gtk_overlay_add_overlay(overlay,preview);g.gtk_overlay_set_overlay_pass_through(overlay,preview,1)
        g.gtk_widget_show_all(host)
        self.leaves.append({'card':card,'source':source,'parent':parent,'host':host,'engine_host':engine,'preview':preview,'readers':readers,'images':images,'reader':None,'fallback':False,'height':150})

    # ==========================================
    # Function: Display untrusted plain mail text using the current bubble palette.
    # Method: Use a selectable wrapped GTK label without markup or source interpretation.
    # ==========================================
    def text_label(self,text,parent):
        from .desktop_general import bind,P,I
        g=self.g;label=message_text(g,g.gtk_label_new(text.encode()));g.gtk_label_set_xalign(label,0);g.gtk_label_set_line_wrap(label,1);g.gtk_label_set_max_width_chars(label,64);g.gtk_label_set_selectable(label,1);bind(self,'gtk','gtk_label_set_line_wrap_mode',None,P,I)(label,2)
        if parent:g.gtk_box_pack_start(parent,label,0,1,0)
        return label

    # ==========================================
    # Function: Remove a leaf's browser before any containing widget can be destroyed.
    # Method: Clear compatibility references first, retain pending Windows hosts and preserve measured height.
    # ==========================================
    def release_leaf(self,leaf):
        reader=leaf['reader']
        if not reader:return
        leaf['reader']=None;card=leaf['card'];g=self.g
        leaf['height']=max(30,g.gtk_widget_get_allocated_height(leaf['host']))
        if reader in leaf['readers']:leaf['readers'].remove(reader)
        if card.get('reader') is reader:card['reader']=None
        for quote in card['quote_cards']:
            if quote.get('reader') is reader:quote['reader']=None
        if self.html_reader is reader:self.html_reader=None
        if self.reader_owner.html_reader is reader:self.reader_owner.html_reader=getattr(self.reader_owner,'legacy_html_reader',None)
        handoff=getattr(self.reader_owner,'reader_handoff',None)
        if handoff and handoff.reader is reader:return
        reader.close();self.evicted+=1
        if os.name=='nt':
            app=self.reader_owner
            if not getattr(app,'chat_reader_parking',None):
                app.chat_reader_parking=g.gtk_box_new(1,0);g.g_object_ref_sink(app.chat_reader_parking)
            g.gtk_widget_reparent(reader.widget,app.chat_reader_parking);app.chat_retired_readers.append(reader)
        g.clear(leaf['engine_host']);g.gtk_widget_set_size_request(leaf['engine_host'],-1,leaf['height']);g.gtk_widget_set_no_show_all(leaf['preview'],0);g.gtk_widget_show(leaf['preview'])

    # ==========================================
    # Function: Remove only leaf records belonging to a released source or quote.
    # Method: Detach records before native destruction can reenter allocation callbacks.
    # ==========================================
    def discard_leaves(self,card,parent=None):
        doomed=[leaf for leaf in self.leaves if leaf['card'] is card and (parent is None or leaf['parent']==parent)]
        self.leaves=[leaf for leaf in self.leaves if leaf not in doomed]
        for leaf in doomed:self.release_leaf(leaf)

    # ==========================================
    # Function: Release all source engines before the shared card lifecycle removes its hosts.
    # Method: Drop deferred leaves first, then use the common quote callback cleanup.
    # ==========================================
    def release_card_readers(self,card):
        self.discard_leaves(card);super().release_card_readers(card)

    # ==========================================
    # Function: Preserve independent quote choices while releasing hidden leaf hosts.
    # Method: Discard only a quote that is actually closing before common GTK cleanup.
    # ==========================================
    def toggle_quote_card(self,identity,path,expanded=None):
        card=self.conversation_cards.get(identity)
        quote=next((quote for quote in card['quote_cards'] if quote['path']==tuple(path)),None) if card else None
        if quote and quote['expanded'] and (expanded is False or expanded is None):self.discard_leaves(card,quote['body_host'])
        super().toggle_quote_card(identity,path,expanded)
        self.sync_conversation_reader()

    # ==========================================
    # Function: Preserve source collapse behavior without leaking deferred body hosts.
    # Method: Drop current-body leaves before the common source toggle clears its native contents.
    # ==========================================
    def toggle_conversation_card(self,identity,expanded=None):
        card=self.conversation_cards.get(identity)
        if card and card['expanded'] and (expanded is False or expanded is None):self.discard_leaves(card,card['body_host'])
        super().toggle_conversation_card(identity,expanded)

    # ==========================================
    # Function: Point document compatibility actions at a live contact reader.
    # Method: Keep the normal conversation focus untouched and prefer an admitted current body.
    # ==========================================
    def sync_conversation_reader(self):
        for card in self.conversation_cards.values():
            sources=[leaf for leaf in self.leaves if leaf['card'] is card and leaf['parent']==card['body_host'] and leaf['source']]
            card['reader']=next((leaf['reader'] for leaf in sources if leaf['reader']),None) if sources else next(iter(card['body_readers']),None)
            for quote in card['quote_cards']:
                sources=[leaf for leaf in self.leaves if leaf['card'] is card and leaf['parent']==quote['body_host'] and leaf['source']]
                quote['reader']=next((leaf['reader'] for leaf in sources if leaf['reader']),None) if sources else next(iter(quote['readers']),None)
        self.html_reader=next((leaf['reader'] for leaf in self.leaves if leaf['reader']),None)
        if self.reader_owner.selected_chat:self.reader_owner.html_reader=self.html_reader or getattr(self.reader_owner,'legacy_html_reader',None)

    # ==========================================
    # Function: Hydrate nearby rich content while retaining warm readers within the fixed eight-engine ceiling.
    # Method: Prioritize visible leaves, keep nearest live surfaces in spare slots and evict only when capacity requires it.
    # ==========================================
    def tick(self):
        app=self.reader_owner;g=self.g
        if app.closing or not app.selected_chat:return
        adjustment=g.gtk_scrolled_window_get_vadjustment(app.chat_scroll)
        from .desktop_general import bind,P
        value=bind(app,'gtk','gtk_adjustment_get_value',C.c_double,P)(adjustment);page=bind(app,'gtk','gtk_adjustment_get_page_size',C.c_double,P)(adjustment)
        if page<2:return
        candidates=[];warm=[]
        for leaf in self.leaves:
            if leaf['reader'] and getattr(leaf['reader'],'failed',False) and not leaf['fallback']:
                leaf['fallback']=True;g.gtk_widget_set_no_show_all(leaf['preview'],0);g.clear(leaf['preview']);g.gtk_box_pack_start(leaf['preview'],self.text_label(fragment_text(leaf['source']) or '(无文字正文)',None),0,1,0);g.gtk_widget_show_all(leaf['preview'])
            if leaf['reader'] and leaf['reader'].document_ready:
                g.gtk_widget_set_no_show_all(leaf['preview'],1);g.gtk_widget_hide(leaf['preview'])
            if not g.gtk_widget_get_mapped(leaf['host']):continue
            x,y=C.c_int(),C.c_int();g.gtk_widget_translate_coordinates(leaf['host'],app.chat_timeline,0,0,C.byref(x),C.byref(y))
            height=max(leaf['height'],g.gtk_widget_get_allocated_height(leaf['host']))
            distance=max(value-(y.value+height),y.value-value-page,0)
            rank=(distance,abs(y.value-value-page*.5),leaf)
            if distance<max(180,page*.5):candidates.append(rank)
            elif leaf['reader']:warm.append(rank)
        candidates.sort(key=lambda item:item[:2]);handoff=getattr(app,'reader_handoff',None)
        limit=self.max_live-(1 if handoff and handoff.reader else 0)
        wanted=[item[2] for item in candidates[:limit]]
        warm.sort(key=lambda item:item[:2]);wanted.extend(item[2] for item in warm[:max(0,limit-len(wanted))])
        for leaf in list(self.leaves):
            if leaf['reader'] and leaf not in wanted:self.release_leaf(leaf)
        admitted=[leaf for leaf in wanted if not leaf['reader'] and not leaf['fallback']]
        if admitted:
            with app.service.store.preference_snapshot():
                for leaf in admitted[:2]:
                    if leaf['reader'] or leaf['fallback']:continue
                    local=[];g.gtk_widget_set_size_request(leaf['engine_host'],-1,-1)
                    entry=next((quote['model'] for quote in leaf['card']['quote_cards'] if quote['body_host']==leaf['parent']),leaf['card']['metadata'])
                    ConversationUI.history_leaf(self,leaf['card'],leaf['source'],leaf['engine_host'],local,leaf['images'],entry)
                    if local:
                        leaf['reader']=local[0];leaf['readers'].extend(local);self.hydrated+=1
                        if leaf['height']>150:g.gtk_widget_set_size_request(leaf['reader'].widget,-1,int(leaf['height']))
                    else:
                        leaf['fallback']=True;g.gtk_widget_set_no_show_all(leaf['preview'],1);g.gtk_widget_hide(leaf['preview'])
                    g.gtk_widget_show_all(leaf['host'])
        self.peak_live=max(self.peak_live,sum(bool(leaf['reader']) for leaf in self.leaves));self.sync_conversation_reader();self.reap_retired()

    # ==========================================
    # Function: Release closed Windows GTK hosts only after pending controller callbacks settle.
    # Method: Observe the existing bridge counters and retain all hosts on the real application during shutdown.
    # ==========================================
    def reap_retired(self):
        app=self.reader_owner;bridge=getattr(app,'windows_webview_bridge',None)
        if os.name!='nt' or not bridge or bridge.md_webview_metrics(1) or bridge.md_webview_metrics(2):return
        retired=app.chat_retired_readers;app.chat_retired_readers=[]
        for reader in retired:self.g.gtk_widget_destroy(reader.widget)

    # ==========================================
    # Function: Reveal an attachment's owning leaf without leaving the contact draft.
    # Method: Use shared provenance/disclosure routing and hydrate the requested exact MIME image index.
    # ==========================================
    def image_reader_for(self,identity,index=None):
        result=super().image_reader_for(identity,index)
        if index is None:return result
        card=self.conversation_cards.get(identity)
        if not card:return None
        leaf=next((leaf for leaf in self.leaves if leaf['card'] is card and any(image['index']==index for image in leaf['images'])),None)
        if leaf:
            x,y=C.c_int(),C.c_int();self.g.gtk_widget_translate_coordinates(leaf['host'],self.reader_owner.chat_timeline,0,0,C.byref(x),C.byref(y))
            from .desktop_general import bind,P
            bind(self.reader_owner,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(self.g.gtk_scrolled_window_get_vadjustment(self.reader_owner.chat_scroll),float(y.value))
            self.tick();return leaf['reader']
        return None
