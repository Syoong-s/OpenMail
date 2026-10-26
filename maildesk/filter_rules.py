"""Validated ordered account/global filing rules and durable new-arrival bookkeeping."""
import hashlib,json,re,time,uuid
from .folders import valid_path

FIELDS={'sender','domain','to','cc','subject','body','header','attachment_name','attachment_type','has_attachment','category','smart','seen','starred_contact','learned','size_kb'}
TEXT_OPS={'contains','not_contains','is','is_not','starts','ends','matches'}
BOOLEAN_FIELDS={'has_attachment','seen','starred_contact'}
SMART_TYPES=('personal','notification','newsletter','verification','invoice','calendar','auto_reply')

# ==========================================
# Function: Add filter state without changing original MIME or implicitly processing historical mail.
# Method: Migrate compact logical identities once and retain queue/attempt records across restarts and folder copies.
# ==========================================
def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS mail_filter_rules(id TEXT PRIMARY KEY,account TEXT NOT NULL,position INTEGER NOT NULL,payload TEXT NOT NULL,revision INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS mail_filter_order ON mail_filter_rules(account,position);
        CREATE TABLE IF NOT EXISTS mail_filter_baselines(account TEXT,folder TEXT,validity TEXT,cutoff INTEGER NOT NULL,PRIMARY KEY(account,folder,validity));
        CREATE TABLE IF NOT EXISTS mail_filter_seen(account TEXT,message_id TEXT,state TEXT NOT NULL,rule TEXT NOT NULL DEFAULT '',source TEXT NOT NULL DEFAULT '',target TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',updated REAL NOT NULL,PRIMARY KEY(account,message_id));
        CREATE TABLE IF NOT EXISTS mail_filter_queue(message TEXT PRIMARY KEY,account TEXT NOT NULL,message_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_filter_models(rule TEXT,account TEXT,payload TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(rule,account));
        CREATE TABLE IF NOT EXISTS mail_filter_log(id INTEGER PRIMARY KEY,account TEXT NOT NULL,message TEXT NOT NULL,rule TEXT NOT NULL,state TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,detail TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS mail_filter_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
    if not db.execute("SELECT 1 FROM mail_filter_meta WHERE key='initial_history'").fetchone():
        db.execute("INSERT OR IGNORE INTO mail_filter_seen(account,message_id,state,updated) SELECT account,message_id,'historical',? FROM messages",(time.time(),))
        db.execute("INSERT INTO mail_filter_meta VALUES('initial_history','1')")
    db.execute("UPDATE mail_filter_seen SET state='uncertain',error='上次移动结果待核对；请先同步，再手动运行',updated=? WHERE state='moving'",(time.time(),))
    db.execute("DELETE FROM mail_filter_queue WHERE EXISTS(SELECT 1 FROM mail_filter_seen s WHERE s.account=mail_filter_queue.account AND s.message_id=mail_filter_queue.message_id AND s.state<>'queued')")

# ==========================================
# Function: Record a folder's first complete UID snapshot as the historical boundary.
# Method: Keep the original cutoff fixed for each UID generation so deferred backfill does not lose genuine later arrivals.
# ==========================================
def baseline(store,account,folder,validity,uids):
    with store.db() as db:
        db.execute('INSERT OR IGNORE INTO mail_filter_meta VALUES(?,?)',('arrival_start:'+account,str(int(time.time()))))
        db.execute('INSERT OR IGNORE INTO mail_filter_baselines VALUES(?,?,?,?)',(account,folder,validity,max((int(uid) for uid in uids),default=0)))

# ==========================================
# Function: Admit each incoming logical message to filtering at most once.
# Method: Enqueue only post-baseline remote UIDs and let account/RFC identity suppress destination copies and repeated synchronization.
# ==========================================
def observe(db,identity,account,folder,validity,uid,message_id,received_at=None):
    boundary=db.execute('SELECT cutoff FROM mail_filter_baselines WHERE account=? AND folder=? AND validity=?',(account,folder,str(validity))).fetchone()
    started=db.execute('SELECT value FROM mail_filter_meta WHERE key=?',('arrival_start:'+account,)).fetchone()
    eligible=boundary is not None and started is not None and isinstance(received_at,(int,float)) and received_at>=int(started['value']) and str(uid).isdigit() and int(uid)>boundary['cutoff'] and not folder.startswith('@') and validity!='local'
    state='queued' if eligible else 'historical'
    added=db.execute('INSERT OR IGNORE INTO mail_filter_seen(account,message_id,state,updated) VALUES(?,?,?,?)',(account,message_id,state,time.time())).rowcount
    if added and eligible:db.execute('INSERT OR IGNORE INTO mail_filter_queue VALUES(?,?,?)',(identity,account,message_id))

# ==========================================
# Function: Reject invalid or unexpectedly broad rule data before it can drive provider mutations.
# Method: Whitelist bounded conditions, explicit source scopes and account-relative existing destination paths.
# ==========================================
def validate(value):
    if not isinstance(value,dict):raise ValueError('过滤器格式无效')
    rule=dict(value);rule['id']=str(rule.get('id') or uuid.uuid4().hex)
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',rule['id']):raise ValueError('过滤器标识无效')
    name=rule.get('name','')
    if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('请输入100字以内的过滤器名称')
    rule['name']=name.strip();rule.setdefault('account','');rule.setdefault('enabled',True);rule.setdefault('mode','all');rule.setdefault('source_mode','all');rule.setdefault('sources',{});rule.setdefault('subfolders',False);rule.setdefault('destinations',{})
    if not isinstance(rule['account'],str) or len(rule['account'])>128 or type(rule['enabled']) is not bool or type(rule['subfolders']) is not bool:raise ValueError('过滤器范围或开关无效')
    if rule['mode'] not in ('all','any') or rule['source_mode'] not in ('all','include','exclude'):raise ValueError('过滤器匹配方式无效')
    if not isinstance(rule['sources'],dict) or len(rule['sources'])>100 or not isinstance(rule['destinations'],dict) or not 1<=len(rule['destinations'])<=100:raise ValueError('请至少为一个账号选择目标文件夹')
    sources={}
    for account,paths in rule['sources'].items():
        if not isinstance(account,str) or not account or not isinstance(paths,list) or len(paths)>500:raise ValueError('来源文件夹无效')
        sources[account]=list(dict.fromkeys(valid_path(path) for path in paths))
    if rule['source_mode']!='all' and not any(sources.values()):raise ValueError('请选择来源文件夹，或改为所有文件夹')
    destinations={account:valid_path(path) for account,path in rule['destinations'].items() if isinstance(account,str) and account}
    if len(destinations)!=len(rule['destinations']):raise ValueError('目标账号无效')
    if rule['account'] and (rule['account'] not in destinations or set(destinations)-{rule['account']} or set(sources)-{rule['account']}):raise ValueError('账号过滤器只能使用本账号的文件夹')
    conditions=rule.get('conditions')
    if not isinstance(conditions,list) or not 1<=len(conditions)<=12:raise ValueError('请添加1至12条匹配条件')
    cleaned=[]
    for item in conditions:
        if not isinstance(item,dict):raise ValueError('过滤条件无效')
        field=item.get('field');op=item.get('op');text=item.get('value','')
        if field not in FIELDS or not isinstance(text,str) or not text.strip() or len(text)>1000:raise ValueError('请填写有效的过滤条件')
        if field in BOOLEAN_FIELDS:
            if op not in ('is','is_not') or text not in ('true','false'):raise ValueError('状态条件须选择是或否')
        elif field in ('category','smart'):
            if op not in ('is','is_not') or text not in (SMART_TYPES if field=='smart' else SMART_TYPES[:4]):raise ValueError('邮件识别类别无效')
        elif field in ('size_kb','learned'):
            if op not in ('gt','lt','gte','lte') or not text.isascii() or not text.isdigit():raise ValueError('大小或学习匹配分数须填写正整数')
            if not 0<=int(text)<=(100 if field=='learned' else 1024*1024):raise ValueError('数值超出范围')
        elif op not in TEXT_OPS:raise ValueError('过滤条件运算符无效')
        condition={'field':field,'op':op,'value':text.strip()}
        if field=='header':
            header=item.get('header','')
            if not isinstance(header,str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9-]{0,77}',header):raise ValueError('请输入合法的邮件头名称，例如 List-Id')
            condition['header']=header.lower()
        cleaned.append(condition)
    return {key:rule[key] for key in ('id','name','account','enabled','mode','source_mode','subfolders')}|{'sources':sources,'destinations':destinations,'conditions':cleaned}

# ==========================================
# Function: Load deterministic account-first then global rule order.
# Method: Keep disabled rules visible to editors but admit only the requested account during execution.
# ==========================================
def rules(store,account=None):
    with store.db() as db:
        rows=db.execute('SELECT * FROM mail_filter_rules ORDER BY position,id').fetchall()
    items=[json.loads(row['payload'])|{'revision':row['revision'],'position':row['position']} for row in rows]
    if account is None:return items
    return [rule for scope in (account,'') for rule in items if rule['account']==scope and rule['enabled'] and account in rule['destinations']]

# ==========================================
# Function: Save one validated rule atomically while preventing stale destination training.
# Method: Version edits for preview invalidation and discard only models whose account destination changed.
# ==========================================
def save(store,value):
    rule=validate(value)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM mail_filter_rules WHERE id=?',(rule['id'],)).fetchone()
        if old is None and db.execute('SELECT count(*) FROM mail_filter_rules').fetchone()[0]>=200:raise ValueError('最多可保存200个过滤器')
        position=old['position'] if old else db.execute('SELECT coalesce(max(position),0)+1 FROM mail_filter_rules').fetchone()[0]
        revision=old['revision']+1 if old else 1
        db.execute('INSERT INTO mail_filter_rules VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET account=excluded.account,payload=excluded.payload,revision=excluded.revision',(rule['id'],rule['account'],position,json.dumps(rule,ensure_ascii=False),revision))
        if old:
            previous=json.loads(old['payload'])
            for row in db.execute('SELECT account FROM mail_filter_models WHERE rule=?',(rule['id'],)).fetchall():
                if previous['destinations'].get(row['account'])!=rule['destinations'].get(row['account']):db.execute('DELETE FROM mail_filter_models WHERE rule=? AND account=?',(rule['id'],row['account']))
    return rule['id']

# ==========================================
# Function: Delete, duplicate or reorder one explicit rule within its own scope.
# Method: Preserve account/global precedence and invalidate prepared previews when order or membership changes.
# ==========================================
def arrange(store,identity,operation):
    items=rules(store);current=next((rule for rule in items if rule['id']==identity),None)
    if current is None:raise ValueError('过滤器已变更，请刷新')
    if operation=='duplicate':return save(store,current|{'id':uuid.uuid4().hex,'name':current['name'][:90]+' · 副本'})
    with store.db() as db:
        if operation=='delete':
            db.execute('DELETE FROM mail_filter_rules WHERE id=?',(identity,));db.execute('DELETE FROM mail_filter_models WHERE rule=?',(identity,))
        elif operation in ('up','down'):
            scoped=[rule for rule in items if rule['account']==current['account']];index=scoped.index(current);target=index+(-1 if operation=='up' else 1)
            if 0<=target<len(scoped):
                scoped[index],scoped[target]=scoped[target],scoped[index]
                db.executemany('UPDATE mail_filter_rules SET position=?,revision=revision+1 WHERE id=?',[(position,rule['id']) for position,rule in enumerate(scoped)])
        else:raise ValueError('过滤器操作无效')

# ==========================================
# Function: Bind a manual preview to the rule and learned-model snapshot that produced it.
# Method: Hash ordered persisted rule values plus model revisions, independent of mutable rendering preferences.
# ==========================================
def fingerprint(store):
    with store.db() as db:
        payload=[list(row) for row in db.execute('SELECT id,position,revision,payload FROM mail_filter_rules ORDER BY account,position,id')]
        models=[list(row) for row in db.execute('SELECT rule,account,updated FROM mail_filter_models ORDER BY rule,account')]
    return hashlib.sha256(json.dumps([payload,models],ensure_ascii=False).encode()).hexdigest()

# ==========================================
# Function: Keep account-relative source/target paths valid after a confirmed folder rename.
# Method: Rewrite only exact paths and delimiter-separated descendants, leaving other accounts and learned content unchanged.
# ==========================================
def rename_folder(store,account,old,new,delimiter):
    with store.db() as db:
        for row in db.execute('SELECT * FROM mail_filter_rules').fetchall():
            rule=json.loads(row['payload']);changed=False
            # ==========================================
            # Function: Rewrite one folder reference within the renamed hierarchy.
            # Method: Require an exact folder or a true delimiter boundary.
            # ==========================================
            def rewrite(path):
                return new+path[len(old):] if path==old or (delimiter and path.startswith(old+delimiter)) else path
            if account in rule['destinations']:
                before=rule['destinations'][account];rule['destinations'][account]=rewrite(before);changed|=before!=rule['destinations'][account]
            if account in rule['sources']:
                before=rule['sources'][account];rule['sources'][account]=[rewrite(path) for path in before];changed|=before!=rule['sources'][account]
            if changed:db.execute('UPDATE mail_filter_rules SET payload=?,revision=revision+1 WHERE id=?',(json.dumps(rule,ensure_ascii=False),row['id']))

# ==========================================
# Function: Retain a concise bounded audit trail for preview, completed moves and actionable failures.
# Method: Store rule/source/destination/reason without copying message bodies into another log.
# ==========================================
def log(db,message,rule,state,target,detail):
    db.execute('INSERT INTO mail_filter_log(account,message,rule,state,source,target,detail,created) VALUES(?,?,?,?,?,?,?,?)',(message['account'],message['id'],rule,state,message['folder'],target,detail[:1000],time.time()))
    db.execute('DELETE FROM mail_filter_log WHERE id NOT IN (SELECT id FROM mail_filter_log ORDER BY id DESC LIMIT 500)')
