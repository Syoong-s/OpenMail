"""Fetch exact MSYS2 source packages into an ignored cache; never execute them."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tarfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'third_party/windows/sources.lock.json'


# ==========================================
# Function: Check that a source package contains its recipe and upstream payload.
# Method: Inspect archive member metadata without extracting or running build scripts.
# ==========================================
def inspect_archive(path):
    with tarfile.open(path) as stream:
        names = [item.name for item in stream if item.isfile()]
    if not any(name.endswith('/PKGBUILD') for name in names):
        raise ValueError('No build recipe: ' + path.name)
    if not any(name.endswith(('.tar.gz', '.tar.xz', '.tar.bz2', '.tar.zst', '.zip', '.tar.lz', '.tgz'))
               or ('/objects/pack/' in name and name.endswith('.pack')) for name in names):
        raise ValueError('No upstream source payload; manual source completion required: ' + path.name)
    return {'files': len(names), 'recipes': [name for name in names if name.endswith('/PKGBUILD')]}


# ==========================================
# Function: Retrieve one versioned source snapshot with an atomic checksum-checked cache.
# Method: Require HTTPS, verify an existing lock or record the first explicitly requested snapshot.
# ==========================================
def fetch(record, directory, pinned):
    url = record['source_tarball_url']
    name = url.rsplit('/', 1)[1]
    target = directory / name
    expected = pinned.get(name, {}).get('sha256')
    if target.is_file():
        with target.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if expected and actual != expected:
            raise ValueError('Cached source hash mismatch: ' + name)
    else:
        error = None
        for host in ('https://repo.msys2.org/', 'https://mirror.msys2.org/'):
            try:
                address = url.replace('https://mirror.msys2.org/', host).replace('https://repo.msys2.org/', host)
                partial = target.with_suffix(target.suffix + '.partial')
                with urlopen(Request(address, headers={'User-Agent': 'TeleMail-release/0.55'}), timeout=60) as source, partial.open('wb') as output:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                with partial.open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                if expected and actual != expected:
                    raise ValueError('Downloaded source hash mismatch: ' + name)
                partial.replace(target)
                error = None
                break
            except Exception as failure:
                error = failure
        if error:
            raise RuntimeError(name + ': ' + str(error)) from error
    contents = inspect_archive(target) if record.get('kind') != 'upstream' else {'files': None, 'recipes': []}
    print('source verified ' + name, flush=True)
    return dict(filename=name, url=url, sha256=actual, bytes=target.stat().st_size, **contents)


# ==========================================
# Function: Materialize all source snapshots for the actual shipped runtime packages.
# Method: Deduplicate split-package sources, fetch concurrently, and preserve exact hash pins.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, default=ROOT / 'dist/TeleMail-Windows-amd64/docs/WINDOWS_RUNTIME_PACKAGES.json')
    parser.add_argument('--update-lock', action='store_true', help='Explicitly pin first source snapshots after review')
    args = parser.parse_args()
    packages = json.loads(args.packages.read_text())['packages']
    pinned = json.loads(LOCK.read_text())['sources'] if LOCK.exists() else {}
    records = {item['source_tarball_url']: item for item in packages}
    if not args.update_lock:
        missing = [url for url in records if url.rsplit('/', 1)[1] not in pinned]
        if missing:
            parser.error('Unpinned sources; review and use --update-lock: ' + ', '.join(missing))
    directory = ROOT / '.runtime/corresponding-sources'
    directory.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda record: fetch(record, directory, pinned), records.values()))
    result = {'snapshot_method': 'versioned MSYS2 source archives containing upstream source, patches and PKGBUILD; initial SHA256 measured at retrieval',
              'sources': {item['filename']: item for item in sorted(results, key=lambda item: item['filename'])}}
    if args.update_lock:
        LOCK.write_text(json.dumps(result, indent=2) + '\n')
    extras = json.loads((ROOT / 'third_party/upstream-sources.lock.json').read_text())['sources']
    for item in extras:
        fetch({'source_tarball_url': item['url'], 'kind': 'upstream'}, directory, {item['filename']: item})
    print(json.dumps({'ok': True, 'archives': len(results) + len(extras),
                      'bytes': sum(item['bytes'] for item in results) + sum(item['bytes'] for item in extras)}, indent=2))


if __name__ == '__main__':
    main()
