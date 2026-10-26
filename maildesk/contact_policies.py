"""Local per-person conversation visibility, ordering and notification preferences."""
from .participant_identity import normalize_address,parse_participants

# ==========================================
# Function: Install durable contact policies independently of message and address membership state.
# Method: Add one person-keyed table without rewriting cached mail or existing address-book rows.
# ==========================================
def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS contact_preferences(
        person TEXT PRIMARY KEY,muted INTEGER NOT NULL DEFAULT 0,
        pinned INTEGER NOT NULL DEFAULT 0,blocked INTEGER NOT NULL DEFAULT 0)''')

# ==========================================
# Function: Load explicit settings for a saved person, defaulting to normal conversation behavior.
# Method: Return plain booleans using the stable address-book identity.
# ==========================================
def get(store,person):
    with store.db() as db:row=db.execute('SELECT muted,pinned,blocked FROM contact_preferences WHERE person=?',(person,)).fetchone()
    return {key:bool(row[key]) if row else False for key in ('muted','pinned','blocked')}

# ==========================================
# Function: Save a complete immutable batch of explicitly edited contact settings.
# Method: Validate every stable person and commit the coalesced switch values in one transaction.
# ==========================================
def save_many(store,changes):
    if not changes or len(changes)>100:raise ValueError('联系人设置数量无效')
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        for person,values in changes.items():
            if not {'muted','pinned','blocked'}<=set(values) or set(values)-{'muted','pinned','blocked','starred'} or any(not isinstance(value,bool) for value in values.values()):raise ValueError('联系人设置无效')
            if not db.execute('SELECT 1 FROM address_people WHERE id=?',(person,)).fetchone():raise ValueError('联系人已变更，请刷新后重试')
            db.execute('''INSERT INTO contact_preferences(person,muted,pinned,blocked) VALUES(?,?,?,?)
                ON CONFLICT(person) DO UPDATE SET muted=excluded.muted,pinned=excluded.pinned,blocked=excluded.blocked''',
                (person,int(values['muted']),int(values['pinned']),int(values['blocked'])))
            if 'starred' in values:db.execute('UPDATE address_people SET starred=? WHERE id=?',(int(values['starred']),person))

# ==========================================
# Function: Preserve conservative policy settings when explicit address-book people are merged.
# Method: Retain any mute/pin/block flag on the chosen target and remove orphaned source preferences.
# ==========================================
def merge(db,target,sources):
    people=[target,*sources];marks=','.join('?' for _ in people)
    flags=db.execute('SELECT max(muted),max(pinned),max(blocked) FROM contact_preferences WHERE person IN ('+marks+')',people).fetchone()
    db.execute('INSERT OR REPLACE INTO contact_preferences VALUES(?,?,?,?)',(target,*[int(value or 0) for value in flags]))
    db.execute('DELETE FROM contact_preferences WHERE person IN ('+','.join('?' for _ in sources)+')',sources)

# ==========================================
# Function: Resolve every active alias whose person must remain quiet.
# Method: Share one policy projection for message, reminder and receipt notification filtering.
# ==========================================
def quiet_addresses(db):
    return frozenset(row[0] for row in db.execute('''SELECT a.address FROM address_mailboxes a
        JOIN contact_preferences p ON p.person=a.person WHERE a.suppressed=0 AND (p.muted=1 OR p.blocked=1)'''))

# ==========================================
# Function: Decide whether an actual sender may contribute to a desktop notification.
# Method: Normalize only original From metadata, never body text or recipient guesses.
# ==========================================
def allows_notice(raw_from,quiet):
    return normalize_address(raw_from or '') not in quiet

# ==========================================
# Function: Honor quiet contacts for both inbound mail and own-sent copies or follow-up reminders.
# Method: Check actual sender first and read recipient headers only for an own-sent notice candidate.
# ==========================================
def allows_message_notice(store,message,quiet,own):
    if not allows_notice(message['raw_from'],quiet):return False
    if not quiet or normalize_address(message['raw_from'] or '') not in own:return True
    with store.db() as db:
        row=db.execute("SELECT json_extract(parsed,'$.headers.to'),json_extract(parsed,'$.headers.cc'),json_extract(parsed,'$.headers.bcc') FROM messages WHERE id=?",(message['id'],)).fetchone()
    if row is None:return False
    return not any(participant['address'] in quiet for participant in parse_participants(list(row)))

# ==========================================
# Function: Toggle one selected contact policy atomically without overwriting other person settings.
# Method: Turn the whole explicit selection off when all are enabled, otherwise enable all; validate every identity first.
# ==========================================
def toggle_many(store,people,key):
    people=list(dict.fromkeys(people))
    if key not in ('muted','pinned','blocked') or not people or len(people)>100:raise ValueError('请选择 1 至 100 位联系人')
    marks=','.join('?' for _ in people)
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT p.id,coalesce(cp.'+key+',0) AS flag FROM address_people p LEFT JOIN contact_preferences cp ON cp.person=p.id WHERE p.id IN ('+marks+')',people).fetchall()
        if len(rows)!=len(people):raise ValueError('联系人已变更，请刷新后重新选择')
        enabled=not all(row['flag'] for row in rows)
        db.executemany('INSERT OR IGNORE INTO contact_preferences(person) VALUES(?)',[(person,) for person in people])
        db.execute('UPDATE contact_preferences SET '+key+'=? WHERE person IN ('+marks+')',[int(enabled),*people])
    return enabled
