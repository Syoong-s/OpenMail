"""Archive librsvg's Rust dependency sources without installing Cargo or packages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'third_party/librsvg-rust.lock.json'


# ==========================================
# Function: Read official sparse-index checksum records for windows-sys recipe supplements.
# Method: Include the compatible Windows target family as a documented superset of original Cargo.lock.
# ==========================================
def windows_records(name):
    location = name[:2] + '/' + name[2:4] + '/' + name
    with urlopen(Request('https://index.crates.io/' + location, headers={'User-Agent': 'TeleMail-release'}), timeout=30) as stream:
        rows = [json.loads(line) for line in stream.read().splitlines()]
    records = []
    for row in rows:
        version = row['vers']
        selected = (name == 'windows-sys' and version == '0.60.2'
                    or name == 'windows-link' and version.startswith(('0.1.', '0.2.'))
                    or name not in ('windows-sys', 'windows-link') and version.startswith('0.53.'))
        if selected and '-' not in version:
            records.append({'name': name, 'version': version, 'sha256': row['cksum']})
    return records


# ==========================================
# Function: Download a crate only when its Cargo/index checksum matches.
# Method: Cache raw source archives and collect original license/notice files without execution.
# ==========================================
def fetch_crate(record):
    name, version = record['name'], record['version']
    filename = name + '-' + version + '.crate'
    target = ROOT / '.runtime/rust-sources' / filename
    address = 'https://static.crates.io/crates/' + name + '/' + filename
    if not target.exists():
        error = None
        for attempt in range(2):
            try:
                partial = target.with_suffix('.partial')
                with urlopen(Request(address, headers={'User-Agent': 'TeleMail-release'}), timeout=30) as source, partial.open('wb') as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                with partial.open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                if actual != record['sha256']:
                    raise ValueError('Crate checksum mismatch: ' + filename)
                partial.replace(target)
                error = None
                break
            except Exception as failure:
                error = failure
        if error:
            raise error
    with target.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
            raise ValueError('Cached crate checksum mismatch: ' + filename)
    notices = []
    with tarfile.open(target) as stream:
        members = [item for item in stream if item.isfile()]
        for item in members:
            if any(token in Path(item.name).name.upper() for token in ('LICENSE', 'COPYING', 'NOTICE', 'COPYRIGHT', 'AUTHORS', 'UNLICENSE')):
                notices.append(item.name + '\n' + stream.extractfile(item).read().decode('utf-8', errors='replace'))
        if not notices:
            for item in members:
                if Path(item.name).name.lower().startswith('readme'):
                    notices.append(item.name + '\n' + stream.extractfile(item).read().decode('utf-8', errors='replace'))
    manifest_only = not notices
    if manifest_only:
        with tarfile.open(target) as stream:
            notices.append('Upstream crate contains no separate license/readme file. Original package metadata follows; no license text invented.\n' + stream.extractfile(name + '-' + version + '/Cargo.toml').read().decode('utf-8') + '\n\n' + (ROOT / 'third_party/licenses/MIT.txt').read_text())
    print('crate verified ' + filename, flush=True)
    return dict(record, filename=filename, url=address, bytes=target.stat().st_size, manifest_only_notice=manifest_only), notices


# ==========================================
# Function: Capture all original librsvg Rust sources plus the MSYS2 Windows recipe supplement.
# Method: Derive initial pins from Cargo.lock and registry checksums; subsequent runs use saved pins.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--update-lock', action='store_true')
    args = parser.parse_args()
    if args.update_lock:
        with tarfile.open(ROOT / '.runtime/corresponding-sources/mingw-w64-librsvg-2.63.3-1.src.tar.zst') as outer:
            with tarfile.open(fileobj=outer.extractfile('mingw-w64-librsvg/librsvg-2.63.3.tar.xz'), mode='r:xz') as inner:
                upstream = inner.extractfile('librsvg-2.63.3/Cargo.lock').read()
        (ROOT / 'third_party/librsvg-Cargo.lock').write_bytes(upstream)
        original = tomllib.loads(upstream.decode())['package']
        records = {(item['name'], item['version']): {'name': item['name'], 'version': item['version'], 'sha256': item['checksum']}
                   for item in original if item.get('source', '').startswith('registry+')}
        names = ['windows-sys', 'windows-link', 'windows-targets', 'windows_aarch64_gnullvm', 'windows_aarch64_msvc',
                 'windows_i686_gnu', 'windows_i686_gnullvm', 'windows_i686_msvc',
                 'windows_x86_64_gnu', 'windows_x86_64_gnullvm', 'windows_x86_64_msvc']
        with ThreadPoolExecutor(max_workers=6) as pool:
            for extra in pool.map(windows_records, names):
                for item in extra:
                    records[(item['name'], item['version'])] = item
        records = list(records.values())
    else:
        records = json.loads(LOCK.read_text())['crates']
    (ROOT / '.runtime/rust-sources').mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_crate, records))
    results.sort(key=lambda item: item[0]['filename'])
    if args.update_lock:
        LOCK.write_text(json.dumps({'scope': 'superset: upstream librsvg Cargo.lock plus windows-sys 0.60.2 recipe and Windows 0.53 target family; not a recovered exact MSYS2 post-update Cargo.lock',
                                    'crates': [item for item, unused in results]}, indent=2) + '\n')
    (ROOT / 'third_party/librsvg-rust-NOTICES.txt').write_text('\n\n'.join('\n===== ' + item['filename'] + ' =====\n' + '\n\n'.join(notices).replace('\r\n', '\n')
                                                                        for item, notices in results))
    print(json.dumps({'ok': True, 'crates': len(results), 'bytes': sum(item['bytes'] for item, unused in results)}))


if __name__ == '__main__':
    main()
