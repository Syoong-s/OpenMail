"""Profile storage controls inside the existing native settings workspace."""

FIELDS=[('mail_retention_enabled','自动移入已删除邮件','check',[]),('mail_retention_days','保留天数（天）','text',[]),('storage_cache','缓存目录','text',[]),('storage_data','数据目录','text',[]),('storage_downloads','下载目录','text',[])]
DESCRIPTION='管理缓存、邮件数据和下载位置，并清理云端已不存在的邮件及无关联联系人。'

# ==========================================
# Function: Populate editable storage paths and parented native folder pickers.
# Method: Bind typed path entries, folder pickers and explicit background cache cleanup controls.
# ==========================================
def bind_storage_settings(app,form):
    g=app.g;locations=app.profile.storage
    from .mail_retention import get_policy
    enabled,days=get_policy(app.service.store)
    form.value('mail_retention_enabled',enabled);form.value('mail_retention_days',str(days))
    g.gtk_widget_set_tooltip_text(form.fields['mail_retention_days'][0],'填写 1 至 36500 的整数，单位为天。点击保存后生效。'.encode())
    for name in ('cache','data','downloads'):
        key='storage_'+name;form.value(key,str(getattr(locations,name)))
        g.gtk_widget_set_tooltip_text(form.fields[key][0],str(getattr(locations,name)).encode())
        button=g.object(form.builder,key+'_choose')
        g.connect(button,'clicked',lambda *unused,field=key:choose_storage_folder(app,form,field),group=form.group)
    host=g.object(form.builder,'page_storage')
    button=g.gtk_button_new_with_label('清理缓存'.encode());form.page_buttons['storage_clean']=button
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'settings-link')
    g.connect(button,'clicked',lambda *unused:clean_storage_cache(app,form),group=form.group)
    g.gtk_box_pack_start(host,button,0,1,10)
    form.cache_cleanup_note=g.gtk_label_new('核对云端后，删除云端已不存在的缓存邮件；删除没有任何缓存邮件关联的非星标联系人。带星标联系人始终保留。无法核对的账号、本地邮件、草稿和下载文件保留。'.encode())
    g.gtk_label_set_line_wrap(form.cache_cleanup_note,1);g.gtk_label_set_xalign(form.cache_cleanup_note,0);g.gtk_label_set_max_width_chars(form.cache_cleanup_note,72);g.gtk_box_pack_start(host,form.cache_cleanup_note,0,1,0)
    retention_note=g.gtk_label_new('自动移入已删除邮件：各账号每 24 小时检查一次，将收件箱中超过保留天数的未置顶邮件移入该账号的已删除邮件。关闭期间到期的检查，会在重新打开后的首次成功同步时补查；未完成的清理继续分批处理。默认开启、365 天；保存开启或天数变更后，下次同步补查。关闭后停止后续自动移动，已移动的邮件可在已删除邮件中找回。'.encode())
    g.gtk_label_set_line_wrap(retention_note,1);g.gtk_label_set_xalign(retention_note,0);g.gtk_label_set_max_width_chars(retention_note,72);g.gtk_box_pack_start(host,retention_note,0,1,8)
    g.gtk_box_reorder_child(host,retention_note,2)
    note=g.object(form.builder,'note_storage')
    g.label(note,'当前账号配置文件：'+str(locations.config)+'\n数据目录包含邮件、草稿、模板、联系人、账号、加密登录信息和应用设置。缓存可重新生成；下载目录只管理 TeleMail 专用文件夹，不移动其他“下载”文件或曾另存到其他位置的文件。\n修改路径后保存将关闭应用，复制并校验文件，再切换位置并重新启动。原目录保留。取消迁移或失败可返回原位置。目标目录须为空，且不能互相包含。')
    g.gtk_label_set_max_width_chars(note,72)
    button=g.gtk_button_new_with_label('迁移并重新启动'.encode());form.page_buttons['storage_migrate']=button
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'settings-link')
    g.connect(button,'clicked',lambda *unused:g.gtk_dialog_response(form.window,1),group=form.group)
    g.gtk_box_pack_start(g.object(form.builder,'page_storage'),button,0,1,10)

