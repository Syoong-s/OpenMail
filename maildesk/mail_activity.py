"""Local calendar activity projections without MIME loading or provider traffic."""
from collections import defaultdict
from datetime import date,datetime,time,timedelta
import re
from .participant_identity import normalize_address


# ==========================================
# Function: Bound a complete 53-column calendar using the user's local civil dates.
# Method: Start on Monday and use midnight timestamps rather than fixed 86400-second days.
# ==========================================
def calendar_bounds(today):
    start=today-timedelta(days=364+today.weekday())
    return start,datetime.combine(start,time.min).timestamp(),datetime.combine(today+timedelta(days=1),time.min).timestamp()


# ==========================================
# Function: Count cached incoming/outgoing mail and project a selected day's lightweight timeline.
# Method: Read indexed envelope metadata, collapse same-account folder copies and paginate only native rows.
# ==========================================
def activity_snapshot(store,accounts,scope=None,selected=None,limit=60,today=None):
    today=today or date.today();selected=selected or today;start,lower,upper=calendar_bounds(today)
    where='m.remote_gone=0 AND m.timestamp>=? AND m.timestamp<?';parameters=[lower,upper]
    if scope is not None:
        where+=' AND m.account IN ('+','.join('?' for _ in scope)+')' if scope else ' AND 0'
        parameters.extend(scope)
    with store.db() as db:
        rows=db.execute('''SELECT m.id,m.account,m.folder,m.message_id,m.sender,m.subject,m.timestamp,m.seen,
            m.archived,m.done,m.trashed,m.spam,coalesce(f.special,'') AS special,
            coalesce(d.sender_name,'') AS sender_name,coalesce(d.recipients,'') AS recipients
            FROM messages m LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
            LEFT JOIN message_display d ON d.message=m.id WHERE '''+where+' ORDER BY m.timestamp DESC,m.id',parameters).fetchall()
        projection=project_activity(rows,accounts,today);items=[dict(row) for row in projection['by_day'].get(selected.isoformat(),[])];total=len(items);items=items[:limit]
        if items:
            previews=dict(db.execute('SELECT id,substr(body,1,160) FROM messages WHERE id IN ('+','.join('?' for _ in items)+')',[row['id'] for row in items]).fetchall())
            for row in items:row['preview']=' '.join(previews.get(row['id'],'').split())
    return {key:value for key,value in projection.items() if key!='by_day'}|{'selected':selected.isoformat(),'items':items,'total':total}


# ==========================================
# Function: Group cached envelope copies into reusable daily counts and timelines.
# Method: Preserve account ownership and trash/archive rules without issuing database queries.
# ==========================================
def project_activity(rows,accounts,today):
    start=calendar_bounds(today)[0];own={key:normalize_address(value) for key,value in accounts.items()}
    groups={}
    for raw in rows:
        row=dict(raw)
        if row['special']=='drafts' or row['folder']=='@drafts':continue
        # Missing Message-ID values must never collapse independent messages.
        message_id=row['message_id']
        if not message_id or re.fullmatch(r'<[0-9a-f]{64}@local>',message_id):message_id=row['id']
        key=(row['account'],message_id,row['sender'],row['subject'],row['timestamp'])
        groups.setdefault(key,[]).append(row)
    days=defaultdict(lambda:{'received':0,'sent':0});by_day=defaultdict(list)
    for copies in groups.values():
        # A moved-to-trash/junk copy hides the activity even while an All Mail copy awaits sync.
        if any(row['trashed'] or row['spam'] or row['special'] in ('trash','spam') for row in copies):continue
        row=min(copies,key=lambda row:(row['special']=='all',not (row['archived'] or row['special']=='archive'),row['folder'].upper()!='INBOX',row['id']))
        day=datetime.fromtimestamp(row['timestamp']).date()
        outgoing=any(copy['folder']=='@sent' or copy['special']=='sent' for copy in copies) or bool(own.get(row['account']) and normalize_address(row['sender'])==own[row['account']])
        direction='sent' if outgoing else 'received';days[day.isoformat()][direction]+=1
        row['direction']=direction;row['done']=bool(row['done'] or row['archived'] or row['special']=='archive')
        row['seen']=all(copy['seen'] for copy in copies);row['copy_ids']=[copy['id'] for copy in copies];by_day[day.isoformat()].append(row)
    for items in by_day.values():items.sort(key=lambda row:(-row['timestamp'],row['id']))
    return {'start':start.isoformat(),'today':today.isoformat(),'days':dict(days),'by_day':dict(by_day),
            'received':sum(day['received'] for day in days.values()),
            'sent':sum(day['sent'] for day in days.values()),'active_days':len(days)}
