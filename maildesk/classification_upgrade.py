"""Incremental verification-category upgrade on a bounded dedicated local worker."""
import json
import time
import unicodedata
from .classifier import classify
from .verification_mail import CODE_CUE

# ==========================================
# Function: Recognize one bounded batch of existing cached verification mail.
# Method: Checkpoint200 thin rows, yield after80ms/4MiB parsed text and guard writes against intervening manual changes.
# ==========================================
def upgrade_verification(store):
    if store.preference('verification_classifier_revision',0)>=1 or not store.preference('recognition_enabled',True):return 0
    started=time.perf_counter();cursor=store.preference('verification_classifier_cursor','');senders={};updates=[];processed=0;parsed_bytes=0
    with store.db() as db:
        rows=db.execute("SELECT id,account,category,reason,substr(subject,1,512) AS subject,substr(body,1,16000) AS body FROM messages WHERE id>? AND override IS NULL AND category<>'verification' ORDER BY id LIMIT 200",(cursor,)).fetchall()
        for row in rows:
            cursor=row['id'];processed+=1;text=unicodedata.normalize('NFKC',row['subject']+'\n'+row['body'])
            if CODE_CUE.search(text):
                raw=db.execute('SELECT parsed FROM messages WHERE id=?',(row['id'],)).fetchone()
                if raw:
                    source=raw['parsed'];parsed_bytes+=len(source.encode('utf-8'));rules=senders.setdefault(row['account'],None)
                    if rules is None:rules=senders[row['account']]=store.sender_rules(row['account'])
                    category,reason=classify(json.loads(source),rules,store.rules,True)
                    if category=='verification':updates.append((category,reason,row['id'],row['category'],row['reason']))
            if time.perf_counter()-started>=.08 or parsed_bytes>=4*1024*1024:break
    changed=0
    if updates:
        with store.db() as db:
            for values in updates:changed+=db.execute('UPDATE messages SET category=?,reason=? WHERE id=? AND override IS NULL AND category=? AND reason=?',values).rowcount
    store.set_preference('verification_classifier_cursor',cursor)
    if processed==len(rows) and len(rows)<200:store.set_preference('verification_classifier_revision',1)
    return changed