# ==========================================
# Function: Put the chosen absolute directory into one editable settings field.
# Method: Reuse the typed folder picker parented to the live main window.
# ==========================================
def choose_storage_folder(app,form,key):
    try:
        folder=app.g.choose_folder(app.window,'选择储存位置',form.value(key))
        if folder is not None:form.value(key,str(folder))
    except (OSError,ValueError,RuntimeError) as error:app.g.label(form.note,str(error))

# ==========================================
# Function: Validate all requested directories while settings remain visible.
# Method: Reuse the core's no-write planning and return None for unchanged paths.
# ==========================================
def storage_plan(app,form):
    from .storage_migration import prepare_migration
    return prepare_migration(app.profile.storage,{key:form.value('storage_'+key).strip() for key in ('cache','data','downloads')})

# ==========================================
# Function: Clean only verified obsolete cache when the user presses the storage action.
# Method: Run network/database work outside GTK, guard repeated clicks and report partial account failures.
# ==========================================
def clean_storage_cache(app,form):
    if getattr(app,'cache_cleanup_busy',False):
        app.message('正在核对云端并清理缓存，请稍候');return
    app.cache_cleanup_busy=True;g=app.g;button=form.page_buttons['storage_clean']
    g.gtk_widget_set_sensitive(button,0);g.gtk_button_set_label(button,'正在核对云端…'.encode())
    # ==========================================
    # Function: Restore the live storage control after its background request finishes.
    # Method: Release application ownership even if the originating Settings form has closed.
    # ==========================================
    def finish():
        app.cache_cleanup_busy=False
        if not form.closed:
            g.gtk_widget_set_sensitive(button,1);g.gtk_button_set_label(button,'清理缓存'.encode())
    # ==========================================
    # Function: Report actual deleted counts and keep every still-live view consistent with the cache.
    # Method: Invalidate prepared bodies, refresh mail/contact lists, and mention accounts that could not be verified.
    # ==========================================
    def ready(result):
        finish()
        if app.closing:return
        with app.local_loader.body_lock:
            app.local_loader.bodies.clear();app.local_loader.body_bytes=0
        selected=getattr(app,'selected','')
        if selected and not selected.startswith(('job:','contact:')):
            with app.service.store.db() as db:exists=bool(db.execute('SELECT 1 FROM messages WHERE id=?',(selected,)).fetchone())
            if not exists:app.clear_reader()
        app.refresh()
        contacts=getattr(getattr(app,'settings_form',None),'contacts_page',None)
        if contacts and not contacts.form.closed:contacts.load(offset=0)
        text='已清理 '+str(result['messages'])+' 封失效缓存邮件、'+str(result['contacts'])+' 位无邮件关联的非星标联系人。'
        if result['skipped']:text+=' '+str(len(result['skipped']))+' 个账号未能核对云端，其邮件缓存已保留。'
        if result.get('compaction_deferred'):text+=' 数据库空间将在后续维护时回收。'
        if not form.closed:g.label(form.cache_cleanup_note,text)
        app.message(text)
    # ==========================================
    # Function: Keep cleanup errors retryable without implying that all accounts were cleaned.
    # Method: Restore the live button and use the application's standard error boundary.
    # ==========================================
    def failed(error):
        finish()
        if not form.closed:g.label(form.cache_cleanup_note,'清理未全部完成，可重新尝试。')
        if not app.closing:app.show_error(error)
    app.background(app.service.clean_cache,ready,failed)

# ==========================================
# Function: Validate pending retention input before any Settings page is saved.
# Method: Accept only a plain positive integer day count and the typed native enable switch.
# ==========================================
def retention_values(form):
    from .mail_retention import validate_policy
    text=str(form.value('mail_retention_days')).strip()
    if not text.isascii() or not text.isdigit() or len(text)>5:raise ValueError('保留天数须为 1 至 36500 的整数')
    return validate_policy(form.value('mail_retention_enabled'),int(text))
