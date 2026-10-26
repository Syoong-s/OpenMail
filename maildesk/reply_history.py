"""Original reply content kept separate from authored text and appended once at MIME creation."""
from html import escape
from .mime import MAX_MESSAGE_BYTES
from .ui_actions import icon_action

# ==========================================
# Function: Retain the selected original mail including all history already present in its body.
# Method: Copy complete source text/HTML without splitting quotes into generated cards.
# ==========================================
def from_message(message):
    parsed=message.get('parsed',{});headers=parsed.get('headers',{})
    sender=headers.get('from') or parsed.get('sender','');date=headers.get('date','')
    caption=('On '+date+', ' if date else '')+sender+' wrote:'
    plain=parsed.get('body','');html=parsed.get('html','')
    if not plain and not html:return {}
    return {'source':message.get('id',''),'caption':caption,'plain':plain,'html':html}

# ==========================================
# Function: Validate durable reply-history metadata independently of authored fields.
# Method: Accept only bounded original string fields without changing their exact source contents.
# ==========================================
def validated(value):
    if not value:return {}
    keys={'source','caption','plain','html'}
    if not isinstance(value,dict) or set(value)-keys or any(not isinstance(v,str) for v in value.values()):raise ValueError('回复历史格式无效')
    if sum(len(v.encode('utf-8')) for v in value.values())>MAX_MESSAGE_BYTES*2:raise ValueError('回复历史过大')
    return {key:value.get(key,'') for key in keys}

# ==========================================
# Function: Render the complete original history as one HTML fragment.
# Method: Preserve existing nested source markup and use one outer attribution rather than card generation.
# ==========================================
def fragment(history):
    content=history.get('html') or '<pre style="white-space:pre-wrap">'+escape(history.get('plain',''))+'</pre>'
    return '<div class="maildesk-reply-history"><p>'+escape(history.get('caption',''))+'</p><blockquote type="cite">'+content+'</blockquote></div>'

# ==========================================
# Function: Include original history only in the final MIME projection.
# Method: Leave saved authored buffers untouched so editing, handoff and repeated saving never duplicate quotes.
# ==========================================
def with_history(draft):
    history=validated(draft.get('reply_history'))
    if not history or not (history['plain'] or history['html']):return draft
    result=dict(draft);plain=history['plain']
    if not plain:
        from .mime import TextExtractor
        extractor=TextExtractor();extractor.feed(history['html']);plain=''.join(extractor.output).strip()
    result['body']=draft.get('body','')+'\n\n'+history['caption']+'\n'+'\n'.join('> '+line for line in plain.splitlines())
    authored=draft.get('html') or '<div>'+escape(draft.get('body','')).replace('\n','<br>')+'</div>'
    result['html']=authored+fragment(history)
    return result

