"""Shared automatic/manual filter execution with preview snapshots and durable move attempts."""
from contextlib import nullcontext
import json,time
from . import filter_rules as rules
from .filter_match import first_match
from .local_mail import is_local_message,LOCAL_ACCOUNT

# ==========================================
# Function: Load compact matching context once per bounded filter run.
# Method: Reuse account-relative folder metadata, explicit contact stars and only locally trained model parameters.
# ==========================================
def context(store):
    from .filter_smart import normalize
    with store.db() as db:
        starred={normalize(row[0]) for row in db.execute('SELECT a.address FROM address_mailboxes a JOIN address_people p ON p.id=a.person WHERE p.starred=1 AND a.suppressed=0')}
        models={(row['rule'],row['account']):json.loads(row['payload']) for row in db.execute('SELECT * FROM mail_filter_models')}
    return {'starred':starred,'models':models,'folders':{(row['account'],row['folder']):row for row in store.list_folders()}}

# ==========================================
# Function: Read only one cached source and the metadata needed for matching and UID verification.
# Method: Leave raw MIME in SQLite until an actually confirmed move needs the existing cache-transfer adapter.
# ==========================================
def source(store,identity):
    with store.db() as db:
        row=db.execute('SELECT id,account,folder,validity,uid,message_id,parsed,category,reason,seen,remote_gone,length(raw) AS raw_size FROM messages WHERE id=?',(identity,)).fetchone()
    if row is None:raise ValueError('邮件已从缓存移除')
    result=dict(row);result['parsed']=json.loads(result['parsed']);return result

# ==========================================
# Function: Persist a completed/no-op/error decision and remove only that logical automatic job.
# Method: Keep an account/RFC ledger plus bounded audit data so folder copies and restart never silently rerun a move.
# ==========================================
def finish(store,message,match,state,detail,_db=None):
    rule=match['rule'] if match else '';target=match['destination'] if match else ''
    with (nullcontext(_db) if _db is not None else store.db()) as db:
        db.execute('''INSERT INTO mail_filter_seen(account,message_id,state,rule,source,target,error,updated) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(account,message_id) DO UPDATE SET state=excluded.state,rule=excluded.rule,source=excluded.source,target=excluded.target,error=excluded.error,updated=excluded.updated''',
            (message['account'],message['message_id'],state,rule,message['folder'],target,detail[:1000],time.time()))
        db.execute('DELETE FROM mail_filter_queue WHERE account=? AND message_id=?',(message['account'],message['message_id']))
        if state!='moving' and (match or state not in ('unmatched','gone')):rules.log(db,message,rule,state,target,detail)

# ==========================================
# Function: Claim a logical move atomically after provider preflight and before any remote mutation.
# Method: Recheck source identity and prior ownership under a short write transaction so competing snapshots cannot both issue MOVE.
# ==========================================
def claim(store,message,match,manual):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE');previous=db.execute('SELECT state FROM mail_filter_seen WHERE account=? AND message_id=?',(message['account'],message['message_id'])).fetchone()
        current=db.execute('SELECT remote_gone,account,folder,validity,uid FROM messages WHERE id=?',(message['id'],)).fetchone()
        if current is None or current['remote_gone'] or any(current[key]!=message[key] for key in ('account','folder','validity','uid')):return 'gone'
        if previous and previous['state'] in ('moving','uncertain'):return 'uncertain'
        if not manual and (previous is None or previous['state']!='queued'):return 'already'
        finish(store,message,match,'moving','正在移动；中断后的结果需要核对',_db=db)
    return 'claimed'

