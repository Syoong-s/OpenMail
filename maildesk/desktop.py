"""Native x64 GTK desktop application; talks directly to the mail core."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
from datetime import datetime
from email import policy
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import subprocess
import sys
import time

from . import __version__
from .demo import seed
from .desktop_profile import DesktopProfile
from .mime import attachment_content
from .service import MailService
from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL
from .desktop_organization import OrganizationUI
from .desktop_inbox import InboxUI
from .desktop_general import GeneralUI
from .desktop_focus import FocusUI
from .desktop_conversation import ConversationUI
from .desktop_accounts import AccountScopeUI
from .desktop_list_render import ListRenderUI
from .desktop_chat import ContactChatUI

ASSETS = Path(__file__).parent / 'desktop_assets'
VIEWS = {'inbox':'收件箱','unread':'未读邮件','priority':'优先处理','pinned':'置顶邮件','sent':'已发送','drafts':'草稿与发件箱','archive':'归档','snoozed':'稍后','reminders':'跟进提醒','aside':'暂存','done':'已完成','trash':'废纸篓','spam':'垃圾邮件','all':'所有邮件','new_senders':'新发件人','blocked':'已屏蔽'}
CATEGORIES = {'personal':'个人','notification':'通知','newsletter':'订阅','verification':'验证码'}
STATES = {'draft':'草稿','queued':'等待发送','sending':'正在发送','sent':'已发送','partial':'部分接受','failed':'发送失败','uncertain':'结果待确认'}

# ==========================================
# Function: Run native windows and coordinate mailbox operations.
# Method: GTK callbacks remain on the main thread; slow work returns through a queue.
# ==========================================
class DesktopApp(ContactChatUI,ListRenderUI,AccountScopeUI, ConversationUI, FocusUI, InboxUI, OrganizationUI, GeneralUI):
    # ==========================================
    # Function: Initialize the native application without touching a live mailbox yet.
    # Method: Let GtkApplication route second activations before acquiring storage locks.
    # ==========================================
    def __init__(self, options):
        from .gtk_native import GtkNative
        self.options, self.profile = options, DesktopProfile(options.demo, options.config, options.data)
        from .reader_runtime import prepare_readers
        prepare_readers()
        self.g = GtkNative()
        self.pending_storage_migration=None;self.storage_shutdown_error=''
        self.g.fonts(ASSETS / 'fonts')
        self.g.g_set_prgname(b'TeleMail')
        self.g.g_set_application_name(b'TeleMail')
        if not self.g.gtk_init_check(None, None):
            raise RuntimeError('无法初始化系统图形桌面，请在桌面会话中打开 TeleMail。')
        self.application = self.g.gtk_application_new(self.profile.application_id.encode(), 4|(32 if os.name=='nt' else 0))
        self.window = self.builder = self.service = self.lock_file = self.composer = None
        self.widgets, self.rows, self.items, self.current = {}, {}, [], None
        self.total=0
        self.document=None
        self.focus_group='';self.summary_rows={};self.quick_buttons={};self.row_status={};self.row_history_badges={}
        self.row_avatar_styles={}
        self.row_groups={}
        self.view, self.selected, self.limit = 'inbox', '', 100
        self.folder_path,self.folder_account,self.smart_query='', '', ''
        self.multi,self.motion=False,True
        self.reader_fade=0
        self.known_messages=None
        self.deadline_notified=set()
        self.rendering, self.closing = False, False
        self.queue = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='maildesk-ui')
        self.last_poll, self.last_sync, self.last_jobs = 0, None, ''
        self.notice_until = 0
        self.timer = None
        self.timer_callback = None
        self.exit_code = 0
        self.g.connect(self.application, 'activate', self.activate)
        self.g.connect(self.application,'open',self.open_files,count=5,types=[C.c_void_p,C.POINTER(C.c_void_p),C.c_int,C.c_char_p,C.c_void_p])
        quit_action = self.g.g_simple_action_new(b'quit', None)
        self.g.connect(quit_action, 'activate', lambda *unused:self.on_delete(force=True), count=3)
        self.g.g_action_map_add_action(self.application, quit_action)
        self.g.g_object_unref(quit_action)

    # ==========================================
    # Function: Resolve cached native widgets by stable builder IDs.
    # Method: Keep borrowed objects alive through the main builder reference.
    # ==========================================
    def widget(self, name):
        if name not in self.widgets:
            self.widgets[name] = self.g.object(self.builder, name)
        return self.widgets[name]

    # ==========================================
    # Function: Bring up or focus the single native mailbox window.
    # Method: Set the product title after GTK titlebar construction and preserve existing profile locks.
    # ==========================================
    def activate(self, *unused):
        if self.closing:return
        if self.window:
            self.restore_window()
            return
        self.builder = self.g.builder((ASSETS / 'main.ui').read_text())
        self.window = self.widget('window')
        self.g.gtk_window_set_application(self.window, self.application)
        self.g.surfaces.attach(self)
        from .windows_frame import bind_window_frame
        bind_window_frame(self,self.window)
        self.g.gtk_window_set_title(self.window,b'TeleMail')
        self.g.gtk_window_set_icon_from_file(self.window, str(ASSETS / 'icon.svg').encode(), None)
        self.g.css(ASSETS / 'style.css')
        self.bind_actions()
        from .richtext import NativeRichText
        self.rich_reader=NativeRichText(self.g,self.widget('body'))
        self.profile.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = (self.profile.data / 'instance.lock').open('a+b')
        try:
            from .platform_native import lock_instance
            lock_instance(self.lock_file)
            accounts = self.profile.accounts()
            self.profile.restore_credentials(accounts)
            self.service = MailService(self.profile.data, accounts, demo=self.profile.demo)
            self.service.store.cache_dir=self.profile.cache
            if self.profile.demo:
                seed(self.service.store)
            if self.service.store.preference('dark_design_revision',0)<4:
                self.service.store.set_preference('theme','dark')
                self.service.store.set_preference('dark_design_revision',4)
            if self.service.store.preference('editor_presentation_revision',0)<8:
                self.service.store.set_preference('composer_new_window',False)
                self.service.store.set_preference('reply_window_size','compact')
                self.service.store.set_preference('editor_presentation_revision',8)
            from .identity_colors import IdentityColors
            self.identity_colors=IdentityColors(self.service.store)
            from .workspace_geometry import WorkspaceGeometry
            self.workspace_geometry=WorkspaceGeometry(self)
            self.initialize_general()
            self.initialize_reader()
            self.initialize_inbox()
            self.initialize_chat()
            self.apply_appearance()
            self.fill_accounts()
            self.rendering=True
            self.g.gtk_combo_box_set_active_id(self.widget('category_filter'), b'all')
            self.rendering=False
            self.refresh()
            self.last_sync=self.service.status['last_sync']
        except Exception as error:
            self.message('无法打开邮箱：' + str(error), permanent=True)
            self.g.label(self.widget('banner'), '数据目录已在使用或配置无效。请关闭旧版本进程，或检查账户配置。')
            self.g.gtk_widget_show_all(self.window)
            return
        self.g.gtk_widget_show_all(self.window)
        for name in ('views_menu','mail_menu','attachments_menu','thread_menu'):
            self.g.gtk_widget_show_all(self.g.gtk_bin_get_child(self.widget(name)))
        self.set_reader_state(False)
        self.g.gtk_widget_set_visible(self.widget('more'), int(getattr(self,'render_has_more',False) or len(self.items)<self.total))
        self.apply_layout()
        if getattr(self.options,'background',False) and self.tray_available():self.g.gtk_widget_hide(self.window)
        self.g.label(self.widget('banner'), '演示邮箱 · 合成邮件，外发已关闭' if self.profile.demo else '你的邮件，你的节奏')
        from .desktop_forms import ask_credential
        if not self.options.self_test:
            for account in accounts:
                if account.id not in self.service.store.preference('paused_accounts',[]):ask_credential(self, account)
        self.service.start()
        self.timer_callback = C.CFUNCTYPE(C.c_int, C.c_void_p)(self.tick)
        self.timer = self.g.g_timeout_add(33, C.cast(self.timer_callback, C.c_void_p), None)
        if self.options.self_test:
            from .desktop_smoke import NativeSmoke
            self.smoke = NativeSmoke(self)
        if not accounts and not self.profile.demo:
            self.message('可直接创建本地文件夹、导入 EML 和保存草稿；添加邮箱账户后即可正常收发。')

    # ==========================================
    # Function: Attach fixed native actions and desktop lifecycle events.
    # Method: Bind signal handlers once, with no HTML/JavaScript event bridge.
    # ==========================================
    def bind_actions(self):
        actions = {'compose':self.open_composer, 'settings':self.settings, 'sync':self.request_sync,
                   'import':self.import_mail, 'reclassify':lambda:self.inbox_menu_action(self.reclassify), 'more':self.load_more,
                   'apply_category':self.apply_category, 'reply':self.reply, 'export':self.export_mail,
                   'edit_draft':self.edit_draft, 'cancel_job':self.cancel_job, 'demo':self.open_demo,
                   'install':self.install,'reader_close':self.close_mail,'delete_draft':self.delete_selected_draft,
                   'search_close':lambda:self.show_search(False)}
        for name, callback in actions.items():
            self.g.connect(self.widget(name), 'clicked', lambda *unused, fn=callback:self.run_action(fn))
        for view in VIEWS:
            self.g.connect(self.widget('nav_' + view), 'clicked', lambda *unused, name=view:self.set_view(name))
        self.g.connect(self.widget('gatekeeper_inbox'),'clicked',lambda *unused:self.set_view('new_senders'))
        for policy in ('accepted','blocked'):
            self.g.connect(self.widget('accept_sender' if policy=='accepted' else 'block_sender'),'clicked',lambda *unused,value=policy:self.background(lambda identity=self.selected:self.service.store.organize(identity,sender_policy=value),lambda result:self.refresh()))
        self.g.connect(self.widget('reschedule_job'),'clicked',lambda *unused:self.change_job_time())
        self.g.connect(self.widget('send_job_now'),'clicked',lambda *unused:self.change_job_time(now=True))
        for name in ('search','category_filter','account_filter'):
            self.g.connect(self.widget(name), 'changed', self.filter_changed)
        self.g.connect(self.widget('messages'), 'row-selected', self.row_selected, count=3)
        for name, key in [('seen','seen'),('pin','pinned'),('priority','priority')]:
            self.g.connect(self.widget(name), 'clicked', lambda *unused, flag=key:self.toggle(flag))
        self.g.connect(self.widget('archive'),'clicked',lambda *unused:self.special_action('inbox' if self.current and (self.current.get('archived') or self.current.get('folder')==self.service.store.special_folder(self.current.get('account',''),'archive')) else 'archive'))
        self.bind_organization()
        for name,view in [('rail_pinned','pinned'),('rail_sent','sent'),('rail_trash','trash'),('rail_done','done')]:
            self.g.connect(self.widget(name),'clicked',lambda *unused,key=view:self.set_view(key))
        self.g.connect(self.widget('search_toggle'),'clicked',lambda *unused:self.show_search())
        self.g.connect(self.widget('search'),'stop-search',lambda *unused:self.show_search(False))
        self.g.connect(self.widget('search'),'key-press-event',self.key_pressed,count=3,returns=True)
        self.g.connect(self.window, 'delete-event', self.on_delete, count=3, returns=True)

    # ==========================================
    # Function: Surface local file/dialog action failures inside the native client.
    # Method: Catch validation and I/O exceptions before crossing the C callback boundary.
    # ==========================================
    def run_action(self, callback):
        try:
            return callback()
        except Exception as error:
            self.show_error(error)

    # ==========================================
    # Function: Submit work without freezing the native event loop.
    # Method: Transfer completion values and bounded errors through a thread-safe queue.
    # ==========================================
    def background(self, operation, success=None, failure=None):
        # ==========================================
        # Function: Run one backend operation on a worker thread.
        # Method: Queue callbacks instead of touching native widgets from that thread.
        # ==========================================
        def run():
            try:
                result = operation()
                self.queue.put((success, result))
            except Exception as error:
                self.queue.put((failure or self.show_error, error))
        self.executor.submit(run)

    # ==========================================
    # Function: Drain UI completions and observe background mailbox state.
    # Method: A GLib timeout updates widgets only on the GTK main thread.
    # ==========================================
    def tick(self, unused):
        if self.closing:return 1
        try:
            self.g.surfaces.poll();self.navigation_hover_tick()
            if getattr(self,'local_loader',None):self.local_loader.tick()
            if getattr(self,'workspace_geometry',None):self.workspace_geometry.tick()
            from .appearance_theme import refresh_readers
            refresh_readers(self)
            while not self.queue.empty() and not self.closing:
                callback, value = self.queue.get_nowait()
                if callback:
                    callback(value)
            self.reveal_conversation_card()
            if self.composer and not self.composer.closed:self.composer.autosave()
            if hasattr(self,"chat_root"):self.chat_tick()
            if getattr(self,"reader_handoff",None):self.reader_handoff.tick()
            if self.reader_fade:
                elapsed=(time.monotonic()-self.reader_fade)/0.24
                self.g.gtk_widget_set_opacity(self.widget('reader_content'),min(1,0.35+0.65*max(0,elapsed)))
                if elapsed>=1:self.reader_fade=0
            if hasattr(self, 'smoke'):
                self.smoke.tick()
                if self.closing:
                    return 1
            if time.monotonic() - self.last_poll >= 2 and self.service:
                self.last_poll = time.monotonic()
                status = self.service.status
                (self.g.gtk_spinner_start if status['syncing'] else self.g.gtk_spinner_stop)(self.widget('spinner'))
                self.check_send_sound()
                self.check_notifications()
                if self.last_sync != status['last_sync']:
                    self.last_sync = status['last_sync']
                    self.refresh()
                if self.view == 'drafts':
                    with self.service.store.db() as db:jobs=db.execute("SELECT value FROM navigation_revision WHERE topic='jobs'").fetchone()[0]
                    if jobs != self.last_jobs:
                        self.last_jobs = jobs
                        self.refresh()
                if time.monotonic() >= self.notice_until:
                    failures = [key for key,value in status['accounts'].items() if not value.get('ok')]
                    text = status.get('worker_error') or ('同步失败：' + '、'.join(failures) if failures else '正在同步邮件…' if status['syncing'] else '最近同步 ' + datetime.fromtimestamp(status['last_sync']).strftime('%H:%M:%S') if status['last_sync'] else '本地邮件核心已就绪')
                    self.g.gtk_widget_set_tooltip_text(self.widget('sync'),text.encode())
                    self.g.gtk_revealer_set_reveal_child(self.widget('toast_revealer'),0)
        except Exception as error:
            self.show_error(error)
        return 1

    # ==========================================
    # Function: Display operation results in the native status area.
    # Method: Use the saved bounded operation-toast lifetime while preserving explicit permanent notices.
    # ==========================================
    def message(self, text, permanent=False):
        from .workspace_geometry import bounded
        duration=bounded(self.service.store.preference('toast_duration',7),7,1,60) if self.service else 7
        self.notice_until = float('inf') if permanent else time.monotonic() + duration
        if self.window:
            self.g.label(self.widget('status'), text)
            self.g.gtk_revealer_set_reveal_child(self.widget('toast_revealer'),1)

    # ==========================================
    # Function: Report an actionable backend failure without crashing GTK.
    # Method: Show exception text for local validation and generic transport failures.
    # ==========================================
    def show_error(self, error):
        self.message('操作未完成：' + str(error))

    # ==========================================
    # Function: Switch the native sidebar mailbox view.
    # Method: Reset pagination and invalidate any stale reader selection.
    # ==========================================
    def set_view(self, view):
        if self.composer and self.composer.embedded and self.composer.busy:return
        if not self.close_document():return
        if getattr(self,'local_loader',None):self.local_loader.cancel('read')
        self.pending_read_identity=''
        self.focus_group=''
        self.view, self.selected, self.limit = view, '', 100
        self.folder_path,self.folder_account,self.smart_query='','',''
        self.g.label(self.widget('view_title'), VIEWS[view])
        self.close_navigation()
        self.refresh()

    # ==========================================
    # Function: Apply search, category or account filters.
    # Method: Ignore programmatic combo reconstruction and reset pagination.
    # ==========================================
    def filter_changed(self, *unused):
        if not self.rendering and unused and unused[0]==self.widget('account_filter') and getattr(self,'chat_composer',None) and not self.chat_composer.autosave(force=True):
            self.rendering=True;self.g.gtk_combo_box_set_active_id(self.widget('account_filter'),getattr(self,'last_chat_account_filter','all').encode());self.rendering=False;return
        self.update_account_pill()
        if not self.rendering and self.service:
            self.limit = 100
            if unused and unused[0]==self.widget('account_filter') and self.view in ('folder','smart'):
                self.set_view('inbox')
            else:self.run_action(self.refresh)

    # ==========================================
    # Function: Expand the currently requested page range.
    # Method: Reuse bounded core queries while preserving the selected message.
    # ==========================================
    def load_more(self):
        self.limit += 100
        self.refresh()

    # ==========================================
    # Function: Query and render native list rows for mail or drafts.
    # Method: Flatten display-only whitespace and enforce single-line GTK labels with stable row identities.
    # ==========================================
    def refresh(self, *unused):
        if not self.service or self.closing:return
        if getattr(self,'chat_source_return',None) and not self.contact_mode() and not self.chat_discard_return():return
        if getattr(self,"selected_chat","") and not self.contact_mode() and not self.leave_chat():return
        self.cancel_list_render()
        self.contact_core()
        with self.service.store.preference_snapshot():self.refresh_snapshot()

    # ==========================================
    # Function: Render one mailbox using a coherent bounded preference snapshot.
    # Method: Batch complete group metadata and labels while limiting native individual rows.
    # ==========================================
    def refresh_snapshot(self,projection=None):
        category = (self.g.gtk_combo_box_get_active_id(self.widget('category_filter')) or b'all').decode()
        account = (self.g.gtk_combo_box_get_active_id(self.widget('account_filter')) or b'all').decode()
        search = self.g.text(self.widget('search'))
        if self.smart_query:search=self.smart_query+' '+search
        scope=self.folder_account or ('' if account=='all' else account)
        if self.view=='inbox' and self.inboxes.active()['accounts']:
            configured=self.inboxes.active()['accounts']
            scope=tuple(configured) if account=='all' else tuple(v for v in configured if v==account)
        if projection is None:
            from .desktop_loading import LocalLoader,mailbox_projection
            if not getattr(self,'local_loader',None):self.local_loader=LocalLoader(self)
            request=(self.view,category,scope,self.folder_path,search,self.limit,self.inboxes.active())
            self.local_loader.request('list',lambda:mailbox_projection(self,request),lambda result:self.apply_projection(result))
            return
        self.begin_list_render(projection,category,search)

    # ==========================================
    # Function: Construct a coherent native mailbox while yielding between short row batches.
    # Method: Preserve stable identities and existing summaries; the idle scheduler owns preference scopes and cancellation.
    # ==========================================
    def render_projection(self,projection,category,search):
        if projection.get('contacts'):
            yield from self.render_contacts(projection);return
        self.g.gtk_widget_show(self.widget('category_filter'));self.g.gtk_widget_show(self.widget('selection'))
        render_has_more=False;self.items=projection['items'];self.total=projection['total']
        self.refresh_folders(projection['folders'],projection['smart']);new_count=projection['new_count']
        self.g.gtk_widget_set_visible(self.widget('gatekeeper_inbox'),bool(new_count))
        self.g.label(self.widget('gatekeeper_inbox'),f'新发件人 {new_count} · 审阅',button=True)
        for key in VIEWS:
            context=self.g.gtk_widget_get_style_context(self.widget('nav_'+key))
            (self.g.gtk_style_context_add_class if key==self.view else self.g.gtk_style_context_remove_class)(context,b'active')
        self.rendering = True
        self.g.disconnect('list-headers')
        self.row_groups={}
        self.rows={}
        self.g.clear(self.widget('messages'))
        self.rows = {}
        self.summary_rows={};self.quick_buttons={};self.row_status={};self.row_history_badges={}
        self.row_avatar_styles={}
        self.row_avatars={}
        selected_row = None
        self.row_groups={}
        grouping=self.service.store.preference('grouping','smart')
        self.inbox_sections={}; self.group_members={}; self.collapsed_rows=set()
        render_items=self.items
        if self.view=='inbox' and not search and category=='all':
            definition=self.inboxes.active()
            sections=projection['sections']
            self.items=[item for section in sections for item in section['items']]
            render_items=[]
            if self.focus_group:self.total=0;self.items=[]
            self.g.label(self.widget('view_subtitle'),definition['name'])
            for section in sections:
                self.group_members[section['key']]=[item['id'] for item in section['items']]
                if self.focus_group:
                    if section['key']==self.focus_group:
                        render_items.extend(section['items'][:self.limit]);self.total=len(section['items'])
                        self.items=list(section['items'])
                elif not section.get('summary'):
                    for item in (section['shown'][:1] if section['collapsed'] else section['shown']):
                        self.inbox_sections[item['id']]=section
                        if section['collapsed']:self.collapsed_rows.add(item['id'])
            if not self.focus_group:
                from .desktop_focus import focused_render_items
                render_items,render_has_more=focused_render_items(sections,self.limit)
        else:
            self.g.label(self.widget('view_subtitle'),'按时间排列')
            if grouping in ('sender','domain') and self.view!='drafts':
                self.items.sort(key=lambda r:((r['sender'].rsplit('@',1)[-1] if grouping=='domain' else r['sender']),-r['timestamp']))
        self.g.gtk_widget_set_visible(self.widget('focus_back'),bool(self.focus_group))
        if self.focus_group:self.g.label(self.widget('view_subtitle'),'分组邮件 · '+self.focus_group.split(':')[0])
        from .desktop_preferences import row_presentation
        presentation=row_presentation(self.service.store)
        avatar_state=self.identity_colors.snapshot([item['account'] for item in self.items])
        self.list_avatar_state=avatar_state
        labels_by_id=projection['labels']
        show_avatar=self.service.store.preference('avatars_mode','everywhere') in ('everywhere','list')
        for index,item in enumerate(render_items):
            if '_summary' in item:self.summary_row(item['_summary']);continue
            row = self.g.gtk_list_box_row_new()
            if self.view!='drafts':self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(row),b'mail-item-row')
            self.g.gtk_widget_set_size_request(row,-1,presentation['row_height'])
            box = self.g.gtk_box_new(1, 1)
            identity = ('job:' if self.view == 'drafts' else '') + item['id']
            self.rows[row] = identity
            section=self.inbox_sections.get(identity)
            if section and self.inboxes.active()['mode']=='smart':
                context=self.g.gtk_widget_get_style_context(row);self.g.gtk_style_context_add_class(context,b'card-row')
                if item==section['shown'][-1] or section['collapsed']:self.g.gtk_style_context_add_class(context,b'card-last')
            if self.view == 'drafts':
                texts = [(STATES[item['state']]+(' · '+datetime.fromtimestamp(item['due']).strftime('%m-%d %H:%M') if item['state']=='queued' else '')+(' · ◉ 回执 '+str(item['receipts']) if item.get('receipts') else ''), 'mail-sender'), (item['draft'].get('subject') or '(无主题)', 'mail-subject'), (item['draft'].get('to') or '(尚无收件人)', 'mail-preview')]
            else:
                suffix = ((' · ☆ 优先' if item['priority'] else '') + (' · 置顶' if item['pinned'] else '')) if presentation['labels_system'] else ''
                labels=labels_by_id.get(identity,[])
                suffix+=('  ['+' · '.join(labels)+']') if labels else ''
                texts = [((item.get('sender_name') or item['sender']) + ' · ' + datetime.fromtimestamp(item['timestamp']).strftime('%m-%d %H:%M'), 'mail-sender'), ((item['subject'] or '(无主题)')+suffix+(' · ◉' if item.get('receipts') else ''), 'mail-subject'), (item['preview'], 'mail-preview')]
            if not presentation['preview_lines']:texts=[pair for pair in texts if pair[1]!='mail-preview']
            for text, css in texts:
                # Fold CRLF, tabs and Unicode separators only in the list; keep original mail intact.
                text = ' '.join(text.split())
                if css == 'mail-preview':text = text[:90*max(1,presentation['preview_lines'])]
                label = self.g.gtk_label_new(text.encode())
                self.g.gtk_label_set_single_line_mode(label, int(not(css=='mail-preview' and presentation['preview_lines']>1)))
                self.g.gtk_label_set_line_wrap(label, int(css=='mail-preview' and presentation['preview_lines']>1))
                if css=='mail-preview':self.g.gtk_label_set_lines(label,presentation['preview_lines'])
                self.g.gtk_label_set_xalign(label, 0)
                self.g.gtk_label_set_ellipsize(label, 3)
                self.g.gtk_label_set_max_width_chars(label, 45)
                self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(label), css.encode())
                self.g.gtk_box_pack_start(box, label, 0, 1, 0)
            if self.view!='drafts':
                horizontal=self.g.gtk_box_new(0,2);self.g.gtk_widget_set_margin_start(box,3)
                avatar=self.g.gtk_label_new(((item.get('sender_name') or item['sender'])[:1].upper()).encode())
                self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(avatar),b'mail-avatar')
                self.apply_avatar(avatar,item['sender'],item['account'],avatar_state)
                self.row_avatar_styles[identity]=self.identity_colors.style(item['sender'],item['account'],avatar_state)
                self.row_avatars[identity]=avatar
                self.g.gtk_widget_set_valign(avatar,3)
                self.g.gtk_widget_set_no_show_all(avatar,not show_avatar)
                self.g.gtk_widget_set_visible(avatar,show_avatar)
                self.g.gtk_box_pack_start(horizontal,self.row_actions(identity,item),0,0,0)
                from .mail_list_visuals import avatar_bubble,row_markers
                avatar_host,badge=avatar_bubble(self.g,avatar,item.get('history_count',1),title='历史会话 · '+str(item.get('history_count',1))+' 封邮件')
                self.row_history_badges[identity]=badge
                self.g.gtk_widget_set_no_show_all(avatar_host,not show_avatar);self.g.gtk_widget_set_visible(avatar_host,show_avatar)
                self.g.gtk_box_pack_start(horizontal,avatar_host,0,0,0)
                self.g.gtk_box_pack_start(horizontal,box,1,1,0)
                markers,self.row_status[identity]=row_markers(self.g,item)
                if self.row_status[identity]:self.g.gtk_box_pack_start(horizontal,markers,0,0,0)
                else:self.g.gtk_widget_destroy(markers)
                if presentation['labels_list']:
                    labels=labels_by_id.get(identity,[])
                    if labels:self.g.gtk_widget_set_tooltip_text(box,('标签：'+' · '.join(labels)).encode())
                if item['id'] in self.inbox_sections:
                    self.row_groups[row]=self.inbox_sections[item['id']]['key']
                elif grouping in ('sender','domain'):
                    group=(item['sender'].rsplit('@',1)[-1] if grouping=='domain' else item['sender']) if grouping in ('sender','domain') else ('优先' if item['priority'] else CATEGORIES[item['category']])
                    self.row_groups[row]=group
                self.g.gtk_container_add(row,horizontal)
            else:
                self.g.gtk_container_add(row, box)
            self.g.gtk_container_add(self.widget('messages'), row)
            if identity in self.collapsed_rows:
                self.g.gtk_widget_set_no_show_all(horizontal,1)
                self.g.gtk_widget_hide(horizontal)
                self.g.gtk_list_box_row_set_selectable(row,0)
                self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(row),b'collapsed-row')
            elif identity == self.selected:
                selected_row = row
            self.g.gtk_widget_show_all(row)
            if index%8==7:
                self.rendering=False;yield
                self.rendering=True
        self.g.gtk_widget_show_all(self.widget('messages'))
        selected_row=next((row for row,identity in self.rows.items() if identity==self.selected),None)
        if selected_row:
            self.g.gtk_list_box_select_row(self.widget('messages'), selected_row)
        self.rendering = False
        self.g.label(self.widget('count'), f'{self.total} ' + ('项' if self.view == 'drafts' else '封邮件'))
        self.render_has_more=render_has_more
        self.g.gtk_widget_set_visible(self.widget('more'), int(render_has_more or (len(render_items) if self.focus_group else len(self.items)) < self.total))
        if self.selected and (selected_row or (not self.selected.startswith('job:') and self.current and self.selected==self.current.get('id'))):
            if not getattr(self,'pending_read_identity',''):self.read(self.selected)
        elif not getattr(self,'pending_read_identity',''):
            self.clear_reader()
        self.apply_layout()

    # ==========================================
    # Function: Apply the newest local mailbox snapshot with coherent native preferences.
    # Method: Keep database scans off GTK and record only bounded timing metadata.
    # ==========================================
    def apply_projection(self,projection):
        with self.service.store.preference_snapshot():self.refresh_snapshot(projection)

    # ==========================================
    # Function: Select a message using the native list selection signal.
    # Method: Ignore removed rows during refresh and read the stable associated ID.
    # ==========================================
    def row_selected(self, listbox, row, unused):
        if not self.rendering and row in self.rows:
            self.layout_override=None
            identity=self.rows[row]
            if identity.startswith('contact:'):self.read_chat(identity[8:])
            else:self.read(identity)

    # ==========================================
    # Function: Set availability of message-specific controls.
    # Method: Keep outbox/draft actions distinct from incoming-mail state mutations.
    # ==========================================
    def set_reader_state(self, mail, job=None):
        active=bool(mail or job)
        if getattr(self,'mail_person_header',None):self.g.gtk_widget_set_visible(self.mail_person_header['root'],bool(mail))
        toolbar=self.widget('reader_toolbar')
        if active:
            self.g.gtk_widget_set_no_show_all(toolbar,0);self.g.gtk_widget_show_all(toolbar);self.g.gtk_widget_set_no_show_all(toolbar,1)
        self.g.gtk_widget_set_visible(toolbar,active)
        self.g.gtk_widget_set_visible(self.widget('subject'),active)
        for name in ('seen','pin','priority','archive','done','move','snooze','more_actions'):self.g.gtk_widget_set_visible(self.widget(name),bool(mail))
        self.g.gtk_widget_set_visible(self.widget('trash'),bool(mail or job and job['state']=='draft'))
        for name in ('seen','pin','priority','archive','trash','done','move','snooze','more_actions','message_category','learn','apply_category','reply','reply_all','forward','export'):
            self.g.gtk_widget_set_sensitive(self.widget(name), int(mail))
        self.g.gtk_widget_set_visible(self.widget('edit_draft'), int(bool(job and job['state'] not in ('queued','sending'))))
        self.g.gtk_widget_set_sensitive(self.widget('reader_close'),bool(mail or job))
        self.g.gtk_widget_set_sensitive(self.widget('trash'),bool(mail or job and job['state']=='draft'))
        self.g.gtk_widget_set_visible(self.widget('delete_draft'),bool(job and job['state']=='draft'))
        for name in ('reply','reply_all','forward'):self.g.gtk_widget_hide(self.widget(name))
        self.g.gtk_widget_set_visible(self.widget('reader_actions'),bool(job))
        for key in ('cancel_job','reschedule_job','send_job_now'):self.g.gtk_widget_set_visible(self.widget(key),int(bool(job and job['state']=='queued')))

    # ==========================================
    # Function: Close the current reader without altering the message's mail state.
    # Method: Save any attached reply, clear selection and return single-pane layouts to the list.
    # ==========================================
    def close_mail(self):
        if getattr(self,'chat_source_return',None):self.chat_resume_original();return
        if not self.close_document():return
        self.thread_window_dismissed=self.selected
        self.close_thread_window()
        self.rendering=True;self.g.gtk_list_box_unselect_all(self.widget('messages'));self.rendering=False
        self.clear_reader();self.layout_override=False;self.apply_layout()

    # ==========================================
    # Function: Delete a selected local unsent draft through the mailbox action.
    # Method: Stop its live editor before deletion so autosave cannot resurrect the removed identity.
    # ==========================================
    def delete_selected_draft(self):
        if not self.selected.startswith('job:'):return
        identity=self.selected[4:];job=self.service.store.job(identity)
        if job['state']!='draft':raise ValueError('只能删除未发送草稿；请先撤销发送计划')
        if self.composer and not self.composer.closed and self.composer.identity==identity:
            if self.composer.busy:return
            self.composer.close();self.composer=None
        self.service.store.delete_draft(identity)
        self.selected='';self.current=None;self.refresh();self.message('草稿已删除')

    # ==========================================
    # Function: Reset stale message content and dynamic signal groups.
    # Method: Destroy old attachment/conversation widgets before clearing text.
    # ==========================================
    def clear_reader(self):
        if getattr(self,'reader_handoff',None):self.reader_handoff.close()
        if getattr(self,'selected_chat','') and not self.leave_chat():return
        if getattr(self,'local_loader',None):self.local_loader.cancel('read')
        self.pending_read_identity=''
        if self.document and self.document.origin_id:self.close_document()
        self.selected, self.current = '', None
        self.clear_conversation()
        self.g.disconnect('reader')
        for name in ('attachments','thread'):
            self.g.clear(self.widget(name))
        self.g.label(self.widget('subject'), '')
        self.g.label(self.widget('sender'), '选择一封邮件，或添加你的邮箱账户。')
        self.g.label(self.widget('reason'), '')
        self.g.label(self.widget('message_tags'),'')
        self.g.text(self.widget('body'), '', view=True)
        self.html_reader=getattr(self,'legacy_html_reader',None)
        self.g.gtk_widget_hide(self.widget('mail_footer'));self.g.gtk_widget_hide(self.widget('message_tags'))
        self.g.gtk_widget_hide(self.widget('sender_review'))
        self.set_reader_state(False)
        if self.contact_mode():self.show_chat_page()
        self.apply_layout()

    # ==========================================
    # Function: Select a message without decoding MIME or querying threads on GTK.
    # Method: Coalesce fast successive choices and apply only the latest prepared local snapshot.
    # ==========================================
    def read(self,identity):
        if self.closing:return
        if identity.startswith('contact:'):self.read_chat(identity[8:]);return
        context=getattr(self,'chat_source_return',None)
        if context and identity!=context['source'] and not self.chat_discard_return():return
        from .reader_handoff import navigation_handoff
        handoff=navigation_handoff(self)
        if handoff:
            if identity.startswith('job:'):handoff.close()
            elif identity!=self.selected:handoff.begin()
        if getattr(self,'selected_chat','') and not self.leave_chat():return
        if self.composer and self.composer.embedded and self.composer.busy and identity!=self.selected:return
        from .desktop_loading import LocalLoader
        if not getattr(self,'local_loader',None):self.local_loader=LocalLoader(self)
        if identity.startswith('job:'):
            self.local_loader.cancel('read');self.pending_read_identity=''
            with self.service.store.preference_snapshot():self.read_loaded(identity)
            return
        self.pending_read_identity=identity;requested=time.monotonic()
        # ==========================================
        # Function: Commit an immutable body snapshot to the current native card tree.
        # Method: Scope preferences once and retain the old view until the replacement is ready.
        # ==========================================
        def ready(prepared):
            self.pending_read_identity='';self.read_prepared=prepared;started=time.monotonic()
            try:
                with self.service.store.preference_snapshot():self.read_loaded(identity)
                self.last_read_timing={'query':prepared['prepare_seconds'],'render':time.monotonic()-started,'dispatch':time.monotonic()-requested}
            finally:self.read_prepared=None
        self.local_loader.request('read',lambda:self.local_loader.message(identity),ready)

    # ==========================================
    # Function: Show a full cached message or one durable outbox item.
    # Method: Load attachments lazily and build only native labels/buttons/text buffers.
    # ==========================================
    def read_loaded(self, identity):
        same_conversation=identity in getattr(self,'conversation_ids',[])
        if self.composer and self.composer.embedded and not getattr(self.composer,'detached',False) and identity!=self.selected and not same_conversation:
            if self.composer.busy:return
            self.composer.on_delete()
            if self.composer and not self.composer.closed:return
        changed=identity!=self.selected
        if changed:self.thread_window_dismissed=''
        if changed:
            if same_conversation:
                if self.document:self.document.close()
            elif not self.close_document():return
        self.selected = identity
        full_editor=bool(self.composer and not self.composer.closed and self.composer.embedded and not getattr(self.composer,'inline',False) and not getattr(self.composer,'detached',False))
        if not full_editor:self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'mail')
        self.reader_fade=0;self.g.gtk_widget_set_opacity(self.widget('reader_content'),1)
        self.g.disconnect('reader')
        for name in ('attachments','thread'):
            self.g.clear(self.widget(name))
        if identity.startswith('job:'):
            self.g.gtk_widget_hide(self.widget('mail_footer'));self.g.gtk_widget_hide(self.widget('message_tags'));self.g.gtk_widget_hide(self.widget('sender_review'))
            job = self.service.store.job(identity[4:])
            self.current = job
            self.g.label(self.widget('subject'), job['draft'].get('subject') or '(无主题)')
            self.g.label(self.widget('sender'), STATES[job['state']] + ' · 发往 ' + job['draft'].get('to',''))
            self.g.label(self.widget('reason'), '\n'.join(filter(None, [job['error'],job['copy_status'],('已收到 '+str(job['receipts'])+' 份阅读回执') if job.get('receipts') else '', '计划发送 ' + datetime.fromtimestamp(job['due']).strftime('%Y-%m-%d %H:%M') if job['state'] == 'queued' else ''])))
            self.g.text(self.widget('body'), job['draft'].get('body',''), view=True)
            self.clear_conversation()
            label=self.g.gtk_label_new((job['draft'].get('body','') or '(无正文)').encode());self.g.gtk_label_set_line_wrap(label,1)
            self.g.gtk_box_pack_start(self.widget('conversation_host'),label,0,1,0);self.g.gtk_widget_show_all(self.widget('conversation_host'))
            self.set_reader_state(False, job)
            self.apply_layout()
            return
        message = self.read_prepared['message'] if getattr(self,'read_prepared',None) else self.service.store.get(identity)
        if changed and not message['seen'] and self.service.store.preference('mark_read_on_open',True):
            if self.service.mark_opened(identity):
                message={**message,'seen':1}
                self.queue.put((lambda result:self.refresh(),None))
                self.background(self.service.flush_read_flags)
        self.current = message
        parsed = message['parsed']
        prepared=getattr(self,'read_prepared',None)
        if prepared and getattr(self,'mail_person_header',None):
            self.update_person_header(self.mail_person_header,prepared.get('person',{}),parsed.get('sender_name',''),message['account'])
            self.g.gtk_widget_show_all(self.mail_person_header['root'])
        review=message.get('sender_policy')=='new' and self.service.store.preference('gatekeeper_mode','off') in ('inThread','explicit')
        self.g.gtk_widget_set_visible(self.widget('sender_review'),review)
        self.g.label(self.widget('subject'), message['subject'])
        self.apply_avatar(self.widget('sender_avatar'),parsed['sender'],message['account'])
        self.g.label(self.widget('sender_avatar'),(parsed['sender_name'] or parsed['sender'])[:1].upper())
        show_avatar=self.service.store.preference('avatars_mode','everywhere') in ('everywhere','reader')
        self.g.gtk_widget_set_no_show_all(self.widget('sender_avatar'),not show_avatar)
        self.g.gtk_widget_set_visible(self.widget('sender_avatar'),show_avatar)
        tags=list(message['labels'])
        with self.service.store.db() as db:
            receipts=db.execute('SELECT count(*) FROM read_receipts r JOIN jobs j ON j.id=r.job WHERE j.account=? AND j.message_id=?',(message['account'],parsed['message_id'])).fetchone()[0]
        if receipts:tags.append(f'◉ 已收到 {receipts} 份阅读回执')
        if message['snoozed_until']>time.time():tags.append('稍后 '+datetime.fromtimestamp(message['snoozed_until']).strftime('%m-%d %H:%M'))
        if message['reminder']:tags.append('提醒 '+datetime.fromtimestamp(message['reminder']).strftime('%m-%d %H:%M'))
        if message['aside']:tags.append('暂存')
        if message['done']:tags.append('已完成')
        self.g.label(self.widget('message_tags'),'  ·  '.join(tags))
        self.g.gtk_widget_set_visible(self.widget('message_tags'),bool(tags))
        self.g.label(self.widget('sender'), f"{parsed['sender_name']} <{parsed['sender']}>\n发往 {parsed['recipients']} · {datetime.fromtimestamp(parsed['timestamp']).strftime('%Y-%m-%d %H:%M')}")
        # The hidden accessibility fallback needs text only; rich conversation leaves own HTML.
        self.g.text(self.widget('body'), parsed['body'] or '(没有可显示的文字正文)', view=True)
        self.mail_image_indices=set()
        self.g.label(self.widget('reason'), message['reason'])
        self.g.gtk_combo_box_set_active_id(self.widget('message_category'), message['category'].encode())
        self.g.gtk_widget_set_tooltip_text(self.widget('seen'), ('标为未读' if message['seen'] else '标为已读').encode())
        self.g.gtk_widget_set_tooltip_text(self.widget('pin'), ('取消置顶' if message['pinned'] else '置顶').encode())
        self.g.gtk_widget_set_tooltip_text(self.widget('priority'), ('取消优先' if message['priority'] else '☆ 优先').encode())
        archived=bool(message['archived']) or message['folder']==self.service.store.special_folder(message['account'],'archive')
        self.g.gtk_widget_set_tooltip_text(self.widget('archive'), ('移回收件箱' if archived else '归档').encode())
        from .ui_actions import state_action
        for name,icon,active in [('pin','spark-layout-pin',message['pinned']),('priority','spark-layout-priority',message.get('effective_priority',message['priority'])),('done','spark-layout-done',message['done']),('seen','spark-layout-seen',message['seen']),('archive','spark-layout-archive',archived),('snooze','spark-layout-snooze',message['snoozed_until']>time.time())]:
            title={'pin':'取消置顶' if active else '置顶','priority':'取消优先' if active else '优先','done':'取消完成' if active else '完成','seen':'标为未读' if active else '标为已读','archive':'移回收件箱' if active else '归档','snooze':'更改稍后时间' if active else '稍后'}[name]
            state_action(self.g,self.widget(name),title,icon,bool(active))
        attachments=parsed['attachments']
        self.g.label(self.widget('attachments_toggle'),f'▤ 附件 {len(attachments)} · {sum(a["size"] for a in attachments)/1024:.0f} KB',button=True)
        self.g.gtk_widget_set_visible(self.widget('attachments_toggle'),bool(attachments))
        for attachment in attachments:
            from .attachment_cards import card as attachment_card
            button=attachment_card(self.g,attachment,lambda item=attachment:(self.g.gtk_popover_popdown(self.widget('attachments_menu')),self.run_action(lambda:self.preview_attachment(identity,item))),'reader');self.g.gtk_container_add(self.widget('attachments'),button);self.g.gtk_widget_show_all(button)
        self.g.gtk_widget_hide(self.widget('thread_toggle'))
        self.g.gtk_widget_hide(self.widget('mail_footer'))
        self.render_conversation(identity)
        if changed:self.ensure_thread_window()
        self.set_reader_state(True)
        self.apply_layout()

    # ==========================================
    # Function: Create one dynamic native attachment/conversation action.
    # Method: Own callbacks in the reader signal group for deterministic cleanup.
    # ==========================================
    def dynamic_button(self, area, caption, callback):
        button = self.g.gtk_button_new_with_label(caption.encode())
        self.g.connect(button, 'clicked', lambda *unused:(self.g.gtk_popover_popdown(self.widget('attachments_menu' if area=='attachments' else 'thread_menu')),self.run_action(callback)), group='reader')
        label=self.g.gtk_bin_get_child(button)
        self.g.gtk_label_set_single_line_mode(label,1);self.g.gtk_label_set_ellipsize(label,3)
        self.g.gtk_label_set_max_width_chars(label,44)
        self.g.gtk_button_set_alignment(button,0,0.5)
        self.g.gtk_box_pack_start(self.widget(area), button, 0, 1, 0)
        self.g.gtk_widget_show_all(button)

    # ==========================================
    # Function: Apply an incoming-mail state update off the GTK thread.
    # Method: Wait for server read-state confirmation before reloading local state.
    # ==========================================
    def update(self, changes):
        if not self.selected or self.selected.startswith('job:'):
            return
        identity = self.selected
        self.background(lambda:self.service.update(identity, changes), lambda result:self.refresh())

    # ==========================================
    # Function: Toggle a message display/read flag.
    # Method: Derive the new boolean from the current durable message state.
    # ==========================================
    def toggle(self, flag):
        if self.current and not self.selected.startswith('job:'):
            if flag=='seen':self.quick_action(self.selected,'seen')
            else:self.update({flag:not bool(self.current[flag])})

    # ==========================================
    # Function: Correct a category and optionally learn the sender.
    # Method: Pass the native selector and checkbox state to the core use case.
    # ==========================================
    def apply_category(self):
        category = (self.g.gtk_combo_box_get_active_id(self.widget('message_category')) or b'').decode()
        self.update({'category':category, 'learn_sender':bool(self.g.gtk_toggle_button_get_active(self.widget('learn')))})

    # ==========================================
    # Function: Request account refresh from the existing background mail worker.
    # Method: Wake the worker without starting a browser or HTTP endpoint.
    # ==========================================
    def request_sync(self):
        if self.service:
            self.service.request_sync()
            self.message('已请求同步')

    # ==========================================
    # Function: Reapply independent classification rules.
    # Method: Run cached reclassification in the native background executor.
    # ==========================================
    def reclassify(self):
        if self.service:
            self.background(self.service.store.reclassify, lambda count:(self.refresh(),self.message(f'已重新归类 {count} 封邮件')))

    # ==========================================
    # Function: Open the graphical mailbox settings dialog.
    # Method: Reuse the profile's validated atomic configuration writer.
    # ==========================================
    def settings(self):
        from .desktop_settings import settings_dialog
        if self.service:
            settings_dialog(self,'accounts')

    # ==========================================
    # Function: Adopt newly saved accounts without restarting the desktop application.
    # Method: Swap the account map under the service lock on a background thread.
    # ==========================================
    def apply_accounts(self, accounts):
        # ==========================================
        # Function: Replace validated mailbox settings safely.
        # Method: Serialize replacement with remote synchronization and state writes.
        # ==========================================
        def apply():
            with self.service.lock:
                self.service.accounts = {a.id:a for a in accounts}
                self.service.status['accounts']={key:value for key,value in self.service.status['accounts'].items() if key in self.service.accounts}
            return True
        self.background(apply, lambda result:(self.fill_accounts(),self.request_sync(),self.message('账户已保存，可在客户端直接收发邮件')))

    # ==========================================
    # Function: Open or focus the native editor.
    # Method: Keep a single explicit draft identity per composer window.
    # ==========================================
    def open_composer(self, draft=None):
        from .desktop_forms import Composer
        if not self.service:
            return
        if self.composer and not self.composer.closed:
            if getattr(self.composer,'detached',False):self.g.gtk_window_present(self.composer.surface_window)
            elif self.composer.embedded:self.g.gtk_stack_set_visible_child_name(self.widget('reader_stack'),b'mail' if getattr(self.composer,'inline',False) else b'composer')
            else:self.g.gtk_window_present(self.composer.window)
            return
        if getattr(self,'selected_chat','') and not getattr(self,'chat_handoff',False) and not self.leave_chat():return
        self.composer = Composer(self, draft)
        self.layout_override=None;self.apply_layout()

    # ==========================================
    # Function: Reply using the RFC reference chain.
    # Method: Preserve account, recipient and thread headers in the new draft.
    # ==========================================
    def reply(self, identity=None):
        if getattr(self,'selected_chat','') and not identity:
            if self.chat_items:self.chat_reply(self.chat_items[-1])
            return
        if identity or (self.current and not self.selected.startswith('job:')):
            message=self.service.store.get(identity) if identity else self.current
            parsed=message['parsed']
            from .reply_options import reply_attachments
            attachments=reply_attachments(self,message)
            if attachments is None:return
            from .reply_history import from_message
            self.open_composer({'reply_history':from_message(message),'reply_source':message['id'],'attachments':attachments,'account':message['account'],'to':parsed['headers'].get('reply-to',parsed['sender']), 'subject':message['subject'] if message['subject'].lower().startswith('re:') else 'Re: ' + message['subject'], 'in_reply_to':parsed['message_id'],'references':' '.join(parsed['references'] + [parsed['message_id']])})

    # ==========================================
    # Function: Edit a saved local draft.
    # Method: Load the full job only after selection and preserve its stable identifier.
    # ==========================================
    def edit_draft(self):
        if self.current and self.selected.startswith('job:') and self.current['state'] not in ('queued','sending'):
            payload={**self.current['draft'],'account':self.current['account']}
            if self.current['state']=='draft':payload['id']=self.current['id']
            elif self.current['state'] in ('uncertain','partial'):
                self.message('原邮件可能已送达部分或全部收件人，请先核对已发送邮件；新草稿需再次明确发送')
            self.open_composer(payload)

    # ==========================================
    # Function: Cancel a queued item before it is claimed.
    # Method: Use the core's atomic queued-to-draft transition.
    # ==========================================
    def cancel_job(self):
        if self.selected.startswith('job:'):
            identity = self.selected[4:]
            self.background(lambda:self.service.store.cancel(identity), lambda result:self.refresh())

    # ==========================================
    # Function: Modify or release the selected send-later job with explicit native actions.
    # Method: Use the serialized service compare-and-update so sent jobs cannot be replayed.
    # ==========================================
    def change_job_time(self,now=False):
        if not self.selected.startswith('job:'):return
        identity=self.selected[4:];job=self.service.store.job(identity)
        if now:due=time.time()
        else:
            from .scheduling import choose_schedule,schedule_timestamp
            value=choose_schedule(self,'修改发送时间',datetime.fromtimestamp(job['due']).isoformat(timespec='minutes'),clear=False)
            if not value:return
            due=schedule_timestamp(value)
        self.background(lambda:self.service.reschedule(identity,due),lambda result:(self.refresh(),self.message('发送计划已更新')))

    # ==========================================
    # Function: Import an EML file through the native filesystem dialog.
    # Method: Retain exact MIME bytes under an idempotent local import identity.
    # ==========================================
    def import_mail(self):
        if not self.service:
            return
        filename = self.g.choose(self.window, '导入 EML 邮件')
        if not filename:
            return
        folder=self.folder_path if self.folder_account==LOCAL_ACCOUNT and self.folder_path else 'INBOX'
        # ==========================================
        # Function: Reveal an imported local message after durable storage succeeds.
        # Method: Switch to its local folder so remote account filters cannot hide it.
        # ==========================================
        def imported(identity):
            if self.profile.demo:self.refresh()
            else:self.open_folder(LOCAL_ACCOUNT,folder)
            self.read(identity)
            self.message('邮件已导入本地文件夹，不会上传到邮箱服务器')
        self.background(lambda:self.service.import_eml(filename,folder),imported)

    # ==========================================
    # Function: Export the selected message through a native save dialog.
    # Method: Write original bytes only to a user-confirmed destination.
    # ==========================================
    def export_mail(self):
        if self.current and not self.selected.startswith('job:'):
            destination = self.g.choose(self.window, '导出 EML 邮件', 'message.eml')
            if destination:
                raw = self.service.store.get(self.selected, raw=True)['raw']
                destination.write_bytes(raw)
                self.message('邮件已导出')

    # ==========================================
    # Function: Save a selected MIME attachment without rendering it.
    # Method: Reparse the cached MIME and use a native destination chooser.
    # ==========================================
    def save_attachment(self, identity, attachment):
        name = Path(attachment['name'].replace('\x00','')).name or 'attachment'
        destination = self.g.choose(self.window, '保存附件', name)
        if destination:
            raw = self.service.store.get(identity, raw=True)['raw']
            part = list(BytesParser(policy=policy.default).parsebytes(raw).walk())[attachment['index']]
            destination.write_bytes(attachment_content(part))
            self.message('附件已保存')

    # ==========================================
    # Function: Open a separate demo profile from the desktop.
    # Method: Spawn the same native executable with its demo flag.
    # ==========================================
    def open_demo(self):
        executable = os.environ.get('TELEMAIL_LAUNCHER')
        if executable:
            subprocess.Popen([executable,'--demo'], start_new_session=True)
        else:
            root = str(Path(__file__).resolve().parent.parent)
            subprocess.Popen([sys.executable,'-I','-c','import sys;sys.path.insert(0,sys.argv.pop(1));from maildesk.desktop import main;raise SystemExit(main())',root,'--demo'], start_new_session=True)

    # ==========================================
    # Function: Register a relocatable application in the user's desktop menu.
    # Method: Copy only the Linux application payload and write a standard desktop entry.
    # ==========================================
    def install(self):
        from .desktop_install import install_user
        executable = os.environ.get('TELEMAIL_LAUNCHER')
        if not executable:
            self.message('请使用发行目录中的 TeleMail 可执行程序安装桌面入口')
            return
        self.background(lambda:install_user(Path(executable).resolve().parent), lambda result:self.message('已添加到应用菜单：TeleMail。以后可直接点击图标启动。'))

    # ==========================================
    # Function: Stage one migration only when mailbox shutdown is accepted.
    # Method: Delegate pending-plan ownership and immediate refusal cleanup to the storage runtime.
    # ==========================================
    def request_storage_migration(self,plan):
        from .storage_runtime import request_storage_migration
        return request_storage_migration(self,plan)

    # ==========================================
    # Function: Close native windows and request process termination.
    # Method: Keep service shutdown in the outer application lifecycle.
    # ==========================================
    def on_delete(self, *unused,force=False):
        if self.closing:return True
        self.cancel_folder_edit()
        if getattr(self,'chat_composer',None) and not self.chat_composer.autosave(force=True):return True
        if self.composer and not self.composer.closed:
            if self.composer.busy:
                self.message('正在保存邮件，请稍后退出');return True
            if self.composer.autosave(force=True) is False:return True
            self.composer.close()
        if not force and self.service and self.service.store.preference('close_to_tray',False) and self.tray_available():
            self.g.gtk_widget_hide(self.window);return True
        if getattr(self,'chat_root',None):
            self.leave_chat();self.g.disconnect('chat-static')
        self.closing = True
        if getattr(self,"reader_handoff",None):self.reader_handoff.close()
        if getattr(self,'workspace_geometry',None):self.workspace_geometry.close()
        self.g.surfaces.shutdown()
        if getattr(self,'folder_capture',None):
            self.g.disconnect('folder-capture');self.g.g_object_unref(self.folder_capture);self.folder_capture=None
        self.g.g_application_hold(self.application)
        readers=[reader for card in getattr(self,'conversation_cards',{}).values() for reader in card.get('body_readers',[])+[item for quote in card.get('quote_cards',[]) for item in quote.get('readers',[])] ]
        readers.extend(getattr(self,'chat_retired_readers',[]))
        readers.append(getattr(self,'legacy_html_reader',None))
        readers.extend(getattr(self,'reader_idle',[]))
        if self.document:readers.append(self.document.engine)
        self.shutdown_readers=list({reader.widget:reader for reader in readers if reader and hasattr(reader,'begin_shutdown')}.values())
        for reader in self.shutdown_readers:reader.begin_shutdown()
        self.close_general(release_readers=False)
        self.g.gtk_widget_hide(self.window)
        if getattr(self,'thread_window',None):self.g.gtk_widget_hide(self.thread_window)
        self.reader_shutdown_phase='views';self.reader_termination_requested=False;self.reader_process_seen={}
        from .reader_shutdown import ReaderDrain
        self.reader_drain=ReaderDrain(time.monotonic())
        self.reader_drain_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.drain_readers)
        self.reader_drain_timer=self.g.g_timeout_add(50,C.cast(self.reader_drain_callback,C.c_void_p),None)
        return True

    # ==========================================
    # Function: Keep the application's session bus alive until owned renderers have drained.
    # Method: Poll only this process's descendants from the GTK main loop, then release the bounded hold.
    # ==========================================
    def drain_readers(self,unused):
        from .reader_shutdown import owned_renderers,ReaderDrain
        now=time.monotonic()
        if self.reader_shutdown_phase=='views':
            active=owned_renderers(web_only=True)
            for pid in active:self.reader_process_seen.setdefault(pid,now)
            bootstrapping=any(now-self.reader_process_seen[pid]<.6 for pid in active)
            if active and not bootstrapping and now-self.reader_drain.started>=.6 and not self.reader_termination_requested:
                self.reader_termination_requested=True
                for reader in self.shutdown_readers:reader.finish_shutdown()
            if not self.reader_drain.ready(now,active) or (self.shutdown_readers and now-self.reader_drain.started<.6):return 1
            if self.reader_drain.timed_out:self.storage_shutdown_error='阅读器未能完全关闭，未开始迁移。'
            if os.name=='nt' and getattr(self,'windows_webview_bridge',None):self.close_general()
            else:self.release_reader_widgets()
            self.shutdown_readers=[];self.reader_shutdown_phase='context';self.reader_drain=ReaderDrain(now)
            return 1
        if os.name=='nt' and getattr(self,'windows_webview_bridge',None):
            bridge=self.windows_webview_bridge;bridge.md_webview_shutdown()
            pending=bridge.md_webview_metrics(1)+bridge.md_webview_metrics(2)
            active=bridge.md_webview_metrics(0)
            drained=bool(bridge.md_webview_drained())
            deadline=10
            if (pending or active or not drained) and now-self.reader_drain.started<deadline:return 1
            if pending or active or not drained:
                self.storage_shutdown_error='Windows 阅读器进程尚未完全关闭，未开始迁移。'
                print('TeleMail: Windows 阅读器在关闭期限内未完全结束',file=sys.stderr)
            self.release_reader_widgets()
            bridge.md_webview_finish()
        elif not self.reader_drain.ready(now,owned_renderers()):return 1
        elif self.reader_drain.timed_out:self.storage_shutdown_error='阅读器进程仍在结束，未开始迁移。'
        self.readers_drained=True
        self.reader_drain_timer=0
        self.g.g_application_release(self.application)
        self.g.g_application_quit(self.application)
        return 0

    # ==========================================
    # Function: Destroy reader surfaces only after their platform's native cleanup phase.
    # Method: Preserve Windows parent HWNDs until owned callbacks close, retaining the existing Linux order.
    # ==========================================
    def release_reader_widgets(self):
        if getattr(self,'reader_surfaces_released',False):return
        self.reader_surfaces_released=True
        self.clear_conversation();self.close_document();self.close_thread_window()
        if getattr(self,'reader_parking',None):
            self.g.gtk_widget_destroy(self.reader_parking);self.g.g_object_unref(self.reader_parking);self.reader_parking=None
        if getattr(self,'chat_reader_parking',None):
            self.g.gtk_widget_destroy(self.chat_reader_parking);self.g.g_object_unref(self.chat_reader_parking);self.chat_reader_parking=None
        self.reader_idle=[];self.chat_retired_readers=[]
        self.close_general();self.g.disconnect('list-headers');self.g.gtk_widget_destroy(self.window)

    # ==========================================
    # Function: Run GTK and release workers, storage lock and native references.
    # Method: Own all resources in one process lifetime with no child web server.
    # ==========================================
    def run(self):
        self.windows_instance=None;restart=False
        try:
            primary=True
            if os.name=='nt':
                from .windows_integration import WindowsInstance
                self.windows_instance=WindowsInstance(self)
                primary=self.windows_instance.primary
            if primary:
                arguments=[b'TeleMail']+[uri.encode() for uri in getattr(self.options,'uris',[])]
                encoded=(C.c_char_p*(len(arguments)+1))(*arguments,None)
                self.g.g_application_run(self.application,len(arguments),C.cast(encoded,C.c_void_p))
        finally:
            self.closing=True
            plan=self.pending_storage_migration;self.pending_storage_migration=None
            try:
                if self.timer:self.g.g_source_remove(self.timer)
                self.cancel_list_render()
                if getattr(self,'local_loader',None):self.local_loader.close()
                if self.service:self.service.close()
                self.executor.shutdown(wait=True,cancel_futures=True)
                if plan:
                    from .storage_runtime import StorageProgress
                    error=self.storage_shutdown_error
                    if not getattr(self,'readers_drained',False):error=error or '阅读器尚未完全关闭，未开始迁移。'
                    worker=getattr(self.service,'worker',None)
                    if worker and worker.is_alive():error='邮件后台服务未能结束，未开始迁移。'
                    progress=StorageProgress(self,plan,error or None)
                    restart=progress.run()
                    self.migrated_storage=progress.result
                    if progress.result is None:self.exit_code=1
            finally:
                if self.windows_instance:self.windows_instance.close();self.windows_instance=None
                if self.lock_file:self.lock_file.close();self.lock_file=None
                self.g.close_icons()
                if self.builder:self.g.g_object_unref(self.builder);self.builder=None
                self.g.g_object_unref(self.application);self.application=None
        if restart:
            from .storage_runtime import restart_desktop
            return restart_desktop(self)
        return self.exit_code

# ==========================================
# Function: Launch the native desktop client.
# Method: Validate the platform and route normal execution directly to GTK.
# ==========================================
def main(argv=None):
    system='Windows 11 x64' if sys.platform=='win32' else 'Linux amd64'
    parser = argparse.ArgumentParser(description='TeleMail '+system+' 桌面客户端')
    parser.add_argument('--version', action='version', version=f'TeleMail {__version__} · {system}')
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--background',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('uris',nargs='*',help='mailto: 链接（仅打开未发送草稿）')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--data', type=Path)
    parser.add_argument('--install-user', action='store_true')
    parser.add_argument('--self-test', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--report', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--screenshot', type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if sys.platform not in ('linux','win32') or platform.machine().lower() not in ('x86_64','amd64'):
        parser.error('此版本支持 Linux amd64 或 Windows 11 x64')
    from .desktop_preferences import parse_mailto
    try:
        for uri in options.uris:parse_mailto(uri)
    except ValueError as error:parser.error(str(error))
    if options.self_test and not options.demo:
        parser.error('原生界面自测仅允许 --demo，避免操作真实邮箱')
    if options.install_user:
        from .desktop_install import install_user
        executable = os.environ.get('TELEMAIL_LAUNCHER')
        if not executable:
            parser.error('请使用发行目录中的 TeleMail 可执行程序')
        print(install_user(Path(executable).resolve().parent))
        return 0
    os.umask(0o077)
    try:
        from .storage_paths import StorageLocations,configure_cache
        configure_cache(StorageLocations(options.demo,options.config,options.data))
        from .reader_runtime import prepare_readers
        prepare_readers()
        return DesktopApp(options).run()
    except (OSError, RuntimeError, ValueError) as error:
        print(f'TeleMail: {error}', file=sys.stderr)
        from .storage_runtime import show_startup_error
        show_startup_error(error)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
