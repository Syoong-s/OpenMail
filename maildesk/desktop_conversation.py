"""Continuous RFC cards with independent local history disclosure and lazy bodies."""
from datetime import datetime
import ctypes as C
import time
from pathlib import Path
import re
from .desktop_general import bind,P,I
from .desktop_preferences import resolved_theme
from .quoted_history import split_history,history_sources,fragment_text,source_cids
from .history_timeline import history_timeline
from .ui_actions import icon_action
from .message_style import app_own_identities,bubble_direction,message_text

# ==========================================
# Function: Present complete source-message envelope details without inventing recipients.
# Method: Read original parsed headers and provide an unambiguous local date fallback.
# ==========================================
def conversation_details(parsed):
    headers=parsed.get('headers',{})
    values=[('发件人',headers.get('from') or parsed.get('sender','')),('收件人',headers.get('to') or parsed.get('recipients',''))]
    values.extend((title,headers.get(key,'')) for key,title in [('cc','抄送'),('bcc','密送'),('reply-to','回复至')])
    values.append(('日期',headers.get('date') or datetime.fromtimestamp(parsed['timestamp']).strftime('%Y-%m-%d %H:%M:%S')))
    return '\n'.join(title+'：'+value for title,value in values if value)

# ==========================================
# Function: Match CID references without sharing unrelated image attachments between fragments.
# Method: Decode quoted and unquoted HTML attribute values using the same canonical CID spelling.
# ==========================================
def fragment_cids(source):
    return source_cids(source)

