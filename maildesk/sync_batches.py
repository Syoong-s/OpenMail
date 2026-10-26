"""Bounded, UID-verified IMAP fetch batches with cooperative foreground checkpoints."""
import re
from datetime import datetime,timedelta,timezone
from .mime import MAX_MESSAGE_BYTES

SIZE_BATCH=100
BODY_BATCH=16
BODY_BYTES=4*1024*1024

# ==========================================
# Function: Leave an incomplete background poll without treating user interaction as a network failure.
# Method: Carry control flow to the owning sync session, whose context manager still disconnects normally.
# ==========================================
class SyncInterrupted(Exception):pass

# ==========================================
# Function: Give a queued interactive operation the next provider turn.
# Method: Test only at safe command/commit boundaries so server mutations never overlap local sync reconciliation.
# ==========================================
def checkpoint(should_yield):
    if should_yield and should_yield():raise SyncInterrupted()

# ==========================================
# Function: Read the server's actual receipt time independently of the sender-controlled Date header.
# Method: Parse standard IMAP INTERNALDATE with an explicit numeric timezone and reject missing/malformed metadata conservatively.
# ==========================================
def received_time(header):
    match=re.search(rb'\bINTERNALDATE "\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}) (\d{2}):(\d{2}):(\d{2}) ([+-])(\d{2})(\d{2})"',header,re.I)
    if not match:return None
    try:
        month=(b'jan',b'feb',b'mar',b'apr',b'may',b'jun',b'jul',b'aug',b'sep',b'oct',b'nov',b'dec').index(match[2].lower())+1
        offset=timedelta(hours=int(match[8]),minutes=int(match[9]))*(1 if match[7]==b'+' else -1)
        return datetime(int(match[3]),month,int(match[1]),int(match[4]),int(match[5]),int(match[6]),tzinfo=timezone(offset)).timestamp()
    except (ValueError,OverflowError):return None

# ==========================================
# Function: Partition candidate bodies by both count and advertised memory footprint.
# Method: Limit ordinary batches to16 messages/4MiB while allowing one valid larger message on its own.
# ==========================================
def body_batches(candidates):
    batch=[];size=0
    for uid,length in candidates:
        if batch and (len(batch)>=BODY_BATCH or size+length>BODY_BYTES):yield batch;batch=[];size=0
        batch.append(uid);size+=length
    if batch:yield batch

# ==========================================
# Function: Cache new UID sources using a bounded number of network round trips and database commits.
# Method: Fetch sizes in bulk, then match each MIME literal to its own UID regardless of response order.
# ==========================================
def fetch_new(client,store,account,folder,validity,uids,should_yield=None,progress=None):
    from .transport import checked,flag_rows
    imported=skipped=0
    for start in range(0,len(uids),SIZE_BATCH):
        checkpoint(should_yield);page=uids[start:start+SIZE_BATCH]
        data=checked(client.uid('FETCH',','.join(page),'(UID RFC822.SIZE INTERNALDATE)'),'读取邮件大小');sizes={};received={}
        for row in data:
            header=row[0] if isinstance(row,tuple) else row
            if not isinstance(header,bytes):continue
            uid=re.search(rb'\bUID (\d+)\b',header,re.I);size=re.search(rb'\bRFC822.SIZE (\d+)\b',header,re.I)
            if uid and size and uid[1].decode() in page:sizes[uid[1].decode()]=int(size[1]);received[uid[1].decode()]=received_time(header)
        candidates=[];page_skipped=0
        for uid in page:
            size=sizes.get(uid)
            if size is None or size>MAX_MESSAGE_BYTES:page_skipped+=1
            else:candidates.append((uid,size))
        skipped+=page_skipped
        if progress:progress(0,page_skipped)
        for batch in body_batches(candidates):
            checkpoint(should_yield)
            rows=checked(client.uid('FETCH',','.join(batch),'(UID FLAGS BODY.PEEK[])'),'读取邮件')
            flags=flag_rows(rows);sources={}
            for row in rows:
                if not isinstance(row,tuple) or not isinstance(row[0],bytes) or not isinstance(row[1],bytes):continue
                uid=re.search(rb'\bUID (\d+)\b',row[0],re.I)
                if not uid or uid[1].decode() not in batch:continue
                identity=uid[1].decode()
                if identity in sources or len(row[1])>MAX_MESSAGE_BYTES:raise RuntimeError('IMAP 邮件内容重复或超过大小限制')
                sources[identity]={'uid':identity,'raw':row[1],'seen':flags.get(identity,False),'received_at':received.get(identity)}
            if set(sources)!=set(batch):raise RuntimeError('IMAP 未返回完整邮件内容，请稍后重试')
            store.ingest_many(account,folder,validity,[sources[uid] for uid in batch]);imported+=len(batch)
            if progress:progress(len(batch),0)
            checkpoint(should_yield)
    return imported,skipped
