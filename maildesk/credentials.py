"""Local authenticated credentials: Linux AES-GCM and native Windows user-bound DPAPI.

The private device key is readable by the Linux user; this does not protect
against that user's processes or root. No passwords enter config JSON or argv.
"""
import base64
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading

_sessions = {}
_authenticated = {}
_session_lock = threading.RLock()
_refresh_locks = {}
_credential_locks = {}
_refresh_savers = {}

# ==========================================
# Function: Bind a credential to the exact account login and transport identity.
# Method: Hash canonical connection fields, preventing reuse for a changed server/user.
# ==========================================
def identity(account):
    values = [account.id, account.email, account.login_name, account.imap_host,
              account.imap_port, account.imap_security, account.smtp_host,
              account.smtp_port, account.smtp_security, account.auth]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

# ==========================================
# Function: Retain desktop credentials without exporting them to child processes.
# Method: Use a locked in-process mapping independent of CLI environment credentials.
# ==========================================
def session_secret(account, value=None):
    with _session_lock:
        key = identity(account)
        if value is not None:
            if value:_sessions[key] = value
            else:_sessions.pop(key, None)
        return _sessions.get(key, '')

# ==========================================
# Function: Associate an encrypted-vault update with one accepted OAuth session.
# Method: Keep refresh persistence callbacks outside the serialized credential bundle.
# ==========================================
def refresh_saver(account, callback=None, clear=False):
    with _session_lock:
        key=identity(account)
        if clear:_refresh_savers.pop(key,None)
        elif callback is not None:_refresh_savers[key]=callback

# ==========================================
# Function: Serialize accepted credential replacement with in-flight token refresh.
# Method: Return a per-identity reentrant lock without blocking unrelated accounts.
# ==========================================
def credential_lock(account):
    with _session_lock:return _credential_locks.setdefault(account.id,threading.RLock())

# ==========================================
# Function: Resolve or refresh an accepted OAuth credential before transport AUTH.
# Method: Serialize refresh per identity, rotate tokens and retain encrypted persistence.
# ==========================================
def access_secret(account, value):
    if account.auth!='oauth2':return value
    from .account_login import decode_oauth,encode_oauth,token_request,LoginError
    import time
    bundle=decode_oauth(value)
    if bundle is None:return value
    with _session_lock:lock=_refresh_locks.setdefault(identity(account),threading.RLock())
    with lock:
        with credential_lock(account):
            current=session_secret(account)
            if not current and os.environ.get(account.secret_env)!=value:
                raise LoginError('登录状态已更新，请重新登录')
            bundle=decode_oauth(current or value)
            if bundle is None:return current or value
            if bundle['expires_at']>time.time()+60:return bundle['access_token']
        if not bundle.get('refresh_token'):raise LoginError('邮箱授权已过期，请在账号设置中重新登录')
        values={'client_id':bundle['client_id'],'refresh_token':bundle['refresh_token'],'grant_type':'refresh_token'}
        if bundle.get('client_secret'):values['client_secret']=bundle['client_secret']
        token=token_request(bundle['provider'],values)
        token.setdefault('refresh_token',bundle['refresh_token'])
        encoded=encode_oauth(bundle['provider'],bundle['client_id'],token,bundle.get('client_secret',''))
        with credential_lock(account),_session_lock:
            # A concurrent logout/re-login must not resurrect an obsolete grant.
            if session_secret(account)!=(current or value):raise LoginError('登录状态已更新，请重试')
            saver=_refresh_savers.get(identity(account))
            if saver:saver(account,encoded)
            session_secret(account,encoded)
        return token['access_token']

# ==========================================
# Function: Register or invoke a successful-login observer for one desktop credential.
# Method: Notify only after the TLS provider has accepted authentication, never on staging.
# ==========================================
def authenticated(account, callback=None, clear=False):
    with _session_lock:
        key=identity(account)
        if clear:_authenticated.pop(key,None);return
        if callback is not None:_authenticated[key]=callback;return
        observer=_authenticated.get(key)
    if observer:observer(account)

