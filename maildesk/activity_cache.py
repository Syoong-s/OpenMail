"""Event-driven calendar metadata cache with bounded transactional change tracking."""
from collections import OrderedDict
from datetime import date
from .mail_activity import calendar_bounds,project_activity

HISTORY=8192
FIELDS='''m.id,m.account,m.folder,m.message_id,m.sender,m.subject,m.timestamp,m.seen,
    m.archived,m.done,m.trashed,m.spam,coalesce(f.special,'') AS special,
    coalesce(d.sender_name,'') AS sender_name,coalesce(d.recipients,'') AS recipients'''
JOINS=''' FROM messages m LEFT JOIN folders f ON f.account=m.account AND f.folder=m.folder
    LEFT JOIN message_display d ON d.message=m.id '''


# ==========================================
# Function: Record which envelopes actually changed without polling the annual mail range.
# Method: Coalesce IDs in transaction triggers and retain a bounded revision window for incremental readers.
# ==========================================
def initialize(db):
    db.executescript('''INSERT OR IGNORE INTO navigation_revision VALUES('activity',0);
        CREATE TABLE IF NOT EXISTS activity_changes(message TEXT PRIMARY KEY,revision INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS activity_changes_revision ON activity_changes(revision);''')
    change="UPDATE navigation_revision SET value=value+1 WHERE topic='activity'; "
    revision="(SELECT value FROM navigation_revision WHERE topic='activity')"
    prune=f'DELETE FROM activity_changes WHERE revision<{revision}-{HISTORY}; '
    for event,reference,condition in (
        ('INSERT','new',''),('DELETE','old',''),
        ('UPDATE OF account,folder,message_id,sender,subject,timestamp,seen,archived,done,trashed,spam,remote_gone','new',
         'WHEN '+' OR '.join('old.'+key+' IS NOT new.'+key for key in ('account','folder','message_id','sender','subject','timestamp','seen','archived','done','trashed','spam','remote_gone'))),
        ('UPDATE OF body','new','WHEN old.body IS NOT new.body')):
        suffix=event.split()[0].lower()+('_body' if event=='UPDATE OF body' else '')
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS activity_message_{suffix} AFTER {event} ON messages {condition} BEGIN
            {change} INSERT INTO activity_changes VALUES({reference}.id,{revision})
            ON CONFLICT(message) DO UPDATE SET revision=excluded.revision; {prune} END''')
    for event in ('INSERT','UPDATE'):
        condition='' if event=='INSERT' else 'WHEN old.sender_name IS NOT new.sender_name OR old.recipients IS NOT new.recipients'
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS activity_display_{event.lower()} AFTER {event} ON message_display {condition} BEGIN
            {change} INSERT INTO activity_changes VALUES(new.message,{revision})
            ON CONFLICT(message) DO UPDATE SET revision=excluded.revision; {prune} END''')
    for event,reference,condition in (('INSERT','new',''),('DELETE','old',''),('UPDATE','new','WHEN old.special IS NOT new.special')):
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS activity_folder_{event.lower()} AFTER {event} ON folders {condition} BEGIN
            {change} INSERT INTO activity_changes SELECT id,{revision} FROM messages
            WHERE account={reference}.account AND folder={reference}.folder
            ON CONFLICT(message) DO UPDATE SET revision=excluded.revision; {prune} END''')


# ==========================================
# Function: Retain calendar metadata across navigation, dates and account scopes.
# Method: Load the year once, patch changed envelopes and memoize scoped day projections without body decoding.
# ==========================================
class ActivityCache:
    # ==========================================
    # Function: Own one worker-confined cache for a mailbox store.
    # Method: Keep metadata and a small preview LRU separate from native row pagination.
    # ==========================================
    def __init__(self,store):
        self.store=store;self.rows={};self.revision=None;self.today=None;self.projections={};self.previews=OrderedDict()
        self.full_loads=0;self.patched_rows=0

    # ==========================================
    # Function: Refresh only the envelopes changed since the last successful snapshot.
    # Method: Read journal and metadata in one SQLite snapshot; fall back only at startup or after journal expiry.
    # ==========================================
    def update(self,db,today):
        revision=db.execute("SELECT value FROM navigation_revision WHERE topic='activity'").fetchone()[0]
        start,lower,upper=calendar_bounds(today)
        if self.revision==revision and self.today==today:return
        if self.revision is None or revision<self.revision or revision-self.revision>HISTORY or today<self.today:
            rows=db.execute('SELECT '+FIELDS+JOINS+'WHERE m.remote_gone=0 AND m.timestamp>=? AND m.timestamp<?',(lower,upper)).fetchall()
            self.rows={row['id']:dict(row) for row in rows};self.previews.clear();self.full_loads+=1
        else:
            if today!=self.today:
                self.rows={identity:row for identity,row in self.rows.items() if lower<=row['timestamp']<upper}
                previous_upper=calendar_bounds(self.today)[2]
                rows=db.execute('SELECT '+FIELDS+JOINS+'WHERE m.remote_gone=0 AND m.timestamp>=? AND m.timestamp<?',(max(lower,previous_upper),upper)).fetchall()
                self.rows.update((row['id'],dict(row)) for row in rows)
            changed=[row[0] for row in db.execute('SELECT message FROM activity_changes WHERE revision>?',(self.revision,))]
            for identity in changed:self.rows.pop(identity,None);self.previews.pop(identity,None)
            for offset in range(0,len(changed),400):
                ids=changed[offset:offset+400]
                rows=db.execute('SELECT '+FIELDS+JOINS+'WHERE m.id IN ('+','.join('?' for _ in ids)+') AND m.remote_gone=0 AND m.timestamp>=? AND m.timestamp<?',ids+[lower,upper]).fetchall()
                self.rows.update((row['id'],dict(row)) for row in rows)
            self.patched_rows+=len(changed)
        self.projections.clear();self.revision=revision;self.today=today

    # ==========================================
    # Function: Project cached statistics and fetch previews only for visible day rows.
    # Method: Reuse all-account envelopes across account/date changes and bound text snippets to 512 messages.
    # ==========================================
    def snapshot(self,accounts,scope=None,selected=None,limit=60,today=None):
        today=today or date.today();selected=selected or today
        with self.store.db() as db:
            db.execute('BEGIN');self.update(db,today)
            key=(tuple(sorted(accounts.items())),None if scope is None else tuple(sorted(scope)))
            if key not in self.projections:
                rows=self.rows.values() if scope is None else (row for row in self.rows.values() if row['account'] in scope)
                if len(self.projections)>=8:self.projections.clear()
                self.projections[key]=project_activity(rows,accounts,today)
            projection=self.projections[key];items=projection['by_day'].get(selected.isoformat(),[])
            visible=[dict(row) for row in items[:limit]];missing=[row['id'] for row in visible if row['id'] not in self.previews]
            for offset in range(0,len(missing),400):
                ids=missing[offset:offset+400]
                for identity,body in db.execute('SELECT id,substr(body,1,160) FROM messages WHERE id IN ('+','.join('?' for _ in ids)+')',ids):
                    self.previews[identity]=' '.join(body.split())
            for row in visible:
                row['preview']=self.previews.get(row['id'],'')
                if row['id'] in self.previews:self.previews.move_to_end(row['id'])
            while len(self.previews)>512:self.previews.popitem(last=False)
        return {key:value for key,value in projection.items() if key!='by_day'}|{'selected':selected.isoformat(),'items':visible,'total':len(items)}
