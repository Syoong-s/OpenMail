"""Small operating-system boundary shared by the Linux and native Windows clients."""
import ctypes as C
import hashlib
import tempfile
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

WINDOWS=sys.platform=='win32'
_DLL_DIRECTORIES=[]
_LIBRARIES={
 'gtk':('libgtk-3.so.0','libgtk-3-0.dll'),'gdk':('libgdk-3.so.0','libgdk-3-0.dll'),
 'object':('libgobject-2.0.so.0','libgobject-2.0-0.dll'),'gio':('libgio-2.0.so.0','libgio-2.0-0.dll'),
 'glib':('libglib-2.0.so.0','libglib-2.0-0.dll'),'pixbuf':('libgdk_pixbuf-2.0.so.0','libgdk_pixbuf-2.0-0.dll'),
 'pango':('libpango-1.0.so.0','libpango-1.0-0.dll'),'pangocairo':('libpangocairo-1.0.so.0','libpangocairo-1.0-0.dll'),
 'cairo':('libcairo.so.2','libcairo-2.dll'),'fontconfig':('libfontconfig.so.1','libfontconfig-1.dll'),
 'crypto':('libcrypto.so.3','libcrypto-3-x64.dll')}

# ==========================================
# Function: Resolve only explicitly supported public native library names.
# Method: Keep cdecl GLib ABI aliases separate from Windows system APIs.
# ==========================================
def library_name(name,windows=None):
    if name not in _LIBRARIES:raise ValueError('Unknown native library: '+name)
    return _LIBRARIES[name][int(WINDOWS if windows is None else windows)]

# ==========================================
# Function: Locate the application-private Windows runtime independently of cwd.
# Method: Resolve the launcher-provided root or the portable app's sibling runtime.
# ==========================================
def runtime_root():
    return Path(os.environ.get('TELEMAIL_WINDOWS_RUNTIME',Path(__file__).resolve().parents[2]/'runtime')).resolve()

# ==========================================
# Function: Configure private DLL and GTK data lookup without modifying global PATH.
# Method: Register private DLL/data paths and initialize coherent whole-window Windows DPI scaling.
# ==========================================
def prepare_windows():
    if not WINDOWS:return
    root=runtime_root();binpath=root/'bin'
    for folder in (root,binpath):
        if folder.is_dir():_DLL_DIRECTORIES.append(os.add_dll_directory(str(folder)))
    os.environ['PATH']=str(binpath)+os.pathsep+os.environ.get('PATH','')
    os.environ.setdefault('GTK_DATA_PREFIX',str(root))
    os.environ.setdefault('GSETTINGS_SCHEMA_DIR',str(root/'share/glib-2.0/schemas'))
    os.environ.setdefault('GIO_MODULE_DIR',str(root/'lib/gio/modules'))
    os.environ.setdefault('GSETTINGS_BACKEND','memory')
    # GApplication still probes a bus in NON_UNIQUE mode. An unsupported private
    # transport fails immediately and prevents optional dbus-daemon autolaunch;
    # 'disabled' is not a special D-Bus token. Preserve a user's existing bus.
    os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS','disabled:')
    os.environ.setdefault('FONTCONFIG_PATH',str(root/'etc/fonts'))
    os.environ.setdefault('FONTCONFIG_FILE',str(root/'etc/fonts/fonts.conf'))
    prepare_pixbuf_cache(root)
    from .windows_display import configure
    configure()

# ==========================================
# Function: Resolve relocatable SVG/image loaders without writing into the application bundle.
# Method: Query relative private module paths from the runtime root and cache complete records in LocalAppData.
# ==========================================
def prepare_pixbuf_cache(root):
    modules=sorted((root/'lib/gdk-pixbuf-2.0/2.10.0/loaders').glob('*.dll'))
    helper=root/'bin/gdk-pixbuf-query-loaders.exe'
    if not modules or not helper.is_file():raise RuntimeError('应用图像运行库不完整，请保留完整 runtime 目录')
    identity=hashlib.sha256(b'pixbuf-relative-v2\0'+str(root).encode())
    for module in modules:
        info=module.stat();identity.update((module.name+str(info.st_size)+str(info.st_mtime_ns)).encode())
    from .storage_paths import active_cache
    folder=active_cache()/'pixbuf'/identity.hexdigest()[:16]
    folder.mkdir(parents=True,exist_ok=True);cache=folder/'loaders.cache'
    if not cache.is_file():
        result=subprocess.run([str(helper),*[str(module.relative_to(root)) for module in modules]],cwd=root,capture_output=True,timeout=30,creationflags=0x08000000)
        if result.returncode or any(module.name.encode() not in result.stdout for module in modules):
            raise RuntimeError('应用图像加载器初始化失败')
        descriptor,temporary=tempfile.mkstemp(prefix='.loaders-',dir=folder)
        try:
            with os.fdopen(descriptor,'wb') as output:output.write(result.stdout)
            os.replace(temporary,cache)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    os.environ['GDK_PIXBUF_MODULE_FILE']=str(cache)
    os.environ['GDK_PIXBUF_MODULEDIR']=str(modules[0].parent)

