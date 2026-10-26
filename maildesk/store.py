"""Transactional SQLite cache, persistent drafts/outbox, and sender corrections."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import threading
import uuid

from .classifier import CATEGORIES, classify
from .mime import parse_message
from .mailbox_store import OrganizationStore
from .search import search_terms

SENDER_POLICY_SQL="coalesce((SELECT policy FROM sender_policy p WHERE p.account=messages.account AND p.sender=messages.sender),(SELECT policy FROM sender_policy p WHERE p.account=messages.account AND p.sender='@'||substr(messages.sender,instr(messages.sender,'@')+1)),'new')"
EFFECTIVE_PRIORITY_SQL="(priority=1 OR coalesce((SELECT policy FROM sender_policy p WHERE p.account=messages.account AND p.sender=messages.sender),(SELECT policy FROM sender_policy p WHERE p.account=messages.account AND p.sender='@'||substr(messages.sender,instr(messages.sender,'@')+1)),'new')='priority' OR EXISTS(SELECT 1 FROM priority_senders ps WHERE ps.account=messages.account AND (ps.sender=messages.sender OR ps.sender='@'||substr(messages.sender,instr(messages.sender,'@')+1))))"

# ==========================================
# Function: Persist mailbox data and all local user state.
# Method: Short-lived WAL connections and parameterized SQL transactions.
# ==========================================
class Store(OrganizationStore):
    # ==========================================
    # Function: Create the local database and recover interrupted deliveries.
    # Method: Set private directory permissions and migrate the initial schema.
    # ==========================================
    def __init__(self, path, rules=()):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.rules = rules
        self._preference_scope = threading.local()
        self._transaction_scope = threading.local()
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, folder TEXT NOT NULL,
                    validity TEXT NOT NULL, uid TEXT NOT NULL, message_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL,
                    body TEXT NOT NULL, timestamp REAL NOT NULL, category TEXT NOT NULL,
                    reason TEXT NOT NULL, parsed TEXT NOT NULL, raw BLOB NOT NULL,
                    seen INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
                    override TEXT, remote_gone INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(account, folder, validity, uid));
                CREATE INDEX IF NOT EXISTS message_time ON messages(timestamp DESC);
                CREATE INDEX IF NOT EXISTS message_thread ON messages(account, thread_id);
                CREATE TABLE IF NOT EXISTS pending_read_flags (
                    message TEXT PRIMARY KEY, seen INTEGER NOT NULL, generation TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sender_rules (
                    account TEXT NOT NULL, sender TEXT NOT NULL, category TEXT NOT NULL,
                    PRIMARY KEY(account, sender));
                CREATE TABLE IF NOT EXISTS folders (
                    account TEXT NOT NULL, folder TEXT NOT NULL, validity TEXT NOT NULL,
                    PRIMARY KEY(account, folder));
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, draft TEXT NOT NULL,
                    raw BLOB, envelope TEXT, message_id TEXT, state TEXT NOT NULL,
                    due REAL NOT NULL, error TEXT NOT NULL DEFAULT '',
                    copy_status TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
            ''')
            self.migrate_organization(db)
            from .address_book import initialize as initialize_address_book
            initialize_address_book(db)
            from .contact_conversations import ContactConversations
            # Projection schema is additive; no cached bodies are scanned here.
            projection=ContactConversations(self,[])
            projection.initialize_schema(db)
            from .navigation_index import initialize as initialize_navigation
            initialize_navigation(db)
            from .thread_graph import initialize_graph
            initialize_graph(db)
            from .filter_rules import initialize as initialize_filters
            initialize_filters(db)
            db.execute("UPDATE jobs SET state='uncertain', error='上次程序在发送过程中退出，需先核对服务商已发送邮件' WHERE state='sending'")
            self._message_columns=','.join('"'+row['name'].replace('"','""')+'"'
                for row in db.execute('PRAGMA table_info(messages)') if row['name']!='raw')
        self.path.chmod(0o600)

    # ==========================================
    # Function: Scope a SQLite transaction to one operation.
    # Method: Reuse an explicit bounded ingest transaction on its own thread; otherwise commit/rollback and close normally.
    # ==========================================
    @contextmanager
    def db(self):
        current=getattr(self._transaction_scope,'connection',None)
        if current is not None:
            yield current
            return
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    # ==========================================
    # Function: Read one account's learned sender categories.
    # Method: Query the composite account/sender key.
    # ==========================================
    def sender_rules(self, account):
        with self.db() as db:
            return {r['sender']: r['category'] for r in db.execute('SELECT * FROM sender_rules WHERE account=?', (account,))}

    # ==========================================
    # Function: Cache one MIME message idempotently.
    # Method: Key by account/folder/UIDVALIDITY/UID; retain existing user corrections.
    # ==========================================
    def ingest(self, account, folder, validity, uid, raw, seen=False, _parsed=None, _received_at=None):
        message = parse_message(raw) if _parsed is None else _parsed
        identity = hashlib.sha256(json.dumps([account, folder, str(validity), str(uid)]).encode()).hexdigest()[:32]
        root = (message['references'] or message['in_reply_to'] or [message['message_id']])[0]
        thread = hashlib.sha256((account + '\0' + root).encode()).hexdigest()[:24]
        category, reason = classify(message, self.sender_rules(account), self.rules,self.preference('recognition_enabled',True))
        with self.db() as db:
            existing=db.execute('SELECT id FROM messages WHERE account=? AND folder=? AND validity=? AND uid=?',(account,folder,str(validity),str(uid))).fetchone()
            if existing:
                identity=existing['id']
            db.execute('''INSERT INTO messages
                (id,account,folder,validity,uid,message_id,thread_id,sender,subject,body,timestamp,category,reason,parsed,raw,seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET seen=coalesce((SELECT seen FROM pending_read_flags WHERE message=excluded.id),excluded.seen), remote_gone=0''',
                (identity, account, folder, str(validity), str(uid), message['message_id'], thread,
                 message['sender'], message['subject'], message['body'], message['timestamp'], category, reason,
                 json.dumps(message, ensure_ascii=False), raw, int(seen)))
            if not existing:
                from .filter_rules import observe as observe_filter_source
                observe_filter_source(db,identity,account,folder,str(validity),str(uid),message['message_id'],_received_at)
            from .thread_graph import record_links
            record_links(db,account,message)
            from .address_book import observe_message,own_addresses
            observe_message(db,message,own_addresses(self))
            db.execute("INSERT OR IGNORE INTO address_observed VALUES(?)",(identity,))
        from .receipts import ingest_report
        ingest_report(self,account,identity,raw)
        if (message['references'] or message['in_reply_to']) and not message['headers'].get('content-type','').lower().startswith('multipart/report'):
            references=list(dict.fromkeys(message['references']+message['in_reply_to']))
            with self.db() as db:
                db.execute("UPDATE messages SET reminder=0 WHERE account=? AND folder='@sent' AND message_id IN ("+','.join('?' for _ in references)+')',[account,*references])
        return identity

    # ==========================================
    # Function: Commit one bounded sync batch together without holding a write lock during MIME parsing.
    # Method: Prepare source models first, then reuse one thread-local connection for messages, identities, links and receipts.
    # ==========================================
    def ingest_many(self,account,folder,validity,sources):
        prepared=[(source,parse_message(source['raw'])) for source in sources]
        with self.db() as db:
            if getattr(self._transaction_scope,'connection',None) is not None:raise RuntimeError('不能嵌套邮件导入批次')
            self._transaction_scope.connection=db
            try:
                return [self.ingest(account,folder,validity,source['uid'],source['raw'],source.get('seen',False),_parsed=parsed,_received_at=source.get('received_at')) for source,parsed in prepared]
            finally:del self._transaction_scope.connection

    # ==========================================
    # Function: Start a verified remote mailbox generation.
    # Method: Mark old UIDVALIDITY rows unavailable without deleting cached content.
    # ==========================================
    def mailbox(self, account, folder, validity):
        with self.db() as db:
            db.execute('UPDATE messages SET remote_gone=1 WHERE account=? AND folder=? AND validity<>?', (account, folder, validity))
            db.execute('INSERT INTO folders(account,folder,validity) VALUES(?,?,?) ON CONFLICT(account,folder) DO UPDATE SET validity=excluded.validity', (account, folder, validity))
            return {r['uid'] for r in db.execute('SELECT uid FROM messages WHERE account=? AND folder=? AND validity=? AND remote_gone=0', (account, folder, validity))}

    # ==========================================
    # Function: Reconcile cached UIDs against a complete server snapshot.
    # Method: Flag disappeared messages and refresh observed read flags in one transaction.
    # ==========================================
    def reconcile(self, account, folder, validity, all_uids, flags):
        with self.db() as db:
            rows = db.execute('SELECT id,uid FROM messages WHERE account=? AND folder=? AND validity=?', (account, folder, validity)).fetchall()
            for row in rows:
                gone = row['uid'] not in all_uids
                db.execute('UPDATE messages SET remote_gone=? WHERE id=?', (int(gone), row['id']))
                if row['uid'] in flags:
                    db.execute('UPDATE messages SET seen=coalesce((SELECT seen FROM pending_read_flags WHERE message=?),?) WHERE id=?', (row['id'],int(flags[row['uid']]),row['id']))

    # ==========================================
    # Function: Persist reading immediately, including while the provider is offline.
    # Method: Commit the cache flag and a retryable exact-message intent in one transaction.
    # ==========================================
    def mark_opened(self,identity,remote=False):
        with self.db() as db:
            row=db.execute('SELECT seen FROM messages WHERE id=?',(identity,)).fetchone()
            if not row or row['seen']:return False
            db.execute('UPDATE messages SET seen=1 WHERE id=?',(identity,))
            if remote:db.execute('INSERT INTO pending_read_flags(message,seen,generation) VALUES(?,1,?) ON CONFLICT(message) DO UPDATE SET seen=1,generation=excluded.generation',(identity,uuid.uuid4().hex))
        return True

    # ==========================================
    # Function: Mark a complete contact's unread source copies read in one local transaction.
    # Method: Persist exact remote read-flag intents while leaving local-cache copies out of the provider queue.
    # ==========================================
    def mark_contact_opened(self,sources,remote=True):
        from .local_mail import is_local_message
        changed=0
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for source in sources:
                count=db.execute('UPDATE messages SET seen=1 WHERE id=? AND seen=0',(source['id'],)).rowcount
                if not count:continue
                changed+=count
                if remote and not is_local_message(source):
                    db.execute('INSERT INTO pending_read_flags(message,seen,generation) VALUES(?,1,?) ON CONFLICT(message) DO UPDATE SET seen=1,generation=excluded.generation',(source['id'],uuid.uuid4().hex))
        return changed

    # ==========================================
    # Function: Read pending provider flags without exposing message content.
    # Method: Keep generation tokens so an older acknowledgement cannot erase a newer intent.
    # ==========================================
    def pending_read_flags(self):
        with self.db() as db:return [dict(row) for row in db.execute('SELECT * FROM pending_read_flags')]

    # ==========================================
    # Function: Acknowledge only the exact read intent successfully sent to the provider.
    # Method: Compare its generation in an atomic delete, preserving newer local changes.
    # ==========================================
    def acknowledge_read(self,identity,generation):
        with self.db() as db:db.execute('DELETE FROM pending_read_flags WHERE message=? AND generation=?',(identity,generation))

    # ==========================================
    # Function: Query filtered mail and paginated summaries.
    # Method: Build whitelisted predicates; keep arbitrary search values bound.
    # ==========================================
    def list_messages(self, view='inbox', category='', account='', search='', offset=0, limit=100, folder='', all_items=False):
        where, values = ['remote_gone=0'], []
        special="coalesce((SELECT special FROM folders f WHERE f.account=messages.account AND f.folder=messages.folder),'')"
        policy=SENDER_POLICY_SQL
        effective_priority=EFFECTIVE_PRIORITY_SQL
        if folder:
            where.append('folder=?');values.append(folder)
        elif view == 'all':
            pass
        elif view in ('trash','spam'):
            where.append(f"({view if view=='spam' else 'trashed'}=1 OR {special}=?)");values.append(view)
        elif view=='archive':
            where.append(f"(archived=1 OR {special}='archive')")
        elif view=='sent':
            where.append(f"(folder='@sent' OR {special}='sent')")
        elif view=='snoozed':
            where.append('snoozed_until>?');values.append(time.time())
        elif view=='reminders':
            where.append('reminder>0')
        elif view=='aside':
            where.append('aside=1')
        elif view=='done':
            where.append('done=1')
        elif view=='blocked':
            where.append(policy+"='blocked'")
        elif view=='new_senders':
            where.append(policy+"='new'")
            where.append("folder='INBOX'")
        else:
            where.extend(['archived=0','trashed=0','spam=0','done=0','aside=0','snoozed_until<=?',f"{special} NOT IN ('trash','spam','archive','sent','drafts')", "folder<>'@sent'",policy+"<>'blocked'"])
            values.append(time.time())
            if view=='inbox':
                where.append("(upper(folder)='INBOX' OR folder='@import')")
            if self.preference('gatekeeper_mode','off')=='explicit' and view in ('inbox','unread','priority','pinned'):
                where.append(policy+"<>'new'")
            if view in ('unread','pinned','priority'):
                where.append({'unread':'seen=0','pinned':'pinned=1','priority':effective_priority}[view])
        for key, value in (('category', category), ('account', account)):
            if key=='account' and isinstance(value,(list,tuple)):
                where.append('account IN ('+','.join('?' for _ in value)+')' if value else '0')
                values.extend(value)
            elif value:
                where.append(f'{key}=?');values.append(value)
        predicates,parameters=search_terms(search)
        where.extend(predicates);values.extend(parameters)
        predicate=' AND '.join(where)
        with self.db() as db:
            total=db.execute('SELECT count(*) FROM messages WHERE '+predicate,values).fetchone()[0]
            page='' if all_items else ' LIMIT ? OFFSET ?'
            parameters=values if all_items else values+[min(max(limit,1),200),max(offset,0)]
            rows=db.execute("SELECT id,account,folder,thread_id,sender,json_extract(parsed,'$.sender_name') AS sender_name,coalesce(json_array_length(parsed,'$.attachments'),0) AS attachments_count,subject,substr(body,1,160) AS preview,timestamp,category,reason,seen,pinned,"+effective_priority+" AS priority,archived,snoozed_until,reminder,aside,done,(SELECT count(*) FROM read_receipts r JOIN jobs j ON j.id=r.job WHERE j.account=messages.account AND j.message_id=messages.message_id) AS receipts FROM messages WHERE "+predicate+' ORDER BY timestamp DESC'+page,parameters).fetchall()
        return {'items':[dict(r) for r in rows],'total':total}

    # ==========================================
    # Function: Read visible row labels without loading full MIME bodies or raw data.
    # Method: Batch stable identities within SQLite parameter limits using one connection.
    # ==========================================
    def labels_for(self,identities):
        identities=list(dict.fromkeys(identities));result={identity:[] for identity in identities}
        with self.db() as db:
            for offset in range(0,len(identities),400):
                page=identities[offset:offset+400]
                for row in db.execute('SELECT message,label FROM message_labels WHERE message IN ('+','.join('?' for _ in page)+') ORDER BY label',page):
                    result[row['message']].append(row['label'])
        return result

    # ==========================================
    # Function: Read a message or fail explicitly.
    # Method: Reuse the post-migration projection and fetch labels/policy on one connection, excluding raw by default.
    # ==========================================
    def get(self, identity, raw=False):
        columns='*' if raw else self._message_columns
        with self.db() as db:
            row=db.execute('SELECT '+columns+', '+EFFECTIVE_PRIORITY_SQL+' AS effective_priority FROM messages WHERE id=?',(identity,)).fetchone()
            if row is None:raise KeyError('邮件不存在')
            result=dict(row);result['labels']=[]
            domain='@'+result['sender'].rsplit('@',1)[-1]
            rows=db.execute('SELECT label,NULL AS policy FROM message_labels WHERE message=? '
                'UNION ALL SELECT NULL,coalesce((SELECT policy FROM sender_policy WHERE account=? AND sender=?),'
                '(SELECT policy FROM sender_policy WHERE account=? AND sender=?),\'new\') ORDER BY label',
                (identity,result['account'],result['sender'],result['account'],domain))
            for item in rows:
                if item['label'] is None:result['sender_policy']=item['policy']
                else:result['labels'].append(item['label'])
        result['parsed']=json.loads(result['parsed'])
        return result

    # ==========================================
    # Function: Show cached members of the same RFC conversation.
    # Method: Restrict by both account and reference-derived thread identity.
    # ==========================================
    def thread(self, identity, message=None):
        message = message if message is not None else self.get(identity)
        with self.db() as db:
            from .thread_graph import conversation
            return conversation(db,message)

    # ==========================================
    # Function: Apply local states and explicit category corrections.
    # Method: Validate actions; optionally persist a sender rule and reclassify peers.
    # ==========================================
    def update(self, identity, changes):
        if not changes or set(changes) - {'seen', 'pinned', 'priority', 'archived', 'category', 'learn_sender'}:
            raise ValueError('无效邮件操作')
        message = self.get(identity)
        with self.db() as db:
            for flag in ('seen', 'pinned', 'priority', 'archived'):
                if flag in changes:
                    if not isinstance(changes[flag], bool):
                        raise ValueError('状态值必须为布尔值')
                    db.execute(f'UPDATE messages SET {flag}=? WHERE id=?', (int(changes[flag]), identity))
                    if flag=='seen':db.execute('DELETE FROM pending_read_flags WHERE message=?',(identity,))
            if 'category' in changes:
                category = changes['category']
                if category not in CATEGORIES:
                    raise ValueError('分类无效')
                db.execute("UPDATE messages SET category=?,override=?,reason='你手动设置的分类' WHERE id=?", (category, category, identity))
                if changes.get('learn_sender'):
                    db.execute('INSERT INTO sender_rules VALUES(?,?,?) ON CONFLICT(account,sender) DO UPDATE SET category=excluded.category', (message['account'], message['sender'], category))
                    db.execute("UPDATE messages SET category=?,reason='使用你为此发件人保存的分类' WHERE account=? AND sender=? AND override IS NULL", (category, message['account'], message['sender']))
        return self.get(identity)

    # ==========================================
    # Function: Reapply rules to messages without individual overrides.
    # Method: Read parsed metadata and evaluate the independent classifier again.
    # ==========================================
    def reclassify(self):
        with self.db() as db:
            rows = db.execute('SELECT id,account,parsed FROM messages WHERE override IS NULL').fetchall()
        for row in rows:
            category, reason = classify(json.loads(row['parsed']), self.sender_rules(row['account']), self.rules,self.preference('recognition_enabled',True))
            with self.db() as db:
                db.execute('UPDATE messages SET category=?,reason=? WHERE id=? AND override IS NULL', (category, reason, row['id']))
        return len(rows)

    # ==========================================
    # Function: Save a new or edited local draft.
    # Method: Permit editing only while its state is draft.
    # ==========================================
    def save_draft(self, account, draft, identity=None):
        identity = identity or uuid.uuid4().hex
        with self.db() as db:
            row = db.execute('SELECT state FROM jobs WHERE id=?', (identity,)).fetchone()
            if row and row['state'] != 'draft':
                raise ValueError('该邮件已进入发送队列，不能覆盖')
            db.execute('INSERT INTO jobs(id,account,draft,state,due,created) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET account=excluded.account,draft=excluded.draft', (identity, account, json.dumps(draft, ensure_ascii=False), 'draft', 0, time.time()))
        return identity

    # ==========================================
    # Function: Commit a complete MIME payload to the durable outbox.
    # Method: Atomically transition a saved draft into queued state.
    # ==========================================
    def enqueue(self, identity, raw, envelope, message_id, due):
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET raw=?,envelope=?,message_id=?,due=?,state='queued',error='' WHERE id=? AND state='draft'", (raw, json.dumps(envelope), message_id, due, identity))
            if cursor.rowcount != 1:
                raise ValueError('草稿不存在或已经排队')

    # ==========================================
    # Function: Claim one due delivery without double sending.
    # Method: Acquire a write lock before selecting and transitioning the job.
    # ==========================================
    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND due<=? ORDER BY due LIMIT 1", (time.time(),)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='sending' WHERE id=?", (row['id'],))
            return dict(row)

    # ==========================================
    # Function: Record the terminal delivery result independently of sent-copy status.
    # Method: Update one durable job with bounded public status messages.
    # ==========================================
    def finish(self, identity, state, error='', copy_status=''):
        with self.db() as db:
            db.execute('UPDATE jobs SET state=?,error=?,copy_status=? WHERE id=?', (state, error, copy_status, identity))

    # ==========================================
    # Function: Expose recent draft and delivery summaries without MIME payloads.
    # Method: Project only bounded list fields in SQLite before crossing to Python.
    # ==========================================
    def jobs(self):
        with self.db() as db:
            return self._job_summaries(db, limit=200)

    # ==========================================
    # Function: Page all durable jobs for the native Drafts and Outbox list.
    # Method: Filter before LIMIT so older 0.30 group drafts remain reachable.
    # ==========================================
    def list_jobs(self, account='', search='', offset=0, limit=100):
        where, values = [], []
        if account:
            where.append('account=?');values.append(account)
        if search:
            where.append("(instr(lower(coalesce(json_extract(draft,'$.subject'),'')),lower(?))>0 OR "
                         "instr(lower(coalesce(json_extract(draft,'$.to'),'')),lower(?))>0 OR "
                         "instr(lower(coalesce(json_extract(draft,'$.body'),'')),lower(?))>0)")
            values.extend([search]*3)
        clause=' WHERE '+' AND '.join(where) if where else ''
        offset=max(0,int(offset));limit=min(100,max(1,int(limit)))
        with self.db() as db:
            total=db.execute('SELECT count(*) FROM jobs'+clause,values).fetchone()[0]
            items=self._job_summaries(db,clause,values,limit,offset)
        return {'items':items,'total':total}

    # ==========================================
    # Function: Query compact job summaries without loading attachment data in Python.
    # Method: Extract bounded fields and attachment names inside SQLite; exact job(id) stays full.
    # ==========================================
    def _job_summaries(self, db, clause='', values=(), limit=200, offset=0):
        rows=db.execute('''SELECT jobs.id,jobs.account,jobs.state,jobs.due,jobs.error,
            jobs.copy_status,jobs.created,
            (SELECT count(*) FROM read_receipts r WHERE r.job=jobs.id) AS receipts,
            substr(coalesce(json_extract(jobs.draft,'$.subject'),''),1,2000) AS subject,
            substr(coalesce(json_extract(jobs.draft,'$.to'),''),1,2000) AS recipient,
            substr(coalesce(json_extract(jobs.draft,'$.body'),''),1,1000) AS body_preview,
            coalesce((SELECT json_group_array(json_object('name',
                substr(coalesce(json_extract(value,'$.name'),''),1,255)))
                FROM json_each(jobs.draft,'$.attachments')),'[]') AS attachment_names
            FROM jobs''' + clause + ' ORDER BY jobs.created DESC,jobs.id DESC LIMIT ? OFFSET ?',
            list(values)+[limit,offset])
        results = []
        for row in rows:
            item=dict(row)
            draft={'subject':item.pop('subject'),'to':item.pop('recipient'),
                   'body':item.pop('body_preview'),
                   'attachments':json.loads(item.pop('attachment_names'))}
            results.append({**item,'draft':draft})
        return results

    # ==========================================
    # Function: Remove only genuinely empty unsent drafts, preserving delivery audit states.
    # Method: Keyset-stream one full draft at a time and compare-and-delete exact unchanged JSON.
    # ==========================================
    def prune_empty_drafts(self):
        from .draft_content import has_draft_content
        removed=[];last_id=''
        with self.db() as db:
            while True:
                row=db.execute("SELECT id,draft FROM jobs WHERE state='draft' AND id>? ORDER BY id LIMIT 1",(last_id,)).fetchone()
                if row is None:break
                last_id=row['id']
                if not has_draft_content(json.loads(row['draft'])):
                    db.execute("DELETE FROM jobs WHERE id=? AND state='draft' AND draft=?",(row['id'],row['draft']))
                    removed.append(row['id'])
                del row
        return removed

    # ==========================================
    # Function: Find local unsent replies associated with visible conversation cards.
    # Method: Query exact source identities once and return complete drafts for safe resumption.
    # ==========================================
    def reply_drafts(self,origins):
        origins=tuple(origins)
        if not origins:return []
        with self.db() as db:
            rows=db.execute("SELECT id,account,draft FROM jobs WHERE state='draft' AND json_extract(draft,'$.reply_source') IN ("+','.join('?' for _ in origins)+') ORDER BY created',origins).fetchall()
        return [{**dict(row),'draft':json.loads(row['draft'])} for row in rows]

    # ==========================================
    # Function: Load one editable draft or delivery item without raw transport bytes.
    # Method: Return full attachment payloads only for the selected item.
    # ==========================================
    def job(self, identity):
        with self.db() as db:
            row = db.execute('SELECT id,account,draft,state,due,error,copy_status,created,(SELECT count(*) FROM read_receipts r WHERE r.job=jobs.id) AS receipts FROM jobs WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError('草稿或发件任务不存在')
        return {**dict(row), 'draft': json.loads(row['draft'])}

    # ==========================================
    # Function: Change one pending delivery time atomically without replaying sent messages.
    # Method: Accept now/future timestamps and compare-and-update queued state in one transaction.
    # ==========================================
    def reschedule(self, identity, due):
        if not isinstance(due,(int,float)) or not time.time()-2<=due<=time.time()+366*86400:
            raise ValueError('发送时间无效')
        with self.db() as db:
            row=db.execute("SELECT draft FROM jobs WHERE id=? AND state='queued'",(identity,)).fetchone()
            if not row:raise ValueError('只能修改尚未开始投递的计划')
            draft=json.loads(row['draft'])
            if draft.get('remind_at') and due>=draft['remind_at']:raise ValueError('发送时间不能晚于未回复提醒；请取消计划后调整提醒')
            from datetime import datetime
            draft['scheduled_at']=datetime.fromtimestamp(due).isoformat(timespec='minutes') if due>time.time()+1 else ''
            cursor=db.execute("UPDATE jobs SET due=?,draft=? WHERE id=? AND state='queued'",(due,json.dumps(draft,ensure_ascii=False),identity))
            if cursor.rowcount!=1:raise ValueError('只能修改尚未开始投递的计划')

    # ==========================================
    # Function: Cancel a queued delivery before it is claimed.
    # Method: Atomically restore editable draft state; sending jobs are immutable.
    # ==========================================
    def cancel(self, identity):
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET state='draft',raw=NULL,envelope=NULL WHERE id=? AND state='queued'", (identity,))
            if cursor.rowcount != 1:
                raise ValueError('只能撤回尚未开始发送的排队邮件')
