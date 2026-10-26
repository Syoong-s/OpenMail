"""Account-free mail storage that never needs an application cloud or mail provider."""
from pathlib import Path
import hashlib

from .mime import MAX_MESSAGE_BYTES

LOCAL_ACCOUNT = '@local'
LOCAL_LABEL = '本地文件夹'
LOCAL_FOLDERS = [('INBOX','inbox'),('Archive','archive'),('Trash','trash'),('Spam','spam')]

# ==========================================
# Function: Initialize persistent account-free local folders once.
# Method: Use a reserved identity rejected by Account validation and preserve all existing state.
# ==========================================
def ensure_local_folders(store):
    if not store.list_folders(LOCAL_ACCOUNT):
        store.save_folders(LOCAL_ACCOUNT,[{'name':path,'special':special,'delimiter':'/','flags':[],
            'selectable':True,'subscribed':True} for path,special in LOCAL_FOLDERS])

# ==========================================
# Function: Distinguish local MIME records from provider-backed UIDs.
# Method: Recognize the reserved local identity and historical local-cache folder names.
# ==========================================
def is_local_message(message):
    return message['account']==LOCAL_ACCOUNT or message['folder'].startswith('@')

# ==========================================
# Function: Import an explicitly selected EML into an existing local folder.
# Method: Bound file reads, validate the destination, and deduplicate by exact MIME digest.
# ==========================================
def import_local_eml(store, filename, folder='INBOX', demo=False):
    filename=Path(filename)
    if filename.stat().st_size>MAX_MESSAGE_BYTES:
        raise ValueError('邮件超过 30 MiB')
    with filename.open('rb') as source:
        raw=source.read(MAX_MESSAGE_BYTES+1)
    if len(raw)>MAX_MESSAGE_BYTES:
        raise ValueError('邮件超过 30 MiB')
    account='demo' if demo else LOCAL_ACCOUNT
    destination='@import' if demo else folder
    if not demo:
        ensure_local_folders(store)
        if not any(r['folder']==destination and r['selectable'] for r in store.list_folders(account)):
            raise ValueError('请选择可用的本地文件夹')
    return store.ingest(account,destination,'local',hashlib.sha256(raw).hexdigest(),raw)
