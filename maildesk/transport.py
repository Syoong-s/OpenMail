"""IMAP/SMTP adapters with mandatory verified TLS and explicit delivery outcomes."""
from contextlib import contextmanager
import imaplib
import re
import smtplib
import ssl

from .mime import MAX_MESSAGE_BYTES

TIMEOUT = 25

# ==========================================
# Function: Represent whether a failed SMTP operation could have delivered mail.
# Method: Carry a public message and an ambiguity flag, without leaking credentials.
# ==========================================
class DeliveryError(Exception):
    # ==========================================
    # Function: Store a safe delivery failure reason.
    # Method: Initialize the exception and classify transport ambiguity.
    # ==========================================
    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain

# ==========================================
# Function: Quote an IMAP mailbox name and encode non-ASCII folder names.
# Method: Implement RFC modified UTF-7 and escape quoted-string metacharacters.
# ==========================================
def mailbox_name(value):
    import base64
    chunks, pending = [], []
    # ==========================================
    # Function: Flush a non-ASCII sequence into modified UTF-7.
    # Method: UTF-16BE bytes followed by modified base64.
    # ==========================================
    def flush():
        if pending:
            encoded = base64.b64encode(''.join(pending).encode('utf-16be')).decode().rstrip('=').replace('/', ',')
            chunks.append('&' + encoded + '-')
            pending.clear()
    for char in value:
        if 0x20 <= ord(char) <= 0x7e:
            flush()
            chunks.append('&-' if char == '&' else char)
        else:
            pending.append(char)
    flush()
    return '"' + ''.join(chunks).replace('\\', '\\\\').replace('"', '\\"') + '"'

# ==========================================
# Function: Validate IMAP tagged responses.
# Method: Raise on non-OK results before accepting any local state changes.
# ==========================================
def checked(response, operation):
    status, data = response
    if status != 'OK':
        raise RuntimeError(f'IMAP {operation} 未成功')
    return data

# ==========================================
# Function: Connect and authenticate to an IMAP server.
# Method: Negotiate verified SSL/STARTTLS and password or XOAUTH2; always disconnect.
# ==========================================
@contextmanager
def imap_connection(account, secret_override=None, notify=True):
    client = None
    try:
        context = ssl.create_default_context()
        if account.imap_security == 'ssl':
            client = imaplib.IMAP4_SSL(account.imap_host, account.imap_port, ssl_context=context, timeout=TIMEOUT)
        else:
            client = imaplib.IMAP4(account.imap_host, account.imap_port, timeout=TIMEOUT)
            checked(client.starttls(ssl_context=context), 'STARTTLS')
        secret = account.secret() if secret_override is None else secret_override
        if account.auth == 'oauth2':
            token = f'user={account.login_name}\x01auth=Bearer {secret}\x01\x01'.encode()
            checked(client.authenticate('XOAUTH2', lambda _: token), '认证')
        else:
            checked(client.login(account.login_name, secret), '认证')
        from .credentials import authenticated
        if notify:authenticated(account)
        yield client
    finally:
        if client is not None:
            try:
                client.logout()
            except (OSError, imaplib.IMAP4.error):
                pass

# ==========================================
# Function: Authenticate a TLS SMTP session without submitting any message.
# Method: Share the exact production TLS/AUTH path with isolated login checks.
# ==========================================
@contextmanager
def smtp_connection(account, secret_override=None):
    client=None
    try:
        context=ssl.create_default_context()
        if account.smtp_security=='ssl':
            client=smtplib.SMTP_SSL(account.smtp_host,account.smtp_port,timeout=TIMEOUT,context=context)
        else:
            client=smtplib.SMTP(account.smtp_host,account.smtp_port,timeout=TIMEOUT)
            client.ehlo();client.starttls(context=context)
        client.ehlo()
        secret=account.secret() if secret_override is None else secret_override
        if account.auth=='oauth2':
            import base64
            token=base64.b64encode(f'user={account.login_name}\x01auth=Bearer {secret}\x01\x01'.encode()).decode()
            code,_=client.docmd('AUTH','XOAUTH2 '+token)
            if code!=235:raise DeliveryError('SMTP OAuth2 认证失败，请重新登录')
        else:client.login(account.login_name,secret)
        yield client
    finally:
        if client is not None:
            try:client.quit()
            except Exception:
                try:client.close()
                except Exception:pass

