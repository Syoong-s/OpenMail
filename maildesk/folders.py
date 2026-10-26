"""IMAP mailbox discovery and mutation without executing foreign application code."""
import base64
import re

SPECIAL_NAMES={
    'inbox':'inbox','sent':'sent','sent items':'sent','sent messages':'sent','已发送':'sent',
    'drafts':'drafts','草稿':'drafts','trash':'trash','deleted items':'trash','deleted messages':'trash','已删除邮件':'trash','废纸篓':'trash','已删除':'trash',
    'junk':'spam','spam':'spam','junk email':'spam','垃圾邮件':'spam','archive':'archive','archives':'archive','归档':'archive'}

# ==========================================
# Function: Decode an IMAP modified UTF-7 mailbox name.
# Method: Preserve ASCII and decode each ampersand-delimited UTF-16BE base64 sequence.
# ==========================================
def decode_mailbox(value):
    text=value.decode('utf-8') if isinstance(value,bytes) else value
    # ==========================================
    # Function: Decode one modified-base64 segment.
    # Method: Restore slash/padding and strictly decode UTF-16BE.
    # ==========================================
    def segment(match):
        encoded=match[1]
        if not encoded:
            return '&'
        try:
            return base64.b64decode(encoded.replace(',','/')+'='*((-len(encoded))%4),validate=True).decode('utf-16be')
        except (ValueError,UnicodeError):
            raise ValueError('服务器返回无效文件夹编码') from None
    return re.sub(r'&([^-]*)-',segment,text)

# ==========================================
# Function: Parse quoted, atom and literal IMAP LIST/LSUB mailbox rows.
# Method: Consume the flags/delimiter prefix separately from arbitrary mailbox names.
# ==========================================
def parse_folder(row):
    header,literal=row if isinstance(row,tuple) else (row,None)
    if not isinstance(header,bytes):
        return None
    match=re.fullmatch(rb'\(([^)]*)\)\s+(NIL|"(?:[^"\\]|\\.)*")\s+(.+)',header,re.I|re.S)
    if not match:
        raise ValueError('服务器返回无效 LIST 行')
    # ==========================================
    # Function: Unescape an IMAP quoted string.
    # Method: Remove only protocol escape prefixes, preserving mailbox bytes.
    # ==========================================
    def unquote(value):
        if value.startswith(b'"') and value.endswith(b'"'):
            return re.sub(rb'\\(.)',rb'\1',value[1:-1])
        return value
    delimiter=None if match[2].upper()==b'NIL' else unquote(match[2]).decode('utf-8')
    name=literal if literal is not None else unquote(match[3])
    path=decode_mailbox(name)
    flags=[v.decode('ascii').lower() for v in match[1].split()]
    special=next((v[1:] for v in flags if v in ('\\inbox','\\sent','\\drafts','\\trash','\\junk','\\archive','\\all')), '')
    special={'junk':'spam','all':'all'}.get(special,special)
    leaf=path.rsplit(delimiter,1)[-1] if delimiter else path
    special=special or SPECIAL_NAMES.get(leaf.casefold(),'')
    return {'name':path,'delimiter':delimiter,'flags':flags,'special':special,'selectable':'\\noselect' not in flags,'subscribed':True}

# ==========================================
# Function: Discover server folders and subscriptions.
# Method: LIST is authoritative; LSUB enriches it and configured folders remain a fallback.
# ==========================================
def discover(client, account, counts=True, should_yield=None):
    from .transport import checked
    from .sync_batches import checkpoint
    checkpoint(should_yield)
    raw=checked(client.list('""','"*"'),'获取文件夹')
    result=[item for row in raw if row and (item:=parse_folder(row))]
    if not result:
        result=[{'name':path,'delimiter':'/','flags':[],'special':SPECIAL_NAMES.get(path.casefold(),''),'selectable':True,'subscribed':True} for path in account.folders]
    try:
        checkpoint(should_yield)
        response,rows=client.lsub('""','"*"')
        if response=='OK' and rows and any(rows):
            subscriptions={item['name'] for row in rows if row and (item:=parse_folder(row))}
            for item in result:
                item['subscribed']=item['name'] in subscriptions
    except (AttributeError,ValueError):
        pass
    from .transport import mailbox_name
    if not counts:return result
    for item in result:
        if not item['selectable']:continue
        checkpoint(should_yield)
        response,data=client.status(mailbox_name(item['name']),'(MESSAGES UNSEEN)')
        if response=='OK':
            raw=b' '.join(row for row in data if isinstance(row,bytes))
            for name,key in ((b'MESSAGES','remote_total'),(b'UNSEEN','remote_unread')):
                match=re.search(rb'\b'+name+rb' (\d+)\b',raw,re.I)
                if match:item[key]=int(match[1])
    return result