# ==========================================
# Function: Render every cached RFC member and preserve independent disclosure choices.
# Method: Keep lightweight metadata cards while loading MIME and native HTML only on demand.
# ==========================================
class ConversationUI:
    # ==========================================
    # Function: Release all body renderers associated with a source card.
    # Method: Close each engine before its native host or owner is destroyed.
    # ==========================================
    def release_card_readers(self,card):
        handoff=getattr(getattr(self,'reader_owner',self),'reader_handoff',None)
        for reader in card.get('body_readers',[]):
            if not handoff or handoff.reader is not reader:reader.close()
        for quote in card.get('quote_cards',[]):
            self.g.disconnect(quote['group'])
            for reader in quote.get('readers',[]):
                if not handoff or handoff.reader is not reader:reader.close()
        card['body_readers']=[];card['reader']=None
        for quote in card.get('quote_cards',[]):quote['readers']=[];quote['reader']=None

    # ==========================================
    # Function: Clear a conversation without destroying an unsent inline reply.
    # Method: Park the exact editor surface before releasing its source card widgets.
    # ==========================================
    def clear_conversation(self):
        editor=getattr(self,'composer',None)
        editor=editor if editor and not editor.closed and editor.inline and not editor.detached else None
        if editor:editor.reparent_surface(self.widget('composer_host'));editor.inline=False;editor.floating=False
        self.html_reader=getattr(self,'legacy_html_reader',None)
        for card in getattr(self,'conversation_cards',{}).values():
            if getattr(self,'reader_handoff',None):self.reader_handoff.prepare(card)
            self.release_card_readers(card);self.g.disconnect(card['group']);self.g.disconnect('reply-drafts-'+card['origin']);self.g.disconnect('history-body-'+card['origin'])
        self.g.disconnect('conversation-reveal-scroll');self.conversation_reveal_state=None
        self.g.disconnect('conversation');self.g.clear(self.widget('conversation_host'))
        self.conversation_cards={};self.conversation_signature=None;self.conversation_tools=None;self.pending_conversation_reveal=None
        self.clear_reply_reserve()
        if editor:editor.size_surface();self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'composer')

    # ==========================================
    # Function: Display all chronological account-scoped RFC members without paging.
    # Method: Retain existing roots and local states, constructing only metadata for closed cards.
    # ==========================================
    def render_conversation(self,identity):
        store=self.service.store;prepared=getattr(self,'read_prepared',None);thread=prepared['thread'] if prepared else store.thread(identity);ids=[row['id'] for row in thread];keep=set(ids)
        message_id=prepared['message']['message_id'] if prepared else store.get(identity)['message_id'];canonical=next((row['id'] for row in thread if row['message_id']==message_id),identity)
        previous=getattr(self,'conversation_cards',{});focused=canonical!=getattr(self,'conversation_focus',None) or canonical not in previous
        signature=(resolved_theme(self),store.preference('reader_font_size',14),store.preference('adapt_dark_html',True),store.preference('load_remote_images',False))
        reload=getattr(self,'conversation_signature',None) not in (None,signature)
        minimize=store.preference('minimize_old_emails',False);minimize_changed=minimize and getattr(self,'conversation_minimize',minimize)!=minimize
        self.conversation_minimize=minimize;self.conversation_ids=ids;self.conversation_focus=canonical;self.conversation_signature=signature;self.conversation_tools=None
        editor=self.composer if self.composer and not self.composer.closed and self.composer.inline and not self.composer.detached else None
        if editor:self.g.gtk_widget_reparent(editor.window,self.widget('composer_host'))
        for origin,card in previous.items():
            if origin not in keep:
                if getattr(self,'reader_handoff',None):self.reader_handoff.prepare(card)
                self.release_card_readers(card);self.g.disconnect(card['group']);self.g.disconnect('reply-drafts-'+origin);self.g.disconnect('history-body-'+origin);self.g.destroy_tree(card.get('timeline_host',card['root']))
        self.conversation_cards={};g=self.g;host=self.widget('conversation_host')
        for index,row in enumerate(thread):
            origin=row['id'];card=previous.get(origin)
            if card:card['metadata']=row
            else:card=self.create_conversation_card(row);g.gtk_box_pack_start(host,card.get('timeline_host',card['root']),0,1,0)
            if prepared and origin in prepared['bodies'] and not card.get('history_model'):card.update(prepared['bodies'][origin])
            self.conversation_cards[origin]=card;g.gtk_box_reorder_child(host,card.get('timeline_host',card['root']),index)
        g.gtk_widget_show_all(host)
        for origin,card in self.conversation_cards.items():
            expanded=card['expanded']
            if focused and origin==canonical:expanded=True
            elif (minimize_changed or (minimize and focused)) and origin!=canonical:expanded=False
            self.toggle_conversation_card(origin,expanded)
        self.update_conversation_metadata(reload)
        if editor:
            target=self.conversation_cards.get(editor.reply.get('reply_source'))
            if target:g.gtk_widget_reparent(editor.window,target['reply_host']);g.gtk_widget_show_all(editor.window)
            else:editor.inline=False;editor.size_surface();g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'composer')
        self.sync_conversation_reader();self.update_reply_draft_cards()
        if focused and not editor:self.pending_conversation_reveal=(canonical,time.monotonic()+.15)

    # ==========================================
    # Function: Reveal an explicitly selected card after native allocation.
    # Method: Scroll only on focus changes, leaving passive arrivals and active replies stationary.
    # ==========================================
    def reveal_conversation_card(self):
        pending=getattr(self,'pending_conversation_reveal',None);now=time.monotonic();g=self.g
        if not pending:
            if getattr(self,'conversation_reveal_state',None):g.disconnect('conversation-reveal-scroll');self.conversation_reveal_state=None
            return
        if now<pending[1]:return
        card=self.conversation_cards.get(pending[0]);image_reader=pending[2] if len(pending)>2 else None
        invalid=(self.composer and not self.composer.closed) or not card or (image_reader and image_reader.closed) or (not image_reader and self.conversation_focus!=pending[0])
        if invalid or now>pending[1]+3:
            self.pending_conversation_reveal=None;g.disconnect('conversation-reveal-scroll');self.conversation_reveal_state=None;return
        target=image_reader.widget if image_reader else card['header']
        scroller=g.gtk_widget_get_ancestor(target,g.gtk_scrolled_window_get_type())
        if not scroller:return
        state=getattr(self,'conversation_reveal_state',None)
        if not state or state['pending']!=pending:
            g.disconnect('conversation-reveal-scroll')
            state=self.conversation_reveal_state={'pending':pending,'geometry':None}
            g.connect(scroller,'scroll-event',self.cancel_conversation_reveal,count=3,returns=True,group='conversation-reveal-scroll')
        viewport=g.gtk_bin_get_child(scroller);child=g.gtk_bin_get_child(viewport)
        target_height=g.gtk_widget_get_allocated_height(target);view_height=g.gtk_widget_get_allocated_height(viewport)
        if target_height<2 or view_height<28 or g.gtk_widget_get_allocated_width(target)<2:return
        x=C.c_int();y=C.c_int();visible_y=C.c_int()
        if not g.gtk_widget_translate_coordinates(target,child,0,0,C.byref(x),C.byref(y)):return
        if not g.gtk_widget_translate_coordinates(target,viewport,0,0,C.byref(x),C.byref(visible_y)):return
        geometry=(y.value,target_height,view_height,g.gtk_widget_get_allocated_height(child))
        visible=0<=visible_y.value and visible_y.value+min(target_height,28)<=view_height
        if visible and state['geometry']==geometry:
            self.pending_conversation_reveal=None;g.disconnect('conversation-reveal-scroll');self.conversation_reveal_state=None
            if image_reader:image_reader.jump_to_image(pending[3])
            return
        state['geometry']=geometry
        if not visible:
            height=max(28,view_height-28)
            g.gtk_adjustment_clamp_page(g.gtk_scrolled_window_get_vadjustment(scroller),float(max(0,y.value-12)),float(y.value+height))

    # ==========================================
    # Function: Let an intentional wheel/trackpad gesture override a pending focus reveal.
    # Method: Cancel only the transient request and let GTK process the original scroll event normally.
    # ==========================================
    def cancel_conversation_reveal(self,*unused):
        self.pending_conversation_reveal=None
        return False

    # ==========================================
    # Function: Create one compact source-bound conversation header and its stable reply hosts.
    # Method: Use cached envelope metadata until local disclosure requests the actual body.
    # ==========================================
    def create_conversation_card(self,row):
        g=self.g;origin=row['id'];group='conversation-card-'+origin;root=g.gtk_box_new(1,7)
        timeline=g.gtk_box_new(1,0);history_host=g.gtk_box_new(1,0)
        g.gtk_widget_set_no_show_all(history_host,1);g.gtk_widget_set_visible(history_host,0)
        g.gtk_box_pack_start(timeline,root,0,1,0);g.gtk_box_pack_start(timeline,history_host,0,1,0)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(root),b'conversation-card')
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(root),('message-'+bubble_direction(row,app_own_identities(self))).encode())
        header=g.gtk_box_new(0,7);g.gtk_box_pack_start(root,header,0,1,0)
        avatar=g.gtk_label_new((row.get('sender_name') or row['sender'])[:1].upper().encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(avatar),b'summary-avatar')
        provider=self.apply_avatar(avatar,row['sender'],row['account']);g.gtk_box_pack_start(header,avatar,0,0,0)
        caption=(row.get('sender_name') or row['sender'])+' → '+(row.get('recipients') or '')
        toggle=g.gtk_button_new_with_label((row.get('sender_name') or row['sender']).encode());g.gtk_button_set_alignment(toggle,0,.5)
        bind(self,'gtk','gtk_button_set_focus_on_click',None,P,I)(toggle,0)
        label=g.gtk_bin_get_child(toggle);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,38)
        message_text(g,toggle);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(toggle),b'conversation-sender');g.gtk_box_pack_start(header,toggle,1,1,0)
        date=g.gtk_label_new(datetime.fromtimestamp(row['timestamp']).strftime('%m-%d %H:%M').encode());message_text(g,date);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(date),b'conversation-date');g.gtk_box_pack_start(header,date,0,0,0)
        disclosure=self.conversation_icon(header,'展开邮件','conversation-open',lambda target=origin:self.toggle_conversation_card(target),group)
        details=g.gtk_menu_button_new();g.gtk_button_set_image(details,g.image_file(Path(__file__).parent/'desktop_assets/icons/conversation-info.svg',17));g.gtk_button_set_always_show_image(details,1)
        popup=g.gtk_popover_new(details);text=g.gtk_label_new(caption.encode());g.gtk_label_set_xalign(text,0);g.gtk_label_set_selectable(text,1);g.gtk_label_set_line_wrap(text,1);g.gtk_label_set_max_width_chars(text,60)
        g.gtk_container_set_border_width(popup,14);g.gtk_container_add(popup,text);g.gtk_widget_show_all(text);g.gtk_menu_button_set_popover(details,popup);g.gtk_box_pack_start(header,details,0,0,0)
        g.gtk_widget_set_tooltip_text(details,'邮件详情'.encode());g.connect(details,'toggled',lambda *unused,target=origin:self.load_card_details(target),group=group)
        menu=g.gtk_menu_button_new();g.gtk_button_set_image(menu,g.gtk_image_new_from_icon_name(b'view-more-symbolic',1));g.gtk_button_set_always_show_image(menu,1)
        popover=g.gtk_popover_new(menu);options=g.gtk_box_new(1,3);g.gtk_menu_button_set_popover(menu,popover);g.gtk_container_add(popover,options)
        for action,title in [('done','完成 / 重新打开'),('seen','已读 / 未读'),('trash','移到废纸篓')]:
            button=g.gtk_button_new_with_label(title.encode());g.connect(button,'clicked',lambda *unused,origin=origin,code=action,popup=popover:(g.gtk_popover_popdown(popup),self.run_action(lambda:self.quick_action(origin,code))),group=group);g.gtk_box_pack_start(options,button,0,1,0)
        g.gtk_widget_show_all(options);g.gtk_box_pack_start(header,menu,0,0,0)
        snippet=g.gtk_label_new((' '.join(row.get('preview','').split())[:130] or '(无文字正文)').encode());g.gtk_label_set_xalign(snippet,0);g.gtk_label_set_ellipsize(snippet,3);g.gtk_label_set_max_width_chars(snippet,70)
        message_text(g,snippet);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(snippet),b'conversation-snippet');g.gtk_box_pack_start(root,snippet,0,1,0)
        content=g.gtk_box_new(1,6);g.gtk_box_pack_start(root,content,0,1,0)
        labels=message_text(g,g.gtk_label_new(b''));g.gtk_box_pack_start(content,labels,0,1,0);body=g.gtk_box_new(1,7);g.gtk_box_pack_start(content,body,0,1,0)
        from .attachment_cards import configure as configure_attachments
        attachments=g.gtk_flow_box_new();configure_attachments(g,attachments);g.gtk_flow_box_set_selection_mode(attachments,0);g.gtk_flow_box_set_max_children_per_line(attachments,64);g.gtk_box_pack_start(content,attachments,0,1,0)
        actions=g.gtk_box_new(0,5);action_widgets={}
        for mode,title in [('reply','回复'),('reply_all','全部回复'),('forward','转发')]:action_widgets[mode]=self.conversation_icon(actions,title,'reader-'+mode.replace('_','-'),lambda origin=origin,code=mode:self.run_action(lambda:self.reply_message(origin,code)),group)
        history_button=self.conversation_icon(actions,'展开引用历史','action-down',lambda origin=origin:self.toggle_card_history(origin),group)
        g.gtk_widget_set_no_show_all(history_button,1);g.gtk_widget_set_visible(history_button,0)
        g.gtk_box_pack_start(content,actions,0,1,0)
        reply_host=g.gtk_box_new(1,0);draft_host=g.gtk_box_new(1,6);g.gtk_box_pack_start(root,reply_host,0,1,0);g.gtk_box_pack_start(root,draft_host,0,1,0)
        g.connect(toggle,'clicked',lambda *unused,target=origin:self.toggle_conversation_card(target),group=group)
        return {'root':root,'timeline_host':timeline,'history_host':history_host,'history_button':history_button,'history_visible':False,'header':header,'content':content,'body_host':body,'body_loaded':False,'body_readers':[],'reader':None,'quote_cards':[],'quote_states':{},'reply_host':reply_host,'draft_host':draft_host,'expanded':origin==self.conversation_focus,'actions':action_widgets,'toggle':toggle,'disclosure':disclosure,'origin':origin,'attachments':{},'attachments_host':attachments,'menu':menu,'group':group,'avatar':avatar,'avatar_provider':provider,'labels_widget':labels,'image_count':0,'snippet':snippet,'caption':caption,'details_button':details,'details_popover':popup,'details_text':text,'metadata':row}

    # ==========================================
    # Function: Resolve complete source envelope details only when requested.
    # Method: Read the original parsed headers without loading or exposing raw MIME source.
    # ==========================================
    def load_card_details(self,identity):
        card=self.conversation_cards.get(identity)
        if card:self.g.label(card['details_text'],conversation_details(card['details_parsed'] if card.get('details_parsed') else self.service.store.get(identity)['parsed']))

    # ==========================================
    # Function: Lazily materialize one mail body with ordered local history cards.
    # Method: Cache immutable provenance, project history onto sibling cards and lazily restore only the current body.
    # ==========================================
    def load_conversation_body(self,card):
        if card['body_loaded']:return
        from .mail_images import message_images
        store=self.service.store;g=self.g
        if not card.get('history_model'):
            message=store.get(card['origin'],raw=True);parsed=message['parsed']
            model=split_history(parsed.get('html',''),parsed.get('body','') or '(无文字正文)');images=message_images(message['raw'])
            all_cids=set().union(*(fragment_cids(source) for source in history_sources(model)))
            card['orphan_images']=[image for image in images if not image.get('cid') or image['cid'].casefold() not in all_cids]
            card['images']=images;card['image_count']=len(images);card['history_model']=model
            card['timeline_model']=history_timeline(model);card['attachments_info']=parsed['attachments']
        card['body_loaded']=True
        self.render_history_segments(card,card['timeline_model']['current'],card['body_host'],(),card['body_readers'])
        has_history=bool(card['timeline_model']['history'])
        g.gtk_widget_set_no_show_all(card['history_button'],not has_history);g.gtk_widget_set_visible(card['history_button'],has_history)
        if card['orphan_images']:
            self.history_leaf(card,'',card['body_host'],card['body_readers'],card['orphan_images'])
        for attachment in card['attachments_info']:
            from .attachment_cards import card as attachment_card
            button=attachment_card(g,attachment,lambda origin=card['origin'],item=attachment:self.run_action(lambda:self.preview_attachment(origin,item)),'history-body-'+card['origin'])
            g.gtk_container_add(card['attachments_host'],button);card['attachments'][attachment['index']]=button
        card['reader']=next(iter(card['body_readers']),None)
        g.gtk_widget_set_no_show_all(card['attachments_host'],not bool(card['attachments_info']));g.gtk_widget_set_visible(card['attachments_host'],bool(card['attachments_info']))
        self.load_card_details(card['origin']);g.gtk_widget_show_all(card['body_host']);g.gtk_widget_show_all(card['attachments_host'])

    # ==========================================
    # Function: Render only the current generation's rich leaves into its independent body host.
    # Method: History projection owns the sibling headers; this routine never recursively creates widgets.
    # ==========================================
    def render_history_segments(self,card,segments,parent,path,readers):
        g=self.g
        for index,segment in enumerate(segments):
            route=path+(index,)
            if segment['kind']=='current':
                source=segment['source'];cids=fragment_cids(source);images=[image for image in card['images'] if image.get('cid','').casefold() in cids]
                if fragment_text(source).strip() or images or re.search(r'<(?:img|table)\b',source,re.I):self.history_leaf(card,source,parent,readers,images)
                continue

    # ==========================================
    # Function: Add a historical reply as a same-level visual sibling of the source message.
    # Method: Keep only a lightweight header until its own local button requests its body.
    # ==========================================
    def create_history_card(self,card,entry):
        g=self.g;route=entry['path'];root=g.gtk_box_new(1,6);wrapper=g.gtk_box_new(1,0)
        connector=g.gtk_box_new(1,0);g.gtk_widget_set_size_request(connector,1,16);g.gtk_widget_set_halign(connector,1);g.gtk_widget_set_margin_start(connector,28)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(connector),b'history-connector')
        g.gtk_box_pack_start(wrapper,connector,0,0,0);g.gtk_box_pack_start(wrapper,root,0,1,0)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(root),b'quoted-history-card')
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(root),('message-'+bubble_direction(entry,app_own_identities(self))).encode())
        g.gtk_box_pack_start(card['history_host'],wrapper,0,1,0)
        header=g.gtk_box_new(0,6);g.gtk_box_pack_start(root,header,0,1,0)
        badge=message_text(g,g.gtk_label_new('历史'.encode()));g.gtk_style_context_add_class(g.gtk_widget_get_style_context(badge),b'history-badge');g.gtk_box_pack_start(header,badge,0,0,0)
        title=entry['title'];toggle=message_text(g,g.gtk_button_new_with_label(title.encode()));g.gtk_button_set_alignment(toggle,0,.5);g.gtk_widget_set_tooltip_text(toggle,title.encode())
        label=g.gtk_bin_get_child(toggle);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,54);g.gtk_box_pack_start(header,toggle,1,1,0)
        if entry['date']:
            date=g.gtk_label_new(entry['date'][:40].encode());g.gtk_label_set_ellipsize(date,3);g.gtk_label_set_max_width_chars(date,24);g.gtk_widget_set_tooltip_text(date,entry['date'].encode());message_text(g,date);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(date),b'conversation-date');g.gtk_box_pack_start(header,date,0,0,0)
        group='history-quote-'+card['origin']+'-'+'-'.join(map(str,route))
        disclosure=self.conversation_icon(header,'展开历史邮件','conversation-open',lambda:self.toggle_quote_card(card['origin'],route),group)
        body=g.gtk_box_new(1,4);g.gtk_box_pack_start(root,body,0,1,0)
        quote={'root':root,'wrapper':wrapper,'connector':connector,'toggle':toggle,'disclosure':disclosure,'body_host':body,'expanded':False,'reader':None,'readers':[],'children':[],'model':entry,'path':route,'group':group}
        card['quote_cards'].append(quote);g.connect(toggle,'clicked',lambda *unused:self.toggle_quote_card(card['origin'],route),group=group)
        self.toggle_quote_card(card['origin'],route,card['quote_states'].get(route,False))

    # ==========================================
    # Function: Render one inert rich body leaf or a readable native fallback.
    # Method: Reuse the existing CSP sanitizer and pass only that fragment's own MIME images.
    # ==========================================
    def history_leaf(self,card,source,parent,readers,images,entry=None):
        g=self.g
        try:
            from .document_reader import HTMLReader
            card['reader_serial']=card.get('reader_serial',0)+1
            reader=HTMLReader(getattr(self,'reader_owner',self),'conversation-html-'+card['origin']+'-'+str(card['reader_serial']))
            entry=entry if entry is not None else next((quote['model'] for quote in card['quote_cards'] if quote['body_host']==parent),card.get('metadata',{}))
            reader.message_own=bubble_direction(entry,app_own_identities(self))=='own'
            if hasattr(reader,'enable_compact_layout'):reader.enable_compact_layout()
            reader.load(source,images=images);reader.mail_image_indexes={image['index'] for image in images}
            text=fragment_text(source);height=min(5000,max(90,35+sum(max(1,(len(line)+69)//70) for line in text.splitlines())*max(23,int(self.service.store.preference('reader_font_size',14))*1.8)+len(images)*300))
            g.gtk_widget_set_size_request(reader.widget,-1,int(min(height,280) if getattr(reader,'compact_mail',False) else height));g.gtk_widget_set_vexpand(reader.widget,0);g.gtk_box_pack_start(parent,reader.widget,0,1,0);reader.attached();readers.append(reader)
        except RuntimeError:
            label=message_text(g,g.gtk_label_new((fragment_text(source) or '(无文字正文)').encode()));g.gtk_label_set_line_wrap(label,1);g.gtk_label_set_selectable(label,1);g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(parent,label,0,1,0)

    # ==========================================
    # Function: Independently disclose one flat historical reply without changing any other card.
    # Method: Create or release only the chosen card's own engines and retain its stable provenance route.
    # ==========================================
    def toggle_quote_card(self,identity,path,expanded=None):
        card=self.conversation_cards.get(identity)
        if not card:return
        if expanded is not False and not (card['expanded'] and card.get('history_visible')):return
        quote=next((item for item in card['quote_cards'] if item['path']==tuple(path)),None)
        if not quote:return
        state=not quote['expanded'] if expanded is None else bool(expanded);card['quote_states'][tuple(path)]=state
        if state and not quote['expanded']:
            quote['expanded']=True;self.render_history_segments(card,quote['model']['segments'],quote['body_host'],quote['path'],quote['readers']);quote['reader']=next(iter(quote['readers']),None)
        elif not state and quote['expanded']:
            for reader in quote['readers']:reader.close()
            quote['readers']=[];quote['reader']=None;self.g.clear(quote['body_host']);quote['expanded']=False
        self.g.gtk_widget_set_no_show_all(quote['body_host'],not state)
        if state:self.g.gtk_widget_show_all(quote['body_host'])
        self.g.gtk_widget_set_visible(quote['body_host'],state)
        self.g.gtk_button_set_image(quote['disclosure'],self.g.image_file(Path(__file__).parent/'desktop_assets/icons'/('conversation-close.svg' if state else 'conversation-open.svg'),17))
        self.g.gtk_widget_set_tooltip_text(quote['disclosure'],('收起引用历史' if state else '展开引用历史').encode())
        if state and quote['reader']:self.html_reader=quote['reader']

    # ==========================================
    # Function: Disclose the source card's entire owned flat history chain on request.
    # Method: Create quote headers once, retain local choices and update the directional action icon.
    # ==========================================
    def toggle_card_history(self,identity,visible=None):
        card=self.conversation_cards.get(identity)
        if not card or not card['expanded']:return
        wanted=not card.get('history_visible') if visible is None else bool(visible)
        card['history_visible']=wanted and bool(card['timeline_model']['history'])
        if card['history_visible'] and not card.get('history_initialized'):
            card['history_initialized']=True
            for entry in card['timeline_model']['history']:self.create_history_card(card,entry)
        self.show_card_history(card,card['history_visible'])
        icon_action(self.g,card['history_button'],'收起引用历史' if card['history_visible'] else '展开引用历史','action-up' if card['history_visible'] else 'action-down',17)
        context=self.g.gtk_widget_get_style_context(card['history_button'])
        (self.g.gtk_style_context_add_class if card['history_visible'] else self.g.gtk_style_context_remove_class)(context,b'active')
        self.sync_conversation_reader()

    # ==========================================
    # Function: Gate quote cards and connectors together without nesting the visual cards.
    # Method: Release hidden engines and retain per-quote disclosure behind a no-show-all host.
    # ==========================================
    def show_card_history(self,card,visible):
        g=self.g;visible=bool(visible and card['expanded'] and card.get('history_visible'))
        for quote in card['quote_cards']:
            wanted=card['quote_states'].get(quote['path'],quote['expanded'])
            self.toggle_quote_card(card['origin'],quote['path'],wanted if visible else False)
            card['quote_states'][quote['path']]=wanted
        g.gtk_widget_set_no_show_all(card['history_host'],not visible)
        if visible:g.gtk_widget_show_all(card['history_host'])
        g.gtk_widget_set_visible(card['history_host'],visible)

    # ==========================================
    # Function: Toggle one RFC card without touching its live reply host or other cards.
    # Method: Gate owned flat histories on source visibility, release engines on collapse and restore local choices.
    # ==========================================
    def toggle_conversation_card(self,identity,expanded=None):
        card=self.conversation_cards.get(identity)
        if not card:return
        opening=expanded is None and not card['expanded'];state=not card['expanded'] if expanded is None else bool(expanded)
        card['expanded']=state
        if state:self.load_conversation_body(card)
        elif card['body_loaded']:
            for reader in card['body_readers']:reader.close()
            card['body_readers']=[];card['reader']=None;self.g.disconnect('history-body-'+identity);self.g.clear(card['body_host']);self.g.clear(card['attachments_host']);card['attachments']={};card['body_loaded']=False
        if not state:
            card['history_visible']=False
            self.g.gtk_style_context_remove_class(self.g.gtk_widget_get_style_context(card['history_button']),b'active')
            icon_action(self.g,card['history_button'],'展开引用历史','action-down',17)
        self.show_card_history(card,state)
        g=self.g;g.gtk_widget_set_no_show_all(card['content'],not state);g.gtk_widget_set_visible(card['content'],state);g.gtk_widget_set_no_show_all(card['snippet'],state);g.gtk_widget_set_visible(card['snippet'],not state)
        g.gtk_button_set_image(card['disclosure'],g.image_file(Path(__file__).parent/'desktop_assets/icons'/('conversation-close.svg' if state else 'conversation-open.svg'),17))
        g.gtk_widget_set_tooltip_text(card['toggle'],(('收起邮件' if state else '展开邮件')+' · '+card['caption']).encode());g.gtk_widget_set_tooltip_text(card['disclosure'],('收起邮件' if state else '展开邮件').encode())
        self.sync_conversation_reader()
        if opening and self.service.store.preference('mark_read_on_open',True) and self.service.mark_opened(identity):self.queue.put((lambda result:self.refresh(),None));self.background(self.service.flush_read_flags)

    # ==========================================
    # Function: Refresh card labels and policies using metadata without decoding all cached MIME.
    # Method: Batch label reads and update only existing open native body engines.
    # ==========================================
    def update_conversation_metadata(self,reload=False):
        store=self.service.store;g=self.g;labels=store.labels_for(self.conversation_cards);own=app_own_identities(self)
        for origin,card in self.conversation_cards.items():
            for item,entry,readers in [(card,card['metadata'],card['body_readers'])]+[(quote,quote['model'],quote['readers']) for quote in card['quote_cards']]:
                direction=bubble_direction(entry,own);context=g.gtk_widget_get_style_context(item['root'])
                g.gtk_style_context_remove_class(context,('message-'+('other' if direction=='own' else 'own')).encode());g.gtk_style_context_add_class(context,('message-'+direction).encode())
                for reader in readers:
                    changed=getattr(reader,'message_own',None)!=(direction=='own');reader.message_own=direction=='own'
                    if changed and not reload:reader.reload()
            row=card['metadata'];values=labels.get(origin,[]) if store.preference('labels_reader',True) else []
            if store.preference('labels_system',False):values=values+list(filter(None,['已完成' if row.get('done') else '', '已置顶' if row.get('pinned') else '',row.get('category','')]))
            g.label(card['labels_widget'],' · '.join(values));g.gtk_widget_set_no_show_all(card['labels_widget'],not bool(values));g.gtk_widget_set_visible(card['labels_widget'],bool(values))
            shown=store.preference('avatars_mode','everywhere') in ('everywhere','reader');g.gtk_widget_set_no_show_all(card['avatar'],not shown);g.gtk_widget_set_visible(card['avatar'],shown)
            style=self.identity_colors.style(row['sender'],row['account'])
            if style!=card.get('avatar_style'):card['avatar_provider']=g.style(card['avatar'],'label { background-color: '+style['background']+'; color: #ffffff; border: 2px solid '+style['border']+'; }',card['avatar_provider']);card['avatar_style']=style
            if reload:
                for reader in card['body_readers']+[reader for quote in card['quote_cards'] for reader in quote['readers']]:
                    reader.reload()
                    if hasattr(reader,'original') and not getattr(reader,'compact_mail',False):
                        source,markdown,images=reader.original;text=fragment_text(source)
                        height=min(5000,max(90,35+sum(max(1,(len(line)+69)//70) for line in text.splitlines())*max(23,int(store.preference('reader_font_size',14))*1.8)+len(images or [])*300))
                        g.gtk_widget_set_size_request(reader.widget,-1,int(height))

    # ==========================================
    # Function: Point compatibility document actions at a live selected body renderer.
    # Method: Prefer current-body leaves without constructing any closed historical message.
    # ==========================================
    def sync_conversation_reader(self):
        card=getattr(self,'conversation_cards',{}).get(getattr(self,'conversation_focus',None))
        self.html_reader=(card.get('reader') or next((quote['reader'] for quote in card['quote_cards'] if quote['reader']),None)) if card else getattr(self,'legacy_html_reader',None)

    # ==========================================
    # Function: Reveal the exact local history leaf owning an image attachment.
    # Method: Open only the owning flat card and return its MIME-index-bound renderer.
    # ==========================================
    def image_reader_for(self,identity,index=None):
        chat=getattr(self,'chat_surface',None)
        if chat is not self and chat and identity in chat.conversation_cards:return chat.image_reader_for(identity,index)
        card=self.conversation_cards.get(identity)
        if not card:
            if self.selected!=identity:self.read(identity)
            if self.selected!=identity:return None
            self.render_conversation(identity);card=self.conversation_cards.get(identity) or self.conversation_cards.get(self.conversation_focus)
        if not card:return None
        self.toggle_conversation_card(card['origin'],True)
        if index is None:return card.get('reader')
        target=next((image for image in card['images'] if image['index']==index),None)
        # ==========================================
        # Function: Find the first ordered quote path referencing this exact CID.
        # Method: Traverse render metadata only; no quoted body is loaded until its ancestor opens.
        # ==========================================
        def locate(segments,path=()):
            for position,segment in enumerate(segments):
                if segment['kind']=='current':
                    if target and target.get('cid','').casefold() in fragment_cids(segment['source']):return path
                else:
                    found=locate(segment['segments'],path+(position,))
                    if found is not None:return found
            return None
        path=locate(card['history_model']['segments'])
        if path:
            self.toggle_card_history(card['origin'],True)
            quote=next((quote for quote in card['quote_cards'] if path in quote['model'].get('aliases',(quote['path'],))),None)
            if quote:self.toggle_quote_card(card['origin'],quote['path'],True)
        readers=card['body_readers']+[reader for quote in card['quote_cards'] for reader in quote['readers']]
        reader=next((reader for reader in readers if index in getattr(reader,'mail_image_indexes',set())),card.get('reader'))
        if reader:
            g=self.g;scroller=g.gtk_widget_get_ancestor(reader.widget,g.gtk_scrolled_window_get_type())
            if scroller and not getattr(reader,'compact_mail',False):g.gtk_widget_set_size_request(reader.widget,-1,max(200,g.gtk_widget_get_allocated_height(scroller)-100))
            self.pending_conversation_reveal=(card['origin'],time.monotonic()+.15,reader,index)
        return reader

    # ==========================================
    # Function: Create a compact original line-icon action with an accessible name.
    # Method: Keep native pointer and keyboard activation on one small rounded button.
    # ==========================================
    def conversation_icon(self,parent,title,icon,callback,group):
        g=self.g;button=g.gtk_button_new()
        g.gtk_button_set_image(button,g.image_file(Path(__file__).parent/'desktop_assets/icons'/(icon+'.svg'),17));g.gtk_button_set_always_show_image(button,1)
        g.gtk_widget_set_tooltip_text(button,title.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'mail-icon-action')
        g.connect(button,'clicked',lambda *unused:callback(),group=group);g.gtk_box_pack_start(parent,button,0,0,0)
        return button

    # ==========================================
    # Function: Release scrolling room reserved by a contextual floating editor.
    # Method: Remove only the conversation's bottom padding, leaving mail and draft cards intact.
    # ==========================================
    def clear_reply_reserve(self):
        self.g.gtk_widget_set_margin_bottom(self.widget('conversation_host'),0)

    # ==========================================
    # Function: Resume a saved or live contextual reply in its existing editor.
    # Method: Reuse one draft identity and optionally transfer its exact form to a native window.
    # ==========================================
    def resume_reply_draft(self,identity,external=False):
        current=self.composer
        if not current or current.closed:
            job=self.service.store.job(identity)
            self.open_composer({**job['draft'],'id':identity,'account':job['account']});current=self.composer
        elif current.identity!=identity:
            self.message('请先保存或关闭当前正在编辑的草稿');return
        if external:current.detach_surface()
        elif current.detached:self.g.gtk_window_present(current.surface_window)
        else:
            self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'mail' if current.inline else b'composer')
            self.g.gtk_widget_show_all(current.window);self.g.gtk_widget_grab_focus(current.fields['body'][0])

    # ==========================================
    # Function: Keep saved reply previews separate from the live conversation editor.
    # Method: Combine local saved reply identities with the single live draft without copying its buffer.
    # ==========================================
    def update_reply_draft_cards(self):
        cards=getattr(self,'conversation_cards',{})
        if not cards:return
        drafts={job['id']:job for job in self.service.store.reply_drafts(cards)}
        editor=self.composer if self.composer and not self.composer.closed else None
        if editor and editor.reply.get('reply_source') in cards:
            drafts[editor.identity]={'id':editor.identity,'account':editor.value('account'),'draft':{key:editor.value(key) for key in ('to','subject','body')}|editor.reply}
        g=self.g
        for origin,card in cards.items():
            group='reply-drafts-'+origin;g.disconnect(group);g.clear(card['draft_host']);card['draft_cards']={}
            for job in drafts.values():
                if job['draft'].get('reply_source')!=origin:continue
                if editor and editor.identity==job['id'] and editor.inline and not editor.detached:continue
                preview=g.gtk_box_new(0,5);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(preview),b'inline-draft-card')
                button=g.gtk_button_new();labels=g.gtk_box_new(1,3)
                for text,css in [('草稿 · '+(job['draft'].get('to') or '回复邮件'),'draft-card-title'),(job['draft'].get('body','').strip().split('\n')[0][:90] or '点击继续撰写','mail-preview')]:
                    label=g.gtk_label_new(text.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,40)
                    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),css.encode());g.gtk_box_pack_start(labels,label,0,1,0)
                g.gtk_container_add(button,labels);g.gtk_box_pack_start(preview,button,1,1,0)
                g.connect(button,'clicked',lambda *unused,identity=job['id']:self.run_action(lambda:self.resume_reply_draft(identity)),group=group)
                popout=self.conversation_icon(preview,'在独立窗口继续撰写','composer-popout',lambda identity=job['id']:self.run_action(lambda:self.resume_reply_draft(identity,True)),group)
                g.gtk_box_pack_start(card['draft_host'],preview,0,1,8);card['draft_cards'][job['id']]={'root':preview,'button':button,'popout':popout}
                if editor and editor.identity==job['id']:editor.inline_card=preview
            g.gtk_widget_show_all(card['draft_host'])
        if editor and editor.inline:editor.size_surface()

    # ==========================================
    # Function: Start an editor under the exact card chosen by the user.
    # Method: Retain source-account headers, MIME attachment identities and reply context.
    # ==========================================
    def reply_message(self,identity,mode='reply'):
        if mode=='reply':self.reply(identity)
        else:self.reply_extended(mode,identity)

    # ==========================================
    # Function: Honor an explicit full-list preference for a separate conversation window.
    # Method: Reparent the existing reader surface rather than constructing another mail or document model.
    # ==========================================
    def ensure_thread_window(self):
        store=self.service.store;g=self.g
        wanted=(not self.closing and bool(self.selected) and not self.selected.startswith('job:') and store.preference('layout_mode','splitView')=='fullScreen' and store.preference('thread_new_window',False) and getattr(self,'thread_window_dismissed','')!=self.selected)
        window=getattr(self,'thread_window',None)
        if window and not wanted:
            g.gtk_widget_reparent(self.widget('reader'),self.thread_reader_parent)
            self.thread_window=None;g.disconnect('thread-window');g.gtk_widget_destroy(window)
            return
        if not wanted:return
        if not window:
            self.thread_reader_parent=g.gtk_widget_get_parent(self.widget('reader'))
            window=g.gtk_window_new(0);self.thread_window=window
            from .windows_frame import bind_window_frame
            bind_window_frame(self,window,'thread-window')
            g.gtk_window_set_title(window,b'TeleMail');g.gtk_window_set_default_size(window,980,760)
            g.gtk_window_set_application(window,self.application);g.gtk_window_set_transient_for(window,self.window)
            g.gtk_widget_reparent(self.widget('reader'),window)
            g.connect(window,'delete-event',lambda *unused:self.close_thread_window(),count=3,returns=True,group='thread-window')
            g.gtk_widget_show(window);g.gtk_window_present(window)
        dark=resolved_theme(self)=='dark';context=g.gtk_widget_get_style_context(window)
        g.gtk_style_context_remove_class(context,b'light' if dark else b'dark');g.gtk_style_context_add_class(context,b'dark' if dark else b'light')

    # ==========================================
    # Function: Return a separate conversation surface to the main native application.
    # Method: Reparent before destroying the empty window and preserve any unsent draft on save failure.
    # ==========================================
    def close_thread_window(self,preserve_composer=False):
        window=getattr(self,'thread_window',None)
        if not window:return True
        if not self.close_document(preserve_composer=preserve_composer):return True
        self.g.gtk_widget_reparent(self.widget('reader'),self.thread_reader_parent)
        self.thread_window=None;self.thread_window_dismissed=self.selected;self.g.disconnect('thread-window');self.g.gtk_widget_destroy(window)
        self.layout_override=False;self.apply_layout();return True
