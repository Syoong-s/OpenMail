"""Continuous bounded local people directory with persistent same-client details."""
import ctypes as C
from . import address_book
from .desktop_general import bind,P,I

# ==========================================
# Function: Keep the address book in the existing settings page with bounded native rows.
# Method: Load overlapping native windows on LocalLoader and retain explicit membership actions.
# ==========================================
class ContactsPage:
    # ==========================================
    # Function: Construct search/list/detail controls owned by the settings form.
    # Method: Use named icon actions, row stars and bounded directory windows while preserving editor values.
    # ==========================================
    def __init__(self,app,form,details_only=False):
        self.details_only=details_only
        self.app=app;self.form=form;self.g=g=app.g;self.store=app.service.store;self.offset=0;self.person='';self.selected=set();self.serial=0;self.items={};self.canonical_details={};self.editor_name_base='';self.editor_addresses_base=set();self.mutating=False;self.editor_selection=0;self.name_revision=0
        self.selecting=False;self.loading=False;self.last_scroll=0;self.editor_sessions={};self.pending_memberships={};self.mutation_serial=0;self.directory_query='';self.letter_buttons={};self.policy_loading=False;self.policy_busy=False;self.policy_pending={};self.policy_overrides={};self.policy_checks={};self.window_limit=120;self.row_widgets={};self.restore_source=0
        host=g.object(form.builder,'page_contacts');self.host=host;self.style(host,'contacts-directory')
        g.connect(host,'unmap',self.page_hidden,group=form.group)
        toolbar=g.gtk_box_new(0,8);self.toolbar=toolbar;self.style(toolbar,'directory-toolbar');g.gtk_box_pack_start(host,toolbar,0,1,0)
        self.search=bind(app,'gtk','gtk_search_entry_new',P)();g.gtk_box_pack_start(toolbar,self.search,1,1,0)
        g.gtk_widget_set_tooltip_text(self.search,'搜索姓名或邮箱 · 支持重音与 Unicode'.encode())
        self.select_button=self.icon_button(toolbar,'多选联系人','action-select',self.toggle_select)
        self.new_button=self.icon_button(toolbar,'新建联系人','action-add',self.new)
        self.count=g.gtk_label_new('正在加载本地通讯录…'.encode());g.gtk_label_set_xalign(self.count,0);self.style(self.count,'directory-count');g.gtk_box_pack_start(host,self.count,0,1,3)
        self.bulk=g.gtk_box_new(0,8);self.style(self.bulk,'directory-bulk');g.gtk_widget_set_no_show_all(self.bulk,1);g.gtk_box_pack_start(host,self.bulk,0,1,0)
        self.icon_button(self.bulk,'合并到所选目标…','contacts-merge',self.bulk_merge);self.icon_button(self.bulk,'删除所选…','spark-layout-trash',self.bulk_delete)
        self.icon_button(self.bulk,'设为带星标联系人','contact-starred',lambda:self.bulk_star(True));self.icon_button(self.bulk,'取消联系人星标','contact-unstarred',lambda:self.bulk_star(False))
        self.bulk_policy_buttons={}
        for key,title,icon in [('muted','免打扰','contact-muted'),('blocked','屏蔽','action-block'),('pinned','置顶','spark-layout-pin')]:
            self.bulk_policy_buttons[key]=self.icon_button(self.bulk,title,icon,lambda flag=key:self.bulk_policy(flag))
        self.bulk_count=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.bulk_count,1);g.gtk_box_pack_start(self.bulk,self.bulk_count,1,1,0)
        columns=g.gtk_box_new(0,5);g.gtk_box_pack_start(host,columns,1,1,0)
        scroll=g.gtk_scrolled_window_new(None,None);self.scroll=scroll;g.gtk_widget_set_size_request(scroll,-1,230);g.gtk_scrolled_window_set_policy(scroll,2,1)
        self.rows=g.gtk_box_new(1,2);g.gtk_container_add(scroll,self.rows);g.gtk_box_pack_start(columns,scroll,1,1,0)
        rail=bind(app,'gtk','gtk_grid_new',P)();self.rail=rail;self.rail_columns=1;self.index_font=None;self.active_letter='';self.style(rail,'directory-index')
        bind(app,'gtk','gtk_grid_set_row_homogeneous',None,P,I)(rail,1);bind(app,'gtk','gtk_grid_set_column_homogeneous',None,P,I)(rail,1)
        index_scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(index_scroll,2,3);g.gtk_widget_set_size_request(index_scroll,25,-1);g.gtk_container_add(index_scroll,rail);g.gtk_box_pack_start(columns,index_scroll,0,0,0);g.gtk_widget_set_tooltip_text(index_scroll,'字母索引 · 当前浏览分组'.encode())
        for letter in '★ABCDEFGHIJKLMNOPQRSTUVWXYZ#':
            button=g.gtk_button_new_with_label(letter.encode());self.letter_buttons[letter]=button;g.gtk_widget_set_tooltip_text(button,('跳转到 '+letter).encode())
            g.connect(button,'clicked',lambda *unused,value=letter:self.app.run_action(lambda:self.jump(value)),group=form.group)
        attach=bind(app,'gtk','gtk_grid_attach',None,P,P,I,I,I,I)
        for index,button in enumerate(self.letter_buttons.values()):attach(rail,button,0,index,1,1)
        g.connect(scroll,'size-allocate',self.fit_index,count=3,group=form.group);self.fit_index(height=400)
        self.adjustment=g.gtk_scrolled_window_get_vadjustment(scroll);g.connect(self.adjustment,'value-changed',self.scrolled,group=form.group)
        self.drawer=g.gtk_popover_new(self.search);self.style(self.drawer,'contact-drawer');g.surfaces.beside(self.drawer,self.scroll)
        g.surfaces.states[self.drawer]['width']=350;g.surfaces.states[self.drawer]['overlay_fallback']=True;g.surfaces.states[self.drawer]['require_anchor_allocation']=True
        editor=g.gtk_box_new(1,10);self.editor=editor;g.gtk_container_set_border_width(editor,15);g.gtk_container_add(self.drawer,editor)
        heading=g.gtk_box_new(0,10);g.gtk_box_pack_start(editor,heading,0,1,0)
        self.editor_avatar=g.gtk_label_new(b'+');self.style(self.editor_avatar,'directory-avatar');g.gtk_box_pack_start(heading,self.editor_avatar,0,0,0)
        self.editor_title=g.gtk_label_new('联系人详情'.encode());self.style(self.editor_title,'directory-name');g.gtk_box_pack_start(heading,self.editor_title,1,1,0)
        self.editor_close=self.icon_button(heading,'关闭','composer-close',self.dismiss_editor)
        self.name=self.entry(editor,'显示姓名')
        label=g.gtk_label_new('邮箱地址 · 每行一个'.encode());g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(editor,label,0,1,0)
        self.addresses=bind(app,'gtk','gtk_text_view_new',P)();bind(app,'gtk','gtk_text_view_set_wrap_mode',None,P,I)(self.addresses,3)
        addresses_scroll=g.gtk_scrolled_window_new(None,None);g.gtk_widget_set_size_request(addresses_scroll,-1,100);g.gtk_scrolled_window_set_policy(addresses_scroll,2,1);g.gtk_container_add(addresses_scroll,self.addresses);g.gtk_box_pack_start(editor,addresses_scroll,0,1,0)
        self.policy_box=g.gtk_box_new(1,3);g.gtk_box_pack_start(editor,self.policy_box,0,1,0)
        for key,title,hint in [('muted','免打扰','保留对话，关闭此联系人的弹窗与未读圆点'),('pinned','置顶','优先显示在对话列表的置顶区域'),('blocked','屏蔽','从对话列表隐藏并关闭通知，保留原邮件'),('starred','带星标联系人','在通讯录和选择收件人时优先显示，并在清理缓存时保留')]:
            check=bind(app,'gtk','gtk_check_button_new_with_label',P,C.c_char_p)(title.encode());self.policy_checks[key]=check;g.gtk_widget_set_tooltip_text(check,hint.encode());g.gtk_box_pack_start(self.policy_box,check,0,1,0)
            g.connect(check,'toggled',self.policy_changed,group=form.group)
        self.policy_note=g.gtk_label_new('开关立即保存 · 新联系人请先保存邮箱'.encode());g.gtk_label_set_xalign(self.policy_note,0);self.style(self.policy_note,'directory-count');g.gtk_box_pack_start(self.policy_box,self.policy_note,0,1,0);g.gtk_widget_set_sensitive(self.policy_box,0)
        actions=g.gtk_box_new(0,7);g.gtk_box_pack_start(editor,actions,0,1,0)
        save=self.button(actions,'保存',self.save);self.style(save,'suggested-action')
        self.icon_button(actions,'写邮件','reader-reply',self.compose);self.icon_button(actions,'删除联系人','spark-layout-trash',self.delete)
        self.split_address=self.entry(editor,'单个邮箱地址 · 用于拆分或写邮件')
        self.button(editor,'拆分此邮箱',self.split)
        self.editor_hint=g.gtk_label_new('关闭保留本次未保存编辑；切换联系人最多保留 40 份。'.encode());g.gtk_label_set_line_wrap(self.editor_hint,1);g.gtk_label_set_max_width_chars(self.editor_hint,28);self.style(self.editor_hint,'directory-count');g.gtk_box_pack_start(editor,self.editor_hint,0,1,0)
        self.note=g.gtk_label_new('记录来信发件人和已发送邮件的收件人 · 设置仅保存在本机'.encode());g.gtk_label_set_line_wrap(self.note,1);g.gtk_label_set_xalign(self.note,0);self.style(self.note,'directory-count');g.gtk_box_pack_start(host,self.note,0,1,3)
        g.connect(self.search,'search-changed',self.search_changed,group=form.group);g.connect(self.name,'changed',self.name_changed,group=form.group)
        if self.details_only:
            g.gtk_widget_set_no_show_all(self.editor_close,1);g.gtk_widget_hide(self.editor_close)
            children=g.gtk_container_get_children(host);node=children
            while node:
                widget=node.contents.data;g.gtk_widget_set_no_show_all(widget,1);g.gtk_widget_hide(widget);node=node.contents.next
            g.g_list_free(children);g.gtk_widget_reparent(editor,host);g.gtk_widget_set_no_show_all(editor,0)
        else:self.load()

    # ==========================================
    # Function: Present one shared editor directly or beside its directory anchor.
    # Method: Keep the same field and save behavior in both the standalone dialog and Settings drawer.
    # ==========================================
    def show_editor(self):
        self.g.gtk_widget_show_all(self.editor if self.details_only else self.drawer)

    # ==========================================
    # Function: Dismiss only the current shared details surface.
    # Method: Respond to the standalone dialog or pop down the directory-owned editor.
    # ==========================================
    def dismiss_editor(self):
        if self.details_only:self.g.gtk_dialog_response(self.form.window,-6)
        else:self.g.gtk_popover_popdown(self.drawer)

    # ==========================================
    # Function: Fit all letters in one quiet column at the directory's actual height.
    # Method: Scale only native label glyphs; homogeneous grid rows share the available space.
    # ==========================================
    def fit_index(self,*unused,height=None):
        height=height if height is not None else self.g.gtk_widget_get_allocated_height(self.scroll)
        size=max(3,min(6,int(height/28)-6))
        if size==self.index_font:return
        self.index_font=size
        for letter,button in self.letter_buttons.items():
            label=self.g.gtk_bin_get_child(button)
            self.g.gtk_label_set_markup(label,('<span size="'+str(size*1024)+'">'+letter+'</span>').encode())

    # ==========================================
    # Function: Highlight the alphabet group currently intersecting the top of the viewport.
    # Method: Read admitted row coordinates, preserving bounded metadata and the user's scroll position.
    # ==========================================
    def track_letter(self):
        value=bind(self.app,'gtk','gtk_adjustment_get_value',C.c_double,P)(self.adjustment);chosen=''
        for identity,row in self.row_widgets.items():
            x,y=I(),I();self.g.gtk_widget_translate_coordinates(row,self.rows,0,0,C.byref(x),C.byref(y))
            if y.value+self.g.gtk_widget_get_allocated_height(row)>value+5:
                chosen=self.items[identity]['letter'];break
        if chosen==self.active_letter:return
        self.active_letter=chosen
        for letter,button in self.letter_buttons.items():
            context=self.g.gtk_widget_get_style_context(button)
            (self.g.gtk_style_context_add_class if letter==chosen else self.g.gtk_style_context_remove_class)(context,b'current-letter')

    # ==========================================
    # Function: Apply a reusable native visual role.
    # Method: Add one CSS class without installing per-row style providers.
    # ==========================================
    def style(self,widget,name):
        self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(widget),name.encode())

    # ==========================================
    # Function: Add a compact tooltip action to the details drawer.
    # Method: Reuse the application's existing icon system and form callback owner.
    # ==========================================
    def icon_button(self,host,title,icon,callback):
        from .ui_actions import icon_action
        button=self.button(host,'',callback);icon_action(self.g,button,title,icon,17);return button

    # ==========================================
    # Function: Dispose the persistent drawer before its owning Settings workspace disappears.
    # Method: Release the managed popup while its editor callbacks are still owned by the form.
    # ==========================================
    def close(self):
        self.serial+=1
        self.app.local_loader.cancel(self.form.group+'-contact-detail')
        if self.restore_source:self.g.g_source_remove(self.restore_source);self.restore_source=0
        if getattr(self,'confirmation',None):self.g.gtk_widget_destroy(self.confirmation)
        self.g.gtk_widget_destroy(self.drawer)

    # ==========================================
    # Function: Dismiss contact details when their Settings page is no longer visible.
    # Method: Cancel either a deferred or open managed card without changing authored editor fields.
    # ==========================================
    def page_hidden(self,*unused):
        if self.drawer in self.g.surfaces.states:self.g.gtk_popover_popdown(self.drawer)

    # ==========================================
    # Function: Add one compact labeled field to the current details pane.
    # Method: Keep labels separate from editable values and form-owned widget lifetimes.
    # ==========================================
    def entry(self,host,title):
        label=self.g.gtk_label_new(title.encode());self.g.gtk_label_set_xalign(label,0);self.g.gtk_box_pack_start(host,label,0,1,0)
        entry=self.g.gtk_entry_new();self.g.gtk_box_pack_start(host,entry,0,1,0);return entry

    # ==========================================
    # Function: Add an explicit local contact action with the existing guarded boundary.
    # Method: Attach all callbacks to the settings form's own signal group.
    # ==========================================
    def button(self,host,title,callback):
        button=self.g.gtk_button_new_with_label(title.encode());self.g.gtk_box_pack_start(host,button,0,1,0)
        self.g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=self.form.group);return button

    # ==========================================
    # Function: Load a bounded local page without blocking native settings input.
    # Method: Coalesce searches, render starred groups and row buttons, and reject closed-form completions.
    # ==========================================
    def load(self,direction='',letter='',offset=None):
        if self.form.closed or self.details_only:return
        self.serial+=1;serial=self.serial;query=self.g.text(self.search);requested_offset=self.offset if offset is None else offset;self.loading=True
        adjustment=self.adjustment
        old_value=bind(self.app,'gtk','gtk_adjustment_get_value',C.c_double,P)(adjustment)
        anchor_id=next(iter(self.row_widgets),'');anchor_y=0
        if direction=='down':anchor_id=list(self.row_widgets)[min(40,len(self.row_widgets)-1)] if self.row_widgets else ''
        if anchor_id:
            x,y=I(),I();self.g.gtk_widget_translate_coordinates(self.row_widgets[anchor_id],self.rows,0,0,C.byref(x),C.byref(y));anchor_y=y.value
        # ==========================================
        # Function: Query one bounded native directory window on the local worker.
        # Method: Include only compact people metadata and a bounded migration batch.
        # ==========================================
        def operation():
            try:
                status=address_book.backfill(self.store)
                return address_book.page(self.store,query,requested_offset,self.window_limit,letter),status
            except Exception as error:return None,str(error)
        # ==========================================
        # Function: Recycle native directory rows without touching the persistent editor.
        # Method: Restore scroll anchors after bounded replacement and invalidate stale requests.
        # ==========================================
        def ready(result):
            if self.form.closed or serial!=self.serial:return
            page,status=result
            if page is None:
                self.loading=False;self.g.label(self.note,status);self.app.show_error(ValueError(status));return
            g=self.g;group=self.form.group+'-contacts-rows';g.disconnect(group);g.clear(self.rows)
            self.items={item['id']:item for item in page['items']};self.total=page['total'];self.offset=page['offset'];self.directory_query=query;self.row_widgets={}
            for identity,item in self.items.items():
                if identity in self.canonical_details:self.canonical_details[identity]=item
            g.label(self.count,str(self.total)+' 位联系人'+(' · 正在补全历史联系人' if not status['complete'] else ' · 本地通讯录'))
            last=''
            for item in page['items']:
                if item['letter']!=last:
                    last=item['letter'];section=g.gtk_label_new(('带星标联系人' if last=='★' else last).encode());g.gtk_label_set_xalign(section,0);self.style(section,'directory-section');g.gtk_box_pack_start(self.rows,section,0,1,0)
                row=g.gtk_box_new(0,7);self.row_widgets[item['id']]=row;self.style(row,'directory-row');g.gtk_box_pack_start(self.rows,row,0,1,0)
                if self.selecting:
                    check=bind(self.app,'gtk','gtk_check_button_new',P)();g.gtk_toggle_button_set_active(check,int(item['id'] in self.selected));g.gtk_box_pack_start(row,check,0,0,0)
                    g.connect(check,'toggled',lambda widget,unused,identity=item['id']:self.mark(identity,bool(g.gtk_toggle_button_get_active(widget)),widget),group=group)
                button=g.gtk_button_new();self.style(button,'directory-person');g.gtk_box_pack_start(row,button,1,1,0)
                body=g.gtk_box_new(0,12);g.gtk_container_add(button,body)
                title=item['name'] or item['addresses'][0]
                avatar=g.gtk_label_new(title[:1].upper().encode());self.style(avatar,'directory-avatar');g.gtk_box_pack_start(body,avatar,0,0,0)
                text=g.gtk_box_new(1,3);g.gtk_box_pack_start(body,text,1,1,0)
                for value,role in [(title,'directory-name'),(item['addresses'][0],'directory-email')]:
                    label=g.gtk_label_new(value.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,24);self.style(label,role);g.gtk_box_pack_start(text,label,0,1,0)
                if len(item['addresses'])>1:
                    badge=g.gtk_label_new((str(len(item['addresses']))+' 邮箱').encode());self.style(badge,'directory-badge');g.gtk_box_pack_start(body,badge,0,0,0)
                g.gtk_widget_set_tooltip_text(button,(title+'\n'+', '.join(item['addresses'])).encode());g.connect(button,'clicked',lambda *unused,value=item:self.choose(value),group=group)
                star=g.gtk_button_new();from .ui_actions import icon_action
                icon_action(g,star,'取消联系人星标' if item['starred'] else '设为带星标联系人','contact-starred' if item['starred'] else 'contact-unstarred',17);g.gtk_box_pack_start(row,star,0,0,0)
                g.connect(star,'clicked',lambda *unused,person=item['id'],enabled=not bool(item['starred']):self.set_stars((person,),enabled),group=group)
            for value,button in self.letter_buttons.items():g.gtk_widget_set_sensitive(button,int(value in page['letters']))
            g.gtk_widget_show_all(self.host);self.update_bulk()
            # ==========================================
            # Function: Restore one replacement window's scroll anchor after GTK allocation.
            # Method: Use native upper-bound differences rather than assuming fixed row heights.
            # ==========================================
            def restore(*unused):
                self.restore_source=0
                if self.form.closed or serial!=self.serial:return 0
                value=0
                if page.get('jump_offset') is not None and page['items']:
                    position=min(len(page['items'])-1,max(0,page['jump_offset']-page['offset']));target=page['items'][position]['id']
                    x,y=I(),I();g.gtk_widget_translate_coordinates(self.row_widgets[target],self.rows,0,0,C.byref(x),C.byref(y));value=max(0,y.value-25)
                if direction and anchor_id in self.row_widgets:
                    x,y=I(),I();g.gtk_widget_translate_coordinates(self.row_widgets[anchor_id],self.rows,0,0,C.byref(x),C.byref(y));value=max(0,old_value+y.value-anchor_y)
                bind(self.app,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(adjustment,value)
                self.last_scroll=value;self.loading=False;self.track_letter();return 0
            if self.restore_source:g.g_source_remove(self.restore_source)
            self.restore_callback=C.CFUNCTYPE(I,P)(restore);self.restore_source=g.g_timeout_add(70,C.cast(self.restore_callback,P),None)
        self.app.local_loader.request('address-ui',operation,ready)

    # ==========================================
    # Function: Load adjacent bounded windows automatically as scrolling reaches an edge.
    # Method: Keep at most 120 native rows and preserve overlap when moving forty identities.
    # ==========================================
    def scrolled(self,*unused):
        import ctypes as C
        if not self.form.closed:self.track_letter()
        if self.loading or self.form.closed or self.g.text(self.search)!=self.directory_query:return
        get=lambda name:bind(self.app,'gtk','gtk_adjustment_get_'+name,C.c_double,P)(self.adjustment)
        value=get('value');previous=self.last_scroll;self.last_scroll=value
        if value>previous and value+get('page_size')>=get('upper')-120 and self.offset+len(self.items)<getattr(self,'total',0):
            self.load('down',offset=self.offset+40)
        elif value<previous and value<100 and self.offset>0:
            self.load('up',offset=max(0,self.offset-40))

    # ==========================================
    # Function: Jump to an absolute letter across the complete search result.
    # Method: Request its global SQL rank even when none of its people are loaded.
    # ==========================================
    def jump(self,letter):
        self.load(letter=letter)

    # ==========================================
    # Function: Track explicit bulk intent only while selection mode is active.
    # Method: Keep stable identities across recycled windows and cap one operation to 100 people.
    # ==========================================
    def mark(self,identity,active,widget=None):
        if active and self.selecting:
            if identity not in self.selected and len(self.selected)>=100:
                if widget:self.g.gtk_toggle_button_set_active(widget,0)
                self.g.label(self.note,'每次最多选择 100 位联系人');return False
            self.selected.add(identity)
        else:self.selected.discard(identity)
        self.update_bulk()

    # ==========================================
    # Function: Show checkboxes and contextual bulk actions only after explicit opt-in.
    # Method: Clear all pending source identities when selection mode ends.
    # ==========================================
    def toggle_select(self):
        self.selecting=not self.selecting;self.selected.clear();self.load()

    # ==========================================
    # Function: Keep the contextual bulk toolbar synchronized with explicit intent.
    # Method: Avoid show-all exposing checkboxes or controls in ordinary directory mode.
    # ==========================================
    def update_bulk(self):
        from .ui_actions import icon_action
        icon_action(self.g,self.select_button,'完成多选' if self.selecting else '多选联系人','spark-layout-done' if self.selecting else 'action-select',17)
        self.g.label(self.bulk_count,str(len(self.selected))+' 位已选')
        from .ui_actions import state_action
        chosen=[self.items[person] for person in self.selected if person in self.items]
        for key,title,icon in [('muted','免打扰','contact-muted'),('blocked','屏蔽','action-block'),('pinned','置顶','spark-layout-pin')]:
            active=bool(chosen) and len(chosen)==len(self.selected) and all(item.get(key) for item in chosen)
            state_action(self.g,self.bulk_policy_buttons[key],('取消' if active else '')+title,icon,active,17)
        if self.selecting:
            self.g.gtk_widget_set_no_show_all(self.bulk,0);self.g.gtk_widget_show_all(self.bulk);self.g.gtk_widget_set_no_show_all(self.bulk,1)
        else:self.g.gtk_widget_hide(self.bulk)

    # ==========================================
    # Function: Persist a row or bulk star action without altering contact membership or chat policies.
    # Method: Reuse the guarded mutation worker and reload the globally sorted directory from its beginning.
    # ==========================================
    def set_stars(self,people,enabled):
        people=tuple(people)
        if not people:raise ValueError('请先选择联系人')
        self.mutate(lambda:address_book.star_many(self.store,people,enabled),'已设为带星标联系人。' if enabled else '已取消联系人星标。',restart=True)

    # ==========================================
    # Function: Apply the explicit toolbar star state to the current immutable selection.
    # Method: Keep star and unstar separate so a mixed selection has predictable behavior.
    # ==========================================
    def bulk_star(self,enabled):
        self.set_stars(tuple(self.selected),enabled)

    # ==========================================
    # Function: Toggle a selected group's mute, block or pin policy while retaining its selection.
    # Method: Use a validated atomic partial update and refresh the shared current editor after completion.
    # ==========================================
    def bulk_policy(self,key):
        from .contact_policies import toggle_many
        people=tuple(self.selected)
        if not people:raise ValueError('请先选择联系人')
        self.mutate(lambda:toggle_many(self.store,people,key),'联系人设置已更新。',refresh_target=bool(self.person),keep_selection=True)

    # ==========================================
    # Function: Confirm the currently chosen stable merge target before any local transaction.
    # Method: Show target name and source count with a separate explicit action in the drawer.
    # ==========================================
    def bulk_merge(self):
        if not self.person or not self.selected-{self.person}:raise ValueError('请先点开合并目标联系人，并勾选来源联系人')
        target=self.person;sources=tuple(self.selected-{target})
        # ==========================================
        # Function: Submit only the target and sources displayed by the confirmation.
        # Method: Reject target navigation and keep the immutable source identities.
        # ==========================================
        def submit():
            if self.person!=target:raise ValueError('合并目标已变更，请重新确认')
            self.mutate(lambda:address_book.merge_many(self.store,target,sources),'所选联系人已合并到当前目标。',refresh_target=True)
        self.confirm_bulk('将 '+str(len(sources))+' 位联系人合并到「'+self.g.text(self.name)+'」',submit)

    # ==========================================
    # Function: Confirm and delete only the explicitly checked local people.
    # Method: Capture immutable stable identities and preserve each mailbox suppression rule.
    # ==========================================
    def bulk_delete(self):
        people=tuple(self.selected)
        if not people:raise ValueError('请先选择要删除的联系人')
        # ==========================================
        # Function: Delete a bounded explicit selection on the existing mutation worker.
        # Method: Retain ordinary remove suppression semantics for every selected person.
        # ==========================================
        def remove():
            self.mutate(lambda:address_book.remove_many(self.store,people),'所选联系人已删除；相关地址已停止自动收集。',reset=self.person in people)
        self.confirm_bulk('删除所选 '+str(len(people))+' 位联系人？此操作将停止自动收集这些地址。',remove)

    # ==========================================
    # Function: Require a separate contextual confirmation for destructive bulk intent.
    # Method: Reuse a same-client popup and never dispatch a compose or send action.
    # ==========================================
    def confirm_bulk(self,title,callback):
        old=getattr(self,'confirmation',None)
        if old:self.g.gtk_widget_destroy(old)
        popup=self.g.gtk_popover_new(self.select_button);self.confirmation=popup;host=self.g.gtk_box_new(1,10);self.g.gtk_container_set_border_width(host,15);self.g.gtk_container_add(popup,host)
        label=self.g.gtk_label_new(title.encode());self.g.gtk_label_set_line_wrap(label,1);self.g.gtk_label_set_max_width_chars(label,30);self.g.gtk_box_pack_start(host,label,0,1,0)
        self.icon_button(host,'确认此操作','spark-layout-done',lambda:(self.g.gtk_popover_popdown(popup),callback()));self.icon_button(host,'取消','composer-close',lambda:self.g.gtk_popover_popdown(popup));self.g.gtk_widget_show_all(popup)

    # ==========================================
    # Function: Reset the continuous directory after debounced Unicode search.
    # Method: Invalidate prior windows and restart from the first matching global identity.
    # ==========================================
    def search_changed(self,*unused):
        self.load(offset=0)

    # ==========================================
    # Function: Retain a bounded session of unsaved authorship while switching people.
    # Method: Store field text and its reconciliation baseline; never auto-commit dismissal.
    # ==========================================
    def remember_editor(self):
        key=self.person or '__new__'
        if not self.person and not (self.g.text(self.name) or self.g.text(self.addresses,view=True)):return
        self.editor_sessions.pop(key,None);self.editor_sessions[key]=(self.g.text(self.name),self.g.text(self.addresses,view=True),self.g.text(self.split_address),self.editor_name_base,set(self.editor_addresses_base))
        if len(self.editor_sessions)>40:self.editor_sessions.pop(next(iter(self.editor_sessions)))

    # ==========================================
    # Function: Populate details for an explicitly selected stable person identity.
    # Method: Keep all aliases visible and editable, with no recipient union on compose.
    # ==========================================
    def choose(self,item):
        self.remember_editor()
        item=self.canonical_details.get(item['id'],item)
        self.editor_selection+=1
        self.editor_name_base=item['name'];self.editor_addresses_base=set(item['addresses'])
        self.person=item['id'];self.g.text(self.name,item['name']);self.g.text(self.addresses,'\n'.join(item['addresses']),view=True);self.g.text(self.split_address,'')
        saved=self.editor_sessions.get(self.person)
        if saved:
            name,addresses,split,name_base,addresses_base=saved
            self.g.text(self.name,name if name!=name_base else item['name']);self.g.text(self.addresses,addresses,view=True);self.g.text(self.split_address,split);self.reconcile_addresses(item['addresses'],addresses_base)
        if self.person in self.pending_memberships:self.editor_addresses_base=set(self.pending_memberships[self.person]['submitted'])
        self.show_policies(item)
        self.g.label(self.editor_avatar,(item['name'] or item['addresses'][0])[:1].upper());self.g.label(self.editor_title,(item['name'] or item['addresses'][0]) if self.details_only else '联系人详情');self.show_editor()

    # ==========================================
    # Function: Start a new independent local person without inferring equal-name membership.
    # Method: Clear only the editor identity and values, retaining the searchable list.
    # ==========================================
    def new(self):
        self.remember_editor()
        self.editor_selection+=1
        self.editor_name_base='';self.editor_addresses_base=set()
        self.person='';self.g.text(self.name,'');self.g.text(self.addresses,'',view=True);self.g.text(self.split_address,'')
        saved=self.editor_sessions.get('__new__')
        if saved:self.g.text(self.name,saved[0]);self.g.text(self.addresses,saved[1],view=True);self.g.text(self.split_address,saved[2])
        self.show_policies({})
        self.g.label(self.editor_avatar,'+');self.g.label(self.editor_title,'新建联系人');self.show_editor()

    # ==========================================
    # Function: Open one explicit stable contact directly from the chat header.
    # Method: Resolve its full saved aliases off GTK, then reuse the existing owned details drawer.
    # ==========================================
    def open_person(self,person):
        if not person or self.form.closed:return
        # ==========================================
        # Function: Present only the requested saved person's still-valid local details.
        # Method: Reject closed Settings completions and use no display-name matching.
        # ==========================================
        def ready(detail):
            if self.form.closed:return
            if detail.get('id'):self.choose(detail)
        self.app.local_loader.request(self.form.group+'-contact-detail',lambda:address_book.sender_detail(self.store,person=person),ready)

    # ==========================================
    # Function: Reflect saved or queued policy choices without triggering write signals during selection.
    # Method: Keep immediate contact settings separate from unsaved name/address editor sessions.
    # ==========================================
    def show_policies(self,item):
        values=self.policy_overrides.get(self.person,item);self.policy_loading=True
        try:
            for key,check in self.policy_checks.items():self.g.gtk_toggle_button_set_active(check,int(bool(values.get(key,False))))
        finally:self.policy_loading=False
        self.g.gtk_widget_set_sensitive(self.policy_box,bool(self.person));self.g.label(self.policy_note,'开关立即保存' if self.person else '请先保存新联系人的邮箱')

    # ==========================================
    # Function: Queue the latest complete policy values for an explicitly selected contact.
    # Method: Coalesce rapid toggles by person and let a single writer preserve their final order.
    # ==========================================
    def policy_changed(self,*unused):
        if self.policy_loading or not self.person or self.form.closed:return
        values={key:bool(self.g.gtk_toggle_button_get_active(check)) for key,check in self.policy_checks.items()}
        self.policy_overrides[self.person]=values;self.policy_pending[self.person]=values;self.g.label(self.policy_note,'正在保存…');self.flush_policies()

    # ==========================================
    # Function: Commit queued policy switches off the native input thread.
    # Method: Drain one immutable batch at a time, finish writes after drawer dismissal and refresh live rows.
    # ==========================================
    def flush_policies(self):
        if self.policy_busy or not self.policy_pending:return
        changes=dict(self.policy_pending);self.policy_pending.clear();self.policy_busy=True
        # ==========================================
        # Function: Acknowledge one durable policy batch without losing toggles made during its write.
        # Method: Repaint only live Settings widgets, then continue any remaining coalesced work.
        # ==========================================
        def ready(unused):
            self.policy_busy=False
            if not self.app.closing:self.app.refresh()
            if not self.form.closed:
                if any('starred' in values for values in changes.values()):self.load(offset=0)
                for person,values in changes.items():
                    if person in self.items:self.items[person].update(values)
                self.update_bulk()
            if not self.form.closed and self.person in changes:self.g.label(self.policy_note,'开关已保存' if not self.policy_pending else '正在保存…')
            self.flush_policies()
        # ==========================================
        # Function: Keep a failed policy edit visible and retryable without pretending it was saved.
        # Method: Release writer ownership and report the existing error boundary.
        # ==========================================
        def failed(error):
            self.policy_busy=False
            if not self.form.closed:self.g.label(self.policy_note,'保存失败，请重新切换后重试')
            if not self.app.closing:self.app.show_error(error)
        from .contact_policies import save_many
        self.app.background(lambda:save_many(self.store,changes),ready,failed)

    # ==========================================
    # Function: Identify name edits made after an asynchronous mutation was submitted.
    # Method: Keep this revision separate from address membership edits.
    # ==========================================
    def name_changed(self,*unused):
        self.name_revision+=1

    # ==========================================
    # Function: Reconcile committed membership with edits made in the visible address field.
    # Method: Apply additions/removals relative to the addresses this editor had shown.
    # ==========================================
    def reconcile_addresses(self,committed,baseline):
        authored=self.g.text(self.addresses,view=True);retained=self.reconcile_text(authored,committed,baseline)
        if retained!=authored:self.g.text(self.addresses,retained,view=True)

    # ==========================================
    # Function: Reconcile visible or retained authored membership with committed aliases.
    # Method: Apply the same three-way additions/removals while retaining invalid authored lines.
    # ==========================================
    def reconcile_text(self,authored,committed,baseline):
        current={line.strip().casefold() for line in authored.splitlines() if line.strip()}
        wanted=(set(committed)-(baseline-current)) | (current-baseline)
        retained=''.join(line for line in authored.splitlines(keepends=True) if not line.strip() or line.strip().casefold() in wanted)
        present={line.strip().casefold() for line in retained.splitlines() if line.strip()}
        missing=[address for address in committed if address in wanted and address not in present]
        if missing:retained+=('' if not retained or retained.endswith('\n') else '\n')+'\n'.join(missing)
        return retained

    # ==========================================
    # Function: Retire only this mutation's temporary submitted baseline after completion.
    # Method: On failure restore canonical bases independently for visible and retained fields without editing authored text.
    # ==========================================
    def release_pending_membership(self,target,token,failed=False):
        pending=self.pending_memberships.get(target)
        if not pending or pending['token']!=token:return
        self.pending_memberships.pop(target,None)
        if not failed or self.form.closed:return
        if self.person==target:self.editor_addresses_base=set(pending['base'])
        key=target or '__new__';saved=self.editor_sessions.get(key)
        if saved:self.editor_sessions[key]=(*saved[:4],set(pending['base']))

    # ==========================================
    # Function: Persist explicit local membership changes away from the native thread.
    # Method: Save any active docked draft first, then reload current conversations after completion.
    # ==========================================
    def mutate(self,operation,message,reset=False,refresh_target=False,save_base=False,restart=False,keep_selection=False):
        if self.mutating or self.policy_busy or self.policy_pending:raise ValueError("正在保存联系人设置，请稍候")
        composer=getattr(self.app,'chat_composer',None)
        if composer and not composer.autosave(force=True):return
        target=self.person;selection=self.editor_selection;name_revision=self.name_revision;submitted_name=self.g.text(self.name)
        submitted_addresses={line.strip().casefold() for line in self.g.text(self.addresses,view=True).splitlines() if line.strip()}
        self.mutation_serial+=1;token=self.mutation_serial
        if save_base:self.pending_memberships[target]={'token':token,'submitted':set(submitted_addresses),'base':set(self.editor_addresses_base)}
        # ==========================================
        # Function: Return committed target membership with a merge transaction.
        # Method: Read only one person and its at-most-100 addresses on the worker.
        # ==========================================
        def committed():
            result=operation()
            if not refresh_target:return result,None
            identity=result if isinstance(result,str) and not reset else target
            with self.store.db() as db:
                row=db.execute('SELECT id,name,starred FROM address_people WHERE id=?',(identity,)).fetchone()
                detail={'id':row['id'],'name':row['name'],'starred':row['starred'],'addresses':[item[0] for item in db.execute('SELECT address FROM address_mailboxes WHERE person=? AND suppressed=0 ORDER BY address',(identity,))]} if row else None
            if detail:
                from .contact_policies import get as contact_policy
                detail.update(contact_policy(self.store,identity))
            return result,detail
        # ==========================================
        # Function: Apply a completed local contact transaction to the open settings page.
        # Method: Avoid destroyed widgets and refresh the conversation projection after membership changes.
        # ==========================================
        def ready(outcome):
            self.mutating=False
            if not self.app.closing:self.app.refresh()
            if self.form.closed:self.release_pending_membership(target,token);return
            result,detail=outcome
            same_selection=self.editor_selection==selection and self.person==target
            if detail:
                self.canonical_details.pop(detail['id'],None)
                self.canonical_details[detail['id']]=detail
                if len(self.canonical_details)>40:self.canonical_details.pop(next(iter(self.canonical_details)))
            elif reset:self.canonical_details.pop(target,None)
            if same_selection:
                if reset and not detail:self.new()
                elif isinstance(result,str) and not reset:self.person=result
            elif reset and not detail and self.person==target:self.new()
            if detail and self.person==detail['id']:
                if (same_selection and self.name_revision==name_revision) or self.g.text(self.name)==self.editor_name_base:
                    self.g.text(self.name,detail['name'])
                self.editor_name_base=detail['name']
                baseline=submitted_addresses if same_selection and save_base else self.editor_addresses_base
                self.reconcile_addresses(detail['addresses'],baseline)
                self.editor_addresses_base=set(detail['addresses'])
                self.policy_overrides.pop(detail['id'],None);self.show_policies(detail)
            saved=self.editor_sessions.get(target)
            if saved and detail:
                name,authored,split,name_base,addresses_base=saved
                name=detail['name'] if name==name_base or (save_base and name==submitted_name) else name
                baseline=submitted_addresses if save_base else addresses_base
                self.editor_sessions[target]=(name,self.reconcile_text(authored,detail['addresses'],baseline),split,detail['name'],set(detail['addresses']))
            elif reset:self.editor_sessions.pop(target,None)
            if not target and isinstance(result,str):self.editor_sessions.pop('__new__',None)
            self.release_pending_membership(target,token)
            if not keep_selection:self.selected.clear()
            self.g.label(self.note,message);self.load(offset=0 if restart else None)
        # ==========================================
        # Function: Retain authored contact fields when validation or a transaction fails.
        # Method: Release the mutation guard and report through the existing application boundary.
        # ==========================================
        def failed(error):
            self.release_pending_membership(target,token,failed=True);self.mutating=False
            if not self.form.closed:self.g.label(self.note,str(error))
            if not self.app.closing:self.app.show_error(error)
        self.mutating=True;self.app.background(committed,ready,failed)

    # ==========================================
    # Function: Save the authored name and explicit mailbox list without silently merging people.
    # Method: Capture a complete immutable edit before submitting its transaction.
    # ==========================================
    def save(self):
        person=self.person;name=self.g.text(self.name);addresses=self.g.text(self.addresses,view=True).splitlines()
        self.mutate(lambda:address_book.save(self.store,person,name,addresses),'联系人已保存；移除的地址将停止自动收集。',refresh_target=True,save_base=True)

    # ==========================================
    # Function: Delete the selected person and durably suppress all its current mailboxes.
    # Method: Preserve cached mail and existing drafts as separate local records.
    # ==========================================
    def delete(self):
        if not self.person:raise ValueError('请先选择一位联系人')
        person=self.person;self.mutate(lambda:address_book.remove(self.store,person),'联系人已删除；这些地址不会因历史或新来信自动重建。',reset=True)

    # ==========================================
    # Function: Merge checked source people into the explicitly selected target.
    # Method: Preserve names, source-local reply routes and every existing draft identity.
    # ==========================================
    def merge(self):
        target=self.person;sources=tuple(self.selected-{target})
        if not target or not sources:raise ValueError('请在左侧勾选来源联系人，并在右侧选择合并目标')
        self.mutate(lambda:address_book.merge_many(self.store,target,sources),'已合并；对话按此人分组，旧草稿仍可在“草稿与发件箱”恢复。',refresh_target=True)

    # ==========================================
    # Function: Split a specifically entered alias back into an independent person.
    # Method: Match exact current membership and preserve the address's original observed display name.
    # ==========================================
    def split(self):
        person=self.person;address=self.g.text(self.split_address).strip()
        if not person:raise ValueError('请先选择一位联系人')
        self.mutate(lambda:address_book.split(self.store,person,address),'该邮箱已拆分为独立联系人。',reset=True,refresh_target=True)

    # ==========================================
    # Function: Compose to one explicitly chosen mailbox from the current editor.
    # Method: Require one address in the split/address selector for multi-address people.
    # ==========================================
    def compose(self):
        addresses=[value.strip() for value in self.g.text(self.addresses,view=True).splitlines() if value.strip()]
        chosen=self.g.text(self.split_address).strip() or (addresses[0] if len(addresses)==1 else '')
        if chosen not in addresses:raise ValueError('多邮箱联系人请在“单个邮箱地址”中填写本次收件邮箱')
        self.app.open_composer({'to':chosen})

# ==========================================
# Function: Open contact details directly from the current conversation without navigating to Settings.
# Method: Host the same editor in one owned native Form and resolve the stable person on the local worker.
# ==========================================
def contact_details_dialog(app,person):
    if not person:raise ValueError('此对话没有可编辑的独立联系人')
    existing=getattr(app,'contact_details_form',None)
    if existing and not existing.closed:
        existing.contacts_page.open_person(person);app.g.gtk_window_present(existing.window);return
    from .desktop_forms import Form
    layout='<interface><object class="GtkBox" id="form"><property name="orientation">vertical</property><child><object class="GtkBox" id="page_contacts"><property name="orientation">vertical</property></object></child><child><object class="GtkLabel" id="note"/></child></object></interface>'
    form=Form(app,'联系人详情',[],390,layout=layout);app.contact_details_form=form
    page=ContactsPage(app,form,details_only=True);form.contacts_page=page
    try:
        app.g.gtk_widget_show_all(form.window);page.open_person(person);app.g.gtk_dialog_run(form.window)
    finally:
        page.close();app.g.disconnect(form.group+'-contacts-rows');form.close();app.contact_details_form=None
