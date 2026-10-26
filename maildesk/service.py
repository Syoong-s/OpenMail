"""Application service coordinating protocol adapters, cache and background work."""
import base64
import binascii
import threading
import time
from email.utils import make_msgid
from pathlib import Path
import json
from contextlib import nullcontext
from .operation_gate import OperationGate

from . import transport
from .mime import MAX_MESSAGE_BYTES, compose
from .store import Store
from .classifier import CATEGORIES
from .organization import OrganizationService
from .local_mail import LOCAL_ACCOUNT,ensure_local_folders,is_local_message,import_local_eml

# ==========================================
# Function: Expose mailbox use cases independently of the UI.
# Method: Serialize synchronization/remote flags and drain persistent delivery jobs.
# ==========================================
class MailService(OrganizationService):
    # ==========================================
    # Function: Initialize accounts, data storage and worker state.
    # Method: Keep credentials in Account environment references and status in memory.
    # ==========================================
    def __init__(self, data_dir, accounts=(), interval=60, demo=False):
        self.data_dir = Path(data_dir)
        self.accounts = {a.id: a for a in accounts}
        rule_path = self.data_dir / 'rules.json'
        rules = json.loads(rule_path.read_text()) if rule_path.exists() else []
        self.store = Store(self.data_dir / 'mail.sqlite3', rules)
        self.interval = max(15,self.store.preference('sync_interval',interval))
        self.demo = demo
        from .participant_identity import own_identities
        self.store.own_addresses=lambda:own_identities(self.accounts.values(),('demo@example.com',) if self.demo else ())
        if not demo:ensure_local_folders(self.store)
        self.stop_event = threading.Event()
        self.sync_event = threading.Event()
        self.lock = OperationGate()
        self._read_flush_lock=threading.Lock()
        self._filter_run_lock=threading.Lock();self.filter_cancel_event=threading.Event()
        self.status = {'syncing': False, 'last_sync': None, 'accounts': {}, 'demo': demo}
        self.worker = None

    # ==========================================
    # Function: Start background synchronization and delivery.
    # Method: Use a daemon thread with cancellable waits.
    # ==========================================
    def start(self):
        self.worker = threading.Thread(target=self.run, name='mail-worker', daemon=True)
        self.worker.start()

    # ==========================================
    # Function: Request another mailbox refresh.
    # Method: Wake the single worker without spawning competing sync operations.
    # ==========================================
    def request_sync(self):
        self.sync_event.set()

    # ==========================================
    # Function: Stop background polling.
    # Method: Signal the event and join within the network timeout allowance.
    # ==========================================
    def close(self):
        self.stop_event.set()
        self.sync_event.set()
        if self.worker:
            self.worker.join(timeout=30)

    # ==========================================
    # Function: Poll mail and submit due jobs while the app runs.
    # Method: A single loop isolates failures per account and persists delivery states.
    # ==========================================
    def run(self):
        next_sync = 0
        while not self.stop_event.is_set():
            if time.monotonic() >= next_sync or self.sync_event.is_set():
                self.sync_event.clear()
                self.sync()
                next_sync = time.monotonic() + self.interval
            try:
                while not self.stop_event.is_set() and self.process_one():
                    pass
            except Exception:
                self.status['worker_error'] = '本地发件队列处理失败，请检查磁盘和数据目录；处理中任务不会自动重发'
            self.sync_event.wait(1)

    # ==========================================
    # Function: Sync configured mailboxes, preserving status for each account.
    # Method: Preserve provider/cache serialization while yielding at bounded checkpoints to waiting interactive operations.
    # ==========================================
    def sync(self):
        if self.demo:
            self.status['last_sync'] = time.time()
            return
        with self.lock.background():
            self.status['syncing'] = True
            interrupted=False
            try:
                self.flush_read_flags(locked=True,should_yield=self.sync_should_yield)
                for account in tuple(self.accounts.values()):
                    if self.sync_should_yield():interrupted=True;break
                    if account.id in self.store.preference('paused_accounts',[]):continue
                    try:
                        result = transport.sync_account(account, self.store,should_yield=self.sync_should_yield)
                        self.status['accounts'][account.id] = {'ok': True, **result}
                        if result.get('filters',{}).get('pending'):self.sync_event.set()
                        if result.get('interrupted'):interrupted=True;break
                    except Exception:
                        self.status['accounts'][account.id] = {'ok': False, 'error': '同步失败，请检查网络、TLS、服务器设置或在账号设置中更新登录'}
                from .desktop_preferences import cached_attachments
                try:
                    if not interrupted:cached_attachments(self.store,should_yield=self.sync_should_yield)
                except (OSError,ValueError):self.status['attachment_cache_error']='附件缓存失败，请检查本机存储；原始邮件保留'
                if not interrupted:self.status['last_sync'] = time.time()
            finally:
                self.status['syncing'] = False
                if interrupted and not self.stop_event.is_set():self.sync_event.set()

    # ==========================================
    # Function: Stop background protocol work before a queued user command or shutdown waits for the whole mailbox.
    # Method: Combine cooperative gate priority with the existing stop event without racing provider operations.
    # ==========================================
    def sync_should_yield(self):
        return self.stop_event.is_set() or self.lock.interrupted()

    # ==========================================
    # Function: Mark an explicitly opened message read before network round trips.
    # Method: Save locally and queue provider synchronization without blocking GTK rendering.
    # ==========================================
    def mark_opened(self,identity):
        message=self.store.get(identity)
        remote=not self.demo and not is_local_message(message)
        return self.store.mark_opened(identity,remote=remote)

    # ==========================================
    # Function: Retry durable automatic read flags while preserving offline local read state.
    # Method: Serialize provider access and acknowledge exact generations only after IMAP succeeds.
    # ==========================================
    def flush_read_flags(self,locked=False,should_yield=None):
        if not locked:
            if not self._read_flush_lock.acquire(blocking=False):return len(self.store.pending_read_flags())
            try:
                with self.lock:return self.flush_read_flags(locked=True,should_yield=should_yield)
            finally:self._read_flush_lock.release()
        from collections import defaultdict
        with self.store.db() as db:
            pending=[dict(row) for row in db.execute('''SELECT p.message,p.seen,p.generation,m.id,m.account,m.folder,m.validity,m.uid,m.remote_gone
                FROM pending_read_flags p LEFT JOIN messages m ON m.id=p.message''')]
        groups=defaultdict(list);acknowledged=[];paused=self.store.preference('paused_accounts',[])
        for row in pending:
            if row['id'] is None or self.demo or is_local_message(row):acknowledged.append(row);continue
            if row['account'] not in self.accounts or row['remote_gone'] or row['account'] in paused:continue
            groups[(row['account'],row['folder'],row['validity'],bool(row['seen']))].append(row)
        should_yield=should_yield or self.sync_should_yield
        for (account,folder,validity,seen),rows in groups.items():
            if should_yield():break
            for start in range(0,len(rows),100):
                if should_yield():break
                page=rows[start:start+100]
                try:
                    if len(page)==1:transport.set_seen(self.accounts[account],page[0],seen)
                    else:transport.set_seen_many(self.accounts[account],page,seen)
                except Exception:break
                acknowledged.extend(page)
        with self.store.db() as db:
            db.executemany('DELETE FROM pending_read_flags WHERE message=? AND generation=?',[(row['message'],row['generation']) for row in acknowledged])
        pending=len(self.store.pending_read_flags());self.status['read_flags_pending']=pending
        if pending and should_yield() and not self.stop_event.is_set():self.sync_event.set()
        return pending

    # ==========================================
    # Function: Change mailbox state with account and UID safety checks.
    # Method: Commit local read state only after a successful remote flag update.
    # ==========================================
    def update(self, identity, changes):
        if not changes or set(changes) - {'seen', 'pinned', 'priority', 'archived', 'category', 'learn_sender'}:
            raise ValueError('无效邮件操作')
        if 'category' in changes and changes['category'] not in CATEGORIES:
            raise ValueError('分类无效')
        if any(key in changes and not isinstance(changes[key], bool) for key in ('seen','pinned','priority','archived','learn_sender')):
            raise ValueError('状态值必须为布尔值')
        with (self.lock if {'seen','pinned'} & changes.keys() else nullcontext()):
            message = self.store.get(identity)
            if ('seen' in changes or 'pinned' in changes) and not self.demo and not is_local_message(message):
                if message['account'] not in self.accounts or message['remote_gone']:
                    raise ValueError('邮件无法对应到当前账户，请先同步')
                for key,flag in (('seen','\\Seen'),('pinned','\\Flagged')):
                    if key in changes:
                        transport.set_seen(self.accounts[message['account']],message,changes[key],flag)
            return self.store.update(identity, changes)

    # ==========================================
    # Function: Save or enqueue a composed message.
    # Method: Validate MIME before persisting; preserve explicit user send intent.
    # ==========================================
    def compose(self, payload, send=False):
        account_id = payload.get('account', '')
        if self.demo and send:
            raise ValueError('演示模式不能向外发送邮件；请使用真实账户配置启动')
        if account_id==LOCAL_ACCOUNT and send:
            raise ValueError('本地草稿不能发送，请先选择已配置的邮箱账户')
        if account_id not in self.accounts and not (account_id==LOCAL_ACCOUNT and not self.demo) and not (self.demo and account_id == 'demo'):
            raise ValueError('请先选择有效账户')
        draft = {key: payload.get(key, '') for key in ('to', 'cc', 'bcc', 'subject', 'body', 'html', 'in_reply_to', 'references')}
        for value in draft.values():
            if not isinstance(value, str):
                raise ValueError('邮件字段必须为文字')
        for key in ('reply_source','scheduled_at','chat_key','chat_route'):
            if key in payload:
                if not isinstance(payload[key],str):raise ValueError('编辑器元数据无效')
                draft[key]=payload[key]
        if 'reply_history' in payload:
            from .reply_history import validated
            draft['reply_history']=validated(payload['reply_history'])
        if 'editor_baseline' in payload:
            baseline=payload['editor_baseline']
            if not isinstance(baseline,dict) or set(baseline)-{'to','cc','bcc','subject','body'} or any(not isinstance(value,str) for value in baseline.values()):raise ValueError('草稿默认内容标记无效')
            draft['editor_baseline']=dict(baseline)
        reminder=float(payload.get('remind_at') or 0)
        if reminder and (not 0<=reminder<=time.time()+366*86400 or (send and reminder<=time.time())):raise ValueError('提醒时间必须在未来一年内')
        draft['remind_at']=reminder
        draft['done_after_send']=bool(payload.get('done_after_send',self.store.preference('done_after_reply',False)))
        draft['request_receipt']=bool(payload.get('request_receipt',self.store.preference('request_receipt',False)))
        attachments = []
        stored = payload.get('attachments', [])
        if not isinstance(stored, list) or len(stored) > 20:
            raise ValueError('每封邮件最多 20 个附件')
        for item in stored:
            if not isinstance(item.get('name'), str) or not isinstance(item.get('base64'), str):
                raise ValueError('附件格式无效')
            try:
                data = base64.b64decode(item['base64'], validate=True)
            except (ValueError, binascii.Error):
                raise ValueError('附件编码无效') from None
            attachments.append({'name': Path(item['name']).name, 'data': data})
        due = float(payload.get('due') or time.time())
        if not 0 <= due <= time.time() + 366 * 86400:
            raise ValueError('定时发送日期无效，最多提前一年')
        if send and reminder and reminder<=due:raise ValueError('未回复提醒时间应晚于发送时间')
        message, targets = (None, None)
        if send:
            from email.utils import formataddr
            account=self.accounts[account_id]
            sender=formataddr((account.display_name,account.email)) if account.display_name else account.email
            from .composer_options import outgoing_options
            prepared=outgoing_options(self.store,account,draft)
            message, targets = compose(sender, {**prepared, 'attachments': attachments}, make_msgid())
        if sum(len(a['data']) for a in attachments) > MAX_MESSAGE_BYTES:
            raise ValueError('附件过大')
        identity = self.store.save_draft(account_id, {**draft, 'attachments': stored}, payload.get('id'))
        if send:
            self.store.enqueue(identity, message.as_bytes(), targets, str(message['Message-ID']), due)
            self.store.set_preference('last_from_account',account_id)
        return {'id': identity, 'state': 'queued' if send else 'draft'}

    # ==========================================
    # Function: Deliver one claimed outbox item.
    # Method: Distinguish rejection, uncertain delivery, partial acceptance and sent-copy errors.
    # ==========================================
    def process_one(self):
        if self.demo:
            return False
        job = self.store.claim()
        if job is None:
            return False
        account = self.accounts.get(job['account'])
        if account is None:
            self.store.finish(job['id'], 'failed', '账户不在当前配置中，邮件未投递')
            return True
        try:
            refused = transport.deliver(account, job['raw'], json.loads(job['envelope']))
        except transport.DeliveryError as error:
            self.store.finish(job['id'], 'uncertain' if error.uncertain else 'failed', str(error))
            return True
        except Exception:
            self.store.finish(job['id'], 'uncertain', '发送结果待确认，请核对服务商已发送邮件')
            return True
        # Record SMTP acceptance before auxiliary cache/APPEND work, which cannot resend.
        state = 'partial' if refused else 'sent'
        error = '部分收件人被拒绝；其余已接受。请核对收件人后另建邮件' if refused else ''
        self.store.finish(job['id'], state, error, '保存副本中')
        try:
            sent_id=self.store.ingest(account.id, '@sent', 'local', job['id'], job['raw'], seen=True)
            draft=json.loads(job['draft'])
            if draft.get('remind_at'):self.store.organize(sent_id,reminder=max(draft['remind_at'],time.time()+1))
            source=draft.get('reply_source')
            if state=='sent' and source and draft.get('done_after_send'):
                original=self.store.get(source)
                if original['account']==account.id:
                    members=self.store.thread(source)
                    with self.store.db() as db:
                        db.executemany('UPDATE messages SET done=1 WHERE account=? AND message_id=?',[(account.id,row['message_id']) for row in members])
            copy_status = transport.append_sent(account, job['raw'])
        except Exception:
            copy_status = '邮件已投递，但副本保存失败；请核对服务商已发送文件夹'
        self.store.finish(job['id'], state, error, copy_status)
        return True

    # ==========================================
    # Function: Reschedule or release one queued message without changing its MIME identity.
    # Method: Serialize against claim/delivery and update only jobs still in queued state.
    # ==========================================
    def reschedule(self, identity, due):
        with self.lock:self.store.reschedule(identity,due)
        self.request_sync()

    # ==========================================
    # Function: Import EML without requiring an IMAP/SMTP account.
    # Method: Serialize a bounded local file import with folder operations; never upload it.
    # ==========================================
    def import_eml(self, filename, folder='INBOX'):
        with self.lock:
            return import_local_eml(self.store,filename,folder,self.demo)

    # ==========================================
    # Function: Explicitly clean obsolete cloud mail cache and unreferenced nonstarred contacts.
    # Method: Delegate to account-isolated read-only verification under the existing worker lock.
    # ==========================================
    def clean_cache(self):
        from .cache_maintenance import clean_cache
        return clean_cache(self)

    # ==========================================
    # Function: Restrict filtering to configured accounts and the application's explicit local/demo mailbox.
    # Method: Return stable account IDs without treating stale cached removed-account folders as active credentials.
    # ==========================================
    def filter_accounts(self):
        return list(dict.fromkeys([*self.accounts,LOCAL_ACCOUNT,*(['demo'] if self.demo else [])]))

    # ==========================================
    # Function: Save a native editor's validated account-relative filter without running it on old mail.
    # Method: Validate configured scope and currently selectable destinations before a single versioned local rule commit.
    # ==========================================
    def save_filter(self,value):
        from .filter_rules import validate,save
        rule=validate(value);accounts=self.filter_accounts();available={(row['account'],row['folder']) for row in self.store.list_folders() if row['selectable']}
        if rule['account'] and rule['account'] not in accounts:raise ValueError('过滤器账号已移除')
        if any(account not in accounts or (account,path) not in available for account,path in rule['destinations'].items()):raise ValueError('请选择当前账号中存在且可选择的目标文件夹')
        return save(self.store,rule)

    # ==========================================
    # Function: Preview ordered rules over all cached mail or an explicit account/folder scope.
    # Method: Reuse exactly the automatic matcher while deferring every provider mutation until manual execution.
    # ==========================================
    def preview_filters(self,account='',folder='',subfolders=False,rule_id=''):
        from .filter_runner import preview
        return preview(self.store,self.filter_accounts(),account,folder,subfolders,rule_id)

    # ==========================================
    # Function: Apply an explicit reviewed manual snapshot to cached historical or new sources.
    # Method: Reuse durable move checks and background-priority turns so ordinary user operations can interrupt between messages.
    # ==========================================
    def run_filter_plan(self,plan):
        from .filter_runner import manual
        return manual(self,plan)

    # ==========================================
    # Function: Learn similarity only when the user explicitly requests target-folder examples.
    # Method: Train an account-isolated bounded model without sending messages or features to an external service.
    # ==========================================
    def train_filter(self,identity,account):
        from .filter_rules import rules
        from .filter_smart import train
        rule=next((rule for rule in rules(self.store) if rule['id']==identity),None)
        if rule is None or account not in self.filter_accounts():raise ValueError('请选择现有过滤器和账号')
        return train(self.store,rule,account)
