"""Inline folder tree editing and direct account-scoped context operations."""
import ctypes as C
import json
from pathlib import Path
from .local_mail import LOCAL_ACCOUNT
from .ui_actions import icon_action

ICONS=Path(__file__).parent/'desktop_assets/icons'

# ==========================================
# Function: Own exact-identity folder controls without a separate management window.
# Method: Render row actions, Enter-only inline edits and guarded service mutations.
# ==========================================
class FolderNavigationUI:
    # ==========================================
    # Function: Defer dynamic widget rebuilds until the current native callback returns.
    # Method: Coalesce requests through the existing desktop main-thread queue.
    # ==========================================
    def queue_folder_refresh(self):
        if getattr(self,'folder_refresh_queued',False):return
        self.folder_refresh_queued=True
        self.queue.put((self.finish_folder_refresh,None))

    # ==========================================
    # Function: Apply a queued folder and pin refresh safely.
    # Method: Release the coalescing flag before rebuilding current metadata.
    # ==========================================
    def finish_folder_refresh(self,unused=None):
        self.folder_refresh_queued=False
        if not getattr(self,'closing',False):self.refresh_folders()

    # ==========================================
    # Function: Keep callback trampolines alive until the current native event has returned.
    # Method: Disconnect signals immediately and retain their Python closures for one queued main-thread turn.
    # ==========================================
    def retire_folder_group(self,group):
        callbacks=list(self.g.callbacks.get(group,[]));self.g.disconnect(group)
        if callbacks:self.queue.put((lambda unused,keep=callbacks:None,None))

    # ==========================================
    # Function: Create one discoverable icon-and-label folder menu command.
    # Method: Keep callbacks owned by a popup-specific group and preserve its accessible caption.
    # ==========================================
    def folder_menu_button(self,host,popup,title,icon,callback,enabled=True,submenu=False,header=False):
        g=self.g;button=g.gtk_menu_button_new() if submenu is True else g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'popover-action');g.gtk_widget_set_tooltip_text(button,title.encode());g.gtk_widget_set_sensitive(button,enabled)
        line=g.gtk_box_new(0,9);g.gtk_container_add(button,line);g.gtk_box_pack_start(line,g.image_file(ICONS/(icon+'.svg'),15),0,0,0);label=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,24);g.gtk_box_pack_start(line,label,1,1,0)
        if submenu:g.gtk_box_pack_start(line,g.image_file(ICONS/'action-next.svg',12),0,0,0)
        group=('folder-popup-header-' if header else 'folder-popup-actions-')+str(popup);self.folder_popup_groups.add(group)
        if submenu is True:
            child=g.gtk_popover_new(button);content=g.gtk_box_new(1,2);g.gtk_container_set_border_width(content,5);g.gtk_container_add(child,content);g.gtk_menu_button_set_popover(button,child)
            g.connect(button,'toggled',lambda *unused:self.run_action(lambda:callback(content,child)) if g.gtk_toggle_button_get_active(button) else None,group=group)
        else:g.connect(button,'clicked',lambda *unused:self.invoke_folder_command(popup,button,callback),group=group)
        g.gtk_box_pack_start(host,button,0,1,0);return button

    # ==========================================
    # Function: Record the invoking menu row before opening a side editor.
    # Method: Preserve the parent menu and give the surface broker an exact adjacent anchor.
    # ==========================================
    def invoke_folder_command(self,popup,button,callback):
        state=self.g.surfaces.states.get(popup)
        if state:state['last_action']=button
        self.run_action(callback)

    # ==========================================
    # Function: Clear only one popup's callbacks and contents.
    # Method: Retain other folder menus and disconnect native handlers before destruction.
    # ==========================================
    def clear_folder_popup(self,host,popup):
        self.retire_folder_group('folder-popup-'+str(popup));self.retire_folder_group('folder-popup-actions-'+str(popup));self.retire_folder_group('folder-popup-header-'+str(popup));self.g.clear(host)

    # ==========================================
    # Function: Construct the direct folder menu when its button opens.
    # Method: Resolve current metadata by account/path and show current state instead of stale captions.
    # ==========================================
    def populate_folder_popup(self,host,popup,account,path=None):
        g=self.g;self.clear_folder_popup(host,popup);rows=self.service.store.list_folders(account)
        if path is None:
            from .desktop_forms import account_settings
            self.folder_menu_button(host,popup,'添加邮箱','settings-accounts',lambda:account_settings(self),submenu='editor',header=True)
            combo=g.gtk_combo_box_text_new();g.gtk_box_pack_start(host,combo,0,1,3)
            for row in rows:g.gtk_combo_box_text_append(combo,row['folder'].encode(),row['folder'].encode())
            selected=self.folder_path if self.folder_account==account and any(r['folder']==self.folder_path for r in rows) else (rows[0]['folder'] if rows else '')
            g.gtk_combo_box_set_active_id(combo,selected.encode());actions=g.gtk_box_new(1,2);g.gtk_box_pack_start(host,actions,0,1,0)
            group='folder-popup-'+str(popup);self.folder_popup_groups.add(group)
            g.connect(combo,'changed',lambda *unused:self.fill_folder_actions(actions,popup,account,(g.gtk_combo_box_get_active_id(combo) or b'').decode()),group=group)
            self.fill_folder_actions(actions,popup,account,selected)
            from .native_choices import NativeChoice
            NativeChoice(g,combo,'选择账户中的文件夹')
        else:self.fill_folder_actions(host,popup,account,path)
        g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Display direct rename, favorite, color, delete, subscription, move and pin operations.
    # Method: Disable protected mutations in the UI while keeping the backend's independent guards.
    # ==========================================
    def fill_folder_actions(self,host,popup,account,path):
        g=self.g;self.retire_folder_group('folder-popup-actions-'+str(popup));g.clear(host);row=next((r for r in self.service.store.list_folders(account) if r['folder']==path),None)
        if not row:
            g.gtk_box_pack_start(host,g.gtk_label_new('暂无文件夹'.encode()),0,1,5);g.gtk_widget_show_all(host);return
        descriptor={'kind':'folder','account':account,'path':path};pinned=self.navigation_is_pinned(descriptor)
        mutable=not row['special'];children=bool(row['delimiter'] and any(r['folder'].startswith(path+row['delimiter']) for r in self.service.store.list_folders(account)))
        commands=[('重命名','folder-edit',lambda:self.edit_existing_folder(row,popup),mutable),
            ('取消收藏' if row['favorite'] else '收藏','folder-favorite',lambda:self.folder_option(row,popup,favorite=not row['favorite']),True),
            ('设置颜色','folder-color',lambda child,menu:self.folder_color_menu(child,menu,row),True),
            ('删除','spark-layout-trash',lambda child,menu:self.folder_delete_menu(child,menu,row),mutable and not row['total'] and not children),
            ('取消订阅' if row['subscribed'] else '订阅','spark-layout-seen',lambda:self.folder_remote_option(row,popup,'unsubscribe' if row['subscribed'] else 'subscribe'),True),
            ('移动','spark-layout-move',lambda child,menu:self.folder_move_menu(child,menu,row),mutable and bool(row['delimiter'])),
            ('取消固定' if pinned else '固定到左侧栏','spark-layout-pin',lambda:(g.gtk_popover_popdown(popup),self.toggle_navigation_pin(descriptor)),bool(row['selectable']))]
        for title,icon,callback,enabled in commands:self.folder_menu_button(host,popup,title,icon,callback,enabled,submenu=title in ('设置颜色','移动','删除'))
        g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Show a small same-popover color chooser.
    # Method: Save documented local color values without touching remote folders.
    # ==========================================
    def folder_color_menu(self,host,popup,row):
        self.clear_folder_popup(host,popup)
        for color,title in [('', '默认'),('blue','蓝色'),('purple','紫色'),('green','绿色'),('orange','橙色'),('red','红色')]:
            button=self.folder_menu_button(host,popup,('✓ ' if row['color']==color else '')+title,'folder-color',lambda c=color:self.folder_option(row,popup,color=c))
            if color:self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(button),('folder-'+color).encode())
        self.g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Require a second explicit click before deleting an empty folder.
    # Method: Keep confirmation in the current popover and reuse server-side deletion protections.
    # ==========================================
    def folder_delete_menu(self,host,popup,row):
        self.clear_folder_popup(host,popup);label=self.g.gtk_label_new('删除此空文件夹？'.encode());self.g.gtk_box_pack_start(host,label,0,1,6)
        self.folder_menu_button(host,popup,'取消','composer-close',lambda:self.g.gtk_popover_popdown(popup))
        self.folder_menu_button(host,popup,'确认删除','spark-layout-trash',lambda:self.folder_remote_option(row,popup,'delete'))
        self.g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Offer only valid parent destinations in this account.
    # Method: Exclude the current folder and its descendants; move through a guarded rename.
    # ==========================================
    def folder_move_menu(self,host,popup,row):
        self.clear_folder_popup(host,popup);delimiter=row['delimiter'];path=row['folder'];basename=path.rsplit(delimiter,1)[-1]
        parents=['']+[r['folder'] for r in self.service.store.list_folders(row['account']) if r['folder']!=path and not r['folder'].startswith(path+delimiter)]
        for parent in parents:
            target=parent+delimiter+basename if parent else basename
            if target==path:continue
            button=self.folder_menu_button(host,popup,parent or '账户根目录','spark-layout-folder',lambda destination=target:self.folder_remote_option(row,popup,'rename',destination))
            self.g.gtk_widget_set_tooltip_text(button,(parent or '账户根目录').encode())
        self.g.gtk_widget_show_all(host)

    # ==========================================
    # Function: Apply local favorite/color options and refresh both folder tree and rail.
    # Method: Use exact account/path metadata and defer widget destruction beyond the action callback.
    # ==========================================
    def folder_option(self,row,popup,**changes):
        self.g.gtk_popover_popdown(popup);self.service.store.folder_options(row['account'],row['folder'],**changes);self.queue_folder_refresh()

    # ==========================================
    # Function: Apply a serialized remote/local folder action without blocking the UI.
    # Method: Update pins and active paths only after backend confirmation.
    # ==========================================
    def folder_remote_option(self,row,popup,operation,target=''):
        if popup:self.g.gtk_popover_popdown(popup)
        account,path=row['account'],row['folder']
        self.background(lambda:self.service.folder_action(account,operation,path,target),lambda result:self.folder_operation_finished(account,operation,path,target,row.get('delimiter','/')))

    # ==========================================
    # Function: Preserve rail destinations and active folder paths after successful mutations.
    # Method: Rewrite exact account-bound prefixes for renames and remove only confirmed deletions.
    # ==========================================
    def folder_operation_finished(self,account,operation,path,target='',delimiter='/'):
        pins=self.navigation_pins();changed=False;updated=[];order_mapping={}
        for item in pins:
            match=item['kind']=='folder' and item['account']==account and (item['path']==path or bool(delimiter and item['path'].startswith(path+delimiter)))
            if match and operation=='delete':order_mapping[self.rail_key(item)]=None;changed=True;continue
            if match and operation=='rename':
                old_key=self.rail_key(item);item={**item,'path':target+item['path'][len(path):]};order_mapping[old_key]=self.rail_key(item);changed=True
            updated.append(item)
        if changed:self.service.store.set_preference('pinned_navigation',updated);self.migrate_rail_keys(order_mapping)
        if self.folder_account==account and (self.folder_path==path or bool(delimiter and self.folder_path.startswith(path+delimiter))):
            if operation=='rename':self.folder_path=target+self.folder_path[len(path):]
            elif operation=='delete':self.view='inbox';self.folder_account=self.folder_path=''
        self.refresh();self.message('文件夹操作完成')

    # ==========================================
    # Function: Render one folder with hover actions and a separately expandable child list.
    # Method: Keep selection, disclosure and context commands as independent native controls.
    # ==========================================
    def folder_tree_row(self,parent,row,has_children,expand_key):
        g=self.g;account,path=row['account'],row['folder'];host=g.gtk_box_new(1,1);event=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(event,0);line=g.gtk_box_new(0,1);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(line),b'folder-item-row');g.gtk_container_add(event,line);g.gtk_box_pack_start(host,event,0,1,0)
        toggle=icon_action(g,g.gtk_toggle_button_new(),'展开或收起子文件夹','conversation-open',12);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(toggle),b'folder-disclosure');g.gtk_box_pack_start(line,toggle,0,0,0)
        delimiter=row['delimiter'];name=path.rsplit(delimiter,1)[-1] if delimiter else path
        name={'inbox':'收件箱','sent':'已发送','drafts':'草稿','archive':'归档','trash':'废纸篓','spam':'垃圾邮件'}.get(row['special'],name)
        caption=('★ ' if row['favorite'] else '')+name+(f"  {row['unread']}" if row['unread'] else '')
        button=g.gtk_button_new_with_label(caption.encode());g.gtk_button_set_alignment(button,0,.5);label=g.gtk_bin_get_child(button);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_width_chars(label,0);g.gtk_label_set_max_width_chars(label,-1)
        icon={'inbox':'inbox','sent':'send','drafts':'compose','archive':'archive','trash':'trash','spam':'trash'}.get(row['special'],'folder');g.gtk_button_set_image(button,g.image_file(ICONS/('spark-layout-'+icon+'.svg'),14));g.gtk_button_set_always_show_image(button,1);self.shrink_navigation_labels(button)
        context=g.gtk_widget_get_style_context(button);g.gtk_style_context_add_class(context,b'folder-row')
        if row['color']:g.gtk_style_context_add_class(context,('folder-'+row['color']).encode())
        if not row['subscribed']:g.gtk_style_context_add_class(context,b'folder-muted')
        if self.folder_account==account and self.folder_path==path:
            g.gtk_style_context_add_class(context,b'active');g.gtk_style_context_add_class(g.gtk_widget_get_style_context(line),b'active')
        g.gtk_widget_set_tooltip_text(button,(account+' / '+path).encode());g.gtk_widget_set_sensitive(button,row['selectable']);g.gtk_box_pack_start(line,button,1,1,0)
        g.connect(button,'clicked',lambda *unused:self.open_folder(account,path),group='folders')
        tools=g.gtk_box_new(0,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(tools),b'folder-inline-tools');g.gtk_box_pack_start(line,tools,0,0,0)
        add=icon_action(g,g.gtk_button_new(),'新建子文件夹','action-add',14);more=g.gtk_menu_button_new();icon_action(g,more,'文件夹操作','spark-layout-more',14)
        for action in (add,more):g.gtk_box_pack_start(tools,action,0,0,0)
        g.gtk_widget_set_sensitive(add,bool(delimiter));g.gtk_widget_set_sensitive(more,not row.get('virtual',False))
        popup=g.gtk_popover_new(more);menu=g.gtk_box_new(1,2);g.gtk_container_set_border_width(menu,6);g.gtk_menu_button_set_popover(more,popup);g.gtk_container_add(popup,menu);g.surfaces.beside(popup,self.widget('folders_menu'))
        g.connect(more,'toggled',lambda *unused:self.folder_row_menu_toggled(more,menu,popup,account,path,event,tools),group='folders')
        children=g.gtk_box_new(1,1);g.gtk_widget_set_margin_start(children,8 if len(json.loads(expand_key))<=2 else 0);revealer=g.gtk_revealer_new();g.gtk_container_add(revealer,children);g.gtk_box_pack_start(host,revealer,0,1,0)
        opened=has_children and self.service.store.preference('expanded_folders',{}).get(expand_key,True);g.gtk_toggle_button_set_active(toggle,opened);g.gtk_revealer_set_reveal_child(revealer,opened);g.gtk_revealer_set_transition_duration(revealer,120 if getattr(self,'motion',True) else 0)
        g.gtk_button_set_image(toggle,g.image_file(ICONS/('conversation-close.svg' if opened else 'conversation-open.svg'),12));g.gtk_widget_set_opacity(toggle,1 if has_children else 0);g.gtk_widget_set_sensitive(toggle,has_children)
        g.connect(toggle,'toggled',lambda *unused:self.folder_disclosure(toggle,revealer,expand_key),group='folders')
        g.connect(add,'clicked',lambda *unused:self.run_action(lambda:self.begin_folder_edit(account,path)),group='folders')
        g.gtk_widget_set_opacity(tools,0);g.gtk_widget_add_events(event,(1<<12)|(1<<13))
        for signal in ('enter-notify-event','leave-notify-event'):
            g.connect(event,signal,lambda *unused,leave=signal.startswith('leave'):self.folder_row_hover(event,tools,more,leave),count=3,returns=True,group='folders')
        for action in (button,add,more):
            g.connect(action,'focus-in-event',lambda *unused:self.navigation_hover(event,tools,line,keyboard=True),count=3,returns=True,group='folders')
            g.connect(action,'focus-out-event',lambda *unused:self.folder_row_hover(event,tools,more,True),count=3,returns=True,group='folders')
        self.folder_buttons[(account,path)]=button;self.folder_row_widgets[(account,path)]={'root':host,'line':line,'button':button,'children':children,'revealer':revealer,'row':row,'add':add,'more':more,'popup':popup,'menu':menu,'toggle':toggle,'event':event,'tools':tools}
        g.gtk_box_pack_start(parent,host,0,1,0);return children

    # ==========================================
    # Function: Refresh menu state on open and restore hover visibility after dismissal.
    # Method: Keep commands visible while the popover is active, then recheck the pointer's row rectangle.
    # ==========================================
    def folder_row_menu_toggled(self,more,host,popup,account,path,event,tools):
        if self.g.gtk_toggle_button_get_active(more):self.populate_folder_popup(host,popup,account,path)
        if not self.g.gtk_toggle_button_get_active(more):self.folder_row_hover(event,tools,more,True)

    # ==========================================
    # Function: Keep row actions visible while the pointer remains anywhere within that row.
    # Method: Ignore child crossing events by checking the event box's current pointer coordinates.
    # ==========================================
    def folder_row_hover(self,event,tools,more,leave):
        return self.navigation_hover(event,tools,self.g.gtk_bin_get_child(event),leave=leave)

    # ==========================================
    # Function: Persist one folder's disclosure without selecting another mailbox.
    # Method: Update the native revealer and the existing stable hierarchy expansion key.
    # ==========================================
    def folder_disclosure(self,toggle,revealer,key):
        opened=bool(self.g.gtk_toggle_button_get_active(toggle));self.g.gtk_revealer_set_reveal_child(revealer,opened)
        state=dict(self.service.store.preference('expanded_folders',{}));state[key]=opened;self.service.store.set_preference('expanded_folders',state)
        self.g.gtk_button_set_image(toggle,self.g.image_file(ICONS/('conversation-close.svg' if opened else 'conversation-open.svg'),12))

    # ==========================================
    # Function: Begin a rename using the same tree-row input as new-folder creation.
    # Method: Dismiss only the menu and preserve the surrounding folder panel.
    # ==========================================
    def edit_existing_folder(self,row,popup):
        self.g.gtk_popover_popdown(popup);self.begin_folder_edit(row['account'],row['folder'],rename=True)

    # ==========================================
    # Function: Insert an inline folder-name entry at the exact account or parent folder.
    # Method: Keep a draft widget only; no folder or service operation exists before Enter.
    # ==========================================
    def begin_folder_edit(self,account,parent='',rename=False):
        self.cancel_folder_edit();g=self.g
        section=self.folder_account_sections.get(account)
        if not section:raise ValueError('账户栏目尚未就绪')
        row_view=self.folder_row_widgets.get((account,parent)) if parent else None
        row=row_view['row'] if row_view else None
        delimiter=row['delimiter'] if row else ('/' if account==LOCAL_ACCOUNT or self.profile.demo else next((r['delimiter'] for r in self.service.store.list_folders(account) if r['delimiter']),''))
        if parent and not delimiter and not rename:raise ValueError('此文件夹不支持子文件夹')
        entry=g.gtk_entry_new();g.gtk_entry_set_placeholder_text(entry,'文件夹名称 · Enter 创建，Esc 取消'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(entry),b'inline-folder-entry')
        if not g.gtk_revealer_get_reveal_child(section['revealer']):self.toggle_folder_account(account,section['revealer'],section['toggle'])
        if not rename and row_view:g.gtk_toggle_button_set_active(row_view['toggle'],1)
        if rename and row_view:
            container=row_view['line'];g.gtk_widget_hide(row_view['button']);g.gtk_widget_set_no_show_all(row_view['button'],1);g.gtk_box_pack_start(container,entry,1,1,0);g.gtk_box_reorder_child(container,entry,1)
            g.text(entry,parent.rsplit(delimiter,1)[-1] if delimiter else parent)
        else:
            container=row_view['children'] if row_view else section['body'];g.gtk_box_pack_start(container,entry,0,1,0);g.gtk_box_reorder_child(container,entry,0)
            g.gtk_revealer_set_reveal_child(row_view['revealer'] if row_view else section['revealer'],1)
        self.folder_edit={'entry':entry,'account':account,'parent':parent,'delimiter':delimiter,'rename':rename,'row_view':row_view}
        g.connect(entry,'activate',lambda *unused:self.run_action(self.commit_folder_edit),group='folder-edit')
        g.connect(entry,'key-press-event',self.folder_edit_key,count=3,returns=True,group='folder-edit')
        g.connect(entry,'focus-out-event',lambda *unused:(self.cancel_folder_edit(),False)[1],count=3,returns=True,group='folder-edit')
        g.gtk_widget_show(entry);g.gtk_widget_grab_focus(entry);g.gtk_editable_select_region(entry,0,-1)

    # ==========================================
    # Function: Cancel a name draft without issuing a backend operation.
    # Method: Clear edit identity before disconnecting/destroying the entry and restore a hidden rename label.
    # ==========================================
    def cancel_folder_edit(self):
        edit=getattr(self,'folder_edit',None)
        if not edit:return
        self.folder_edit=None;g=self.g;self.retire_folder_group('folder-edit');g.gtk_widget_destroy(edit['entry'])
        if edit['rename'] and edit['row_view']:
            button=edit['row_view']['button'];g.gtk_widget_set_no_show_all(button,0);g.gtk_widget_show(button)
        if getattr(self,'folder_refresh_pending',False):self.folder_refresh_pending=False;self.queue_folder_refresh()

    # ==========================================
    # Function: Consume Escape before the folder panel's ordinary dismissal handler.
    # Method: Cancel only the unfinished draft and leave current navigation visible.
    # ==========================================
    def folder_edit_key(self,widget,event,unused):
        key=C.c_uint()
        if self.g.gdk_event_get_keyval(event,C.byref(key)) and key.value==65307:self.cancel_folder_edit();return True
        return False

    # ==========================================
    # Function: Validate a single folder name and commit only on explicit Enter.
    # Method: Derive the full path from server delimiter and exact parent; discard unchanged renames.
    # ==========================================
    def commit_folder_edit(self):
        edit=getattr(self,'folder_edit',None)
        if not edit:return
        name=self.g.text(edit['entry']).strip();delimiter=edit['delimiter'];parent=edit['parent']
        if not name:self.cancel_folder_edit();return
        if name in ('.','..') or (delimiter and delimiter in name) or '/' in name or any(ord(c)<32 for c in name):raise ValueError('只需输入文件夹名称，不要输入路径或控制字符')
        prefix=parent.rsplit(delimiter,1)[0]+delimiter if edit['rename'] and delimiter and delimiter in parent else ''
        target=(prefix+name) if edit['rename'] else ((parent+delimiter if parent else '')+name)
        from .folders import valid_path
        valid_path(target)
        if edit['rename'] and target==parent:self.cancel_folder_edit();return
        if any(r['folder']==target for r in self.service.store.list_folders(edit['account'])):raise ValueError('此位置已有同名文件夹')
        account=edit['account'];rename=edit['rename'];self.cancel_folder_edit()
        if rename:
            row={'account':account,'folder':parent,'delimiter':delimiter};self.folder_remote_option(row,None,'rename',target)
        else:self.background(lambda:self.service.folder_action(account,'create',target,''),lambda result:self.folder_operation_finished(account,'create',target))

    # ==========================================
    # Function: Cancel an inline draft on any pointer press outside its actual entry rectangle.
    # Method: Observe capture-phase window coordinates without claiming the gesture or blocking the clicked action.
    # ==========================================
    def folder_pointer_press(self,gesture,count,x,y,unused):
        edit=getattr(self,'folder_edit',None)
        panel=getattr(self,'navigation_panel','')
        if panel and not self.g.surfaces.opened:
            left,top=C.c_int(),C.c_int();widget=self.widget(panel)
            if self.g.gtk_widget_translate_coordinates(widget,self.window,0,0,C.byref(left),C.byref(top)) and not (left.value<=x<left.value+self.g.gtk_widget_get_allocated_width(widget) and top.value<=y<top.value+self.g.gtk_widget_get_allocated_height(widget)):
                rail=self.g.gtk_widget_get_allocated_width(self.widget('rail'))
                if x>=rail:self.close_navigation();return
        if not edit:return
        entry=edit['entry'];left,top=C.c_int(),C.c_int()
        translated=self.g.gtk_widget_translate_coordinates(entry,self.window,0,0,C.byref(left),C.byref(top))
        inside=translated and left.value<=x<left.value+self.g.gtk_widget_get_allocated_width(entry) and top.value<=y<top.value+self.g.gtk_widget_get_allocated_height(entry)
        if not inside:self.cancel_folder_edit()
