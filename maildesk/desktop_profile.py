"""Native desktop paths and atomic graphical account configuration."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from .config import Account, load_accounts

# ==========================================
# Function: Locate desktop settings independently of the launch working directory.
# Method: Use TeleMail-owned XDG config/data paths with separate live and demo profiles.
# ==========================================
class DesktopProfile:
    # ==========================================
    # Function: Resolve explicit or XDG-standard desktop paths.
    # Method: Keep demos separate and never look up relative config in the caller's cwd.
    # ==========================================
    def __init__(self, demo=False, config=None, data=None):
        from .storage_paths import StorageLocations, configure_cache
        self.storage = StorageLocations(demo, config, data)
        configure_cache(self.storage)
        self.demo = self.storage.demo
        self.config, self.data = self.storage.config, self.storage.data
        self.cache, self.downloads = self.storage.cache, self.storage.downloads
        self.original_config, self.original_data = self.storage.original_config, self.storage.original_data
        self.application_id = ('org.telemail.Desktop.p' + self.storage.scope.removeprefix('explicit-')) if self.storage.scope.startswith('explicit-') else ('org.telemail.Desktop.Demo' if demo else 'org.telemail.Desktop')
        from .credentials import CredentialVault
        self.vault=CredentialVault(self.config)
        self.pending={};self.credential_errors={};self.credential_lock=threading.RLock()

    # ==========================================
    # Function: Read saved settings without storing credential material.
    # Method: Reuse the core's strict account validation.
    # ==========================================
    def accounts(self):
        return [] if self.demo or not self.config.exists() else load_accounts(self.config)

    # ==========================================
    # Function: Save or replace mailbox settings and stage a credential for login verification.
    # Method: Validate before private-file replacement and persist secrets only after authentication.
    # ==========================================
    def save_account(self, values, secret='', remember=True):
        account = Account(**{**values, 'folders': tuple(values.get('folders', ['INBOX']))})
        if self.demo:
            raise ValueError('演示模式不能修改真实账户；请打开普通 TeleMail 窗口')
        accounts = self.accounts()
        mapping = {item.id: item for item in accounts}
        mapping[account.id] = account
        self.write_accounts(list(mapping.values()))
        if secret:self.stage_credential(account,secret,remember)
        return list(mapping.values())

    # ==========================================
    # Function: Atomically write non-secret account settings.
    # Method: Stage a private JSON file before replacing the existing configuration.
    # ==========================================
    def write_accounts(self, accounts):
        self.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(prefix='.accounts-', dir=self.config.parent)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
                json.dump({'accounts': [asdict(item) for item in accounts]}, file, ensure_ascii=False, indent=2)
                file.write('\n')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.config)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    # ==========================================
    # Function: Commit only the exact candidate explicitly accepted after both checks.
    # Method: Match the receipt to account/credential, persist privately, then adopt session.
    # ==========================================
    def commit_verified_login(self, account, secret, receipt, remember=True):
        from .credentials import identity,session_secret,authenticated,refresh_saver,credential_lock
        import time
        if self.demo:raise ValueError('演示模式不能修改真实账户')
        if (receipt.get('identity')!=identity(account) or
            receipt.get('credential_digest')!=hashlib.sha256(secret.encode()).hexdigest() or
            not 0<=time.time()-receipt.get('verified_at',0)<600):
            raise ValueError('登录验证已失效，请重新验证')
        with credential_lock(account),self.credential_lock:
            mapping={item.id:item for item in self.accounts()}
            if any(item.id!=account.id and item.email.casefold()==account.email.casefold() for item in mapping.values()):
                raise ValueError('这个邮箱已经添加，请更新原账号的登录')
            old=mapping.get(account.id)
            with self.vault.lock:
                old_records=self.vault.load()
                mapping[account.id]=account
                try:
                    if remember:self.vault.save(account,secret)
                    else:
                        records=dict(old_records);records.pop(account.id,None)
                        if self.vault.records.exists() or records:self.vault.write(records)
                    self.write_accounts(list(mapping.values()))
                except Exception:
                    # Configuration failure must not silently replace a good saved login.
                    if self.vault.records.exists():
                        rollback=self.vault.load()
                        if account.id in old_records:rollback[account.id]=old_records[account.id]
                        else:rollback.pop(account.id,None)
                        self.vault.write(rollback)
                    raise
            if old is not None and identity(old)!=identity(account):
                session_secret(old,'');authenticated(old,clear=True);refresh_saver(old,clear=True)
            session_secret(account,secret);authenticated(account,clear=True)
            refresh_saver(account,clear=True)
            if remember:refresh_saver(account,self.vault.save)
            self.pending.pop(account.id,None);self.credential_errors.pop(account.id,None)
            return list(mapping.values())

    # ==========================================
    # Function: Make a typed credential available for this login attempt.
    # Method: Retain it in memory and remember the user's persistence choice.
    # ==========================================
    def stage_credential(self, account, secret, remember=True):
        from .credentials import identity,session_secret,authenticated,credential_lock
        with credential_lock(account),self.credential_lock:
            session_secret(account,secret)
            self.pending[account.id]=(identity(account),secret,remember)
            if not remember:self.vault.forget(account);session_secret(account,secret)
            authenticated(account,self.authenticated)

    # ==========================================
    # Function: Observe accepted provider authentication without failing a valid connection.
    # Method: Surface local persistence errors separately from network/mailbox status.
    # ==========================================
    def authenticated(self, account):
        try:self.confirm_login(account)
        except (ValueError,OSError):self.credential_errors[account.id]='登录成功，但本机凭据保存失败，请在账号设置中重试'

    # ==========================================
    # Function: Persist a staged credential after a successful provider login.
    # Method: Check the exact connection fingerprint to reject stale concurrent edits.
    # ==========================================
    def confirm_login(self, account):
        from .credentials import identity,authenticated
        with self.credential_lock:
            value=self.pending.get(account.id)
            if not value or value[0]!=identity(account):return
            if value[2]:self.vault.save(account,value[1])
            self.pending.pop(account.id,None);self.credential_errors.pop(account.id,None)
            authenticated(account,clear=True)

    # ==========================================
    # Function: Restore remembered credentials at native application startup.
    # Method: Authenticate local ciphertext and keep failures scoped to one account.
    # ==========================================
    def restore_credentials(self, accounts):
        from .credentials import session_secret,refresh_saver
        for account in accounts:
            try:
                value=self.vault.get(account)
                if value:
                    session_secret(account,value);refresh_saver(account,self.vault.save)
            except (ValueError,OSError,KeyError):
                self.credential_errors[account.id]='无法读取已保存凭据，请在账号设置中重新登录'

    # ==========================================
    # Function: Report credential persistence without revealing its content.
    # Method: Inspect pending state and validate an existing saved envelope.
    # ==========================================
    def credential_state(self, account):
        if account.id in self.pending:return '待验证后保存' if self.pending[account.id][2] else '仅本次会话'
        try:return '已在本机保存' if self.vault.get(account) else '尚未保存'
        except (ValueError,OSError,KeyError):return '需要重新登录'

    # ==========================================
    # Function: Forget saved and staged credentials for a mailbox.
    # Method: Remove only its encrypted record and in-memory credential.
    # ==========================================
    def forget_credential(self, account):
        from .credentials import session_secret,authenticated,refresh_saver,credential_lock
        with credential_lock(account),self.credential_lock:
            self.pending.pop(account.id,None);self.vault.forget(account);session_secret(account,'')
            authenticated(account,clear=True)
            refresh_saver(account,clear=True)
            self.credential_errors.pop(account.id,None)

    # ==========================================
    # Function: Remove an account connection while preserving downloaded mail.
    # Method: Rewrite configuration without the account and forget its local login.
    # ==========================================
    def remove_account(self, account):
        if self.demo:raise ValueError('演示模式不能修改真实账户')
        accounts=[item for item in self.accounts() if item.id!=account.id]
        self.write_accounts(accounts);self.forget_credential(account)
        return accounts