# ==========================================
# Function: Read the selected mailbox UID generation.
# Method: Require a numeric UIDVALIDITY response instead of assuming a default.
# ==========================================
def uid_validity(client):
    data = client.response('UIDVALIDITY')[1]
    if not data or not data[0] or not data[0].isdigit():
        raise RuntimeError('服务器未返回有效 UIDVALIDITY，已停止同步以保护缓存')
    return data[0].decode('ascii')

# ==========================================
# Function: Parse UID/FLAGS rows returned by IMAP FETCH.
# Method: Inspect response headers only; never scan MIME literal bodies for flags.
# ==========================================
def flag_rows(data):
    flags = {}
    for item in data or []:
        header = item[0] if isinstance(item, tuple) else item
        if not isinstance(header, bytes):
            continue
        match = re.search(rb'\bUID (\d+)\b', header)
        flag_match = re.search(rb'\bFLAGS \(([^)]*)\)', header)
        if match and flag_match:
            flags[match[1].decode()] = b'\\Seen' in flag_match[1].split()
    return flags

# ==========================================
# Function: Observe remote star flags independently of read flags.
# Method: Match UID/FLAGS atoms and case-fold system flags without treating other keywords as starred.
# ==========================================
def star_rows(data):
    result={}
    for row in data:
        header=row[0] if isinstance(row,tuple) else row
        if not isinstance(header,bytes):continue
        uid=re.search(rb'\bUID (\d+)\b',header,re.I);flags=re.search(rb'\bFLAGS \(([^)]*)\)',header,re.I)
        if uid and flags:result[uid[1].decode()]=b'\\flagged' in flags[1].lower().split()
    return result

# ==========================================
# Function: Synchronize bounded message bodies and complete cached flag snapshots without starving explicit actions.
# Method: Batch size/body requests, commit bounded source groups and cooperatively stop before another provider command.
# ==========================================
def sync_account(account, store, limit=200, should_yield=None):
    from .sync_batches import checkpoint,fetch_new,SyncInterrupted
    report={'imported':0,'skipped_large':0,'folders':0,'retention':{'moved':0},'filters':{}}
    # ==========================================
    # Function: Preserve committed progress even when foreground work interrupts a later batch.
    # Method: Account only for successful body transactions and inspected oversized sources.
    # ==========================================
    def progress(imported,skipped):
        report['imported']+=imported;report['skipped_large']+=skipped
    try:
        checkpoint(should_yield)
        with imap_connection(account) as client:
            from .folders import discover
            folders=discover(client,account,should_yield=should_yield);report['folders']=len(folders)
            checkpoint(should_yield);store.save_folders(account.id,folders)
            for descriptor in folders:
                if not descriptor['selectable']:continue
                checkpoint(should_yield);folder=descriptor['name']
                checked(client.select(mailbox_name(folder), readonly=True), '选择文件夹')
                validity=uid_validity(client);checkpoint(should_yield)
                snapshot=checked(client.uid('SEARCH',None,'ALL'),'搜索')
                uids=(snapshot[0] or b'').decode().split()
                if any(not uid.isdigit() for uid in uids):raise RuntimeError('服务器返回无效 UID')
                uids=sorted(set(uids),key=int);known=store.mailbox(account.id,folder,validity)
                from .filter_rules import baseline as filter_baseline
                filter_baseline(store,account.id,folder,validity,uids)
                missing=[uid for uid in uids if uid not in known]
                selected=missing[-max(0,limit-report['imported']):] if report['imported']<limit else []
                fetch_new(client,store,account.id,folder,validity,selected,should_yield,progress)
                all_uids=set(uids);refresh=sorted((known|set(selected))&all_uids,key=int);flags={};stars={}
                for start in range(0,len(refresh),100):
                    checkpoint(should_yield)
                    data=checked(client.uid('FETCH',','.join(refresh[start:start+100]),'(UID FLAGS)'),'同步已读状态')
                    flags.update(flag_rows(data));stars.update(star_rows(data))
                checkpoint(should_yield);store.reconcile(account.id,folder,validity,all_uids,flags)
                with store.db() as db:
                    db.executemany('UPDATE messages SET pinned=? WHERE account=? AND folder=? AND validity=? AND uid=?',
                        [(int(star),account.id,folder,validity,uid) for uid,star in stars.items()])
            checkpoint(should_yield)
            from .filter_runner import automatic as run_filters
            run_filters(account,store,client,should_yield,report['filters'])
            checkpoint(should_yield)
            # Daily completion persists across restarts; due and unfinished checks use this authenticated sync.
            from .mail_retention import run_due
            try:report['retention']=run_due(account,store,client,should_yield=should_yield)
            except SyncInterrupted:raise
            except Exception:report['retention']={'pending':'过期邮件移动未完成，将在下次同步重试'}
    except SyncInterrupted:report['interrupted']=True
    return report

