"""Stage pinned redistributable Windows runtime and Linux cross compiler privately.

Python 3.14+, standard library only; run from WSL: python3 tools/prepare_windows_runtime.py.
No package manager, virtual environment, installer, or global configuration is changed.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'third_party/windows'
SDK = ROOT / '.runtime/windows-sdk'

# ==========================================
# Function: Read the fixed runtime closure and compiler/SDK/Python artifact pins.
# Method: Return one normalized inventory without resolving moving dependencies.
# ==========================================
def inventory():
    closure = json.loads((EVIDENCE / 'msys2-runtime-closure.json').read_text())
    artifacts = json.loads((EVIDENCE / 'artifacts.json').read_text())
    records = [dict(item, kind='msys2') for item in closure['packages']
               if item['name'] not in ('mingw-w64-ucrt-x86_64-poppler', 'mingw-w64-ucrt-x86_64-poppler-data')]
    for name in ('python', 'webview2_sdk', 'cross_compiler'):
        records.append(dict(artifacts[name], kind=name, name=name))
    return records

# ==========================================
# Function: Publish the complete app-private build and runtime inventory before fetching.
# Method: Generate a readable table retaining licenses, dependency edges and exact hashes.
# ==========================================
def write_manifest(records):
    text = ['# Native Windows 11 dependency manifest', '',
            'These are app-private distributable files and a WSL cross-build SDK. No global Python, '
            'pixi, conda, Windows package installation, or system PATH is modified. '
            'Full metadata, dependency edges, source and license URLs are in '
            '`third_party/windows/msys2-runtime-closure.json` and `artifacts.json`.', '',
            'The extraction includes development files for analysis. The shipped runtime is reduced '
            'to the required DLL closure, data, fonts, loader modules and licenses. '
            'Existing Microsoft Edge WebView2 is reused; the SDK loader is bundled.', '',
            '| Package | Version | Download bytes | Checksum | License |',
            '| --- | --- | ---: | --- | --- |']
    for record in records:
        digest = record.get('sha256', 'SHA512/base64:' + record.get('sha512_base64', ''))
        license_text = ', '.join(record.get('licenses', ['vendor license included in archive']))
        text.append(f"| [{record['name']}]({record['url']}) | {record['version']} | "
                    f"{record['compressed_size']} | {digest} | {license_text} |")
    text += ['', f"Total pinned downloads: {sum(item['compressed_size'] for item in records):,} bytes.",
             'Windows target: amd64/UCRT, Windows 11. Build host: Linux amd64; llvm-mingw cross compiler.', '']
    target = ROOT / 'docs/WINDOWS_DEPENDENCIES.md'
    target.write_text('\n'.join(text), encoding='utf-8')
    return target

# ==========================================
# Function: Verify one completed archive against vendor size and cryptographic pin.
# Method: Stream SHA256 or SHA512 without loading large archives into memory.
# ==========================================
def verified(path, record):
    if not path.is_file() or path.stat().st_size != record['compressed_size']:
        return False
    algorithm = 'sha256' if 'sha256' in record else 'sha512'
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, algorithm).digest()
    expected = bytes.fromhex(record['sha256']) if algorithm == 'sha256' else base64.b64decode(record['sha512_base64'])
    return digest == expected

# ==========================================
# Function: Fetch a pinned archive with bounded retries and atomic verified promotion.
# Method: Reuse only matching cached bytes; require HTTPS and ordinary TLS verification.
# ==========================================
def download(record):
    destination = SDK / 'downloads' / record['url'].rsplit('/', 1)[1]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if verified(destination, record):
        return destination
    partial = destination.with_name(destination.name + '.partial')
    for attempt in range(3):
        try:
            url = record['url']
            if attempt and url.startswith('https://mirror.msys2.org/'):
                url = url.replace('https://mirror.msys2.org/', 'https://repo.msys2.org/', 1)
            request = Request(url, headers={'User-Agent': 'TeleMail-native-build/1.0'})
            with urlopen(request, timeout=90) as source, partial.open('wb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            if not verified(partial, record):
                raise ValueError('Archive size or checksum mismatch: ' + record['name'])
            partial.replace(destination)
            print('verified ' + destination.name, flush=True)
            return destination
        except Exception as error:
            print(f"download error {record['name']} attempt {attempt + 1}: {error}", flush=True)
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))

# ==========================================
# Function: Extract trusted pinned archives without executing package scripts.
# Method: Restrict MSYS payloads to ucrt64 and reject archive traversal or ZIP symlinks.
# ==========================================
def extract(record, archive):
    kind = record['kind']
    target = SDK / {'msys2': 'msys2/root', 'python': 'cpython',
                    'webview2_sdk': 'webview2', 'cross_compiler': 'llvm-mingw'}[kind]
    target.mkdir(parents=True, exist_ok=True)
    stamp = SDK / 'extracted' / (archive.name + '.json')
    if stamp.is_file():
        return
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                path = PurePosixPath(member.filename)
                if path.is_absolute() or '..' in path.parts or ((member.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError('Unsafe ZIP member: ' + member.filename)
            source.extractall(target)
    else:
        with tarfile.open(archive) as source:
            members = [member for member in source if kind != 'msys2' or member.name.startswith('ucrt64/')]
            source.extractall(target, members=members, filter='data')
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps(record, indent=2) + '\n')

# ==========================================
# Function: Prepare the app-private SDK with a reviewable manifest and integrity report.
# Method: Parallelize independent downloads, then extract sequentially to avoid collisions.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    records = inventory()
    print(write_manifest(records), flush=True)
    if args.manifest_only:
        return
    with ThreadPoolExecutor(max_workers=6) as pool:
        archives = list(pool.map(download, records))
    for record, archive in zip(records, archives):
        extract(record, archive)
    report = {'archives': len(records), 'all_pinned_archives_verified': True,
              'sdk': str(SDK), 'python': str(SDK / 'cpython'),
              'webview2': str(SDK / 'webview2'),
              'ucrt64': str(SDK / 'msys2/root/ucrt64'),
              'compiler': str(next((SDK / 'llvm-mingw').glob('*/bin/x86_64-w64-mingw32-clang++')))}
    (SDK / 'staged-runtime.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)

if __name__ == '__main__':
    main()
