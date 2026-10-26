"""Compact transactionally maintained display and draft routing metadata."""

# ==========================================
# Function: Add compact projections without decoding cached MIME/draft payloads at startup.
# Method: Install additive projections and explicit upsert triggers that survive outer draft upserts.
# ==========================================
def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS navigation_revision(topic TEXT PRIMARY KEY,value INTEGER NOT NULL);
        INSERT OR IGNORE INTO navigation_revision VALUES('jobs',0);
        CREATE TRIGGER IF NOT EXISTS jobs_revision_insert AFTER INSERT ON jobs BEGIN UPDATE navigation_revision SET value=value+1 WHERE topic='jobs'; END;
        CREATE TRIGGER IF NOT EXISTS jobs_revision_update AFTER UPDATE ON jobs BEGIN UPDATE navigation_revision SET value=value+1 WHERE topic='jobs'; END;
        CREATE TRIGGER IF NOT EXISTS jobs_revision_delete AFTER DELETE ON jobs BEGIN UPDATE navigation_revision SET value=value+1 WHERE topic='jobs'; END;
        CREATE TABLE IF NOT EXISTS message_display(
        message TEXT PRIMARY KEY,sender_name TEXT,recipients TEXT,raw_from TEXT);
        CREATE TABLE IF NOT EXISTS chat_job_index(job TEXT PRIMARY KEY,chat_key TEXT NOT NULL,preview TEXT);
        CREATE INDEX IF NOT EXISTS chat_job_contact ON chat_job_index(chat_key,job);
        CREATE TRIGGER IF NOT EXISTS display_message_insert AFTER INSERT ON messages BEGIN
          INSERT OR REPLACE INTO message_display VALUES(new.id,json_extract(new.parsed,'$.sender_name'),json_extract(new.parsed,'$.recipients'),json_extract(new.parsed,'$.headers.from'));
        END;
        CREATE TRIGGER IF NOT EXISTS display_message_update AFTER UPDATE OF parsed ON messages BEGIN
          INSERT OR REPLACE INTO message_display VALUES(new.id,json_extract(new.parsed,'$.sender_name'),json_extract(new.parsed,'$.recipients'),json_extract(new.parsed,'$.headers.from'));
          DELETE FROM contact_envelopes WHERE message=new.id;
          DELETE FROM contact_attachment_candidates WHERE message=new.id;
          DELETE FROM contact_payload_fingerprints WHERE message=new.id;
          DELETE FROM address_observed WHERE message=new.id;
          INSERT OR IGNORE INTO address_pending VALUES(new.id);
        END;
        CREATE TRIGGER IF NOT EXISTS display_message_delete AFTER DELETE ON messages BEGIN
          DELETE FROM message_display WHERE message=old.id;
          DELETE FROM address_observed WHERE message=old.id;
          DELETE FROM address_pending WHERE message=old.id;
        END;
        DROP TRIGGER IF EXISTS chat_job_insert;
        DROP TRIGGER IF EXISTS chat_job_update;
        CREATE TRIGGER IF NOT EXISTS chat_job_insert_v2 AFTER INSERT ON jobs BEGIN
          INSERT INTO chat_job_index(job,chat_key,preview) VALUES(new.id,coalesce(json_extract(new.draft,'$.chat_key'),''),substr(json_extract(new.draft,'$.body'),1,100))
          ON CONFLICT(job) DO UPDATE SET chat_key=excluded.chat_key,preview=excluded.preview;
        END;
        CREATE TRIGGER IF NOT EXISTS chat_job_update_v2 AFTER UPDATE OF draft ON jobs BEGIN
          INSERT INTO chat_job_index(job,chat_key,preview) VALUES(new.id,coalesce(json_extract(new.draft,'$.chat_key'),''),substr(json_extract(new.draft,'$.body'),1,100))
          ON CONFLICT(job) DO UPDATE SET chat_key=excluded.chat_key,preview=excluded.preview;
        END;
        CREATE TRIGGER IF NOT EXISTS chat_job_delete AFTER DELETE ON jobs BEGIN
          DELETE FROM chat_job_index WHERE job=old.id;
        END;''')

# ==========================================
# Function: Populate old compact projections in finite background transactions.
# Method: Admit at most 128 messages and 32 complete drafts per call, preserving indexed current rows.
# ==========================================
def backfill(store):
    with store.db() as db:
        if db.execute("SELECT 1 FROM address_migrations WHERE key='navigation-complete'").fetchone():return True
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT m.id,length(CAST(m.parsed AS BLOB)) AS bytes FROM messages m LEFT JOIN message_display d ON d.message=m.id WHERE d.message IS NULL LIMIT 128').fetchall()
        admitted=0;limited=False
        for row in rows:
            if admitted and admitted+row['bytes']>4*1024*1024:limited=True;break
            admitted+=row['bytes']
            db.execute("INSERT OR IGNORE INTO message_display SELECT id,json_extract(parsed,'$.sender_name'),json_extract(parsed,'$.recipients'),json_extract(parsed,'$.headers.from') FROM messages WHERE id=?",(row['id'],))
        jobs=db.execute('SELECT j.id,length(CAST(j.draft AS BLOB)) AS bytes FROM jobs j LEFT JOIN chat_job_index x ON x.job=j.id WHERE x.job IS NULL LIMIT 32').fetchall()
        admitted=0
        for row in jobs:
            if admitted and admitted+row['bytes']>4*1024*1024:limited=True;break
            admitted+=row['bytes']
            db.execute("INSERT OR IGNORE INTO chat_job_index SELECT id,coalesce(json_extract(draft,'$.chat_key'),''),substr(json_extract(draft,'$.body'),1,100) FROM jobs WHERE id=?",(row['id'],))
        complete=not limited and len(rows)<128 and len(jobs)<32
        if complete:db.execute("INSERT OR IGNORE INTO address_migrations VALUES('navigation-complete','1')")
    return complete
