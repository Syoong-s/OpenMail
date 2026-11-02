"""Durable local mail intents, coalesced flags and recoverable provider moves."""
import time
import uuid
from collections import defaultdict


# ==========================================
# Function: Install durable mutations and cheap mailbox invalidation counters.
# Method: Keep move source identities separate from immediate local destinations.
# ==========================================
def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS pending_pinned_flags (
            message TEXT PRIMARY KEY, seen INTEGER NOT NULL, generation TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pending_moves (
            message TEXT PRIMARY KEY, account TEXT NOT NULL, source_folder TEXT NOT NULL,
            source_validity TEXT NOT NULL, source_uid TEXT NOT NULL, destination TEXT NOT NULL,
            generation TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            attempted_destination TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
            retry_at REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS pending_move_source ON pending_moves(account,source_folder,source_validity,source_uid);
        INSERT OR IGNORE INTO navigation_revision VALUES('mail',0);
        CREATE TRIGGER IF NOT EXISTS mail_revision_insert AFTER INSERT ON messages BEGIN
            UPDATE navigation_revision SET value=value+1 WHERE topic='mail'; END;
        CREATE TRIGGER IF NOT EXISTS mail_revision_delete AFTER DELETE ON messages BEGIN
            UPDATE navigation_revision SET value=value+1 WHERE topic='mail'; END;
        CREATE TRIGGER IF NOT EXISTS mail_revision_update AFTER UPDATE ON messages
        WHEN old.folder<>new.folder OR old.seen<>new.seen OR old.pinned<>new.pinned
          OR old.priority<>new.priority OR old.archived<>new.archived OR old.done<>new.done
          OR old.remote_gone<>new.remote_gone OR old.category<>new.category
          OR old.aside<>new.aside OR old.snoozed_until<>new.snoozed_until
        BEGIN UPDATE navigation_revision SET value=value+1 WHERE topic='mail'; END;
        UPDATE pending_moves SET state='uncertain' WHERE state='sending';
    ''')
    for table in ('message_labels','sender_policy','priority_senders','folders'):
        for operation in ('INSERT','UPDATE','DELETE'):
            db.execute('CREATE TRIGGER IF NOT EXISTS mutation_revision_'+table+'_'+operation+' AFTER '+operation+' ON '+table+" BEGIN UPDATE navigation_revision SET value=value+1 WHERE topic='mail'; END")
    db.executescript('''CREATE TRIGGER IF NOT EXISTS mutation_cleanup AFTER DELETE ON messages BEGIN
        DELETE FROM pending_read_flags WHERE message=old.id;
        DELETE FROM pending_pinned_flags WHERE message=old.id;
        DELETE FROM pending_moves WHERE message=old.id;
        END;''')


# ==========================================
# Function: Commit provider flags without waiting for a network connection.
# Method: Update compact rows and replace each flag's durable generation atomically.
# ==========================================
def flags(service, identities, key, value):
    from .local_mail import is_local_message
    if key not in ('seen','pinned','priority') or not isinstance(value,bool):
        raise ValueError('无效邮件状态')
    identities=list(dict.fromkeys(identities));store=service.store
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for identity in identities:
            row=db.execute('SELECT id,account,folder,validity,uid,remote_gone FROM messages WHERE id=?',(identity,)).fetchone()
            if row is None:raise ValueError('所选邮件已不存在')
            remote=not service.demo and not is_local_message(row) and key!='priority'
            if remote and (row['account'] not in service.accounts or row['remote_gone']):
                raise ValueError('邮件无法对应到当前账户，请先同步')
            db.execute('UPDATE messages SET '+key+'=? WHERE id=?',(int(value),identity))
            if key!='priority':
                table='pending_read_flags' if key=='seen' else 'pending_pinned_flags'
                if remote:
                    db.execute('INSERT INTO '+table+' VALUES(?,?,?) ON CONFLICT(message) DO UPDATE SET seen=excluded.seen,generation=excluded.generation',
                               (identity,int(value),uuid.uuid4().hex))
                else:db.execute('DELETE FROM '+table+' WHERE message=?',(identity,))
    return identities


# ==========================================
# Function: Move a cached message immediately while retaining its stable UI identity.
# Method: Journal the original UID and isolate provisional destinations from real UIDs.
# ==========================================
def move(service, identity, destination):
    from .local_mail import is_local_message,LOCAL_ACCOUNT
    store=service.store;mapping=store.preference('folder_mapping',{})
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        source=db.execute('SELECT id,account,folder,validity,uid,remote_gone FROM messages WHERE id=?',(identity,)).fetchone()
        if source is None:raise ValueError('邮件不存在')
        target=db.execute('SELECT special FROM folders WHERE account=? AND folder=? AND present=1 AND selectable=1',
                          (source['account'],destination)).fetchone()
        if target is None:raise ValueError('目标文件夹不存在或不可选择')
        local=service.demo or is_local_message(source)
        if local and not service.demo and source['account']!=LOCAL_ACCOUNT:
            raise ValueError('本地副本不能直接移动到服务器')
        if not local and (source['account'] not in service.accounts or source['remote_gone']):
            raise ValueError('邮件无法对应到当前账户，请先同步')
        if source['folder']!=destination:
            if local:
                validity,uid='local',uuid.uuid4().hex
            else:
                generation=uuid.uuid4().hex
                db.execute('''INSERT INTO pending_moves(message,account,source_folder,source_validity,source_uid,destination,generation)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT(message) DO UPDATE SET
                    destination=excluded.destination,generation=excluded.generation''',
                    (identity,source['account'],source['folder'],source['validity'],source['uid'],destination,generation))
                validity,uid='pending',identity
            db.execute('UPDATE messages SET folder=?,validity=?,uid=? WHERE id=?',(destination,validity,uid,identity))
        special=next((key for key,value in mapping.get(source['account'],{}).items() if value==destination),target['special'])
        archived=special=='archive'
        db.execute('UPDATE messages SET archived=?,done=?,trashed=?,spam=?,aside=0,snoozed_until=0 WHERE id=?',
                   (int(archived),int(archived),int(special=='trash'),int(special=='spam'),identity))
    return identity


# ==========================================
# Function: Resolve queued flags to the actual remote source during a pending move.
# Method: Skip uncertain moves until recovery can establish a verified UID again.
# ==========================================
def flag_sources(store, table):
    with store.db() as db:
        return [dict(row) for row in db.execute('''SELECT p.message,p.seen,p.generation,m.id,m.account,m.remote_gone,
            coalesce(q.source_folder,m.folder) AS folder,coalesce(q.source_validity,m.validity) AS validity,
            coalesce(q.source_uid,m.uid) AS uid,q.state AS move_state
            FROM '''+table+''' p JOIN messages m ON m.id=p.message LEFT JOIN pending_moves q ON q.message=m.id''')]


# ==========================================
# Function: Batch local flag intents by provider, mailbox generation and target value.
# Method: Acknowledge exact generations so edits made during network I/O survive.
# ==========================================
def flush_flags(service, should_yield=lambda:False):
    from . import transport
    paused=service.store.preference('paused_accounts',[])
    for table,flag in (('pending_read_flags','\\Seen'),('pending_pinned_flags','\\Flagged')):
        groups=defaultdict(list)
        for row in flag_sources(service.store,table):
            if row['account'] in paused or row['account'] not in service.accounts or row['remote_gone']:continue
            if row['move_state'] in ('uncertain','sending','confirming'):continue
            groups[(row['account'],row['folder'],row['validity'],bool(row['seen']))].append(row)
        for (account,folder,validity,value),rows in groups.items():
            for start in range(0,len(rows),100):
                if should_yield():return
                page=rows[start:start+100]
                try:
                    if len(page)==1:transport.set_seen(service.accounts[account],page[0],value,flag)
                    else:transport.set_seen_many(service.accounts[account],page,value,flag)
                except Exception:
                    service.status['mutation_error']='更改已保存在本机，后台同步失败，将在下次同步重试'
                    break
                with service.store.db() as db:
                    db.executemany('DELETE FROM '+table+' WHERE message=? AND generation=?',[(r['message'],r['generation']) for r in page])


# ==========================================
# Function: Rebind one locally moved message after the server acknowledges its new UID.
# Method: Preserve newer move intents and all local state while advancing the journal source.
# ==========================================
def acknowledge_move(store, row, destination, mapping):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT * FROM pending_moves WHERE message=?',(row['message'],)).fetchone()
        if current is None:return
        if current['destination']==destination:
            duplicate=db.execute('SELECT id FROM messages WHERE account=? AND folder=? AND validity=? AND uid=? AND id<>?',
                                 (row['account'],destination,mapping['validity'],mapping['uid'],row['message'])).fetchone()
            if duplicate:
                db.execute('INSERT OR IGNORE INTO message_labels SELECT ?,label FROM message_labels WHERE message=?',(row['message'],duplicate['id']))
                db.execute('DELETE FROM messages WHERE id=?',(duplicate['id'],))
            db.execute('UPDATE messages SET folder=?,validity=?,uid=?,remote_gone=0 WHERE id=?',
                       (destination,mapping['validity'],mapping['uid'],row['message']))
            db.execute('DELETE FROM pending_moves WHERE message=?',(row['message'],))
            db.execute("UPDATE mail_filter_seen SET state='manual',error='' WHERE account=? AND message_id=(SELECT message_id FROM messages WHERE id=?) AND state='uncertain'",(row['account'],row['message']))
        else:
            db.execute("UPDATE pending_moves SET source_folder=?,source_validity=?,source_uid=?,state='pending',attempted_destination='',retry_at=0,error='' WHERE message=?",
                       (destination,mapping['validity'],mapping['uid'],row['message']))


# ==========================================
# Function: Push coalesced moves without replaying an ambiguous destructive command.
# Method: Record sending before I/O, recover uncertain outcomes by exact payload, back off failures.
# ==========================================
def flush_moves(service, should_yield=lambda:False):
    from . import folders
    store=service.store;paused=store.preference('paused_accounts',[])
    with store.db() as db:
        pending=[dict(row) for row in db.execute('SELECT * FROM pending_moves WHERE retry_at<=? ORDER BY rowid',(time.time(),))]
    for row in pending:
        if should_yield():return
        if row['account'] not in service.accounts or row['account'] in paused:continue
        account=service.accounts[row['account']]
        source={'account':row['account'],'folder':row['source_folder'],'validity':row['source_validity'],'uid':row['source_uid'],'remote_gone':0}
        try:
            if row['state'] in ('uncertain','confirming','sending'):
                destination=row['attempted_destination']
                mapping=folders.recover_transfer(account,source,destination,store.get(row['message'],raw=True),confirmed=row['state']=='confirming')
                if mapping:acknowledge_move(store,row,destination,mapping);continue
                # Recovery proved source exists and no matching destination; a later pass may retry.
                with store.db() as db:db.execute("UPDATE pending_moves SET state='pending',retry_at=0,error='' WHERE message=?",(row['message'],))
                continue
            destination=row['destination']
            if destination==source['folder']:
                acknowledge_move(store,row,destination,{'validity':source['validity'],'uid':source['uid']});continue
            with store.db() as db:
                claimed=db.execute("UPDATE pending_moves SET state='sending',attempted_destination=? WHERE message=? AND generation=? AND state='pending'",
                                   (destination,row['message'],row['generation'])).rowcount
            if not claimed:continue
            mapping=folders.transfer(account,source,destination)
            if mapping:acknowledge_move(store,row,destination,mapping)
            else:
                with store.db() as db:db.execute("UPDATE pending_moves SET state='confirming' WHERE message=?",(row['message'],))
                mapping=folders.recover_transfer(account,source,destination,store.get(row['message'],raw=True),confirmed=True)
                if mapping:acknowledge_move(store,row,destination,mapping)
        except Exception:
            with store.db() as db:
                db.execute("""UPDATE pending_moves SET state=CASE WHEN state='sending' THEN 'uncertain' ELSE state END,
                    attempts=attempts+1,retry_at=?,error=? WHERE message=?""",
                    (time.time()+min(900,15*2**min(row['attempts'],6)),'移动尚未同步，后台将核对服务器后重试',row['message']))
            service.status['mutation_error']='更改已保存在本机，移动尚未同步；后台将核对服务器后重试'


# ==========================================
# Function: Flush durable mail intents under the existing provider serialization gate.
# Method: Recover moves before the next pass resolves flags to their final remote identity.
# ==========================================
def flush(service, should_yield=lambda:False):
    service.status.pop('mutation_error',None)
    migrate_done(service)
    if not service.demo:
        flush_flags(service,should_yield)
        flush_moves(service,should_yield)
    with service.store.db() as db:
        pending=sum(db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('pending_moves','pending_read_flags','pending_pinned_flags'))
        failed=db.execute("SELECT 1 FROM pending_moves WHERE error<>'' LIMIT 1").fetchone()
    if failed:service.status.setdefault('mutation_error','更改已保存在本机，移动尚未同步；后台将核对服务器后重试')
    service.status['mutations_pending']=pending
    return pending


# ==========================================
# Function: Convert older local-only completed items into real archive intents.
# Method: Resolve discovered per-account archive mappings in bounded batches and preserve unmapped mail.
# ==========================================
def migrate_done(service):
    with service.store.db() as db:
        rows=[dict(row) for row in db.execute('''SELECT m.id,m.account FROM messages m LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            WHERE m.done=1 AND m.archived=0 AND m.remote_gone=0 AND m.folder NOT LIKE '@%'
            AND coalesce(f.special,'') NOT IN ('archive','all','sent','trash','spam')
            AND m.id NOT IN (SELECT message FROM pending_moves) LIMIT 100''')]
    destinations={}
    for row in rows:
        if not service.demo and row['account'] not in service.accounts:continue
        if row['account'] not in destinations:destinations[row['account']]=service.store.special_folder(row['account'],'archive')
        if destinations[row['account']]:
            try:move(service,row['id'],destinations[row['account']])
            except ValueError:continue  # A concurrent account/folder edit can invalidate a captured migration row.
        else:service.status['mutation_error']='历史已完成邮件尚未归档，请在文件夹管理中设置归档映射'
