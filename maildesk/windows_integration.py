"""User-scoped native Windows desktop registration; never edits machine-wide settings."""
import base64
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys

# ==========================================
# Function: Resolve the current portable native executable for optional integration.
# Method: Require an actual launcher path rather than registering a Python source command.
# ==========================================
def executable():
    value=Path(os.environ.get('TELEMAIL_LAUNCHER',sys.executable)).resolve()
    if value.suffix.lower()!='.exe' or not value.is_file():raise ValueError('请使用 TeleMail.exe 设置系统集成')
    return value

# ==========================================
# Function: Read the current user's explicit startup registration.
# Method: Inspect only TeleMail's own HKCU Run value without changing Windows settings.
# ==========================================
def startup_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value=winreg.QueryValueEx(key,'TeleMail')[0]
        return value==subprocess.list2cmdline([str(executable()),'--background'])
    except OSError:return False

# ==========================================
# Function: Enable or disable launch-at-login only for the current user.
# Method: Write a correctly quoted native executable command into TeleMail's HKCU Run value.
# ==========================================
def set_autostart(enabled):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:winreg.SetValueEx(key,'TeleMail',0,winreg.REG_SZ,subprocess.list2cmdline([str(executable()),'--background']))
        else:
            try:winreg.DeleteValue(key,'TeleMail')
            except FileNotFoundError:pass
    return enabled

# ==========================================
# Function: Register TeleMail as an available mail application without overriding user choices.
# Method: Add owned current-user capabilities and a mailto ProgID with safe quoted URI argv.
# ==========================================
def register_application():
    import winreg
    launcher=executable();command=subprocess.list2cmdline([str(launcher)])+' -- "%1"'
    values={r'Software\Classes\TeleMail.Mailto':{'':'TeleMail mail link','URL Protocol':''},
        r'Software\Classes\TeleMail.Mailto\DefaultIcon':{'':str(launcher)+',0'},
        r'Software\Classes\TeleMail.Mailto\shell\open\command':{'':command},
        r'Software\TeleMail\Capabilities':{'ApplicationName':'TeleMail','ApplicationDescription':'TeleMail 本地邮件客户端'},
        r'Software\TeleMail\Capabilities\URLAssociations':{'mailto':'TeleMail.Mailto'},
        r'Software\RegisteredApplications':{'TeleMail':r'Software\TeleMail\Capabilities'}}
    for path,entries in values.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key:
            for name,value in entries.items():winreg.SetValueEx(key,name,0,winreg.REG_SZ,value)
    return launcher

# ==========================================
# Function: Create an ordinary Start-menu entry pointing directly at TeleMail.exe.
# Method: Use Windows' installed shell shortcut COM object only during explicit installation.
# ==========================================
def install_user(bundle=None):
    if bundle is not None:
        candidate=Path(bundle)/'TeleMail.exe'
        if not candidate.is_file() or candidate.read_bytes()[:2]!=b'MZ':raise ValueError('请选择完整的 Windows TeleMail 发行目录')
    launcher=register_application()
    folder=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs'
    folder.mkdir(parents=True,exist_ok=True);shortcut=folder/'TeleMail.lnk'
    # PowerShell is a one-time ShellLink creator, never part of application startup.
    literal=lambda value:"'"+str(value).replace("'","''")+"'"
    script='$s=(New-Object -ComObject WScript.Shell).CreateShortcut('+literal(shortcut)+');$s.TargetPath='+literal(launcher)+';$s.WorkingDirectory='+literal(launcher.parent)+';$s.IconLocation='+literal(str(launcher)+',0')+';$s.Save()'
    encoded=base64.b64encode(script.encode('utf-16-le')).decode()
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand',encoded],check=True,creationflags=0x08000000,timeout=30,capture_output=True)
    return shortcut

# ==========================================
# Function: Open Windows' own default-app chooser after registering capabilities.
# Method: Respect protected UserChoice ownership and let the user select TeleMail normally.
# ==========================================
def default_mail_client():
    register_application()
    shell=C.WinDLL('shell32').ShellExecuteW
    shell.argtypes=[C.c_void_p,C.c_wchar_p,C.c_wchar_p,C.c_wchar_p,C.c_wchar_p,C.c_int];shell.restype=C.c_void_p
    result=shell(None,'open','ms-settings:defaultapps',None,None,1)
    if not result or result<=32:raise ValueError('无法打开 Windows 默认应用设置')
    return True