# ==========================================
# Function: Disclose the original mail in a single native reader below the authored buffer.
# Method: Create at most one complete-source renderer lazily; never construct nested history widgets.
# ==========================================
class ReplyHistoryView:
    # ==========================================
    # Function: Add directional history controls and a bounded original-content host.
    # Method: Keep generated history outside the editable TextView and payload's authored HTML.
    # ==========================================
    def __init__(self,owner,parent,data):
        self.owner=owner;self.app=owner.app;self.g=g=owner.g;self.data=validated(data);self.reader=None;self.content_ready=False;self.expanded=False;self.closed=False
        self.root=g.gtk_box_new(1,3);g.gtk_box_pack_start(parent,self.root,0,1,0)
        controls=g.gtk_box_new(0,0);self.controls=controls;g.gtk_widget_set_halign(controls,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(controls),b'reply-history-controls');g.gtk_box_pack_start(self.root,controls,0,0,0)
        self.button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'reply-history-toggle');g.gtk_box_pack_start(controls,self.button,0,0,0);self.update_toggle()
        self.remove_button=g.gtk_button_new();icon_action(g,self.remove_button,'删除附带历史（保留原邮件）','composer-close',14);g.gtk_button_set_image(self.remove_button,None);g.gtk_button_set_label(self.remove_button,'×'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.remove_button),b'reply-history-remove');g.gtk_box_pack_start(controls,self.remove_button,0,0,0)
        self.host=g.gtk_box_new(1,0);g.gtk_widget_set_no_show_all(self.host,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.host),b'reply-history-card');g.gtk_box_pack_start(self.root,self.host,0,1,0)
        self.set_visible(bool(self.data))
        g.connect(self.button,'clicked',lambda *unused:self.toggle(),group=owner.group)
        g.connect(self.remove_button,'clicked',lambda *unused:self.remove(),group=owner.group)

    # ==========================================
    # Function: Express the next history action with a directional icon and explicit name.
    # Method: Remove the empty label from GtkButton image layout, center the smaller arrow and retain accessible action text.
    # ==========================================
    def update_toggle(self):
        icon_action(self.g,self.button,'收起附带历史' if self.expanded else '展开附带历史','filter-chevron-up' if self.expanded else 'filter-chevron-down',10)
        self.g.gtk_button_set_label(self.button,None);self.g.gtk_button_set_alignment(self.button,.5,.5)

    # ==========================================
    # Function: Detach history from this draft without changing its source mail or reply headers.
    # Method: Clear durable owner metadata before closing the one preview and returning focus to authored text.
    # ==========================================
    def remove(self):
        if self.closed or self.owner.closed or not self.data:return
        if not self.owner.remove_reply_history():return
        self.data={};self.expanded=False
        if self.reader:self.reader.close();self.reader=None
        self.g.gtk_widget_hide(self.host);self.set_visible(False)
        self.g.gtk_widget_grab_focus(self.owner.body if hasattr(self.owner,'body') else self.g.object(self.owner.builder,'body'))
        if hasattr(self.owner,'queue_surface_size'):self.owner.queue_surface_size()

    # ==========================================
    # Function: Keep disclosure availability explicit across ancestor show-all operations.
    # Method: Protect the original-history host and hide the entire control in a collapsed chat dock.
    # ==========================================
    def set_visible(self,visible):
        g=self.g
        if visible and self.data:
            g.gtk_widget_set_no_show_all(self.root,0);g.gtk_widget_show_all(self.root);g.gtk_widget_set_no_show_all(self.root,1)
        else:g.gtk_widget_set_no_show_all(self.root,1);g.gtk_widget_hide(self.root)

    # ==========================================
    # Function: Toggle one bounded raw-history view while preserving the original authored buffer.
    # Method: Reuse the existing sanitized HTML reader and retain the same single instance on folding.
    # ==========================================
    def toggle(self):
        if self.closed or self.owner.closed or not self.data:return
        self.expanded=not self.expanded;g=self.g
        if self.expanded and not self.content_ready:
            try:
                from .document_reader import HTMLReader
                self.reader=HTMLReader(self.app,self.owner.group+'-original-history');self.reader.load(fragment(self.data));g.gtk_widget_set_size_request(self.reader.widget,-1,170);g.gtk_box_pack_start(self.host,self.reader.widget,0,1,0);self.reader.attached()
            except RuntimeError:
                if self.reader:self.reader.close();self.reader=None
                plain=self.data.get('plain') or ''
                if not plain:
                    from .mime import TextExtractor
                    extractor=TextExtractor();extractor.feed(self.data.get('html',''));plain=''.join(extractor.output).strip()
                text=g.gtk_label_new(plain.encode());g.gtk_label_set_line_wrap(text,1);g.gtk_label_set_selectable(text,1)
                scroll=g.gtk_scrolled_window_new(None,None);g.gtk_widget_set_size_request(scroll,-1,170);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_container_add(scroll,text);g.gtk_box_pack_start(self.host,scroll,0,1,0)
            self.content_ready=True
        if self.expanded:
            g.gtk_widget_set_no_show_all(self.host,0);g.gtk_widget_show_all(self.host);g.gtk_widget_set_no_show_all(self.host,1)
        else:g.gtk_widget_hide(self.host)
        self.update_toggle()
        if hasattr(self.owner,'queue_surface_size'):
            self.owner.queue_surface_size();self.owner.scroll_into_view()

    # ==========================================
    # Function: Release the complete-source reader before its owning composer widgets disappear.
    # Method: Use the existing reader shutdown contract with no independent browser window.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True
        if self.reader:self.reader.close();self.reader=None
