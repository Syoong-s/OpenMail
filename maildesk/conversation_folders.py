"""Persisted account/folder selection shared by every contact conversation projection."""
import json

PREFERENCE='conversation_folder_scope'
EXCLUDED_SPECIAL=('trash','spam','drafts')
EXCLUDED_NAMES=('trash','spam','junk','deleted items','drafts','@draft','@drafts')

# ==========================================
# Function: Validate a stable explicit folder selection without guessing account or path aliases.
# Method: Normalize only the policy shape, deduplicate exact identities and preserve choices for temporarily unavailable folders.
# ==========================================
def normalized(value):
    if not isinstance(value,dict) or value.get('mode')!='custom':return {'mode':'default','folders':[]}
    chosen=set()
    for item in value.get('folders',[]) if isinstance(value.get('folders'),list) else []:
        if isinstance(item,dict) and isinstance(item.get('account'),str) and isinstance(item.get('folder'),str) and item['account'] and item['folder']:
            chosen.add((item['account'],item['folder']))
    if len(chosen)>4096:raise ValueError('选择的对话文件夹过多')
    result={'mode':'custom','folders':[{'account':account,'folder':folder} for account,folder in sorted(chosen)]}
    if len(json.dumps(result,ensure_ascii=False))>100000:raise ValueError('选择的文件夹信息过长，请减少选择后再保存')
    return result

# ==========================================
# Function: Read the current conversation folder policy with backward-compatible defaults.
# Method: Use the Store preference snapshot when called from a projection worker.
# ==========================================
def load(store):return normalized(store.preference(PREFERENCE,{}))

# ==========================================
# Function: Persist one validated local-only policy after the parent settings form is saved.
# Method: Store exact account/path pairs without touching remote mail or folder subscriptions.
# ==========================================
def save(store,value):store.set_preference(PREFERENCE,normalized(value))

# ==========================================
# Function: Honor user-assigned special folder paths when the server does not advertise their role.
# Method: Extract only validated exact account/path mappings for the existing excluded special-use kinds.
# ==========================================
def mapped_specials(store):
    mapping=store.preference('folder_mapping',{});result=[]
    for account,folders in mapping.items() if isinstance(mapping,dict) else ():
        if not isinstance(account,str) or not isinstance(folders,dict):continue
        for special,folder in folders.items():
            if special in EXCLUDED_SPECIAL and isinstance(folder,str) and folder:result.append((account,folder,special))
    return result

# ==========================================
# Function: Apply the same scope to list summaries, timeline bodies, copy metadata and unread actions.
# Method: Preserve legacy default predicates; custom selection admits selected special folders explicitly and keeps hidden flags scoped to their actual special folder.
# ==========================================
def predicates(store):
    policy=load(store);where=['m.remote_gone=0'];values=[];mapped=mapped_specials(store)
    if policy['mode']=='default':
        where.extend(["m.trashed=0","m.spam=0","coalesce(f.special,'') NOT IN ('trash','spam','drafts')","lower(m.folder) NOT IN ('trash','spam','junk','deleted items','drafts','@draft','@drafts')"])
        if mapped:
            where.append('NOT ('+' OR '.join('(m.account=? AND m.folder=?)' for _ in mapped)+')')
            for account,folder,special in mapped:values.extend((account,folder))
    else:
        folders=policy['folders'];where.append('(m.account,m.folder) IN (VALUES '+','.join('(?,?)' for _ in folders)+')' if folders else '0')
        for folder in folders:values.extend((folder['account'],folder['folder']))
        for flag,special,names in [('spam','spam',"'spam','junk'"),('trashed','trash',"'trash','deleted items'")]:
            paths=[(account,folder) for account,folder,kind in mapped if kind==special]
            extra=' OR '+' OR '.join('(m.account=? AND m.folder=?)' for _ in paths) if paths else ''
            where.append("(m."+flag+"=0 OR f.special='"+special+"' OR lower(m.folder) IN ("+names+")"+extra+")")
            for account,folder in paths:values.extend((account,folder))
    return where,values

# ==========================================
# Function: Show the default scope accurately before a custom folder selection is made.
# Method: Match existing special-use metadata and legacy well-known folder names.
# ==========================================
def recommended(folder):return folder.get('special','') not in EXCLUDED_SPECIAL and folder['folder'].lower() not in EXCLUDED_NAMES

# ==========================================
# Function: Enumerate both discovered server folders and cache-only local mail folders.
# Method: Union authoritative selectable folders with live cached paths and retain removed saved selections as unavailable rows.
# ==========================================
def inventory(store):
    with store.db() as db:
        rows=db.execute('''WITH paths AS (
            SELECT account,folder FROM folders WHERE present=1 AND selectable=1
            UNION SELECT account,folder FROM messages WHERE remote_gone=0)
            SELECT p.account,p.folder,coalesce(f.special,'') AS special,coalesce(f.present,1) AS present,
                count(m.id) AS cached FROM paths p
            LEFT JOIN folders f ON f.account=p.account AND f.folder=p.folder
            LEFT JOIN messages m ON m.account=p.account AND m.folder=p.folder AND m.remote_gone=0
            GROUP BY p.account,p.folder ORDER BY p.account,lower(p.folder)''').fetchall()
    result={ (row['account'],row['folder']):dict(row) for row in rows }
    for account,folder,special in mapped_specials(store):
        if (account,folder) in result:result[(account,folder)]['special']=special
    for item in load(store)['folders']:
        key=(item['account'],item['folder'])
        if key not in result:result[key]={**item,'special':'','present':0,'cached':0}
    return sorted(result.values(),key=lambda row:(row['account'],row['folder'].casefold()))