# ==========================================
# Function: Validate a mailbox path before any remote command.
# Method: Reject empty/control/reserved local paths while allowing Unicode and spaces.
# ==========================================
def valid_path(path):
    if not isinstance(path,str) or not path.strip() or len(path)>1000 or path.startswith('@') or any(ord(c)<32 or ord(c)==127 for c in path):
        raise ValueError('文件夹名称为空、过长或包含控制字符')
    return path.strip()

# ==========================================
# Function: Create, rename, delete or subscribe to one server folder.
# Method: Use imaplib commands and quote Unicode paths through the existing transport.
# ==========================================
def mutate_folder(account, operation, path, target=''):
    from .transport import imap_connection,mailbox_name,checked
    path=valid_path(path)
    if operation not in ('create','rename','delete','subscribe','unsubscribe'):
        raise ValueError('未知文件夹操作')
    if operation in ('delete','rename') and path.upper()=='INBOX':
        raise ValueError('不能删除或重命名收件箱')
    if operation=='delete':
        with imap_connection(account) as client:
            checked(client.select(mailbox_name(path),readonly=True),'检查文件夹')
            snapshot=checked(client.uid('SEARCH',None,'ALL'),'检查剩余邮件')
            if any(row and row.strip() for row in snapshot):
                raise ValueError('服务器文件夹仍有邮件，请先移出全部邮件')
        # Reconnect in authenticated state; neither CLOSE nor optional UNSELECT is required.
    with imap_connection(account) as client:
        method=getattr(client,operation)
        args=[mailbox_name(path)]
        if operation=='rename':
            args.append(mailbox_name(valid_path(target)))
        checked(method(*args),'修改文件夹')
        if operation=='create':
            client.subscribe(mailbox_name(path))
        return discover(client,account,counts=False)

# ==========================================
# Function: Verify an exact message generation before remote mutation.
# Method: Refuse stale UIDs and never use sequence numbers as message identities.
# ==========================================
def select_message(client, message):
    from .transport import checked,mailbox_name,uid_validity
    if message['remote_gone'] or not str(message['uid']).isdigit():
        raise ValueError('邮件已不在原文件夹，请先同步')
    checked(client.select(mailbox_name(message['folder']),readonly=False),'选择文件夹')
    if uid_validity(client)!=message['validity']:
        raise ValueError('邮箱 UID 世代已变化，请先同步后重试')

# ==========================================
# Function: Copy or safely move one UID to a destination mailbox.
# Method: Prefer UID MOVE; otherwise require UIDPLUS for a targeted COPY/STORE/EXPUNGE.
# ==========================================
def transfer(account, message, destination, copy=False):
    from .transport import imap_connection
    destination=valid_path(destination)
    if destination==message['folder']:
        raise ValueError('邮件已经在此文件夹中')
    with imap_connection(account) as client:
        select_message(client,message)
        return transfer_selected(client,message,destination,copy)

# ==========================================
# Function: Transfer one previously generation-verified UID using an existing authenticated connection.
# Method: Share targeted MOVE/UIDPLUS behavior with serialized retention; never expunge unrelated mail.
# ==========================================
def transfer_selected(client,message,destination,copy=False):
    from .transport import mailbox_name,checked
    destination=valid_path(destination)
    if destination==message['folder']:raise ValueError('邮件已经在此文件夹中')
    capabilities={v.decode().upper() if isinstance(v,bytes) else v.upper() for v in client.capabilities}
    if not copy and 'MOVE' not in capabilities and 'UIDPLUS' not in capabilities:
        raise ValueError('服务器不支持 MOVE 或 UIDPLUS；可使用“复制到”，原邮件会保留')
    if not copy and 'MOVE' in capabilities:
        checked(client.uid('MOVE',message['uid'],mailbox_name(destination)),'移动邮件')
    else:
        checked(client.uid('COPY',message['uid'],mailbox_name(destination)),'复制邮件')
        if not copy:
            checked(client.uid('STORE',message['uid'],'+FLAGS.SILENT','(\\Deleted)'),'移除原邮件')
            checked(client.uid('EXPUNGE',message['uid']),'完成移动')
    code,data=client.response('COPYUID')
    if data and isinstance(data[0],bytes):
        match=re.fullmatch(rb'(\d+) (\d+) (\d+)',data[0])
        if match and match[2].decode()==str(message['uid']):
            return {'validity':match[1].decode(),'uid':match[3].decode()}
    return None

# ==========================================
# Function: Permanently delete only the explicitly selected message UID.
# Method: Require UIDPLUS and never issue mailbox-wide EXPUNGE or CLOSE.
# ==========================================
def delete_message(account, message):
    from .transport import imap_connection,checked
    with imap_connection(account) as client:
        select_message(client,message)
        if b'UIDPLUS' not in client.capabilities and 'UIDPLUS' not in client.capabilities:
            raise ValueError('服务器不支持定向删除 UIDPLUS，请使用移动到废纸篓')
        checked(client.uid('STORE',message['uid'],'+FLAGS.SILENT','(\\Deleted)'),'标记删除')
        checked(client.uid('EXPUNGE',message['uid']),'永久删除')