# ==========================================
# Function: Encrypt or authenticate/decrypt a small credential with AES-256-GCM.
# Method: Call OpenSSL EVP with a 96-bit nonce, 128-bit tag and account-bound AAD.
# ==========================================
def aes_gcm(key, nonce, data, aad=b'', tag=None):
    if len(key) != 32 or len(nonce) != 12 or (tag is not None and len(tag) != 16):
        raise ValueError('本机凭据格式无效')
    from .platform_native import load_library
    lib=load_library('crypto');P=C.c_void_p;I=C.c_int
    signatures={'EVP_CIPHER_CTX_new':(P,), 'EVP_CIPHER_CTX_free':(None,P),
        'EVP_aes_256_gcm':(P,), 'EVP_CIPHER_CTX_ctrl':(I,P,I,I,P)}
    mode='Encrypt' if tag is None else 'Decrypt'
    signatures.update({f'EVP_{mode}Init_ex':(I,P,P,P,P,P),
        f'EVP_{mode}Update':(I,P,P,P,P,I),f'EVP_{mode}Final_ex':(I,P,P,P)})
    for name,signature in signatures.items():
        fn=getattr(lib,name);fn.restype=signature[0];fn.argtypes=signature[1:]
    context=lib.EVP_CIPHER_CTX_new()
    if not context:raise ValueError('本机凭据加密不可用')
    output=C.create_string_buffer(len(data)+16);length=I();final=I()
    try:
        init=getattr(lib,f'EVP_{mode}Init_ex');update=getattr(lib,f'EVP_{mode}Update')
        if init(context,lib.EVP_aes_256_gcm(),None,key,nonce)!=1:raise ValueError('本机凭据加密不可用')
        if aad and update(context,None,C.byref(length),aad,len(aad))!=1:raise ValueError('本机凭据认证失败')
        if update(context,output,C.byref(length),data,len(data))!=1:raise ValueError('本机凭据处理失败')
        used=length.value
        if tag is not None and lib.EVP_CIPHER_CTX_ctrl(context,0x11,16,C.create_string_buffer(tag))!=1:
            raise ValueError('本机凭据认证失败')
        if getattr(lib,f'EVP_{mode}Final_ex')(context,C.byref(output,used),C.byref(final))!=1:
            raise ValueError('本机凭据已损坏或与此账户不匹配，请重新登录')
        result=output.raw[:used+final.value]
        if tag is not None:return result
        result_tag=C.create_string_buffer(16)
        if lib.EVP_CIPHER_CTX_ctrl(context,0x10,16,result_tag)!=1:raise ValueError('本机凭据认证失败')
        return result,result_tag.raw
    finally:lib.EVP_CIPHER_CTX_free(context)

