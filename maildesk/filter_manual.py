"""Visible manual-run scope summaries and explicit account/folder/rule pickers."""
import ctypes as C
from .desktop_general import bind,P,I
from .desktop_forms import Form
from .filter_cards import label,style,chip
from .ui_actions import ICONS

# ==========================================
# Function: Keep legacy selection values without presenting three independent dropdowns.
# Method: Own plain combo controllers in an invisible box so existing change/invalidation semantics remain intact.
# ==========================================
def controller(g,parent,items):
    widget=g.gtk_combo_box_text_new()
    for identity,text in items:g.gtk_combo_box_text_append(widget,identity.encode(),text.encode())
    g.gtk_combo_box_set_active_id(widget,b'');g.gtk_box_pack_start(parent,widget,0,0,0)
    return widget

# ==========================================
# Function: Show the exact selected source and filter with separate, readable selection dialogs.
# Method: Keep selection drafts local until Apply, invalidating an existing preview only when the committed scope changes.
# ==========================================
class ManualRunPanel:
    # ==========================================
    # Function: Build the divided manual section, summary cards and native descendant switch.
    # Method: Expose only two named selection cards plus the independent subtree setting.
    # ==========================================
    def __init__(self,page,host,accounts):
        self.page=page;self.app=page.app;self.g=g=page.g;self.accounts=accounts;self.signature=None
        self.separator=separator=bind(self.app,'gtk','gtk_separator_new',P,I)(0);style(g,separator,'filter-manual-divider');g.gtk_box_pack_start(host,separator,0,1,10)
        heading=label(g,'手动运行','filter-manual-heading');g.gtk_box_pack_start(host,heading,0,1,2)
        hint=label(g,'选择范围与过滤器 → 预览匹配 → 运行移动','filter-manual-hint');g.gtk_box_pack_start(host,hint,0,1,3)
        hidden=g.gtk_box_new(0,0);g.gtk_widget_set_no_show_all(hidden,1);g.gtk_box_pack_start(host,hidden,0,0,0)
        page.run_account=controller(g,hidden,[('','所有账号'),*accounts]);page.run_folder=controller(g,hidden,[('','所有文件夹')]);page.run_rule=controller(g,hidden,[('','全部启用的过滤器')])
        line=g.gtk_box_new(0,9);g.gtk_box_pack_start(host,line,0,1,5)
        self.source_button,self.source_title,self.source_detail=self.card(line,'spark-layout-folder',self.choose_source)
        self.rule_button,self.rule_title,self.rule_detail=self.card(line,'settings-filters',self.choose_rule)
        self.selected=g.gtk_flow_box_new();g.gtk_flow_box_set_selection_mode(self.selected,0);g.gtk_flow_box_set_max_children_per_line(self.selected,3);g.gtk_flow_box_set_column_spacing(self.selected,5);g.gtk_flow_box_set_row_spacing(self.selected,5);g.gtk_box_pack_start(host,self.selected,0,1,2)
        switchline=g.gtk_box_new(0,8);g.gtk_box_pack_start(host,switchline,0,1,4)
        page.subfolders=bind(self.app,'gtk','gtk_switch_new',P)();g.gtk_widget_set_valign(page.subfolders,3);g.gtk_box_pack_start(switchline,page.subfolders,0,0,0)
        g.gtk_box_pack_start(switchline,label(g,'手动扫描子文件夹','filter-manual-hint'),0,0,0)
        g.gtk_widget_set_tooltip_text(page.subfolders,'仅扩展所选文件夹的手动扫描范围；规则内部的来源条件仍然生效。选择所有文件夹时已包含全部子文件夹。'.encode())

    # ==========================================
    # Function: Create one wide selection card with a persistent title and second-line context.
    # Method: Keep all visible values outside popup menus, with icon, ellipsis and full hover text.
    # ==========================================
    def card(self,parent,icon,callback):
        g=self.g;button=style(g,g.gtk_button_new(),'filter-run-choice');row=g.gtk_box_new(0,9);g.gtk_container_add(button,row)
        g.gtk_box_pack_start(row,g.image_file(ICONS/(icon+'.svg'),18),0,0,0);texts=g.gtk_box_new(1,4);g.gtk_box_pack_start(row,texts,1,1,0)
        title=label(g,'','filter-run-title',32);detail=label(g,'','filter-manual-hint',40);g.gtk_box_pack_start(texts,title,0,1,0);g.gtk_box_pack_start(texts,detail,0,1,0)
        g.gtk_box_pack_start(row,g.image_file(ICONS/'folder-edit.svg',13),0,0,0);g.gtk_box_pack_start(parent,button,1,1,0)
        g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=self.page.form.group)
        return button,title,detail

    # ==========================================
    # Function: Resolve rules that can actually run in the selected account scope.
    # Method: Mirror enabled/account-target eligibility while leaving first-match precedence to the shared engine.
    # ==========================================
    def eligible(self):
        from .settings_filters import active
        account=active(self.g,self.page.run_account)
        return [rule for rule in self.page.items.values() if rule['enabled'] and (not account or (rule['account'] in ('',account) and account in rule['destinations']))]

    # ==========================================
    # Function: Reflect every committed selection and list the concrete enabled filters in all-rule mode.
    # Method: Rebuild only on selection/rule changes, and prevent preview when a selected rule is paused or out of scope.
    # ==========================================
    def sync(self):
        from .settings_filters import active
        g=self.g;page=self.page;account=active(g,page.run_account);folder=active(g,page.run_folder);identity=active(g,page.run_rule);eligible=self.eligible();allowed={r['id'] for r in eligible};rule=page.items.get(identity)
        valid=not identity or identity in allowed
        for widget in (self.source_button,self.rule_button):g.gtk_widget_set_sensitive(widget,not page.busy)
        g.gtk_widget_set_sensitive(page.preview_button,not page.busy and valid)
        signature=(account,folder,identity,tuple((r['id'],r['name'],r['enabled'],r['account'],tuple(sorted(r['destinations']))) for r in page.items.values()))
        if signature==self.signature:return
        self.signature=signature;names=dict(self.accounts)
        g.label(self.source_title,names.get(account,'所有账号'));g.label(self.source_detail,'来源 · '+(folder or '所有文件夹'))
        g.gtk_widget_set_tooltip_text(self.source_button,('选择账号与来源文件夹\n'+names.get(account,'所有账号')+' · '+(folder or '所有文件夹')).encode())
        title=rule['name'] if rule else '全部启用的过滤器';detail=('已暂停' if rule and not rule['enabled'] else '不适用于当前账号' if not valid else ('全局规则' if rule and not rule['account'] else names.get(rule['account'],rule['account']) if rule else str(len(eligible))+' 条过滤器参与匹配'))
        g.label(self.rule_title,title);g.label(self.rule_detail,detail);g.gtk_widget_set_tooltip_text(self.rule_button,('选择过滤器\n'+title+' · '+detail).encode())
        g.clear(self.selected)
        for value in ([rule] if rule else eligible[:6]):g.gtk_container_add(self.selected,chip(g,value['name'],'settings-filters','filter-condition',32))
        if not rule and len(eligible)>6:g.gtk_container_add(self.selected,chip(g,'另 '+str(len(eligible)-6)+' 条','','filter-chip'))
        g.gtk_widget_show_all(self.selected)

    # ==========================================
    # Function: Keep long picker captions inside the dialog and expose their complete value on hover.
    # Method: Ellipsize the button's native label rather than expanding its window requisition.
    # ==========================================
    def fit_row(self,button):
        g=self.g;g.gtk_button_set_alignment(button,0,.5);child=g.gtk_bin_get_child(button)
        g.gtk_label_set_ellipsize(child,3);g.gtk_label_set_max_width_chars(child,56)
        g.gtk_widget_set_tooltip_text(button,bind(self.app,'gtk','gtk_button_get_label',C.c_char_p,P)(button))

    # ==========================================
    # Function: Choose one account and one of its folders in a unified, searchable dialog.
    # Method: Highlight the draft selection and commit both controller values only on Apply.
    # ==========================================
    def choose_source(self):
        from .settings_filters import active
        g=self.g;page=self.page;state={'account':active(g,page.run_account),'folder':active(g,page.run_folder)}
        form=Form(self.app,'选择手动运行范围',[],680);self.source_form=form;root=g.object(form.builder,'form')
        accounts=g.gtk_flow_box_new();g.gtk_flow_box_set_selection_mode(accounts,0);g.gtk_flow_box_set_max_children_per_line(accounts,2);g.gtk_box_pack_start(root,accounts,0,1,3)
        search=g.gtk_entry_new();bind(self.app,'gtk','gtk_entry_set_placeholder_text',None,P,C.c_char_p)(search,'搜索文件夹…'.encode());g.gtk_box_pack_start(root,search,0,1,4)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_widget_set_size_request(scroll,-1,260);rows=g.gtk_box_new(1,3);g.gtk_container_add(scroll,rows);g.gtk_box_pack_start(root,scroll,1,1,0)
        self.source_accounts={};self.source_folders={};folder_group=form.group+'-folders'
        # ==========================================
        # Function: Mark the current draft folder without changing the page or prepared preview.
        # Method: Update visible row labels only; a click never destroys its own signal closure.
        # ==========================================
        def select_folder(folder):
            state['folder']=folder
            for path,button in self.source_folders.items():g.gtk_button_set_label(button,(('✓  ' if path==folder else '    ')+(path or '所有文件夹')).encode())
        # ==========================================
        # Function: Render the selected account's folders and filter them by the search entry.
        # Method: Disconnect only the separate folder signal group before replacing its widgets.
        # ==========================================
        def folders():
            g.disconnect(folder_group);g.clear(rows);self.source_folders={};query=(g.gtk_entry_get_text(search) or b'').decode().casefold()
            values=['']+[r['folder'] for r in page.store.list_folders(state['account']) if r['selectable']] if state['account'] else ['']
            for path in values:
                if path and query not in path.casefold():continue
                button=g.gtk_button_new_with_label((('✓  ' if path==state['folder'] else '    ')+(path or '所有文件夹')).encode());style(g,button,'filter-pick-row');self.fit_row(button);g.gtk_box_pack_start(rows,button,0,1,0);self.source_folders[path]=button
                g.connect(button,'clicked',lambda *unused,value=path:select_folder(value),group=folder_group)
            g.gtk_widget_show_all(rows)
        # ==========================================
        # Function: Switch the dialog's draft account and reset its account-relative folder.
        # Method: Keep the main page unchanged until the explicit Apply response.
        # ==========================================
        def select_account(account):
            state.update(account=account,folder='')
            for value,button in self.source_accounts.items():g.gtk_button_set_label(button,(('✓  ' if value==account else '')+dict([('','所有账号'),*self.accounts])[value]).encode())
            folders()
        for identity,text in [('','所有账号'),*self.accounts]:
            button=g.gtk_button_new_with_label((('✓  ' if identity==state['account'] else '')+text).encode());style(g,button,'filter-pick-row');self.fit_row(button);g.gtk_container_add(accounts,button);self.source_accounts[identity]=button
            g.connect(button,'clicked',lambda *unused,value=identity:select_account(value),group=form.group)
        g.connect(search,'changed',lambda *unused:folders(),group=form.group);folders()
        form.button('取消',-6);form.button('使用这个范围',1);g.gtk_widget_show_all(form.window);response=g.gtk_dialog_run(form.window);g.disconnect(folder_group);form.close()
        if response==1:
            if active(g,page.run_account)!=state['account']:g.gtk_combo_box_set_active_id(page.run_account,state['account'].encode())
            if active(g,page.run_folder)!=state['folder']:g.gtk_combo_box_set_active_id(page.run_folder,state['folder'].encode())

    # ==========================================
    # Function: Choose a clearly named enabled filter while showing account ownership and matching selection.
    # Method: Use searchable radio-like rows and an explicit Apply response, preserving Cancel semantics.
    # ==========================================
    def choose_rule(self):
        from .settings_filters import active
        g=self.g;page=self.page;state={'id':active(g,page.run_rule)};names=dict(self.accounts)
        form=Form(self.app,'选择手动运行的过滤器',[],680);self.rule_form=form;root=g.object(form.builder,'form');search=g.gtk_entry_new();g.gtk_entry_set_placeholder_text(search,'搜索过滤器名称…'.encode());g.gtk_box_pack_start(root,search,0,1,4)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_widget_set_size_request(scroll,-1,300);rows=g.gtk_box_new(1,4);g.gtk_container_add(scroll,rows);g.gtk_box_pack_start(root,scroll,1,1,0);group=form.group+'-rules';self.rule_options={}
        values=[('', '全部启用的过滤器','按账号优先、列表顺序匹配')]+[(r['id'],r['name'],('全局规则' if not r['account'] else names.get(r['account'],r['account']))+' · '+str(len(r['conditions']))+' 条条件') for r in self.eligible()]
        # ==========================================
        # Function: Mark one draft rule using a persistent row check symbol.
        # Method: Leave filtering and the page's prepared preview untouched until Apply.
        # ==========================================
        def select(identity):
            state['id']=identity
            for value,(button,caption) in self.rule_options.items():g.gtk_button_set_label(button,(('✓  ' if value==identity else '    ')+caption).encode())
        # ==========================================
        # Function: Filter eligible rule rows without retaining stale callbacks.
        # Method: Rebuild on search-entry changes in a separate signal group from the entry itself.
        # ==========================================
        def render():
            g.disconnect(group);g.clear(rows);self.rule_options={};query=(g.gtk_entry_get_text(search) or b'').decode().casefold()
            for identity,name,detail in values:
                if identity and query not in name.casefold():continue
                caption=name+'\n'+detail;button=g.gtk_button_new_with_label((('✓  ' if identity==state['id'] else '    ')+caption).encode());style(g,button,'filter-pick-row');self.fit_row(button);g.gtk_box_pack_start(rows,button,0,1,0);self.rule_options[identity]=(button,caption)
                g.connect(button,'clicked',lambda *unused,value=identity:select(value),group=group)
            g.gtk_widget_show_all(rows)
        g.connect(search,'changed',lambda *unused:render(),group=form.group);render();form.button('取消',-6);form.button('使用这个过滤器',1);g.gtk_widget_show_all(form.window);response=g.gtk_dialog_run(form.window);g.disconnect(group);form.close()
        if response==1 and active(g,page.run_rule)!=state['id']:g.gtk_combo_box_set_active_id(page.run_rule,state['id'].encode())
