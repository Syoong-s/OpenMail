"""Configurable account-scoped inbox retention with durable daily scheduling."""
from datetime import datetime
import json
import math

from . import transport
from .folders import transfer_selected,select_message

DEFAULT_DAYS=365
MAX_DAYS=36500
CHECK_INTERVAL=24*60*60

# ==========================================
# Function: Validate the saved enable switch and age threshold before any mail can move.
# Method: Require a real boolean and an integer number of days between1 and36500.
# ==========================================
def validate_policy(enabled,days):
    if not isinstance(enabled,bool):raise ValueError('自动清理开关无效')
    if type(days) is not int or not 1<=days<=MAX_DAYS:raise ValueError('保留天数须为 1 至 36500 的整数')
    return enabled,days

# ==========================================
# Function: Read a coherent current retention policy independently of a rendering preference snapshot.
# Method: Fetch both persisted values in one SQLite snapshot and preserve enabled/365-day defaults on upgrade.
# ==========================================
def get_policy(store):
    import json
    with store.db() as db:
        values={row['key']:json.loads(row['value']) for row in db.execute("SELECT key,value FROM preferences WHERE key IN ('mail_retention_enabled','mail_retention_days')")}
    return validate_policy(values.get('mail_retention_enabled',True),values.get('mail_retention_days',DEFAULT_DAYS))

# ==========================================
# Function: Save the complete explicitly approved policy without exposing a partially changed threshold.
# Method: Persist both typed values atomically and invalidate completed checks only on effective changes.
# ==========================================
def save_policy(store,enabled,days):
    enabled,days=validate_policy(enabled,days)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        values={row['key']:json.loads(row['value']) for row in db.execute("SELECT key,value FROM preferences WHERE key IN ('mail_retention_enabled','mail_retention_days','mail_retention_revision')")}
        previous=(values.get('mail_retention_enabled',True),values.get('mail_retention_days',DEFAULT_DAYS))
        if previous!=(enabled,days):
            revision=values.get('mail_retention_revision',0)+1
            db.execute('INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('mail_retention_revision',json.dumps(revision)))
        db.executemany('INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [('mail_retention_enabled',json.dumps(enabled)),('mail_retention_days',json.dumps(days))])

# ==========================================
# Function: Read a coherent policy generation and per-account durable completion marker.
# Method: Use one SQLite snapshot so restart and settings changes cannot borrow another policy's completion.
# ==========================================
def schedule_snapshot(db,account_id):
    key='mail_retention_completed:'+str(account_id)
    values={row['key']:json.loads(row['value']) for row in db.execute('SELECT key,value FROM preferences WHERE key IN (?,?,?,?)',
        ('mail_retention_enabled','mail_retention_days','mail_retention_revision',key))}
    policy=validate_policy(values.get('mail_retention_enabled',True),values.get('mail_retention_days',DEFAULT_DAYS))
    token=(*policy,values.get('mail_retention_revision',0))
    return key,token,values.get(key,{})

# ==========================================
# Function: Run a due account's retention check, including catch-up after the app was closed.
# Method: Persist completion only for a finished batch under the same policy; partial and failed work stays due.
# ==========================================
def run_due(account,store,client,limit=200,now=None,should_yield=None):
    stamp=(now or datetime.now().astimezone()).timestamp()
    with store.db() as db:key,token,state=schedule_snapshot(db,account.id)
    if not token[0]:return {'moved':0,'disabled':True}
    completed=state.get('at') if isinstance(state,dict) else None
    if (isinstance(state,dict) and state.get('policy')==list(token) and type(completed) in (int,float)
            and math.isfinite(completed) and 0<=stamp-completed<CHECK_INTERVAL):
        return {'moved':0,'skipped':True}
    result=expire_inbox(account,store,client,limit,now,should_yield)
    if result.get('disabled') or result.get('pending') or result.get('more'):return result
    from .sync_batches import checkpoint
    checkpoint(should_yield)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        _,current,_=schedule_snapshot(db,account.id)
        if current==token:
            completed=(now or datetime.now().astimezone()).timestamp()
            db.execute('INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                (key,json.dumps({'at':completed,'policy':list(token)})))
    return result

# ==========================================
# Function: Calculate the exact elapsed-day age boundary independently of leap years and daylight saving.
# Method: Subtract the configured count of24-hour days from the reference timestamp.
# ==========================================
def days_cutoff(days,now=None):
    validate_policy(True,days)
    return (now or datetime.now().astimezone()).timestamp()-days*86400

# ==========================================
# Function: Move old unpinned inbox mail to this account's mapped cloud trash after successful sync.
# Method: Recheck cloud stars and live policy, move a bounded batch, and report whether more work may remain.
# ==========================================
def expire_inbox(account,store,client,limit=200,now=None,should_yield=None):
    policy=get_policy(store);enabled,days=policy
    if not enabled:return {'moved':0,'disabled':True}
    destination=store.special_folder(account.id,'trash')
    if not destination:return {'moved':0,'pending':'未设置已删除邮件文件夹'}
    inbox=store.special_folder(account.id,'inbox') or 'INBOX'
    if destination.casefold()==inbox.casefold():return {'moved':0,'pending':'收件箱与已删除邮件映射相同'}
    cutoff=days_cutoff(days,now)
    with store.db() as db:
        candidates=[dict(row) for row in db.execute('''SELECT id,account,folder,validity,uid,remote_gone FROM messages
            WHERE account=? AND (upper(folder)='INBOX' OR folder=?) AND remote_gone=0 AND pinned=0
            AND timestamp>0 AND timestamp<? AND validity<>'local' ORDER BY timestamp,id LIMIT ?''',(account.id,inbox,cutoff,max(1,int(limit))))]
    moved=0
    from .sync_batches import checkpoint
    for message in candidates:
        checkpoint(should_yield)
        if get_policy(store)!=policy:break
        select_message(client,message)
        checkpoint(should_yield)
        rows=transport.checked(client.uid('FETCH',message['uid'],'(UID FLAGS)'),'核对过期邮件星标')
        stars=transport.star_rows(rows)
        if message['uid'] not in stars:continue
        if stars[message['uid']]:
            with store.db() as db:db.execute('UPDATE messages SET pinned=1 WHERE id=?',(message['id'],))
            continue
        if get_policy(store)!=policy:break
        checkpoint(should_yield)
        mapping=transfer_selected(client,message,destination)
        store.transfer_local(message['id'],destination,local=False,mapping=mapping);moved+=1
    return {'moved':moved,'more':len(candidates)>=max(1,int(limit))}
