"""Cross-build a self-contained Windows 11 amd64 client from WSL with Python 3.14+.

Prepare pinned archives with tools/prepare_windows_runtime.py first. No global install.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / '.runtime/windows-sdk'
UCRT = SDK / 'msys2/root/ucrt64'
COMPILER = SDK / 'llvm-mingw/llvm-mingw-20261006-ucrt-ubuntu-22.04-x86_64/bin'

# ==========================================
# Function: Extract native DLL imports without executing a target binary.
# Method: Parse PE32+ section RVAs and both regular and delay import directories.
# ==========================================
def pe_imports(path):
    data = path.read_bytes()
    if data[:2] != b'MZ':
        raise ValueError('Not a PE binary: ' + str(path))
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if data[offset:offset + 4] != b'PE\0\0':
        raise ValueError('Invalid PE signature: ' + str(path))
    machine, sections = struct.unpack_from('<HH', data, offset + 4)
    optional_size = struct.unpack_from('<H', data, offset + 20)[0]
    optional = offset + 24
    if machine != 0x8664 or struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ValueError('Expected Windows amd64 PE32+: ' + str(path))
    segments = []
    for index in range(sections):
        section = optional + optional_size + 40 * index
        virtual_size, address, raw_size, raw_offset = struct.unpack_from('<IIII', data, section + 8)
        segments.append((address, max(virtual_size, raw_size), raw_offset))

    # ==========================================
    # Function: Map a PE virtual address to the on-disk section containing it.
    # Method: Require the requested address to fall within an actual image section.
    # ==========================================
    def file_offset(address):
        for start, size, disk in segments:
            if start <= address < start + size:
                return disk + address - start
        raise ValueError('Invalid PE RVA: ' + str(path))

    imports = []
    for index, width, name_offset in ((1, 20, 12), (13, 32, 4)):
        address, size = struct.unpack_from('<II', data, optional + 112 + index * 8)
        if not address or not size:
            continue
        cursor = file_offset(address)
        while any(data[cursor:cursor + width]):
            name_address = struct.unpack_from('<I', data, cursor + name_offset)[0]
            start = file_offset(name_address)
            imports.append(data[start:data.index(b'\0', start)].decode('ascii').lower())
            cursor += width
    return imports

# ==========================================
# Function: Make the official MIDL header usable on a case-sensitive MinGW host.
# Method: Generate SDK GUID specializations and a filename-case forwarding header.
# ==========================================
def sdk_compat():
    folder = SDK / 'compat'
    folder.mkdir(exist_ok=True)
    (folder / 'EventToken.h').write_text('#include <eventtoken.h>\n')
    header = (SDK / 'webview2/build/native/include/WebView2.h').read_text()
    lines = ['#include <WebView2.h>']
    for text, name in re.findall(r'MIDL_INTERFACE\("([0-9a-fA-F-]+)"\)\s+(\w+)\s*:', header):
        a, b, c, d, e, f = uuid.UUID(text).fields
        values = [a, b, c, d, e] + list(f.to_bytes(6, 'big'))
        lines.append('__CRT_UUID_DECL(' + name + ',' + ','.join(hex(value) for value in values) + ')')
    (folder / 'webview_uuids.h').write_text('\n'.join(lines) + '\n')
    return folder

# ==========================================
# Function: Compile only small native entry and embedded-browser bridge binaries.
# Method: Use Linux-hosted llvm-mingw with explicit include/link settings and static C++ support.
# ==========================================
def compile_native(bundle):
    compat = sdk_compat()
    target = bundle / 'runtime/bin'
    target.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(COMPILER / 'x86_64-w64-mingw32-clang++'), '-std=c++17', '-O2',
                    '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-shared',
                    '-static-libstdc++', '-static-libgcc', '-Wl,--no-insert-timestamp', '-isystem', str(SDK / 'webview2/build/native/include'),
                    '-I' + str(compat), '-include', str(compat / 'webview_uuids.h'),
                    str(ROOT / 'native/windows/webview_bridge.cpp'), '-lole32', '-luuid', '-luser32', '-lgdi32',
                    '-lkernel32', '-o', str(target / 'maildesk-webview.dll')], check=True)
    resources = compile_resources()
    subprocess.run([str(COMPILER / 'x86_64-w64-mingw32-clang'), '-std=c11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-Wl,--no-insert-timestamp', '-municode', '-mwindows',
                    str(ROOT / 'native/windows/launcher.c'), str(resources), '-lshell32', '-luser32',
                    '-o', str(bundle / 'TeleMail.exe')], check=True)
    subprocess.run([str(COMPILER / 'x86_64-w64-mingw32-clang'), '-std=c11', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-municode', '-Wl,--no-insert-timestamp',
                    str(ROOT / 'native/windows/python_host.c'), str(resources),
                    '-o', str(ROOT / '.runtime/build-windows/maildesk-python.exe')], check=True)
    shutil.copy2(SDK / 'webview2/build/native/x64/WebView2Loader.dll', target)

# ==========================================
# Function: Read a native image-loader failure without hiding its cause.
# Method: Match GLib's public error layout and release each owned diagnostic after decoding.
# ==========================================
class ImageError(C.Structure):
    _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]

# ==========================================
# Function: Render the application icon using the build host's SVG loader.
# Method: Decode and encode through GdkPixbuf, preserving GError details and loader setup guidance.
# ==========================================
def render_icon(source, destination):
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pixbuf = C.CDLL('libgdk_pixbuf-2.0.so.0')
    error_pointer = C.POINTER(C.c_void_p)
    pixbuf.gdk_pixbuf_new_from_file_at_scale.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int, error_pointer]
    pixbuf.gdk_pixbuf_new_from_file_at_scale.restype = C.c_void_p
    pixbuf.gdk_pixbuf_savev.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p, C.c_void_p, C.c_void_p, error_pointer]
    pixbuf.gdk_pixbuf_savev.restype = C.c_int
    objects = C.CDLL('libgobject-2.0.so.0')
    objects.g_object_unref.argtypes, objects.g_object_unref.restype = [C.c_void_p], None
    glib = C.CDLL('libglib-2.0.so.0')
    glib.g_error_free.argtypes, glib.g_error_free.restype = [C.c_void_p], None

    # ==========================================
    # Function: Preserve the native decoder or encoder error in the build failure.
    # Method: Decode UTF-8 diagnostics and free GLib storage before returning the exception.
    # ==========================================
    def failure(operation, error):
        detail = 'native image library returned no diagnostic'
        if error:
            try:
                detail = C.cast(error, C.POINTER(ImageError)).contents.message.decode('utf-8', errors='replace')
            finally:
                glib.g_error_free(error)
        hint = ' SVG decoding requires host librsvg2-common and a working GdkPixbuf loader cache.' if operation == 'render' else ''
        return RuntimeError(f'Cannot {operation} application icon {source}: {detail}.{hint}')

    error = C.c_void_p()
    image = pixbuf.gdk_pixbuf_new_from_file_at_scale(str(source).encode(), 128, 128, 1, C.byref(error))
    if not image:
        raise failure('render', error)
    try:
        error = C.c_void_p()
        if not pixbuf.gdk_pixbuf_savev(image, str(destination).encode(), b'png', None, None, C.byref(error)):
            raise failure('encode', error)
    finally:
        objects.g_object_unref(image)
    return destination

# ==========================================
# Function: Embed the existing application icon and standard DPI/compatibility manifest.
# Method: Render the repository SVG with native diagnostics, then compile a native PE resource.
# ==========================================
def compile_resources():
    sysroot = ROOT / '.runtime/build-windows'
    render_icon(ROOT / 'maildesk/desktop_assets/icon.svg', sysroot / 'icon.png')
    png = (sysroot / 'icon.png').read_bytes()
    (sysroot / 'maildesk.ico').write_bytes(struct.pack('<HHH', 0, 1, 1) +
        struct.pack('<BBBBHHII', 128, 128, 0, 0, 1, 32, len(png), 22) + png)
    resource = sysroot / 'app.rc'
    resource.write_text('1 ICON "' + str(sysroot / 'maildesk.ico') + '"\n' +
                        '1 24 "' + str(ROOT / 'packaging/windows.manifest') + '"\n')
    target = sysroot / 'resources.o'
    subprocess.run([str(COMPILER / 'x86_64-w64-mingw32-windres'), str(resource), str(target)], check=True)
    return target

# ==========================================
# Function: Copy one portable data subtree without build metadata or archive libraries.
# Method: Preserve relative runtime layout while excluding development-only payloads.
# ==========================================
def copy_tree(source, destination):
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('*.dll.a', '*.a', '__pycache__', '*.pyc', '*.h'))

# ==========================================
# Function: Ship the full imported DLL closure and runtime-discovered image modules.
# Method: Resolve each non-system import against the pinned UCRT archive inventory.
# ==========================================
def copy_runtime(bundle):
    runtime = bundle / 'runtime'
    # Clear generated dependency trees so rebuilds cannot retain the retired PDF engine.
    for folder in ('python', 'lib', 'share', 'etc'):
        target = runtime / folder
        if target.exists():shutil.rmtree(target)
    for path in (runtime / 'bin').iterdir():
        if path.is_file() and path.name not in ('maildesk-webview.dll', 'WebView2Loader.dll'):path.unlink()
    shutil.copytree(SDK / 'cpython', runtime / 'python', dirs_exist_ok=True)
    shutil.copy2(ROOT / '.runtime/build-windows/maildesk-python.exe', runtime / 'python/python.exe')
    (runtime / 'python/python314._pth').write_text('python314.zip\n.\n../../app\n', encoding='utf-8')
    sources = {path.name.lower(): path for path in (UCRT / 'bin').glob('*.dll')}
    for path in (runtime / 'python').glob('*.dll'):
        sources.setdefault(path.name.lower(), path)
    loaders = UCRT / 'lib/gdk-pixbuf-2.0/2.10.0/loaders'
    shipped_loaders = runtime / 'lib/gdk-pixbuf-2.0/2.10.0/loaders'
    copy_tree(loaders, shipped_loaders)
    copy_tree(UCRT / 'lib/gio/modules', runtime / 'lib/gio/modules')
    # AES-GCM remains a supported credentials utility independent of the retired PDF engine.
    queue = [sources[name] for name in ('libgtk-3-0.dll', 'libgdk-3-0.dll', 'libcrypto-3-x64.dll')]
    queue += list(shipped_loaders.glob('*.dll')) + list((runtime / 'bin').glob('*.dll'))
    queue += list((runtime / 'lib').rglob('*.dll')) + list((runtime / 'python').glob('*.pyd'))
    seen = set()
    system = set(('advapi32 avrt bcrypt bcryptprimitives cfgmgr32 comctl32 comdlg32 crypt32 '
                  'cryptbase d2d1 d3d11 d3d9 dbghelp dcomp dnsapi dsound dwmapi dwrite dxgi '
                  'gdi32 gdiplus hid imm32 iphlpapi kernel32 ksuser msimg32 msvcrt mswsock '
                  'ncrypt netapi32 normaliz ntdll ole32 oleacc oleaut32 opengl32 powrprof '
                  'propsys psapi rpcrt4 secur32 setupapi shell32 shlwapi sspicli ucrtbase '
                  'urlmon user32 userenv usp10 uxtheme version win32u windowscodecs '
                  'winhttp wininet winmm winspool wintrust wldap32 ws2_32 wtsapi32').split())
    missing = set()
    while queue:
        source = queue.pop()
        name = source.name.lower()
        if name in seen:
            continue
        seen.add(name)
        if source.parent == UCRT / 'bin':
            shutil.copy2(source, runtime / 'bin' / source.name)
        for dependency in pe_imports(source):
            if dependency in sources:
                queue.append(sources[dependency])
            elif dependency.startswith(('api-ms-', 'ext-ms-')) or dependency.removesuffix('.dll') in system or dependency == 'winspool.drv':
                continue
            elif dependency in {path.name.lower() for path in (runtime / 'bin').glob('*.dll')}:
                continue
            else:
                missing.add(dependency)
    if missing:
        raise ValueError('Unresolved Windows imports: ' + ', '.join(sorted(missing)))
    for name in ('gdk-pixbuf-query-loaders.exe', 'glib-compile-schemas.exe'):
        shutil.copy2(UCRT / 'bin' / name, runtime / 'bin' / name)
    for folder in ('icons', 'themes', 'glib-2.0/schemas', 'fontconfig'):
        copy_tree(UCRT / 'share' / folder, runtime / 'share' / folder)
    for locale in ('zh_CN', 'zh_TW', 'zh_HK', 'en_US'):
        copy_tree(UCRT / 'share/locale' / locale, runtime / 'share/locale' / locale)
    copy_tree(UCRT / 'etc/fonts', runtime / 'etc/fonts')
    from release_assets import attribute_windows_runtime
    attribute_windows_runtime(bundle, SDK)
    subprocess.run(['glib-compile-schemas', str(runtime / 'share/glib-2.0/schemas')], check=True)
    return sorted(seen)

# ==========================================
# Function: Create a reproducible native application bundle plus per-file integrity evidence.
# Method: Check host SVG support separately or stage the native executable, private DLLs and optional ZIP.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/TeleMail-Windows-amd64')
    parser.add_argument('--zip', action='store_true')
    parser.add_argument('--check-icon', action='store_true', help='Verify host SVG/PNG support without the Windows SDK')
    args = parser.parse_args()
    if args.check_icon:
        icon = render_icon(ROOT / 'maildesk/desktop_assets/icon.svg', ROOT / '.runtime/build-windows/icon.png')
        print('Host SVG/PNG icon rendering verified: ' + str(icon))
        return
    bundle = args.output.resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    for folder in ('app', 'docs'):
        target = bundle / folder
        if target.exists():
            shutil.rmtree(target)
    compile_native(bundle)
    imports = copy_runtime(bundle)
    from build_legacy_doc import build as build_doc_reader
    build_doc_reader(bundle,COMPILER)
    copy_tree(ROOT / 'maildesk', bundle / 'app/maildesk')
    shutil.copy2(ROOT / 'packaging/windows_bootstrap.py', bundle / 'app/bootstrap.py')
    docs = bundle / 'docs'
    docs.mkdir(exist_ok=True)
    from release_assets import copy_release_documents
    copy_release_documents(bundle)
    shutil.copy2(SDK / 'cpython/LICENSE.txt', docs / 'PYTHON_LICENSE.txt')
    for name in ('LICENSE.txt', 'LICENSE', 'LICENSE.md'):
        if (SDK / 'webview2' / name).is_file():
            shutil.copy2(SDK / 'webview2' / name, docs / 'WEBVIEW2_LICENSE.txt')
    shutil.copy2(COMPILER.parent / 'LICENSE.TXT', docs / 'LLVM_MINGW_LICENSE.txt')
    if (SDK / 'webview2/NOTICE.txt').is_file():
        shutil.copy2(SDK / 'webview2/NOTICE.txt', docs / 'WEBVIEW2_NOTICE.txt')
    version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (ROOT / 'maildesk/__init__.py').read_text())[1]
    manifest = {'name': 'TeleMail', 'version': version, 'application_license': 'MIT', 'binary_combination_license': 'GPL-3.0-or-later; third-party terms retained', 'os': 'windows', 'architecture': 'amd64',
                'entrypoint': 'TeleMail.exe', 'requires_wsl': False, 'requires_installed_python': False,
                'ui': 'native GTK3/Win32 with embedded WebView2 and offline PDF.js',
                'webview2_runtime': 'Microsoft Edge WebView2 Evergreen (installed Windows runtime)',
                'pdf_engine': 'PDF.js 6.4.299 (offline legacy browser build)',
                'internal_pdf_resource_transport': 'app-owned loopback capability; no external server',
                'private_native_modules': imports,
                'sha256': {str(path.relative_to(bundle)).replace(os.sep, '/'):
                           hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted(bundle.rglob('*')) if path.is_file() and path.name != 'manifest.json'}}
    (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.zip:
        with zipfile.ZipFile(bundle.parent / f'telemail-{version}-windows-amd64.zip', 'w',
                             compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(bundle.rglob('*')):
                if path.is_file():
                    archive.write(path, Path(bundle.name) / path.relative_to(bundle))
    print(json.dumps({'bundle': str(bundle), 'files': len(manifest['sha256']),
                      'bytes': sum(path.stat().st_size for path in bundle.rglob('*') if path.is_file())}, indent=2))

if __name__ == '__main__':
    main()
