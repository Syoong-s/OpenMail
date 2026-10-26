"""Account-scoped RFC reference components independent of arrival order."""
import json

# ==========================================
# Function: Maintain a bounded indexed graph of RFC reference identifiers.
# Method: Link each message to explicit References/In-Reply-To values without subject matching.
# ==========================================
def record_links(db,account,message):
    own=message['message_id']
    references=list(dict.fromkeys(message.get('references',[])+message.get('in_reply_to',[])))[:200]
    db.executemany('INSERT OR IGNORE INTO thread_links(account,source,target) VALUES(?,?,?)',[(account,own,value) for value in references if value and value!=own])

# ==========================================
# Function: Migrate cached RFC links once without discarding physical mail copies.
# Method: Backfill parsed metadata in batches and index both traversal directions.
# ==========================================
def initialize_graph(db):
    db.execute('CREATE TABLE IF NOT EXISTS thread_graph_migrations(version INTEGER PRIMARY KEY)')
    exists=db.execute('SELECT 1 FROM thread_graph_migrations WHERE version=1').fetchone()
    db.executescript('''CREATE TABLE IF NOT EXISTS thread_links(account TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(account,source,target));
    CREATE INDEX IF NOT EXISTS thread_links_reverse ON thread_links(account,target,source);
    CREATE INDEX IF NOT EXISTS message_rfc_identity ON messages(account,message_id);''')
    if not exists:
        cursor=db.execute('SELECT account,parsed FROM messages')
        while True:
            page=cursor.fetchmany(200)
            if not page:break
            for row in page:record_links(db,row['account'],json.loads(row['parsed']))
        db.execute('INSERT OR IGNORE INTO thread_graph_migrations(version) VALUES(1)')

# ==========================================
# Function: Return one chronological visible copy per RFC message in a conversation.
# Method: Keep the explicitly opened physical source; prefer sent copies for passive members.
# ==========================================
def conversation(db,message):
    rows=db.execute('''WITH RECURSIVE component(mid) AS (
      SELECT ? UNION SELECT CASE WHEN l.source=c.mid THEN l.target ELSE l.source END
      FROM thread_links l JOIN component c ON (l.source=c.mid OR l.target=c.mid) WHERE l.account=? LIMIT 10000)
      SELECT m.id,m.message_id,m.sender,coalesce(d.sender_name,json_extract(m.parsed,'$.sender_name')) AS sender_name,
      coalesce(d.recipients,json_extract(m.parsed,'$.recipients')) AS recipients,substr(m.body,1,160) AS preview,
      m.subject,m.timestamp,m.folder,m.account,m.seen,m.pinned,m.done,m.category FROM messages m
      JOIN component c ON c.mid=m.message_id LEFT JOIN message_display d ON d.message=m.id WHERE m.account=? AND m.remote_gone=0
      ORDER BY m.timestamp,m.id''',(message['message_id'],message['account'],message['account'])).fetchall()
    unique={};selected=message['id']
    for row in rows:
        value=dict(row);key=value['message_id'] or value['id']
        if key not in unique or value['id']==selected or (unique[key]['id']!=selected and value['folder']=='@sent'):
            unique[key]=value
    return sorted(unique.values(),key=lambda row:(row['timestamp'],row['id']))