# ==========================================
# Function: Change server read state for the exact cached UID generation.
# Method: Re-select and verify UIDVALIDITY before UID STORE.
# ==========================================
def set_seen(account, message, seen, flag='\\Seen'):
    from .folders import select_message
    if flag not in ('\\Seen','\\Flagged'):
        raise ValueError('不支持的 IMAP 标记')
    with imap_connection(account) as client:
        select_message(client,message)
        checked(client.uid('STORE', message['uid'], '+FLAGS.SILENT' if seen else '-FLAGS.SILENT', '('+flag+')'), '设置邮件状态')

# ==========================================
# Function: Apply one flag to a bounded group in the same verified account and UID generation.
# Method: Authenticate/select once and send a UID set, leaving exact local acknowledgements to the owning service.
# ==========================================
def set_seen_many(account,messages,seen,flag='\\Seen'):
    from .folders import select_message
    if flag not in ('\\Seen','\\Flagged') or not messages or len(messages)>100:raise ValueError('批量邮件状态无效')
    first=messages[0];key=(account.id,first['folder'],first['validity'])
    if any((row['account'],row['folder'],row['validity'])!=key or row['remote_gone'] or not str(row['uid']).isdigit() for row in messages):raise ValueError('邮件 UID 范围已变化，请同步后重试')
    with imap_connection(account) as client:
        select_message(client,first)
        checked(client.uid('STORE',','.join(dict.fromkeys(str(row['uid']) for row in messages)),'+FLAGS.SILENT' if seen else '-FLAGS.SILENT','('+flag+')'),'批量设置邮件状态')

# ==========================================
# Function: Submit a MIME payload using SMTP with explicit ambiguity handling.
# Method: Confirm TLS/auth before DATA and distinguish definite rejection/disconnect.
# ==========================================
def deliver(account, raw, recipients):
    client = None
    data_started = False
    try:
        context = ssl.create_default_context()
        if account.smtp_security == 'ssl':
            client = smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=TIMEOUT, context=context)
        else:
            client = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=TIMEOUT)
            client.ehlo()
            client.starttls(context=context)
        client.ehlo()
        secret = account.secret()
        if account.auth == 'oauth2':
            import base64
            token = base64.b64encode(f'user={account.login_name}\x01auth=Bearer {secret}\x01\x01'.encode()).decode()
            code, _ = client.docmd('AUTH', 'XOAUTH2 ' + token)
            if code != 235:
                raise DeliveryError('SMTP OAuth2 认证失败，请检查令牌')
        else:
            client.login(account.login_name, secret)
        data_started = True
        refused = client.sendmail(account.email, recipients, raw)
        return refused
    except DeliveryError:
        raise
    except smtplib.SMTPAuthenticationError:
        raise DeliveryError('SMTP 认证失败，请检查授权码或令牌') from None
    except smtplib.SMTPRecipientsRefused:
        raise DeliveryError('全部收件人被服务器拒绝，邮件未投递') from None
    except smtplib.SMTPSenderRefused:
        raise DeliveryError('发件地址被服务器拒绝，邮件未投递') from None
    except smtplib.SMTPDataError:
        raise DeliveryError('SMTP 服务器拒绝了邮件内容，邮件未投递') from None
    except Exception:
        raise DeliveryError('发送连接中断，结果待确认' if data_started else '连接或认证失败，邮件未投递', uncertain=data_started) from None
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                # A failed QUIT cannot turn a confirmed DATA acceptance into a failure.
                try:
                    client.close()
                except Exception:
                    pass

# ==========================================
# Function: Save an optional server sent-copy after confirmed SMTP acceptance.
# Method: IMAP APPEND is separate from delivery and must never trigger resubmission.
# ==========================================
def append_sent(account, raw):
    if not account.sent_folder:
        return '未配置服务器已发送文件夹，仅保存本地副本'
    with imap_connection(account) as client:
        checked(client.append(mailbox_name(account.sent_folder), '(\\Seen)', None, raw), '保存已发送副本')
    return '已保存服务器副本'
