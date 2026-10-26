"""Explicit cloud-verified cache cleanup, preserving local mail and starred people."""
import hashlib
import shutil
from pathlib import Path

from . import transport
from .folders import parse_folder
from .participant_identity import parse_participants

# ==========================================
# Function: Obtain authoritative existence evidence without downloading bodies or changing server mail.
# Method: Require LIST plus successful read-only UIDVALIDITY/SEARCH for every selectable mailbox.
# ==========================================
def cloud_snapshot(account):
    snapshot={}
    with transport.imap_connection(account) as client:
        rows=transport.checked(client.list('""','"*"'),'核对云端文件夹')
        folders=[item for row in rows if row and (item:=parse_folder(row))]
        if not folders or not any(item['selectable'] for item in folders):
            raise ValueError('云端文件夹列表不完整，保留该账号缓存')
        for item in folders:
            folder=item['name']
            if not item['selectable']:
                snapshot[folder]=None;continue
            transport.checked(client.select(transport.mailbox_name(folder),readonly=True),'核对云端文件夹')
            validity=transport.uid_validity(client)
            rows=transport.checked(client.uid('SEARCH',None,'ALL'),'核对云端邮件')
            if len(rows)!=1 or not isinstance(rows[0],bytes):
                raise ValueError('云端邮件列表不完整，保留该账号缓存')
            uids=rows[0].decode('ascii').split()
            if any(not uid.isdecimal() or int(uid)<1 for uid in uids):
                raise ValueError('云端返回无效邮件标识，保留该账号缓存')
            snapshot['INBOX' if folder.upper()=='INBOX' else folder]=(validity,frozenset(uids))
    return snapshot

# ==========================================
# Function: Delete only physical cache copies disproven by a complete account snapshot.
# Method: Remove dependent projections transactionally; preserve local copies and shared attachment files.
# ==========================================
def purge_messages(store,account,snapshot):
    from .local_mail import LOCAL_ACCOUNT
    if account==LOCAL_ACCOUNT:return 0
    attachment_root=Path(store.cache_dir)/'attachments' if getattr(store,'cache_dir',None) else None
    removed=0;attachment_dirs=set()
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        candidates=db.execute("SELECT id,folder,validity,uid FROM messages WHERE account=? AND folder NOT LIKE '@%' AND validity<>'local'",(account,)).fetchall()
        for message in candidates:
            if not message['uid'].isdigit():continue
            folder='INBOX' if message['folder'].upper()=='INBOX' else message['folder']
            evidence=snapshot.get(folder)
            if folder in snapshot and evidence is None:continue
            if evidence and message['validity']==evidence[0] and message['uid'] in evidence[1]:continue
            identity=message['id'];raw=None
            if attachment_root and attachment_root.is_dir() and not attachment_root.is_symlink():
                raw=db.execute('SELECT raw FROM messages WHERE id=?',(identity,)).fetchone()[0]
            for table in ('message_labels','pending_read_flags','contact_envelopes','contact_attachment_candidates','contact_payload_fingerprints'):
                db.execute('DELETE FROM '+table+' WHERE message=?',(identity,))
            db.execute('DELETE FROM messages WHERE id=?',(identity,));removed+=1
            if raw is not None and not db.execute('SELECT 1 FROM messages WHERE raw=? LIMIT 1',(raw,)).fetchone():
                attachment_dirs.add(hashlib.sha256(raw).hexdigest())
        db.execute('''DELETE FROM thread_links WHERE account=? AND NOT EXISTS(
            SELECT 1 FROM messages m WHERE m.account=thread_links.account AND m.message_id=thread_links.source)''',(account,))
    for digest in attachment_dirs:
        target=attachment_root/digest
        if target.is_dir() and not target.is_symlink():
            try:shutil.rmtree(target)
            except OSError:pass  # The database is authoritative; locked reusable files can be retried later.
    return removed

# ==========================================
# Function: Prune nonstarred people with no remaining cached mail referencing any saved alias.
# Method: Stream original participant headers into a temporary indexed set in the same transaction.
# ==========================================
def prune_contacts(store):
    with store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TEMP TABLE cached_addresses(address TEXT PRIMARY KEY)')
        cursor=db.execute("SELECT sender,json_extract(parsed,'$.headers.from'),json_extract(parsed,'$.headers.to'),json_extract(parsed,'$.headers.cc'),json_extract(parsed,'$.headers.bcc') FROM messages")
        for row in cursor:
            addresses={item['address'] for item in parse_participants([value for value in row if value])}
            db.executemany('INSERT OR IGNORE INTO cached_addresses VALUES(?)',[(address,) for address in addresses])
        db.execute('''CREATE TEMP TABLE orphan_people AS SELECT p.id FROM address_people p WHERE p.starred=0
            AND NOT EXISTS(SELECT 1 FROM address_mailboxes a JOIN cached_addresses c ON c.address=a.address
                WHERE a.person=p.id AND a.suppressed=0)''')
        count=db.execute('SELECT count(*) FROM orphan_people').fetchone()[0]
        db.execute('DELETE FROM contact_preferences WHERE person IN (SELECT id FROM orphan_people)')
        # Cache pruning is not a manual suppression: fresh future mail may observe these people again.
        db.execute('DELETE FROM address_mailboxes WHERE person IN (SELECT id FROM orphan_people)')
        db.execute('DELETE FROM address_people WHERE id IN (SELECT id FROM orphan_people)')
    return count

# ==========================================
# Function: Run the user's explicit cache maintenance request under the remote-operation lock.
# Method: Isolate failures by account and prune contacts only after verified cache deletions finish.
# ==========================================
def clean_cache(service):
    result={'messages':0,'contacts':0,'verified':[],'skipped':[]}
    with service.lock:
        paused=service.store.preference('paused_accounts',[])
        for account in tuple(service.accounts.values()):
            if service.demo or account.id in paused:
                result['skipped'].append(account.id);continue
            try:snapshot=cloud_snapshot(account)
            except Exception:
                result['skipped'].append(account.id);continue
            result['messages']+=purge_messages(service.store,account.id,snapshot)
            result['verified'].append(account.id)
        result['contacts']=prune_contacts(service.store)
        if result['messages']:
            try:
                with service.store.db() as db:
                    db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.execute('VACUUM')
            except Exception:result['compaction_deferred']=True
    return result