# ==========================================
# Function: Bind an application-private DLL or a Linux system SONAME.
# Method: Prefer absolute private paths on Windows and retain lazy loading.
# ==========================================
def load_library(name):
    alias=library_name(name)
    if WINDOWS:
        root=runtime_root()
        for candidate in (root/'bin'/alias,root/alias):
            if candidate.is_file():return C.CDLL(str(candidate))
        raise RuntimeError('缺少应用私有运行库：'+str(root/'bin'/alias))
    return C.CDLL(alias)

# ==========================================
# Function: Return native per-user configuration and mailbox roots.
# Method: Follow Windows roaming/local conventions or Linux XDG conventions.
# ==========================================
def profile_homes(windows=None):
    if WINDOWS if windows is None else windows:
        return (Path(os.environ.get('APPDATA',Path.home()/'AppData/Roaming')),
                Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local')))
    return (Path(os.environ.get('XDG_CONFIG_HOME',Path.home()/'.config')),
            Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share')))

# ==========================================
# Function: Exclude simultaneous writers to one user's mailbox cache.
# Method: Lock one persistent byte on Windows or the existing whole file on Linux.
# ==========================================
def lock_instance(file):
    if WINDOWS:
        import msvcrt
        file.seek(0,2)
        if not file.tell():file.write(b'\0');file.flush()
        file.seek(0);msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)

# ==========================================
# Function: Open an explicit safe web or mail link in the user's default application.
# Method: Validate the scheme and use native ShellExecute/GIO without a command shell.
# ==========================================
def open_uri(uri,windows=None):
    if any(ord(char)<32 for char in uri) or urlsplit(uri).scheme.lower() not in ('https','http','mailto'):
        raise ValueError('不支持的外部链接')
    if WINDOWS if windows is None else windows:
        shell=C.WinDLL('shell32',use_last_error=True).ShellExecuteW
        shell.argtypes=[C.c_void_p,C.c_wchar_p,C.c_wchar_p,C.c_wchar_p,C.c_wchar_p,C.c_int];shell.restype=C.c_void_p
        result=shell(None,'open',uri,None,None,1)
        if not result or result<=32:raise OSError('无法打开链接')
    else:subprocess.Popen(['gio','open',uri],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

# ==========================================
# Function: Protect or unprotect one small account-bound credential with Windows DPAPI.
# Method: Request current-user protection without UI and release every LocalAlloc result.
# ==========================================
def protect_data(data,entropy,decrypt=False):
    # ==========================================
    # Function: Match the documented native Blob structure layout.
    # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
    # ==========================================
    class Blob(C.Structure):
        _fields_=[('size',C.c_uint32),('data',C.POINTER(C.c_ubyte))]
    raw=C.create_string_buffer(data);extra=C.create_string_buffer(entropy)
    source=Blob(len(data),C.cast(raw,C.POINTER(C.c_ubyte)))
    bound=Blob(len(entropy),C.cast(extra,C.POINTER(C.c_ubyte)));output=Blob()
    crypt=C.WinDLL('crypt32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[C.POINTER(Blob),C.c_void_p,C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_uint32,C.POINTER(Blob)]
    function.restype=C.c_int
    if not function(C.byref(source),None,C.byref(bound),None,None,1,C.byref(output)):
        raise ValueError('Windows 本机凭据认证失败，请重新登录')
    kernel=C.WinDLL('kernel32',use_last_error=True);kernel.LocalFree.argtypes=[C.c_void_p];kernel.LocalFree.restype=C.c_void_p
    try:return C.string_at(output.data,output.size)
    finally:kernel.LocalFree(output.data)
