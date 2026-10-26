"""Bounded saved-contact chooser shared by native mail recipient fields."""
import ctypes as C
from email.headerregistry import Address
from email.utils import getaddresses
from . import address_book
from .desktop_general import bind,P,I
from .participant_identity import normalize_address
from .ui_actions import icon_action

# ==========================================
# Function: Add an explicit saved-contact selector to one existing recipient entry.
# Method: Query local metadata off GTK and require a separate choice for multi-address people.
# ==========================================
class RecipientPicker:
    # ==========================================
    # Function: Construct a compact input-row button and an owned searchable contact popup.
    # Method: Preserve the original GtkEntry and use one request channel per field.
    # ==========================================
    def __init__(self,owner,entry,row):
        self.owner=owner;self.app=owner.app;self.g=g=owner.g;self.entry=entry;self.closed=False;self.serial=0;self.offset=0;self.total=0;self.loading=False;self.items=[];self.row_buttons={};self.alias_popup=None;self.alias_buttons={};self.restore_source=0;self.last_scroll=0;self.directory_query=''
        self.group='recipient-picker-'+str(entry);self.channel=self.group
        self.button=g.gtk_menu_button_new();icon_action(g,self.button,'从通讯录选择联系人','settings-contacts',16)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'recipient-picker-button');g.gtk_box_pack_start(row,self.button,0,0,0)
        self.popup=g.gtk_popover_new(self.button);self.style(self.popup,'recipient-picker');g.surfaces.states[self.popup]['width']=340
        self.content=g.gtk_box_new(1,6);g.gtk_container_set_border_width(self.content,8);g.gtk_container_add(self.popup,self.content)
        heading=g.gtk_label_new('选择联系人'.encode());g.gtk_label_set_xalign(heading,0);self.style(heading,'picker-heading');g.gtk_box_pack_start(self.content,heading,0,1,0)
        self.search=bind(self.app,'gtk','gtk_search_entry_new',P)();g.gtk_entry_set_placeholder_text(self.search,'搜索姓名或邮箱'.encode());g.gtk_box_pack_start(self.content,self.search,0,1,0)
        self.scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(self.scroll,2,1);g.gtk_scrolled_window_set_propagate_natural_height(self.scroll,1);g.gtk_scrolled_window_set_max_content_height(self.scroll,280);g.gtk_box_pack_start(self.content,self.scroll,0,1,0)
        self.rows=g.gtk_box_new(1,2);g.gtk_container_add(self.scroll,self.rows)
        footer=g.gtk_box_new(0,6);g.gtk_box_pack_start(self.content,footer,0,1,0)
        self.note=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.note,0);g.gtk_label_set_ellipsize(self.note,3);self.style(self.note,'choice-description');g.gtk_box_pack_start(footer,self.note,1,1,0)
        self.adjustment=g.gtk_scrolled_window_get_vadjustment(self.scroll);g.connect(self.adjustment,'value-changed',self.scrolled,group=self.group)
        g.gtk_menu_button_set_popover(self.button,self.popup)
        g.connect(self.button,'toggled',self.toggled,group=self.group);g.connect(self.search,'search-changed',lambda *unused:self.load(0) if self.opened() else None,group=self.group)
        g.connect(self.button,'unmap',lambda *unused:self.dismiss(),group=self.group)

    # ==========================================
    # Function: Assign one shared visual role without per-row CSS providers.
    # Method: Keep all colors in the existing generated theme stylesheet.
    # ==========================================
    def style(self,widget,role):
        self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(widget),role.encode())

    # ==========================================
    # Function: Check popup lifetime before applying asynchronous metadata.
    # Method: Require both the editor and its managed menu to remain open.
    # ==========================================
    def opened(self):
        return not self.closed and not self.owner.closed and bool(self.g.surfaces.states.get(self.popup,{}).get('open'))

    # ==========================================
    # Function: Load on explicit opening and invalidate pending results on dismissal.
    # Method: Retain the query for reopening but reset the result offset each time.
    # ==========================================
    def toggled(self,*unused):
        if self.closed:return
        if self.g.gtk_toggle_button_get_active(self.button):
            if getattr(self.owner,'busy',False):self.dismiss();return
            self.load(0);self.g.gtk_widget_grab_focus(self.search)
        else:
            self.serial+=1;self.loading=False;self.app.local_loader.cancel(self.channel)
            if self.restore_source:self.g.g_source_remove(self.restore_source);self.restore_source=0

    # ==========================================
    # Function: Query a bounded searchable slice of the same saved Settings contacts.
    # Method: Use shared star-first directory pages, latest-only requests and successful offset commits.
    # ==========================================
    def load(self,offset=0,direction=''):
        if not self.opened():return
        self.serial+=1;serial=self.serial;query=self.g.text(self.search);self.loading=True;g=self.g
        g.label(self.note,'正在加载…')
        old_value=bind(self.app,'gtk','gtk_adjustment_get_value',C.c_double,P)(self.adjustment);anchor_id=next(iter(self.row_buttons),'');anchor_y=0
        if direction=='down' and self.items:anchor_id=self.items[min(40,len(self.items)-1)]['id']
        if anchor_id in self.row_buttons:
            x,y=I(),I();g.gtk_widget_translate_coordinates(self.row_buttons[anchor_id],self.rows,0,0,C.byref(x),C.byref(y));anchor_y=y.value
        # ==========================================
        # Function: Read compact local contact metadata without blocking native input.
        # Method: Return a bounded page or a presentation error without touching any mail provider.
        # ==========================================
        def operation():
            try:return address_book.page(self.app.service.store,query,offset,120),''
            except Exception as error:return None,str(error)
        # ==========================================
        # Function: Replace only the still-open selector's result rows.
        # Method: Reject stale search/editor completions before accessing any native widget.
        # ==========================================
        def ready(result):
            if not self.opened() or serial!=self.serial or query!=g.text(self.search):return
            page,error=result
            if error:self.loading=False;g.label(self.note,'加载失败，可重新搜索');self.app.message(error);return
            if self.alias_popup in g.surfaces.states:g.gtk_widget_destroy(self.alias_popup)
            g.surfaces.retire(self.group+'-aliases')
            self.offset=page['offset'];self.total=page['total'];self.items=page['items'];self.row_buttons={};self.alias_popup=None;self.alias_buttons={};self.directory_query=query
            g.surfaces.retire(self.group+'-rows');g.clear(self.rows)
            last=''
            for item in self.items:
                if item['letter']!=last:
                    last=item['letter'];section=g.gtk_label_new(('带星标联系人' if last=='★' else last).encode());g.gtk_label_set_xalign(section,0);self.style(section,'picker-section');g.gtk_box_pack_start(self.rows,section,0,1,0)
                button=g.gtk_button_new();self.style(button,'choice-option');line=g.gtk_box_new(0,9);g.gtk_container_add(button,line)
                title=item['name'] or item['addresses'][0]
                avatar=g.gtk_label_new(title[:1].upper().encode());self.style(avatar,'picker-avatar');g.gtk_box_pack_start(line,avatar,0,0,0)
                labels=g.gtk_box_new(1,2);g.gtk_box_pack_start(line,labels,1,1,0)
                for text,role in [(title,''),(item['addresses'][0],'choice-description')]:
                    label=g.gtk_label_new(text.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,28)
                    if role:self.style(label,role)
                    g.gtk_box_pack_start(labels,label,0,1,0)
                if len(item['addresses'])>1:
                    more=g.gtk_label_new((str(len(item['addresses']))+' 邮箱 ›').encode());self.style(more,'choice-description');g.gtk_box_pack_start(line,more,0,0,0)
                self.row_buttons[item['id']]=button;g.gtk_box_pack_start(self.rows,button,0,1,0)
                g.connect(button,'clicked',lambda *unused,person=item['id'],anchor=button:self.choose(person,anchor),group=self.group+'-rows')
            if not self.items:
                empty=g.gtk_label_new(('没有匹配的联系人' if query else '通讯录中还没有联系人').encode());self.style(empty,'picker-empty');g.gtk_box_pack_start(self.rows,empty,0,1,0)
            g.label(self.note,str(self.total)+' 位联系人' if self.total else '本地通讯录')
            g.gtk_widget_show_all(self.content);state=g.surfaces.states.get(self.popup)
            if state:g.surfaces.position(state)
            # ==========================================
            # Function: Retain the visible contact when replacing an overlapping scroll window.
            # Method: Restore its native row offset after GTK allocation without a visible page transition.
            # ==========================================
            def restore(*unused):
                self.restore_source=0
                if not self.opened() or serial!=self.serial:return 0
                value=0
                if direction and anchor_id in self.row_buttons:
                    x,y=I(),I();g.gtk_widget_translate_coordinates(self.row_buttons[anchor_id],self.rows,0,0,C.byref(x),C.byref(y));value=max(0,old_value+y.value-anchor_y)
                bind(self.app,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(self.adjustment,value)
                self.last_scroll=value;self.loading=False;return 0
            if self.restore_source:g.g_source_remove(self.restore_source)
            self.restore_callback=C.CFUNCTYPE(I,P)(restore);self.restore_source=g.g_timeout_add(40,C.cast(self.restore_callback,P),None)
        self.app.local_loader.request(self.channel,operation,ready)

    # ==========================================
    # Function: Browse all saved contacts continuously in the same grouped popup.
    # Method: Move a bounded overlapping window only at scroll edges and preserve its visual anchor.
    # ==========================================
    def scrolled(self,*unused):
        if self.loading or not self.opened() or self.g.text(self.search)!=self.directory_query:return
        get=lambda name:bind(self.app,'gtk','gtk_adjustment_get_'+name,C.c_double,P)(self.adjustment)
        value=get('value');previous=self.last_scroll;self.last_scroll=value
        if value>previous and value+get('page_size')>=get('upper')-80 and self.offset+len(self.items)<self.total:self.load(self.offset+40,'down')
        elif value<previous and value<70 and self.offset>0:self.load(max(0,self.offset-40),'up')

    # ==========================================
    # Function: Resolve the clicked person's current saved addresses before inserting anything.
    # Method: Requery its stable ID and show an additional side popup when there are multiple aliases.
    # ==========================================
    def choose(self,person,anchor):
        if not self.opened() or getattr(self.owner,'busy',False):return
        self.serial+=1;serial=self.serial
        # ==========================================
        # Function: Apply one explicit person's latest mailbox membership.
        # Method: Keep the entry unchanged until exactly one saved address is chosen.
        # ==========================================
        def ready(detail):
            if not self.opened() or serial!=self.serial:return
            addresses=detail.get('addresses',[])
            if not addresses:self.g.label(self.note,'此联系人已没有可用邮箱');return
            if len(addresses)==1:self.insert(detail.get('name',''),addresses[0]);return
            self.show_aliases(anchor,detail)
        self.app.local_loader.request(self.channel,lambda:address_book.sender_detail(self.app.service.store,person=person),ready)

    # ==========================================
    # Function: Present every saved alias as a separate explicit choice beside its contact.
    # Method: Use the broker's nested popup ownership and bounded native alias rows.
    # ==========================================
    def show_aliases(self,anchor,detail):
        g=self.g
        if self.alias_popup in g.surfaces.states:g.gtk_widget_destroy(self.alias_popup)
        g.surfaces.retire(self.group+'-aliases')
        self.alias_popup=g.gtk_popover_new(anchor);self.style(self.alias_popup,'recipient-picker');g.surfaces.beside(self.alias_popup,anchor);g.surfaces.states[self.alias_popup]['width']=300
        box=g.gtk_box_new(1,3);g.gtk_container_set_border_width(box,8);g.gtk_container_add(self.alias_popup,box)
        title=g.gtk_label_new(('选择邮箱 · '+(detail.get('name') or '联系人')).encode());g.gtk_label_set_xalign(title,0);g.gtk_label_set_ellipsize(title,3);self.style(title,'picker-heading');g.gtk_box_pack_start(box,title,0,1,0)
        self.alias_buttons={}
        for address in detail['addresses']:
            button=g.gtk_button_new_with_label(address.encode());self.style(button,'choice-option');g.gtk_widget_set_tooltip_text(button,address.encode());g.gtk_box_pack_start(box,button,0,1,0);self.alias_buttons[address]=button
            label=g.gtk_bin_get_child(button);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,30);g.gtk_label_set_xalign(label,0)
            g.connect(button,'clicked',lambda *unused,email=address,name=detail.get('name',''):self.insert(name,email),group=self.group+'-aliases')
        g.gtk_widget_show_all(box);g.gtk_popover_popup(self.alias_popup)

    # ==========================================
    # Function: Append exactly the explicitly selected mailbox without duplicating an existing recipient.
    # Method: Preserve authored recipients, encode display names safely and let normal changed handlers run.
    # ==========================================
    def insert(self,name,address):
        if not self.opened() or getattr(self.owner,'busy',False):return
        address=normalize_address(address)
        if not address:return
        current=self.g.text(self.entry);existing={normalize_address(value) for _,value in getaddresses([current])}
        if address not in existing:
            try:text=str(Address(display_name=' '.join(name.split()),addr_spec=address))
            except ValueError:
                local,domain=address.rsplit('@',1)
                text=str(Address(display_name=' '.join(name.split()),username=local,domain=domain))
            prefix=current.rstrip().rstrip(',;').rstrip()
            self.g.text(self.entry,(prefix+', ' if prefix else '')+text)
        self.dismiss();self.g.gtk_widget_grab_focus(self.entry);bind(self.app,'gtk','gtk_editable_set_position',None,P,I)(self.entry,-1)

    # ==========================================
    # Function: Close the selector branch without changing recipients.
    # Method: Cancel asynchronous results and let the broker dismiss nested alias popups together.
    # ==========================================
    def dismiss(self):
        if self.closed:return
        self.serial+=1;self.loading=False;self.app.local_loader.cancel(self.channel)
        if self.restore_source:self.g.g_source_remove(self.restore_source);self.restore_source=0
        if self.popup in self.g.surfaces.states:self.g.gtk_popover_popdown(self.popup)

    # ==========================================
    # Function: Release all selector callbacks before its owning editor is destroyed.
    # Method: Cancel worker delivery, dispose managed popup controllers and retire callback trampolines safely.
    # ==========================================
    def close(self):
        if self.closed:return
        self.dismiss();self.closed=True
        for popup in (self.alias_popup,self.popup):
            if popup in self.g.surfaces.states:self.g.gtk_widget_destroy(popup)
        for suffix in ('','-rows','-aliases'):self.g.surfaces.retire(self.group+suffix)
