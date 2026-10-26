"""Validated connection settings; credentials resolve from memory or CLI environment."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re

# ==========================================
# Function: Validate a single mailbox configuration.
# Method: Immutable settings with explicit TLS and environment credential references.
# ==========================================
@dataclass(frozen=True)
class Account:
    id: str
    email: str
    imap_host: str
    smtp_host: str
    username: str = ''
    imap_port: int = 993
    smtp_port: int = 465
    imap_security: str = 'ssl'
    smtp_security: str = 'ssl'
    auth: str = 'password'
    secret_env: str = 'MAIL_PASSWORD'
    folders: tuple[str, ...] = ('INBOX',)
    sent_folder: str = ''
    title: str = ''
    display_name: str = ''

    # ==========================================
    # Function: Reject malformed or insecure connection settings.
    # Method: Validate ports, identifiers, protocol modes, and header values.
    # ==========================================
    def __post_init__(self):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.id):
            raise ValueError('账户 id 只能包含字母、数字、下划线和短横线')
        if '@' not in self.email or any(c in self.email for c in '\r\n'):
            raise ValueError('账户邮箱格式无效')
        if any(c in self.title+self.display_name for c in '\r\n'):
            raise ValueError('账号名称和发件人名称不能包含换行')
        for host in (self.imap_host, self.smtp_host):
            if not host or any(c.isspace() for c in host):
                raise ValueError('邮件服务器地址无效')
        for port in (self.imap_port, self.smtp_port):
            if not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError('邮件服务器端口无效')
        if self.imap_security not in ('ssl', 'starttls') or self.smtp_security not in ('ssl', 'starttls'):
            raise ValueError('连接必须使用 ssl 或 starttls')
        if self.auth not in ('password', 'oauth2'):
            raise ValueError('认证只支持 password 或 oauth2')
        if not self.secret_env or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', self.secret_env):
            raise ValueError('secret_env 必须是环境变量名称')
        if not self.folders or any(not f or any(c in f for c in '\r\n') for f in self.folders):
            raise ValueError('必须指定有效的同步文件夹')

    # ==========================================
    # Function: Resolve the credential without storing or displaying it.
    # Method: Prefer the desktop session cache, retaining environment support for CLI use.
    # ==========================================
    def secret(self):
        from .credentials import session_secret
        value = session_secret(self) or os.environ.get(self.secret_env)
        if not value:
            raise ValueError(f'请在账号设置中登录账户 {self.id}')
        from .credentials import access_secret
        return access_secret(self,value)

    # ==========================================
    # Function: Resolve the provider login identity.
    # Method: Fall back to the email address when username is omitted.
    # ==========================================
    @property
    def login_name(self):
        return self.username or self.email

# ==========================================
# Function: Load accounts and detect accidental duplicate identities.
# Method: Parse local JSON; reject unknown keys via the dataclass constructor.
# ==========================================
def load_accounts(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('accounts'), list):
        raise ValueError('配置必须包含 accounts 数组')
    if any(not isinstance(a, dict) or not isinstance(a.get('folders', ['INBOX']), list) for a in data['accounts']):
        raise ValueError('账户必须是对象，folders 必须是文件夹名称数组')
    accounts = [Account(**{**a, 'folders': tuple(a.get('folders', ['INBOX']))}) for a in data['accounts']]
    if len({a.id for a in accounts}) != len(accounts):
        raise ValueError('账户 id 不可重复')
    return accounts
