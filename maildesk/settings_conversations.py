"""Staged native settings for which cloud/local folders feed contact conversations."""
import ctypes as C
from .desktop_general import bind,P
from .conversation_folders import inventory,load,recommended,normalized,save
from .local_mail import LOCAL_ACCOUNT

# ==========================================
# Function: Edit conversation aggregation without modifying cloud mail or saving on incidental clicks.
# Method: Group exact folder choices by account, stage changes with the parent settings dialog and apply only on Save.
# ==========================================
class ConversationFolderSettings:
    # ==========================================
    # Function: Populate one settings page with the current discovered and cache-only folders.
    # Method: Load inventory on the bounded local worker, then create native widgets on GTK's thread.
    # ==========================================
    def __init__(self,app,form):
        self.app=app;self.form=form;self.g=app.g;self.policy=load(app.service.store);self.checks={};self.rows=[];self.headings={};self.loading=True;self.closed=False;self.bulk=False
        g=self.g;host=g.object(form.builder,'page_conversations');self.host=host
        line=g.gtk_box_new(0,12);g.gtk_box_pack_start(host,line,0,1,0);label=g.gtk_label_new('汇总范围'.encode());g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(line,label,1,1,0)
        self.mode=g.gtk_combo_box_text_new();g.gtk_combo_box_text_append(self.mode,b'default','默认文件夹'.encode());g.gtk_combo_box_text_append(self.mode,b'custom','自定义文件夹'.encode());g.gtk_combo_box_set_active_id(self.mode,self.policy['mode'].encode());g.gtk_box_pack_start(line,self.mode,0,0,0)
        from .native_choices import NativeChoice
        self.choice=NativeChoice(g,self.mode,'汇总范围','conversation-folder-mode');form.choices.append(self.choice)
        self.note=g.gtk_label_new('默认汇总收件箱、已发送和普通文件夹，排除垃圾邮件、已删除及草稿。自定义范围可选择这些文件夹；只显示已同步或导入本机的邮件。'.encode());g.gtk_label_set_line_wrap(self.note,1);g.gtk_label_set_xalign(self.note,0);g.gtk_label_set_max_width_chars(self.note,66);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.note),b'settings-description');g.gtk_box_pack_start(host,self.note,0,1,8)
        self.search=bind(app,'gtk','gtk_search_entry_new',P)();g.gtk_entry_set_placeholder_text(self.search,'搜索文件夹'.encode());g.gtk_box_pack_start(host,self.search,0,1,4)
        controls=g.gtk_box_new(0,6);self.controls=controls;g.gtk_box_pack_start(host,controls,0,1,4);self.all=g.gtk_button_new_with_label('全选'.encode());self.none=g.gtk_button_new_with_label('清空'.encode())
        for button in (self.all,self.none):g.gtk_box_pack_start(controls,button,0,0,0)
        g.gtk_widget_set_tooltip_text(self.all,'选择当前搜索结果中的文件夹'.encode());g.gtk_widget_set_tooltip_text(self.none,'取消当前搜索结果中的选择'.encode())
        self.count=g.gtk_label_new('正在读取文件夹…'.encode());g.gtk_label_set_xalign(self.count,0);g.gtk_box_pack_start(controls,self.count,1,1,8)
        self.list=g.gtk_box_new(1,2);g.gtk_box_pack_start(host,self.list,0,1,0)
        g.connect(self.mode,'changed',self.mode_changed,group=form.group);g.connect(self.search,'search-changed',self.filter,group=form.group)
        g.connect(self.all,'clicked',lambda *unused:self.select_all(True),group=form.group);g.connect(self.none,'clicked',lambda *unused:self.select_all(False),group=form.group)
        app.local_loader.request('conversation-folders-settings',lambda:inventory(app.service.store),self.loaded)

    # ==========================================
    # Function: Name local transport copies without displaying internal folder identifiers.
    # Method: Keep cloud folder paths exact and translate only known internal local buckets.
    # ==========================================
    def title(self,folder):
        return {'@sent':'已发送（本机副本）','@draft':'草稿（本机）','@drafts':'草稿（本机）','@local-cache':'本机邮件'}.get(folder,folder)

    # ==========================================
    # Function: Render all folder choices in account groups after background inventory completes.
    # Method: Preserve unavailable saved paths and use ordinary checkbox rows with readable cloud/local provenance.
    # ==========================================
    def loaded(self,items):
        if self.closed or self.form.closed:return
        g=self.g;chosen={(item['account'],item['folder']) for item in self.policy['folders']};account=None
        for item in items:
            key=(item['account'],item['folder'])
            if account!=item['account']:
                account=item['account'];entry=self.app.service.accounts.get(account);name=(entry.title or entry.email) if entry else '本地文件夹' if account==LOCAL_ACCOUNT else account
                heading=g.gtk_label_new(name.encode());g.gtk_label_set_xalign(heading,0);g.gtk_widget_set_margin_top(heading,16);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(heading),b'directory-section');g.gtk_box_pack_start(self.list,heading,0,1,0);self.headings[account]=heading
            row=g.gtk_box_new(0,10);g.gtk_widget_set_margin_start(row,6);g.gtk_widget_set_margin_top(row,4);g.gtk_widget_set_margin_bottom(row,4)
            check=bind(self.app,'gtk','gtk_check_button_new_with_label',P,C.c_char_p)(self.title(item['folder']).encode());label=g.gtk_bin_get_child(check);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,38);g.gtk_widget_set_tooltip_text(check,item['folder'].encode());g.gtk_toggle_button_set_active(check,key in chosen if self.policy['mode']=='custom' else recommended(item));g.gtk_widget_set_hexpand(check,1);g.gtk_box_pack_start(row,check,1,1,0);self.checks[key]=check
            detail='暂不可用 · 保留选择' if not item['present'] else ('本机' if account==LOCAL_ACCOUNT or item['folder'].startswith('@') else '云端')+' · '+str(item['cached'])+' 封已缓存'
            label=g.gtk_label_new(detail.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),b'mail-preview');g.gtk_box_pack_start(row,label,0,0,0);g.gtk_box_pack_start(self.list,row,0,1,0);self.rows.append((row,item,check))
            g.connect(check,'toggled',self.count_selected,group=self.form.group)
        self.loading=False;g.gtk_widget_show_all(self.list);self.mode_changed();self.filter()

    # ==========================================
    # Function: Distinguish the automatic default from an explicitly saved fixed set of folder identities.
    # Method: Disable editing under default mode and retain staged custom checkbox choices while switching modes.
    # ==========================================
    def mode_changed(self,*unused):
        custom=(self.g.gtk_combo_box_get_active_id(self.mode) or b'default')==b'custom'
        for widget in (self.list,self.search,self.controls):
            self.g.gtk_widget_set_no_show_all(widget,not custom);self.g.gtk_widget_set_visible(widget,custom)
        for button in (self.list,self.all,self.none):self.g.gtk_widget_set_sensitive(button,custom and not self.loading)
        self.count_selected()

    # ==========================================
    # Function: Filter the visible folder rows without changing checked selections.
    # Method: Match account and complete folder path case-insensitively on GTK's main thread.
    # ==========================================
    def filter(self,*unused):
        query=self.g.text(self.search).strip().casefold();visible_accounts=set()
        for row,item,check in self.rows:
            visible=not query or query in (item['account']+' '+item['folder']).casefold()
            self.g.gtk_widget_set_no_show_all(row,not visible);self.g.gtk_widget_set_visible(row,visible)
            if visible:visible_accounts.add(item['account'])
        for account,heading in self.headings.items():
            visible=account in visible_accounts;self.g.gtk_widget_set_no_show_all(heading,not visible);self.g.gtk_widget_set_visible(heading,visible)

    # ==========================================
    # Function: Apply bulk selection to the currently visible search results.
    # Method: Update checkbox states together and count once so large folder inventories remain responsive.
    # ==========================================
    def select_all(self,selected):
        self.bulk=True
        try:
            for row,item,check in self.rows:
                if self.g.gtk_widget_get_visible(row):self.g.gtk_toggle_button_set_active(check,selected)
        finally:self.bulk=False
        self.count_selected()

    # ==========================================
    # Function: Show the size of the staged custom selection with a useful empty-state hint.
    # Method: Count native checkbox state without reading mail or saving a preference.
    # ==========================================
    def count_selected(self,*unused):
        if self.loading or self.bulk:return
        count=sum(bool(self.g.gtk_toggle_button_get_active(check)) for check in self.checks.values())
        self.g.label(self.count,('已选择 '+str(count)+' 个文件夹；保存后生效') if count else '未选择文件夹，对话列表将为空')

    # ==========================================
    # Function: Validate staged folder state while the parent settings dialog can still report errors.
    # Method: Preserve the current policy if inventory is unchanged/loading and reject incomplete custom edits.
    # ==========================================
    def value(self):
        mode=(self.g.gtk_combo_box_get_active_id(self.mode) or b'default').decode()
        if self.loading:
            if mode!=self.policy['mode']:raise ValueError('文件夹仍在加载，请稍候保存')
            return self.policy
        return normalized({'mode':mode,'folders':[{'account':account,'folder':folder} for (account,folder),check in self.checks.items() if self.g.gtk_toggle_button_get_active(check)]})

    # ==========================================
    # Function: Commit the chosen scope only with the parent settings Save action.
    # Method: Store exact account/path identities and report whether existing chat state must be invalidated.
    # ==========================================
    def save(self):
        value=self.value();changed=value!=load(self.app.service.store)
        if changed:save(self.app.service.store,value)
        return changed

    # ==========================================
    # Function: Ignore a pending inventory result after the parent settings dialog is destroyed.
    # Method: Use a closed guard on the callback instead of cancelling another settings page's loader channel.
    # ==========================================
    def close(self):self.closed=True