# ==========================================
# Function: Move one matched source with the application's existing UID-generation and targeted-expunge safeguards.
# Method: Check destination and original source, persist a moving intent before the provider mutation and never replay ambiguous attempts.
# ==========================================
def execute(store,message,match,client=None,local=False,manual=False):
    from . import folders,transport
    target=match['destination']
    with store.db() as db:previous=db.execute('SELECT state FROM mail_filter_seen WHERE account=? AND message_id=?',(message['account'],message['message_id'])).fetchone()
    if previous and previous['state'] in ('moving','uncertain'):
        return 'uncertain','上次移动结果待核对；请先同步，在来源和目标文件夹核对后使用普通移动处理'
    if message['remote_gone']:return 'gone','原件已不在来源文件夹'
    if target==message['folder']:
        finish(store,message,match,'unchanged','已经位于目标文件夹');return 'unchanged','已经位于目标文件夹'
    destination=next((row for row in store.list_folders(message['account']) if row['folder']==target and row['selectable']),None)
    if destination is None:
        detail='目标文件夹不存在或不可选择，请修正过滤器后手动运行';finish(store,message,match,'failed',detail);return 'failed',detail
    try:
        if not local:
            folders.select_message(client,message)
            flags=transport.flag_rows(transport.checked(client.uid('FETCH',message['uid'],'(UID FLAGS)'),'核对过滤器原件'))
            if message['uid'] not in flags:raise ValueError('服务器原件已变更，请先同步后手动运行')
    except Exception:
        detail='核对来源邮件失败，请同步后手动运行';finish(store,message,match,'failed',detail);return 'failed',detail
    claimed=claim(store,message,match,manual)
    if claimed!='claimed':return claimed,'来源已经处理、变更或有移动需要核对'
    try:mapping=None if local else folders.transfer_selected(client,message,target)
    except Exception:
        detail='移动结果待核对，不自动重试；请同步并核对来源和目标文件夹';finish(store,message,match,'uncertain',detail);return 'uncertain',detail
    try:store.transfer_local(message['id'],target,local=local,mapping=mapping)
    except Exception:
        if local:
            detail='本地移动失败，请检查存储后重新预览';finish(store,message,match,'failed',detail);return 'failed',detail
        detail='云端已确认移动，缓存等待下次同步更新';finish(store,message,match,'moved',detail);return 'moved',detail
    finish(store,message,match,'moved',match['reason']);return 'moved',match['reason']

# ==========================================
# Function: Evaluate only durable post-baseline new-arrival jobs for one synchronized account.
# Method: Process at most100 logical sources, share the authenticated session and yield before another candidate when user work queues.
# ==========================================
def automatic(account,store,client,should_yield=None,report=None):
    from .sync_batches import checkpoint
    report=report if report is not None else {};report.update(processed=0,moved=0,failed=0)
    items=rules.rules(store,account.id)
    if not items:
        with store.db() as db:
            report['processed']=db.execute('SELECT count(*) FROM mail_filter_queue WHERE account=?',(account.id,)).fetchone()[0]
            db.execute("UPDATE mail_filter_seen SET state='unmatched',updated=? WHERE account=? AND state='queued'",(time.time(),account.id))
            db.execute('DELETE FROM mail_filter_queue WHERE account=?',(account.id,))
        report['pending']=0;return report
    ctx=context(store)
    with store.db() as db:pending=[row[0] for row in db.execute('SELECT message FROM mail_filter_queue WHERE account=? ORDER BY rowid LIMIT 100',(account.id,))]
    for identity in pending:
        checkpoint(should_yield)
        try:message=source(store,identity)
        except ValueError:
            with store.db() as db:db.execute('DELETE FROM mail_filter_queue WHERE message=?',(identity,))
            continue
        if message['remote_gone']:finish(store,message,None,'gone','原件已移动');continue
        match=first_match(message,items,ctx) if items else None
        if match is None:finish(store,message,None,'unmatched','未匹配启用的过滤器');state='unmatched'
        else:state,unused=execute(store,message,match,client)
        report['processed']+=1;report['moved']+=int(state=='moved');report['failed']+=int(state in ('failed','uncertain'))
    with store.db() as db:report['pending']=db.execute('SELECT count(*) FROM mail_filter_queue WHERE account=?',(account.id,)).fetchone()[0]
    return report

