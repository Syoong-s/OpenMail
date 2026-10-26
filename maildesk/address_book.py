"""Durable local people observed from inbound senders and verified own-sent recipients."""
import json
import time
import uuid
import unicodedata
from email.utils import getaddresses
from email.parser import BytesHeaderParser
from email import policy
from .participant_identity import normalize_address, _single_from, parse_participants, own_identities

# ==========================================
# Function: Add the local address book without changing existing mail or drafts.
# Method: Add people, mailbox suppression, durable stars and bounded migration ledgers additively.
# ==========================================
def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS address_people(
        id TEXT PRIMARY KEY,name TEXT NOT NULL DEFAULT '',custom_name INTEGER NOT NULL DEFAULT 0,
        conversation TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS address_mailboxes(
        address TEXT PRIMARY KEY,person TEXT REFERENCES address_people(id),observed_name TEXT NOT NULL DEFAULT '',
        suppressed INTEGER NOT NULL DEFAULT 0,last_seen REAL NOT NULL DEFAULT 0);
        CREATE INDEX IF NOT EXISTS address_person ON address_mailboxes(person,suppressed);
        CREATE TABLE IF NOT EXISTS address_migrations(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS address_observed(message TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS address_pending(message TEXT PRIMARY KEY);
    ''')
    if 'starred' not in {row[1] for row in db.execute('PRAGMA table_info(address_people)')}:
        db.execute('ALTER TABLE address_people ADD COLUMN starred INTEGER NOT NULL DEFAULT 0')
    from .contact_policies import initialize as initialize_policies
    initialize_policies(db)

# ==========================================
# Function: Record exactly one valid actual From mailbox in the current transaction.
# Method: Reject ambiguous/multiple From headers and honor durable per-address suppression.
# ==========================================
def observe(db, raw_from, timestamp=0):
    if not _single_from(raw_from):return
    name,address=getaddresses([raw_from])[0];address=normalize_address(address)
    if not address:return
    row=db.execute('SELECT person,suppressed,last_seen,observed_name FROM address_mailboxes WHERE address=?',(address,)).fetchone()
    if row and row['suppressed']:return
    name=' '.join(name.split())[:256]
    if row:
        if timestamp<row['last_seen'] and row['observed_name']:name=''
        db.execute('UPDATE address_mailboxes SET observed_name=CASE WHEN ?<>\'\' THEN ? ELSE observed_name END,last_seen=max(last_seen,?) WHERE address=?',(name,name,timestamp,address))
        if name:db.execute("UPDATE address_people SET name=? WHERE id=? AND custom_name=0",(name,row['person']))
    else:
        person=uuid.uuid4().hex
        db.execute('INSERT INTO address_people(id,name) VALUES(?,?)',(person,name))
        db.execute('INSERT INTO address_mailboxes(address,person,observed_name,last_seen) VALUES(?,?,?,?)',(address,person,name,timestamp))

# ==========================================
# Function: Resolve the live configured own-account set without guessing provider aliases.
# Method: Accept the service callback or an explicit immutable identity set in offline diagnostics.
# ==========================================
def own_addresses(store):
    value=getattr(store,'own_addresses',())
    return own_identities(value() if callable(value) else value)

# ==========================================
# Function: Observe inbound senders and each actual recipient of a valid own-sent message.
# Method: Exclude own identities and never promote incoming To/Cc/Bcc addresses to contacts.
# ==========================================
def observe_message(db,parsed,own):
    headers=parsed.get('headers') or {};raw=headers.get('from',parsed.get('sender',''))
    if not parsed.get('from_valid',True) or not _single_from(raw):return
    sender=parse_participants(raw);outgoing=sender[0]['address'] in own
    participants=parse_participants([headers.get(key,'') for key in ('to','cc','bcc')]) if outgoing else sender
    for participant in participants:
        if participant['address'] not in own:
            from email.headerregistry import Address
            local,domain=participant['address'].rsplit('@',1)
            observe(db,str(Address(display_name=participant['name'],username=local,domain=domain)),parsed.get('timestamp',0))

# ==========================================
# Function: Migrate saved names and inbound/outbound participant metadata incrementally.
# Method: Bound each background batch; ledger all rows, including rejected/suppressed senders.
# ==========================================
def backfill(store,limit=128):
    limit=min(256,max(1,int(limit)));own=own_addresses(store)
    import hashlib
    migration='participants-v2:'+hashlib.sha256(json.dumps(sorted(own)).encode()).hexdigest()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM address_migrations WHERE key='legacy'").fetchone():
            row=db.execute("SELECT value FROM preferences WHERE key='contacts'").fetchone()
            try:legacy=json.loads(row['value']) if row else {}
            except (TypeError,ValueError):legacy={}
            for value,name in legacy.items() if isinstance(legacy,dict) else ():
                address=normalize_address(value)
                if not address:continue
                observe(db,address)
                db.execute('UPDATE address_people SET name=?,custom_name=1 WHERE id=(SELECT person FROM address_mailboxes WHERE address=?)',(' '.join(str(name).split())[:256],address))
            db.execute("INSERT INTO address_migrations VALUES('legacy','1')")
        active=db.execute("SELECT value FROM address_migrations WHERE key='participants-active'").fetchone()
        if not active or active[0]!=migration:
            db.execute('DELETE FROM address_observed');db.execute("DELETE FROM address_migrations WHERE key='complete'");db.execute("INSERT INTO address_migrations VALUES('participants-active',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(migration,))
        complete=bool(db.execute("SELECT 1 FROM address_migrations WHERE key='complete'").fetchone())
        join='JOIN address_pending o ON o.message=m.id' if complete else 'LEFT JOIN address_observed o ON o.message=m.id'
        where='' if complete else 'WHERE o.message IS NULL'
        candidates=db.execute('SELECT m.id,length(CAST(m.parsed AS BLOB)) AS bytes FROM messages m '+join+' '+where+' ORDER BY m.rowid LIMIT ?',(limit,)).fetchall()
        processed=0;admitted_bytes=0;limited=False
        for candidate in candidates:
            if processed and admitted_bytes+candidate['bytes']>4*1024*1024:limited=True;break
            row=db.execute("""SELECT m.id,json_extract(m.parsed,'$.headers') AS headers,json_extract(m.parsed,'$.headers.from') AS raw_from,
                json_extract(m.parsed,'$.sender') AS sender,json_extract(m.parsed,'$.from_valid') AS from_valid,
                CASE WHEN json_type(m.parsed,'$.from_valid') IS NULL THEN substr(m.raw,1,65536) END AS legacy_headers,
                m.timestamp FROM messages m WHERE m.id=?""",(candidate['id'],)).fetchone()
            admitted_bytes+=candidate['bytes'];processed+=1
            raw_from=row['raw_from'] if row['raw_from'] is not None else row['sender']
            valid=row['from_valid']
            if valid is None:
                head=row['legacy_headers'] or b''
                if b'\r\n\r\n' in head or b'\n\n' in head:
                    header=BytesHeaderParser(policy=policy.default).parsebytes(head)
                    raw_from=', '.join(str(value) for value in header.get_all('From',[]))
                    valid=len(header.get_all('From',[]))==1
                else:valid=False
            if valid:
                headers=json.loads(row['headers'] or '{}');headers['from']=raw_from
                observe_message(db,{'headers':headers,'from_valid':True,'timestamp':row['timestamp']},own)
            db.execute('INSERT OR IGNORE INTO address_observed VALUES(?)',(row['id'],))
            db.execute('DELETE FROM address_pending WHERE message=?',(row['id'],))
        done=not limited and len(candidates)<limit
        if done:db.execute("INSERT OR IGNORE INTO address_migrations VALUES('complete','1')")
    return {'processed':processed,'complete':done,'metadata_bytes':admitted_bytes,'byte_budget':4*1024*1024}

# ==========================================
# Function: Normalize searchable directory text without guessing transliterations.
# Method: Casefold Unicode and remove combining accents while preserving non-Latin names.
# ==========================================
def directory_fold(value):
    return ''.join(char for char in unicodedata.normalize('NFKD',str(value or '').casefold()) if not unicodedata.combining(char))

# ==========================================
# Function: Group a real name or mailbox into a global alphabetical directory.
# Method: Use its folded first character; retain non-Latin identities in the final hash bucket.
# ==========================================
def directory_letter(value):
    first=directory_fold(value).strip()[:1].upper()
    return first if first and 'A'<=first<='Z' else '#'

# ==========================================
# Function: Fetch a bounded searchable window or locate a global letter outside that window.
# Method: Put starred people first, then fold Unicode and calculate matching global letter offsets in SQL.
# ==========================================
def page(store,search='',offset=0,limit=40,letter=''):
    term=directory_fold(search.strip()[:256]);limit=min(120,max(1,int(limit)))
    display="coalesce(nullif(p.name,''),(SELECT min(address) FROM address_mailboxes WHERE person=p.id AND suppressed=0),'')"
    alphabet='directory_letter('+display+')'
    bucket="CASE WHEN p.starred=1 THEN '★' ELSE "+alphabet+' END'
    order="p.starred DESC,CASE WHEN "+bucket+"='#' THEN 1 ELSE 0 END,"+bucket+",directory_fold("+display+"),p.id"
    where="EXISTS(SELECT 1 FROM address_mailboxes a WHERE a.person=p.id AND a.suppressed=0 AND (instr(directory_fold(a.address),?)>0 OR instr(directory_fold(a.observed_name),?)>0 OR instr(directory_fold(p.name),?)>0))"
    with store.db() as db:
        db.create_function('directory_fold',1,directory_fold,deterministic=True);db.create_function('directory_letter',1,directory_letter,deterministic=True)
        total=db.execute('SELECT count(*) FROM address_people p WHERE '+where,(term,term,term)).fetchone()[0]
        letters=[row[0] for row in db.execute('SELECT DISTINCT '+bucket+' FROM address_people p WHERE '+where,(term,term,term))]
        if letter:
            predicate='0' if letter=='★' else ("p.starred=1 OR (p.starred=0 AND "+alphabet+"<>'#'"+(" AND "+alphabet+'<?' if letter!='#' else '')+")")
            args=(term,term,term,letter) if letter not in ('★','#') else (term,term,term)
            offset=db.execute('SELECT count(*) FROM address_people p WHERE '+where+' AND ('+predicate+')',args).fetchone()[0]
        jump_offset=int(offset) if letter else None
        if letter:offset=max(0,offset-min(40,limit//3))
        offset=min(max(0,int(offset)),max(0,total-1))
        rows=db.execute('SELECT p.*,coalesce(cp.muted,0) AS muted,coalesce(cp.pinned,0) AS pinned,coalesce(cp.blocked,0) AS blocked,'+bucket+' AS letter FROM address_people p LEFT JOIN contact_preferences cp ON cp.person=p.id WHERE '+where+' ORDER BY '+order+' LIMIT ? OFFSET ?',(term,term,term,limit,offset)).fetchall()
        items=[]
        for row in rows:
            item=dict(row);item['addresses']=[r[0] for r in db.execute('SELECT address FROM address_mailboxes WHERE person=? AND suppressed=0 ORDER BY address LIMIT 100',(row['id'],))];items.append(item)
    return {'items':items,'total':total,'offset':offset,'letters':letters,'jump_offset':jump_offset}

# ==========================================
# Function: Resolve only a validated actual sender from modern or legacy selected mail.
# Method: Honor explicit validity; for old rows inspect at most 64 KiB of unique original From headers.
# ==========================================
def message_sender_address(store,identity,parsed):
    valid=parsed.get('from_valid')
    raw_from=(parsed.get('headers') or {}).get('from',parsed.get('sender',''))
    if valid is None:
        with store.db() as db:row=db.execute('SELECT substr(raw,1,65536) FROM messages WHERE id=?',(identity,)).fetchone()
        head=row[0] if row and row[0] else b''
        if b'\r\n\r\n' not in head and b'\n\n' not in head:return ''
        headers=BytesHeaderParser(policy=policy.default).parsebytes(head)
        senders=headers.get_all('From',[])
        if len(senders)!=1:return ''
        raw_from=str(senders[0]);valid=True
    return normalize_address(raw_from) if valid and _single_from(raw_from) else ''

# ==========================================
# Function: Read the canonical saved person belonging only to a valid original sender.
# Method: Resolve one mailbox or explicit person key and at most one hundred saved aliases off GTK.
# ==========================================
def sender_detail(store,address='',person=''):
    address=normalize_address(address)
    with store.db() as db:
        row=db.execute('SELECT p.id,p.name,p.starred,coalesce(cp.muted,0) AS muted,coalesce(cp.pinned,0) AS pinned,coalesce(cp.blocked,0) AS blocked FROM address_people p LEFT JOIN contact_preferences cp ON cp.person=p.id WHERE p.id=?',(person,)).fetchone() if person else db.execute('SELECT p.id,p.name,p.starred,coalesce(cp.muted,0) AS muted,coalesce(cp.pinned,0) AS pinned,coalesce(cp.blocked,0) AS blocked FROM address_people p JOIN address_mailboxes a ON a.person=p.id LEFT JOIN contact_preferences cp ON cp.person=p.id WHERE a.address=? AND a.suppressed=0',(address,)).fetchone()
        if not row:return {'name':'','addresses':[address] if address else []}
        return {**dict(row),'addresses':[item[0] for item in db.execute('SELECT address FROM address_mailboxes WHERE person=? AND suppressed=0 ORDER BY address LIMIT 100',(row['id'],))]}

# ==========================================
# Function: Save an explicitly edited person's name and complete mailbox membership.
# Method: Validate each bare mailbox, reject silent merges and suppress removed addresses.
# ==========================================
def save(store,person,name,addresses):
    normalized=[]
    for value in addresses:
        value=value.strip()
        if not value:continue
        address=normalize_address(value)
        if not _single_from(value) or not address or address!=value.casefold():raise ValueError('请逐行填写有效的纯邮箱地址')
        if address not in normalized:normalized.append(address)
    if not normalized or len(normalized)>100:raise ValueError('每位联系人需要 1 至 100 个邮箱地址')
    person=person or uuid.uuid4().hex;name=' '.join(str(name).split())[:256]
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for address in normalized:
            other=db.execute('SELECT person,suppressed FROM address_mailboxes WHERE address=?',(address,)).fetchone()
            if other and not other['suppressed'] and other['person']!=person:raise ValueError('该地址已属于另一位联系人，请使用“合并到此人”')
        conversation='contact:person:'+person if len(normalized)>1 else ''
        db.execute('INSERT INTO address_people(id,name,custom_name,conversation) VALUES(?,?,1,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,custom_name=1,conversation=CASE WHEN excluded.conversation<>\'\' THEN excluded.conversation ELSE address_people.conversation END',(person,name,conversation))
        db.execute('UPDATE address_mailboxes SET person=NULL,suppressed=1 WHERE person=? AND address NOT IN ('+','.join('?' for _ in normalized)+')',[person,*normalized])
        for address in normalized:db.execute('INSERT INTO address_mailboxes(address,person) VALUES(?,?) ON CONFLICT(address) DO UPDATE SET person=excluded.person,suppressed=0',(address,person))
    return person

# ==========================================
# Function: Delete a person without letting cached or future mail recreate the entry.
# Method: Retain mailbox tombstones until an explicit manual re-add and leave all mail/drafts intact.
# ==========================================
def remove(store,person):
    with store.db() as db:
        db.execute('UPDATE address_mailboxes SET person=NULL,suppressed=1 WHERE person=?',(person,))
        db.execute('DELETE FROM contact_preferences WHERE person=?',(person,))
        db.execute('DELETE FROM address_people WHERE id=?',(person,))

# ==========================================
# Function: Delete a bounded explicit bulk selection in one local transaction.
# Method: Validate every stable person first, then suppress aliases and remove people atomically.
# ==========================================
def remove_many(store,people):
    people=list(dict.fromkeys(people))
    if not people or len(people)>100:raise ValueError('每次请选择 1 至 100 位联系人')
    marks=','.join('?' for _ in people)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT count(*) FROM address_people WHERE id IN ('+marks+')',people).fetchone()[0]!=len(people):raise ValueError('联系人已变更，请刷新后重新选择')
        db.execute('UPDATE address_mailboxes SET person=NULL,suppressed=1 WHERE person IN ('+marks+')',people)
        db.execute('DELETE FROM contact_preferences WHERE person IN ('+marks+')',people)
        db.execute('DELETE FROM address_people WHERE id IN ('+marks+')',people)

# ==========================================
# Function: Merge two explicitly selected people while preserving exact mail routes and drafts.
# Method: Move mailbox membership transactionally; group only direct conversations via SQL projection.
# ==========================================
def merge(store,target,source):
    return merge_many(store,target,[source])

# ==========================================
# Function: Merge a bounded explicitly selected set of people in one durable transaction.
# Method: Validate all memberships first, preserve the target's name and leave mail/draft records untouched.
# ==========================================
def merge_many(store,target,sources):
    sources=list(dict.fromkeys(sources))
    if not target or not sources or target in sources or len(sources)>100:raise ValueError('请选择不同的来源和目标联系人（每次最多 100 位）')
    people=[target,*sources];marks=','.join('?' for _ in people);source_marks=','.join('?' for _ in sources)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT count(*) FROM address_people WHERE id IN ('+marks+')',people).fetchone()[0]!=len(people):raise ValueError('联系人已变更，请刷新后重试')
        if db.execute('SELECT count(*) FROM address_mailboxes WHERE person IN ('+marks+') AND suppressed=0',people).fetchone()[0]>100:raise ValueError('合并后每位联系人最多 100 个邮箱地址')
        from .contact_policies import merge as merge_policies
        merge_policies(db,target,sources)
        db.execute('UPDATE address_mailboxes SET person=? WHERE person IN ('+source_marks+')',[target,*sources])
        db.execute('UPDATE address_people SET conversation=?,custom_name=1,starred=(SELECT max(starred) FROM address_people WHERE id IN ('+marks+')) WHERE id=?',['contact:person:'+target,*people,target])
        db.execute('DELETE FROM address_people WHERE id IN ('+source_marks+')',sources)

# ==========================================
# Function: Split one selected address into its own independent local person.
# Method: Keep the address active with its observed name while preserving other memberships.
# ==========================================
def split(store,person,address):
    with store.db() as db:
        row=db.execute('SELECT observed_name FROM address_mailboxes WHERE person=? AND address=? AND suppressed=0',(person,address)).fetchone()
        if not row:raise ValueError('请选择此联系人的一个邮箱地址')
        identity=uuid.uuid4().hex
        db.execute('INSERT INTO address_people(id,name,starred) SELECT ?,?,starred FROM address_people WHERE id=?',(identity,row['observed_name'],person))
        db.execute('INSERT INTO contact_preferences SELECT ?,muted,pinned,blocked FROM contact_preferences WHERE person=?',(identity,person))
        db.execute('UPDATE address_mailboxes SET person=? WHERE person=? AND address=?',(identity,person,address))
    return identity

# ==========================================
# Function: Offer bounded local completion using current merged/custom person names.
# Method: Join durable mailboxes only, excluding suppressed contacts and full-mail JSON scans.
# ==========================================
def suggestions(store,limit=300):
    with store.db() as db:return [(row['address'],row['name'] or row['observed_name']) for row in db.execute('SELECT a.address,p.name,a.observed_name FROM address_mailboxes a JOIN address_people p ON p.id=a.person WHERE a.suppressed=0 ORDER BY p.starred DESC,a.last_seen DESC,a.address LIMIT ?',(min(300,max(1,limit)),))]

# ==========================================
# Function: Star or unstar an explicit bounded set of saved people independently of chat pinning.
# Method: Validate stable identities and commit one person-level flag for all aliases atomically.
# ==========================================
def star_many(store,people,enabled=True):
    people=list(dict.fromkeys(people))
    if not people or len(people)>100 or not isinstance(enabled,bool):raise ValueError('每次请选择 1 至 100 位联系人')
    marks=','.join('?' for _ in people)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT count(*) FROM address_people WHERE id IN ('+marks+')',people).fetchone()[0]!=len(people):raise ValueError('联系人已变更，请刷新后重新选择')
        db.execute('UPDATE address_people SET starred=? WHERE id IN ('+marks+')',[int(enabled),*people])
