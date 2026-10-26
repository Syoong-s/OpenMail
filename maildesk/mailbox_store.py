"""Folder hierarchy, saved searches and durable personal mail organization."""
import json
from contextlib import contextmanager
from copy import deepcopy
import time
import uuid

# ==========================================
# Function: Add folder and personal-workflow persistence to the message store.
# Method: Keep schema migrations additive and use parameterized SQLite transactions.
# ==========================================
class OrganizationStore:
    # ==========================================
    # Function: Upgrade existing v0.1/v0.2 caches without discarding mail.
    # Method: Inspect table columns before adding defaults and auxiliary tables.
    # ==========================================
    def migrate_organization(self, db):
        additions = {
            'folders': {'delimiter': "TEXT DEFAULT '/'", 'flags': "TEXT NOT NULL DEFAULT '[]'", 'special': "TEXT NOT NULL DEFAULT ''", 'subscribed': 'INTEGER NOT NULL DEFAULT 1', 'selectable': 'INTEGER NOT NULL DEFAULT 1', 'favorite': 'INTEGER NOT NULL DEFAULT 0', 'color': "TEXT NOT NULL DEFAULT ''", 'present': 'INTEGER NOT NULL DEFAULT 1', 'remote_total':'INTEGER', 'remote_unread':'INTEGER'},
            'messages': {'snoozed_until': 'REAL NOT NULL DEFAULT 0', 'reminder': 'REAL NOT NULL DEFAULT 0', 'aside': 'INTEGER NOT NULL DEFAULT 0', 'done': 'INTEGER NOT NULL DEFAULT 0', 'trashed': 'INTEGER NOT NULL DEFAULT 0', 'spam': 'INTEGER NOT NULL DEFAULT 0'}}
        for table, columns in additions.items():
            existing = {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
            for column, definition in columns.items():
                if column not in existing:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
        db.executescript('''
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS smart_folders (id TEXT PRIMARY KEY, name TEXT NOT NULL, account TEXT NOT NULL DEFAULT '', query TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sender_policy (account TEXT NOT NULL, sender TEXT NOT NULL, policy TEXT NOT NULL, PRIMARY KEY(account,sender));
            CREATE TABLE IF NOT EXISTS message_labels (message TEXT NOT NULL, label TEXT NOT NULL, PRIMARY KEY(message,label));
            CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, name TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS priority_senders (account TEXT NOT NULL, sender TEXT NOT NULL, PRIMARY KEY(account,sender));
            CREATE TABLE IF NOT EXISTS read_receipts (job TEXT NOT NULL, recipient TEXT NOT NULL, received REAL NOT NULL, message TEXT NOT NULL, PRIMARY KEY(job,recipient));
        ''')

    # ==========================================
    # Function: Set account-scoped sender/domain priority without accepting a blocked sender.
    # Method: Maintain an independent priority table and migrate removed legacy priority policies.
    # ==========================================
    def set_priority_sender(self, account, sender, enabled=True):
        from .composer_options import rule_sender
        sender=rule_sender(sender)
        with self.db() as db:
            if enabled:db.execute('INSERT OR IGNORE INTO priority_senders VALUES(?,?)',(account,sender))
            else:
                db.execute('DELETE FROM priority_senders WHERE account=? AND sender=?',(account,sender))
                db.execute("UPDATE sender_policy SET policy='accepted' WHERE account=? AND sender=? AND policy='priority'",(account,sender))

    # ==========================================
    # Function: Read all explicit priority identities for a settings account.
    # Method: Include legacy sender policies so existing user choices remain editable.
    # ==========================================
    def priority_senders(self, account):
        with self.db() as db:
            return [row[0] for row in db.execute("SELECT sender FROM priority_senders WHERE account=? UNION SELECT sender FROM sender_policy WHERE account=? AND policy='priority' ORDER BY sender",(account,account))]

    # ==========================================
    # Function: Store or remove one explainable sender/domain category correction.
    # Method: Validate category and identity before changing account-scoped rules.
    # ==========================================
    def category_rule(self, account, sender, category):
        from .composer_options import rule_sender
        from .classifier import CATEGORIES
        sender=rule_sender(sender)
        if category not in (*CATEGORIES,'remove'):raise ValueError('邮件分类无效')
        with self.db() as db:
            if category=='remove':db.execute('DELETE FROM sender_rules WHERE account=? AND sender=?',(account,sender))
            else:db.execute('INSERT INTO sender_rules VALUES(?,?,?) ON CONFLICT(account,sender) DO UPDATE SET category=excluded.category',(account,sender,category))

    # ==========================================
    # Function: Retain an authoritative LIST/LSUB folder snapshot.
    # Method: Upsert server metadata while preserving user favorites and generation IDs.
    # ==========================================
    def save_folders(self, account, folders):
        with self.db() as db:
            db.execute('UPDATE folders SET present=0 WHERE account=?', (account,))
            for item in folders:
                db.execute('''INSERT INTO folders(account,folder,validity,delimiter,flags,special,subscribed,selectable,present)
                    VALUES(?,?,'',?,?,?,?,?,1) ON CONFLICT(account,folder) DO UPDATE SET
                    delimiter=excluded.delimiter, flags=excluded.flags, special=excluded.special,
                    subscribed=excluded.subscribed,selectable=excluded.selectable,present=1''',
                    (account,item['name'],item.get('delimiter','/'),json.dumps(item.get('flags',[])),item.get('special',''),int(item.get('subscribed',True)),int(item.get('selectable',True))))
                db.execute('UPDATE folders SET remote_total=?,remote_unread=? WHERE account=? AND folder=?',(item.get('remote_total'),item.get('remote_unread'),account,item['name']))
            db.execute('''UPDATE messages SET remote_gone=1 WHERE account=? AND folder NOT LIKE '@%'
                AND folder IN (SELECT folder FROM folders WHERE account=? AND present=0)''', (account,account))

    # ==========================================
    # Function: List folders with cached unread and total badges.
    # Method: Account-scoped joins keep identical paths on different accounts separate.
    # ==========================================
    def list_folders(self, account=''):
        with self.db() as db:
            return [dict(row) for row in db.execute('''SELECT f.*,coalesce(f.remote_total,count(m.id)) AS total,
                coalesce(f.remote_unread,sum(CASE WHEN m.seen=0 THEN 1 ELSE 0 END),0) AS unread
                FROM folders f LEFT JOIN messages m ON m.account=f.account AND m.folder=f.folder AND m.remote_gone=0
                WHERE f.present=1 AND (?='' OR f.account=?) GROUP BY f.account,f.folder
                ORDER BY f.favorite DESC,lower(f.folder)''',(account,account))]

    # ==========================================
    # Function: Find a special-use folder advertised or selected for an account.
    # Method: Prefer explicit user mapping, then LIST special-use metadata.
    # ==========================================
    def special_folder(self, account, special):
        configured = self.preference('folder_mapping', {}).get(account, {}).get(special)
        rows = self.list_folders(account)
        if configured and any(r['folder']==configured and r['selectable'] for r in rows):
            return configured
        return next((r['folder'] for r in rows if r['special']==special and r['selectable']), '')

    # ==========================================
    # Function: Save personal folder favorites, colors and subscription metadata.
    # Method: Accept only documented state fields and existing folder identities.
    # ==========================================
    def folder_options(self, account, folder, **changes):
        if not changes or set(changes)-{'favorite','color','subscribed'}:
            raise ValueError('文件夹设置无效')
        if 'color' in changes and changes['color'] not in ('','blue','purple','green','orange','red'):
            raise ValueError('文件夹颜色无效')
        with self.db() as db:
            for key,value in changes.items():
                result=db.execute(f'UPDATE folders SET {key}=? WHERE account=? AND folder=? AND present=1',(value,account,folder))
                if result.rowcount!=1:
                    raise ValueError('文件夹不存在')

    # ==========================================
    # Function: Preserve cached messages and folder favorites after a successful rename.
    # Method: Rewrite the exact path and delimiter-separated descendants in one transaction.
    # ==========================================
    def rename_folder(self, account, old, new, delimiter='/'):
        with self.db() as db:
            rows=db.execute('SELECT folder FROM folders WHERE account=?',(account,)).fetchall()
            for row in rows:
                path=row['folder']
                if path==old or (delimiter and path.startswith(old+delimiter)):
                    target=new+path[len(old):]
                    db.execute('UPDATE folders SET folder=? WHERE account=? AND folder=?',(target,account,path))
                    db.execute('UPDATE messages SET folder=? WHERE account=? AND folder=?',(target,account,path))
        mapping=self.preference('folder_mapping',{})
        for key,value in mapping.get(account,{}).items():
            if value==old or (delimiter and value.startswith(old+delimiter)):
                mapping[account][key]=new+value[len(old):]
        self.set_preference('folder_mapping',mapping)
        from .filter_rules import rename_folder as rename_filter_folders
        rename_filter_folders(self,account,old,new,delimiter)

    # ==========================================
    # Function: Hide a remotely deleted folder without deleting original cached MIME.
    # Method: Mark folder/message rows unavailable only after confirmed server success.
    # ==========================================
    def remove_folder(self, account, folder):
        with self.db() as db:
            db.execute('UPDATE folders SET present=0 WHERE account=? AND folder=?',(account,folder))
            db.execute('UPDATE messages SET remote_gone=1 WHERE account=? AND folder=?',(account,folder))

    # ==========================================
    # Function: Apply a successful remote move or local demo/import copy.
    # Method: Preserve local flags and labels; remote copies arrive through normal sync.
    # ==========================================
    def transfer_local(self, identity, destination, copy=False, local=True, mapping=None):
        message=self.get(identity,raw=True)
        target=None
        if local or mapping:
            target=self.ingest(message['account'],destination,mapping['validity'] if mapping else 'local',mapping['uid'] if mapping else uuid.uuid4().hex,message['raw'],bool(message['seen']))
            with self.db() as db:
                for field in ('pinned','priority','snoozed_until','reminder','aside','done'):
                    db.execute(f'UPDATE messages SET {field}=? WHERE id=?',(message[field],target))
                db.execute('INSERT OR IGNORE INTO message_labels SELECT ?,label FROM message_labels WHERE message=?',(target,identity))
        if not copy:
            with self.db() as db:
                db.execute('UPDATE messages SET remote_gone=1 WHERE id=?',(identity,))
        return target

    # ==========================================
    # Function: Read a typed persisted desktop preference.
    # Method: Decode one JSON value or return the caller's immutable default.
    # ==========================================
    def preference(self, key, default=None):
        snapshot=getattr(self._preference_scope,'values',None)
        if snapshot is not None:
            if key not in snapshot:
                encoded=self._preference_scope.encoded.get(key)
                if encoded is None and key=='contacts':
                    with self.db() as db:
                        row=db.execute('SELECT value FROM preferences WHERE key=?',(key,)).fetchone()
                    encoded=row['value'] if row else None
                if encoded is None:return deepcopy(default)
                snapshot[key]=json.loads(encoded)
            return deepcopy(snapshot[key])
        with self.db() as db:
            row=db.execute('SELECT value FROM preferences WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else default

    # ==========================================
    # Function: Bound preference work during one synchronous desktop render.
    # Method: Snapshot encoded settings once, decode accessed keys lazily and never cache across UI operations.
    # ==========================================
    @contextmanager
    def preference_snapshot(self):
        previous=getattr(self._preference_scope,'values',None)
        if previous is None:
            with self.db() as db:self._preference_scope.encoded={row['key']:row['value'] for row in db.execute("SELECT key,value FROM preferences WHERE key<>'contacts'")}
            self._preference_scope.values={}
        try:yield
        finally:
            if previous is None:
                del self._preference_scope.values
                del self._preference_scope.encoded

    # ==========================================
    # Function: Persist one desktop preference atomically.
    # Method: Bound JSON size and replace the unique preference key.
    # ==========================================
    def set_preference(self, key, value):
        encoded=json.dumps(value,ensure_ascii=False)
        if len(encoded)>100000:
            raise ValueError('设置内容过长')
        with self.db() as db:
            db.execute('INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded))
        snapshot=getattr(self._preference_scope,'values',None)
        if snapshot is not None:snapshot[key]=json.loads(encoded)

    # ==========================================
    # Function: Save or edit a dynamic search folder.
    # Method: Validate its query before persisting a stable local identifier.
    # ==========================================
    def save_smart_folder(self, name, query, account='', identity=None):
        from .search import search_terms
        search_terms(query)
        if not name.strip() or not query.strip():
            raise ValueError('请填写智能文件夹名称和搜索条件')
        identity=identity or uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO smart_folders VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,account=excluded.account,query=excluded.query',(identity,name.strip()[:100],account,query))
        return identity

    # ==========================================
    # Function: Enumerate dynamic search folders.
    # Method: Return stable IDs for navigation and editing.
    # ==========================================
    def smart_folders(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM smart_folders ORDER BY name')]

    # ==========================================
    # Function: Remove a saved search without deleting any message.
    # Method: Delete only the smart-folder definition.
    # ==========================================
    def delete_smart_folder(self, identity):
        with self.db() as db:
            db.execute('DELETE FROM smart_folders WHERE id=?',(identity,))

    # ==========================================
    # Function: Apply personal workflow state and labels.
    # Method: Whitelist fields, bound timestamps, and keep sender screening account-scoped.
    # ==========================================
    def organize(self, identity, **changes):
        if not changes or set(changes)-{'snoozed_until','reminder','aside','done','trashed','spam','labels','sender_policy'}:
            raise ValueError('整理操作无效')
        message=self.get(identity)
        with self.db() as db:
            for key,value in changes.items():
                if key=='labels':
                    labels=list(dict.fromkeys(v.strip() for v in value if isinstance(v,str) and v.strip()))
                    if len(labels)>20 or any(len(v)>60 for v in labels):
                        raise ValueError('标签最多 20 个，每个不超过 60 字')
                    db.execute('DELETE FROM message_labels WHERE message=?',(identity,))
                    db.executemany('INSERT INTO message_labels VALUES(?,?)',[(identity,label) for label in labels])
                elif key=='sender_policy':
                    domain=value.startswith('domain:') if isinstance(value,str) else False
                    if domain:value=value.split(':',1)[1]
                    if value not in ('new','accepted','blocked','priority'):
                        raise ValueError('发件人筛选状态无效')
                    db.execute('INSERT INTO sender_policy VALUES(?,?,?) ON CONFLICT(account,sender) DO UPDATE SET policy=excluded.policy',(message['account'],('@'+message['sender'].rsplit('@',1)[-1]) if domain else message['sender'],value))
                else:
                    if key in ('reminder','snoozed_until'):
                        if not isinstance(value,(int,float)) or not 0<=value<=time.time()+366*86400:
                            raise ValueError('日期必须在一年以内')
                    elif not isinstance(value,bool):
                        raise ValueError('状态必须为布尔值')
                    db.execute(f'UPDATE messages SET {key}=? WHERE id=?',(value,identity))
        return self.get(identity)

    # ==========================================
    # Function: Save a reusable personal message template.
    # Method: Persist subject/body independently of provider and sending state.
    # ==========================================
    def save_template(self, name, subject, body, identity=None):
        if not name.strip() or len(body)>100000:
            raise ValueError('模板需要名称，正文不超过 100000 字')
        identity=identity or uuid.uuid4().hex
        with self.db() as db:
            db.execute('INSERT INTO templates VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,subject=excluded.subject,body=excluded.body',(identity,name.strip()[:100],subject,body))
        return identity

    # ==========================================
    # Function: Read reusable personal templates.
    # Method: Return named definitions in deterministic navigation order.
    # ==========================================
    def templates(self):
        with self.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM templates ORDER BY name')]
        order=self.preference('template_order',[])
        return sorted(rows,key=lambda row:(order.index(row['id']) if row['id'] in order else len(order),row['name'].casefold()))

    # ==========================================
    # Function: Duplicate or reorder a local template independently of existing drafts.
    # Method: Copy stored text with a fresh ID or persist an explicit stable ordering.
    # ==========================================
    def arrange_template(self, identity, operation):
        rows=self.templates();index=next((i for i,row in enumerate(rows) if row['id']==identity),None)
        if index is None:raise ValueError('模板不存在')
        if operation=='duplicate':
            row=rows[index];return self.save_template(row['name']+' · 副本',row['subject'],row['body'])
        if operation not in ('up','down'):raise ValueError('模板操作无效')
        target=max(0,min(len(rows)-1,index+(-1 if operation=='up' else 1)))
        rows[index],rows[target]=rows[target],rows[index]
        self.set_preference('template_order',[row['id'] for row in rows]);return identity

    # ==========================================
    # Function: Delete a personal template.
    # Method: Remove its definition without affecting previously created drafts.
    # ==========================================
    def delete_template(self, identity):
        with self.db() as db:
            db.execute('DELETE FROM templates WHERE id=?',(identity,))

    # ==========================================
    # Function: Discard one unsent local draft without touching delivery audit records.
    # Method: Refuse queued/sending/confirmed deliveries and delete only draft state.
    # ==========================================
    def delete_draft(self, identity):
        with self.db() as db:
            row=db.execute('SELECT state FROM jobs WHERE id=?',(identity,)).fetchone()
            if row and row['state']!='draft':raise ValueError('只能删除未排队的草稿，请先撤销发送')
            db.execute("DELETE FROM jobs WHERE id=? AND state='draft'",(identity,))