# ==========================================
# Function: Preview exact cached source/destination choices before any manual provider mutation.
# Method: Stream cached rows, apply the same ordered matcher and bind the prepared snapshot to rule/model revisions.
# ==========================================
def preview(store,accounts,account='',folder='',subfolders=False,rule_id='',limit=1000):
    if account and account not in accounts:raise ValueError('请选择有效账号')
    if folder and not account:raise ValueError('请先选择账号，再选择来源文件夹')
    items=rules.rules(store)
    ctx=context(store);fingerprint=rules.fingerprint(store);entries=[];seen=set();scanned=0;unchanged=0;uncertain=0;truncated=False
    if folder and (account,folder) not in ctx['folders']:raise ValueError('来源文件夹已变更，请重新选择')
    parameters=[];where=['remote_gone=0',"folder NOT LIKE '@%'"]
    if account:where.append('account=?');parameters.append(account)
    else:
        if not accounts:return {'fingerprint':fingerprint,'entries':[],'scanned':0,'unchanged':0,'uncertain':0,'truncated':False}
        where.append('account IN ('+','.join('?' for unused in accounts)+')');parameters.extend(accounts)
    delimiter=ctx['folders'].get((account,folder),{}).get('delimiter')
    with store.db() as db:
        cursor=db.execute('SELECT id,account,folder,validity,uid,message_id,parsed,category,reason,seen,remote_gone,length(raw) AS raw_size FROM messages WHERE '+' AND '.join(where)+" ORDER BY (upper(folder)='INBOX') DESC,timestamp DESC,id",parameters)
        while rows:=cursor.fetchmany(24):
            for row in rows:
                message=dict(row);path=message['folder']
                if folder and path!=folder and not (subfolders and delimiter and path.startswith(folder+delimiter)):continue
                logical=(message['account'],message['message_id'])
                if logical in seen:continue
                seen.add(logical);scanned+=1;message['parsed']=json.loads(message['parsed']);match=first_match(message,items,ctx)
                if match is None:continue
                if rule_id and match['rule']!=rule_id:continue
                if match['destination']==path:unchanged+=1;continue
                state=db.execute('SELECT state FROM mail_filter_seen WHERE account=? AND message_id=?',logical).fetchone()
                if state and state['state'] in ('moving','uncertain'):uncertain+=1;continue
                entries.append({key:message[key] for key in ('id','account','folder','validity','uid','message_id')}|match|{'subject':message['parsed']['subject'][:200]})
                if len(entries)>=limit:truncated=True;break
            if truncated:break
    if rules.fingerprint(store)!=fingerprint:raise ValueError('预览期间过滤器发生变化，请重新预览')
    return {'fingerprint':fingerprint,'entries':entries,'scanned':scanned,'unchanged':unchanged,'uncertain':uncertain,'truncated':truncated,'created':time.time()}

# ==========================================
# Function: Run a prepared manual snapshot with exact source checks and foreground-friendly pause/resume.
# Method: Retain sessions per account within bounded turns, revalidate rule revisions and never implicitly include newly arrived cache rows.
# ==========================================
def manual(service,plan):
    from . import transport
    if not isinstance(plan,dict) or not isinstance(plan.get('entries'),list) or len(plan['entries'])>1000:raise ValueError('请先预览，单次最多运行1000封匹配邮件')
    if plan.get('fingerprint')!=rules.fingerprint(service.store):raise ValueError('过滤器或学习样本已变更，请重新预览')
    if not service._filter_run_lock.acquire(blocking=False):raise ValueError('已有过滤器正在手动运行')
    service.filter_cancel_event.clear();report={'running':True,'processed':0,'moved':0,'failed':0,'skipped':0,'total':len(plan['entries']),'cancelled':False,'errors':[]};service.status['filters']=report;index=0
    try:
        while index<len(plan['entries']):
            if service.stop_event.is_set() or service.filter_cancel_event.is_set():report['cancelled']=True;break
            with service.lock.background():
                if service.stop_event.is_set() or service.filter_cancel_event.is_set():report['cancelled']=True;break
                if service.sync_should_yield():continue
                if rules.fingerprint(service.store)!=plan['fingerprint']:raise ValueError('运行期间过滤器发生变化；已完成的移动保留，请重新预览剩余邮件')
                items=rules.rules(service.store);ctx=context(service.store);account=plan['entries'][index]['account'];descriptor=service.accounts.get(account)
                local=service.demo or account==LOCAL_ACCOUNT;connection=nullcontext(None) if local else transport.imap_connection(descriptor) if descriptor else None
                if connection is None:raise ValueError('账号已移除，请重新预览')
                try:
                    with connection as client:
                        turn=0
                        while index<len(plan['entries']) and plan['entries'][index]['account']==account and turn<25:
                            if service.sync_should_yield() or service.filter_cancel_event.is_set():break
                            entry=plan['entries'][index];index+=1;turn+=1
                            try:
                                message=source(service.store,entry['id'])
                                if any(message[key]!=entry[key] for key in ('account','folder','validity','uid','message_id')) or message['remote_gone']:report['skipped']+=1;continue
                                match=first_match(message,items,ctx)
                                if not match or match['rule']!=entry['rule'] or match['destination']!=entry['destination']:report['skipped']+=1;continue
                                state,detail=execute(service.store,message,match,client,local=local or is_local_message(message),manual=True)
                                report['moved']+=int(state=='moved');report['failed']+=int(state in ('failed','uncertain'));report['skipped']+=int(state in ('unchanged','gone','already'))
                                if state in ('failed','uncertain'):report['errors'].append(detail)
                            except Exception as error:report['failed']+=1;report['errors'].append(str(error))
                            finally:report['processed']+=1
                except (OSError,transport.imaplib.IMAP4.error):
                    report['failed']+=1;report['errors'].append('连接失败；剩余邮件未运行，请重新预览');break
        if report['moved']:service.request_sync()
        return report
    finally:report['running']=False;service._filter_run_lock.release()
