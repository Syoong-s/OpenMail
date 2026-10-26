"""Per-user Linux desktop installation with a relocatable native ELF entry point."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import subprocess

# ==========================================
# Function: Encode an executable filename for a freedesktop Exec value.
# Method: Escape reserved characters and desktop field-code percent signs.
# ==========================================
def desktop_exec(path):
    value = str(path).replace('\\', '\\\\\\\\').replace('"', '\\\\"').replace('`', '\\\\`').replace('$', '\\\\$').replace('%', '%%')
    return '"' + value + '"'

# ==========================================
# Function: Construct a non-terminal Linux application-menu entry.
# Method: Follow freedesktop desktop-entry keys with a separate demo action.
# ==========================================
def desktop_entry(executable, icon):
    command = desktop_exec(executable)
    # GIO validates the first Exec token before expanding %% in filenames.
    # env is a Linux executable (no shell); keep percent-bearing paths in argv.
    if '%' in str(executable):
        command = '/usr/bin/env -- ' + command
    return '\n'.join(['[Desktop Entry]', 'Type=Application', 'Version=1.0', 'Name=TeleMail',
        'GenericName=Email Client', 'Comment=Native Linux email client',
        'Comment[zh_CN]=Linux 原生邮件客户端', 'Exec=' + command + ' %u', 'MimeType=x-scheme-handler/mailto;', 'TryExec=' + str(executable).replace('\\', '\\\\'), 'Icon=' + str(icon),
        'Terminal=false', 'Categories=Network;Email;', 'StartupNotify=true',
        'StartupWMClass=TeleMail', 'Actions=Demo;', '', '[Desktop Action Demo]',
        'Name=Demo mailbox', 'Name[zh_CN]=体验演示邮箱', 'Exec=' + command + ' --demo', ''])

# ==========================================
# Function: Install the portable bundle into the current user's Linux application menu.
# Method: Stage immutable content by digest and atomically update owned desktop/symlink files.
# ==========================================
def install_user(bundle):
    bundle = Path(bundle).resolve()
    executable, payload = bundle / 'TeleMail', bundle / 'app'
    if not executable.is_file() or executable.read_bytes()[:4] != b'\x7fELF' or not (payload / 'maildesk/desktop.py').is_file():
        raise ValueError('请选择完整的 Linux TeleMail 发行目录')
    digest = hashlib.sha256()
    digest.update(executable.read_bytes())
    for file in sorted(payload.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            digest.update(str(file.relative_to(payload)).encode())
            digest.update(file.read_bytes())
    data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    state = data_home / 'telemail-application'
    state.mkdir(parents=True, exist_ok=True)
    target = state / digest.hexdigest()[:16]
    if not target.exists():
        staging = Path(tempfile.mkdtemp(prefix='.install-', dir=state))
        try:
            shutil.copy2(executable, staging / 'TeleMail')
            shutil.copytree(payload, staging / 'app', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            (staging / 'TeleMail').chmod(0o755)
            os.rename(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    applications = data_home / 'applications'
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / 'org.telemail.Desktop.desktop'
    descriptor, temporary = tempfile.mkstemp(prefix='.telemail-', dir=applications)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            file.write(desktop_entry(target / 'TeleMail', target / 'app/maildesk/desktop_assets/icon.svg'))
        os.chmod(temporary, 0o644)
        os.replace(temporary, entry)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    startup=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'autostart/org.telemail.Desktop.desktop'
    if startup.is_file():set_autostart(True)
    return entry

# ==========================================
# Function: Locate the currently installed desktop entry owned by TeleMail.
# Method: Require the normal installer output before registering optional OS behavior.
# ==========================================
def installed_entry():
    path=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'applications/org.telemail.Desktop.desktop'
    if not path.is_file():raise ValueError('请先从应用菜单安装 TeleMail，然后设置系统集成')
    return path

# ==========================================
# Function: Enable or disable startup only after an explicit settings choice.
# Method: Create a user-scoped XDG entry using the immutable installed executable and no shell.
# ==========================================
def set_autostart(enabled):
    path=Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config'))/'autostart/org.telemail.Desktop.desktop'
    if not enabled:
        path.unlink(missing_ok=True);return path
    original=installed_entry().read_text()
    lines=original.split('[Desktop Action',1)[0].splitlines()
    lines=[line for line in lines if not line.startswith(('Actions=','MimeType='))]
    lines=[line.replace(' %u','')+' --background' if line.startswith('Exec=') else line for line in lines]
    lines += ['X-GNOME-Autostart-enabled=true','']
    path.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.telemail-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:output.write('\n'.join(lines))
        os.chmod(temporary,0o600);os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return path

# ==========================================
# Function: Set TeleMail as the current user's mailto handler on explicit request.
# Method: Use xdg-mime argv without a shell and report unavailable desktop integration.
# ==========================================
def default_mail_client():
    installed_entry()
    try:result=subprocess.run(['xdg-mime','default','org.telemail.Desktop.desktop','x-scheme-handler/mailto'],capture_output=True,text=True,timeout=15)
    except (OSError,subprocess.TimeoutExpired) as error:raise ValueError('当前桌面不支持默认邮件应用设置') from error
    if result.returncode:raise ValueError('系统拒绝默认邮件应用设置，请在桌面“默认应用”中选择 TeleMail')
    return True

# Native Windows integration keeps existing Linux installers and settings untouched.
if os.name=='nt':
    from .windows_integration import install_user,set_autostart,default_mail_client