# ==========================================
# Function: Route second activations to the matching native Windows mailbox profile.
# Method: Own a per-profile mutex and a hidden WM_COPYDATA window on the GTK thread.
# ==========================================
class WindowsInstance:
    # ==========================================
    # Function: Reserve one profile before opening its database.
    # Method: Resolve a second instance by exact application ID and bounded Unicode activation data.
    # ==========================================
    def __init__(self,app):
        import time
        self.app=app;self.window=None;self.primary=False;self.closed=False
        self.kernel=C.WinDLL('kernel32',use_last_error=True);self.user=C.WinDLL('user32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=[C.c_void_p,C.c_int,C.c_wchar_p];self.kernel.CreateMutexW.restype=C.c_void_p
        self.kernel.CloseHandle.argtypes=[C.c_void_p];self.kernel.CloseHandle.restype=C.c_int
        self.classname='TeleMailActivation.'+app.profile.application_id
        self.mutex=self.kernel.CreateMutexW(None,False,'Local\\'+self.classname)
        if not self.mutex:raise OSError('无法创建应用实例锁')
        exists=C.get_last_error()==183
        self.user.FindWindowW.argtypes=[C.c_wchar_p,C.c_wchar_p];self.user.FindWindowW.restype=C.c_void_p
        self.user.SendMessageTimeoutW.argtypes=[C.c_void_p,C.c_uint,C.c_size_t,C.c_ssize_t,C.c_uint,C.c_uint,C.POINTER(C.c_size_t)];self.user.SendMessageTimeoutW.restype=C.c_size_t
        # ==========================================
        # Function: Match the documented native CopyData structure layout.
        # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
        # ==========================================
        class CopyData(C.Structure):_fields_=[('tag',C.c_size_t),('size',C.c_uint),('data',C.c_void_p)]
        self.CopyData=CopyData
        if exists:
            deadline=time.monotonic()+3;target=None
            while not target and time.monotonic()<deadline:
                target=self.user.FindWindowW(self.classname,None)
                if not target:time.sleep(.04)
            if not target:self.close();raise OSError('另一个 TeleMail 实例正在启动，请稍后重试')
            import json
            payload=C.create_unicode_buffer(json.dumps(getattr(app.options,'uris',[])))
            packet=CopyData(1,C.sizeof(payload),C.cast(payload,C.c_void_p));result=C.c_size_t()
            if not self.user.SendMessageTimeoutW(target,0x4a,0,C.addressof(packet),2,3000,C.byref(result)):
                self.close();raise OSError('无法激活已打开的 TeleMail，请检查旧进程状态')
            return
        self.primary=True;self.proc_type=C.WINFUNCTYPE(C.c_ssize_t,C.c_void_p,C.c_uint,C.c_size_t,C.c_ssize_t)
        # ==========================================
        # Function: Match the documented native WindowClass structure layout.
        # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
        # ==========================================
        class WindowClass(C.Structure):
            _fields_=[('style',C.c_uint),('proc',C.c_void_p),('cls_extra',C.c_int),('wnd_extra',C.c_int),('instance',C.c_void_p),('icon',C.c_void_p),('cursor',C.c_void_p),('background',C.c_void_p),('menu',C.c_wchar_p),('name',C.c_wchar_p)]
        self.kernel.GetModuleHandleW.argtypes=[C.c_wchar_p];self.kernel.GetModuleHandleW.restype=C.c_void_p
        self.user.RegisterClassW.argtypes=[C.c_void_p];self.user.RegisterClassW.restype=C.c_ushort
        self.user.CreateWindowExW.argtypes=[C.c_uint,C.c_wchar_p,C.c_wchar_p,C.c_uint,C.c_int,C.c_int,C.c_int,C.c_int,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p];self.user.CreateWindowExW.restype=C.c_void_p
        self.user.DefWindowProcW.argtypes=[C.c_void_p,C.c_uint,C.c_size_t,C.c_ssize_t];self.user.DefWindowProcW.restype=C.c_ssize_t
        self.user.DestroyWindow.argtypes=[C.c_void_p];self.user.DestroyWindow.restype=C.c_int
        self.user.UnregisterClassW.argtypes=[C.c_wchar_p,C.c_void_p];self.user.UnregisterClassW.restype=C.c_int
        self.instance=self.kernel.GetModuleHandleW(None);self.callback=self.proc_type(self.dispatch)
        definition=WindowClass();definition.proc=C.cast(self.callback,C.c_void_p);definition.instance=self.instance;definition.name=self.classname
        self.user.RegisterClassW(C.byref(definition))
        self.window=self.user.CreateWindowExW(0,self.classname,'TeleMail activation',0,0,0,0,0,None,None,self.instance,None)
        if not self.window:self.close();raise OSError('无法创建应用激活窗口')

    # ==========================================
    # Function: Accept only bounded activation requests for this exact profile.
    # Method: Parse copied UTF-16 JSON and let the existing safe mailto parser open unsent drafts.
    # ==========================================
    def dispatch(self,window,message,wparam,lparam):
        if message==0x4a:
            if self.app.closing:return 0
            try:
                import json
                packet=C.cast(lparam,C.POINTER(self.CopyData)).contents
                if packet.tag!=1 or not 0<packet.size<=65536 or packet.size%C.sizeof(C.c_wchar):return 0
                data=C.wstring_at(packet.data,packet.size//C.sizeof(C.c_wchar)).rstrip('\0')
                values=json.loads(data)
                if not isinstance(values,list) or len(values)>8 or not all(isinstance(value,str) for value in values):return 0
                self.app.restore_window()
                for uri in values:self.app.run_action(lambda value=uri:self.app.open_mailto(value))
                return 1
            except Exception:return 0
        return self.user.DefWindowProcW(window,message,wparam,lparam)

    # ==========================================
    # Function: Release only this profile's owned activation resources.
    # Method: Destroy the callback HWND before closing the mutex and retained trampoline.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True
        if self.window:self.user.DestroyWindow(self.window);self.window=None
        if self.primary and hasattr(self,'instance'):self.user.UnregisterClassW(self.classname,self.instance)
        if self.mutex:self.kernel.CloseHandle(self.mutex);self.mutex=None
