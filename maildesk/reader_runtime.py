"""Optional private native reader runtime; never downloads or installs on launch."""
import ctypes.util
import hashlib
from xml.sax.saxutils import escape
import os
import shutil
from pathlib import Path
import sys

# ==========================================
# Function: Adopt a separately approved, project-specific native runtime.
# Method: Reexec this Linux entry with private libraries and read-only helper namespace mappings.
# ==========================================
def prepare_readers():
    if sys.platform=='win32':
        from .platform_native import prepare_windows
        prepare_windows();return
    prepare_reader_graphics()
    prepare_reader_fonts()
    root=Path(os.environ.get('TELEMAIL_READER_ROOT',Path.home()/'.local/pixi-apps/telemail-readers/root')).resolve()
    if not (root/'usr/lib/x86_64-linux-gnu/libwebkit2gtk-4.1.so.0').is_file():return
    if os.environ.get('TELEMAIL_READER_ACTIVE')==str(root):return
    if ctypes.util.find_library('webkit2gtk-4.1') and not os.environ.get('TELEMAIL_READER_ROOT'):return
    libraries=root/'usr/lib/x86_64-linux-gnu'
    os.environ['TELEMAIL_READER_ACTIVE']=str(root)
    os.environ['LD_LIBRARY_PATH']=str(libraries)+':'+str(libraries/'libproxy')+':'+str(root/'usr/lib')+(':'+os.environ['LD_LIBRARY_PATH'] if os.environ.get('LD_LIBRARY_PATH') else '')
    os.environ['WEBKIT_EXEC_PATH']=str(libraries/'webkit2gtk-4.1')
    os.environ['WEBKIT_INJECTED_BUNDLE_PATH']=str(libraries/'webkit2gtk-4.1/injected-bundle')
    os.environ['GIO_EXTRA_MODULES']=str(libraries/'gio/modules')
    os.environ['XDG_DATA_DIRS']=str(root/'usr/share')+':'+os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share')
    command=[sys.executable,*sys.orig_argv[1:]]
    helpers=Path('/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1')
    if not (helpers/'WebKitNetworkProcess').exists():
        wrapper=shutil.which('bwrap')
        if not wrapper:raise RuntimeError('独立 WebKit 运行库需要系统 bubblewrap；也可使用发行版提供的 WebKitGTK。')
        command=[wrapper,'--bind','/','/','--overlay-src','/usr/lib/x86_64-linux-gnu',
                 '--overlay-src',str(libraries),'--ro-overlay','/usr/lib/x86_64-linux-gnu',
                 '--overlay-src','/usr/bin','--overlay-src',str(root/'usr/bin'),'--ro-overlay','/usr/bin',
                 '--proc','/proc','--dev-bind','/dev','/dev','--',*command]
    os.execv(command[0],command)

# ==========================================
# Function: Resolve an app-local safe WebKit graphics policy on WSLg.
# Method: Prefer CPU composition where private Mesa has no matching DRI device; honor explicit overrides.
# ==========================================
def reader_software_graphics():
    policy=os.environ.get('TELEMAIL_WEBKIT_ACCELERATION','auto').lower()
    if policy in ('software','hardware'):return policy=='software'
    return bool(os.environ.get('WSL_DISTRO_NAME') or os.environ.get('WSL_INTEROP') or Path('/mnt/wslg').is_dir())

# ==========================================
# Function: Configure only TeleMail and its renderer subprocesses before WebKit starts.
# Method: Disable WSLg DMA-BUF composition for the software policy without changing global drivers or sandboxing.
# ==========================================
def prepare_reader_graphics():
    if reader_software_graphics():
        os.environ.setdefault('WEBKIT_DISABLE_DMABUF_RENDERER','1')
        os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE','1')
        os.environ.setdefault('GALLIUM_DRIVER','llvmpipe')

# ==========================================
# Function: Make the bundled Chinese font visible to renderer subprocesses.
# Method: Write a process-specific Fontconfig include in the application's private cache.
# ==========================================
def prepare_reader_fonts():
    font_directory=Path(__file__).resolve().parent/'desktop_assets/fonts'
    if not font_directory.is_dir():return
    from .storage_paths import active_cache
    cache=active_cache()/'reader-fonts'
    marker=str(font_directory)+'|'+str(cache)
    identity=hashlib.sha256(marker.encode()).hexdigest()[:16]
    config=cache/(identity+'.conf')
    if os.environ.get('TELEMAIL_READER_FONTS')==marker and os.environ.get('FONTCONFIG_FILE')==str(config) and config.is_file():return
    cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Preserve the user's original parent through reader reexec and storage restart;
    # never make a new generated configuration depend on the previous cache.
    inherited=os.environ.get('TELEMAIL_READER_FONTCONFIG_PARENT')
    if inherited is None:
        inherited='/etc/fonts/fonts.conf' if os.environ.get('TELEMAIL_READER_FONTS') else os.environ.get('FONTCONFIG_FILE','/etc/fonts/fonts.conf')
    source='<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><include ignore_missing="yes">'+escape(inherited)+'</include><dir>'+escape(str(font_directory))+'</dir><cachedir>'+escape(str(cache))+'</cachedir></fontconfig>\n'
    if not config.exists() or config.read_text()!=source:config.write_text(source)
    os.environ['FONTCONFIG_FILE']=str(config)
    os.environ['TELEMAIL_READER_FONTCONFIG_PARENT']=inherited
    os.environ['TELEMAIL_READER_FONTS']=marker