# ==========================================
# Function: Maintain encrypted saved logins in an application-private directory.
# Method: Atomically replace 0600 records and keep a separate 0600 random device key.
# ==========================================
class CredentialVault:
    # ==========================================
    # Function: Isolate credentials for each explicit account configuration.
    # Method: Derive a stable namespace from the resolved config path.
    # ==========================================
    def __init__(self, config):
        path=Path(config).resolve()
        self.root=path.parent/('credentials-'+hashlib.sha256(str(path).encode()).hexdigest()[:12])
        self.records=self.root/'logins.json';self.keyfile=self.root/'device.key'
        self.lock=threading.RLock()

    # ==========================================
    # Function: Reject public, foreign-owned or symlinked secret files.
    # Method: Open without following links and validate the actual descriptor mode.
    # ==========================================
    def read_private(self, path):
        if os.name=='nt':
            info=path.lstat()
            if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
                raise ValueError('本机凭据文件不能是链接')
        descriptor=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
        with os.fdopen(descriptor,'rb') as file:
            info=os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode&0o077)):
                raise ValueError('本机凭据文件权限无效，请在账号设置中重新登录')
            return file.read(1024*1024)

    # ==========================================
    # Function: Read the local key or generate it only for a new vault.
    # Method: Create with O_EXCL and never silently replace a lost existing key.
    # ==========================================
    def key(self):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.root.is_symlink():raise ValueError('本机凭据目录无效')
        if not self.keyfile.exists():
            if self.records.exists():raise ValueError('本机凭据密钥丢失，请忘记凭据后重新登录')
            try:
                descriptor=os.open(self.keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(descriptor,'wb') as file:file.write(os.urandom(32));file.flush();os.fsync(file.fileno())
            except FileExistsError:pass
        key=self.read_private(self.keyfile)
        if len(key)!=32:raise ValueError('本机凭据密钥无效')
        return key

    # ==========================================
    # Function: Read only bounded credential envelopes without exposing values.
    # Method: Parse a private JSON map of authenticated ciphertext records.
    # ==========================================
    def load(self):
        if not self.records.exists():return {}
        data=json.loads(self.read_private(self.records))
        if not isinstance(data,dict):raise ValueError('本机凭据索引无效')
        return data

    # ==========================================
    # Function: Commit a complete credential index without partial writes.
    # Method: Flush a private temporary file then atomically replace the index.
    # ==========================================
    def write(self, records):
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        descriptor,temporary=tempfile.mkstemp(prefix='.logins-',dir=self.root)
        try:
            with os.fdopen(descriptor,'w') as file:
                json.dump(records,file);file.flush();os.fsync(file.fileno())
            os.replace(temporary,self.records)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)

    # ==========================================
    # Function: Save one verified login without placing plaintext in settings.
    # Method: Use a fresh random nonce and account identity as authenticated metadata.
    # ==========================================
    def save(self, account, secret):
        if not secret or len(secret.encode())>65536:raise ValueError('邮箱凭据长度无效')
        with self.lock:
            if os.name=='nt':
                from .platform_native import protect_data
                self.root.mkdir(parents=True,exist_ok=True)
                if self.root.is_symlink():raise ValueError('本机凭据目录无效')
                records=self.load();encrypted=protect_data(secret.encode(),identity(account).encode())
                records[account.id]={'identity':identity(account),'protection':'windows-dpapi-user','data':base64.b64encode(encrypted).decode()}
                self.write(records);return
            key=self.key();records=self.load();nonce=os.urandom(12)
            ciphertext,tag=aes_gcm(key,nonce,secret.encode(),identity(account).encode())
            records[account.id]={'identity':identity(account),'data':base64.b64encode(nonce+tag+ciphertext).decode()}
            self.write(records)

    # ==========================================
    # Function: Restore only a login matching the current account settings.
    # Method: Verify GCM before decoding or releasing any credential bytes.
    # ==========================================
    def get(self, account):
        with self.lock:
            record=self.load().get(account.id)
            if not record or record.get('identity')!=identity(account):return ''
            raw=base64.b64decode(record['data'],validate=True)
            if os.name=='nt':
                from .platform_native import protect_data
                if record.get('protection')!='windows-dpapi-user':raise ValueError('本机凭据平台不匹配，请重新登录')
                return protect_data(raw,identity(account).encode(),decrypt=True).decode()
            if len(raw)<28:raise ValueError('本机凭据格式无效')
            return aes_gcm(self.key(),raw[:12],raw[28:],identity(account).encode(),raw[12:28]).decode()

    # ==========================================
    # Function: Forget one saved login while retaining downloaded mail.
    # Method: Atomically remove its envelope, with no message database changes.
    # ==========================================
    def forget(self, account):
        with credential_lock(account):
            with self.lock:
                records=self.load();records.pop(account.id,None)
                if records:self.write(records)
                elif self.records.exists():self.records.unlink()
            session_secret(account,'')
