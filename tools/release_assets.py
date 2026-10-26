"""Public release documents and exact MSYS2 runtime attribution (Python 3.12+)."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ('BUILDING.md', 'PRIVACY.md', 'THIRD_PARTY.md', 'RELEASING.md',
             'CHANGELOG.md', 'PDFJS_READER.md', 'PDFJS_VERIFICATION.json',
             'THIRD_PARTY_FONTS.md', 'ASSETS.md', 'WINDOWS_LICENSE.md')


# ==========================================
# Function: Include only reviewed public documents and original license notices.
# Method: Copy a fixed list shared by both platform builders; exclude private evidence.
# ==========================================
def copy_release_documents(bundle):
    docs = bundle / 'docs'
    docs.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
    shutil.copy2(ROOT / 'NOTICE', bundle / 'NOTICE')
    shutil.copytree(ROOT / 'third_party/supplemental-licenses', docs / 'third_party/supplemental-licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'third_party/supplemental-licenses.json', docs / 'third_party/SUPPLEMENTAL_LICENSES.json')
    shutil.copytree(ROOT / 'third_party/licenses', docs / 'third_party/licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'third_party/librsvg-rust-NOTICES.txt', docs / 'LIBRSVG_RUST_NOTICES.txt')
    for name in DOCUMENTS:
        shutil.copy2(ROOT / 'docs' / name, docs / name)


# ==========================================
# Function: Identify every shipped MSYS2 file and retain its package-specific licenses.
# Method: Match runtime paths against verified pinned binary archives and fail on gaps.
# ==========================================
def attribute_windows_runtime(bundle, sdk):
    runtime = bundle / 'runtime'
    desired = {}
    for folder in ('bin', 'lib', 'share', 'etc'):
        for path in (runtime / folder).rglob('*'):
            if not path.is_file():
                continue
            relative = path.relative_to(runtime).as_posix()
            if relative.startswith(('share/licenses/', 'share/antiword/')):
                continue
            if relative in ('bin/maildesk-webview.dll', 'bin/WebView2Loader.dll', 'bin/antiword.exe'):
                continue
            desired['ucrt64/' + relative] = path
    inventory = json.loads((ROOT / 'third_party/windows/msys2-runtime-closure.json').read_text())
    packages = []
    unmatched = set(desired)
    license_paths = set()
    for record in inventory['packages']:
        if record['name'].endswith(('-poppler', '-poppler-data')):
            continue
        archive = sdk / 'downloads' / record['url'].rsplit('/', 1)[1]
        if not archive.is_file():
            continue
        with archive.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                raise ValueError('Pinned package changed: ' + record['name'])
        with tarfile.open(archive) as stream:
            members = {item.name.lstrip('./'): item for item in stream}
            owned = sorted(set(members) & set(desired))
            if not owned:
                continue
            for name in owned:
                member = members[name]
                if member.isfile() and stream.extractfile(member).read() != desired[name].read_bytes():
                    raise ValueError('Runtime differs from pinned package: ' + name)
            for name, member in members.items():
                if name.startswith('ucrt64/share/licenses/') and member.isfile():
                    destination = runtime / name.removeprefix('ucrt64/')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(stream.extractfile(member).read())
                    license_paths.add(destination.relative_to(runtime).as_posix())
            packages.append(dict(record, shipped_files=[name.removeprefix('ucrt64/') for name in owned]))
            unmatched.difference_update(owned)
    if unmatched:
        raise ValueError('Unattributed runtime files: ' + ', '.join(sorted(unmatched)))
    # Some libraries are covered by shared package license directories; retain
    # the supplied notices without inventing a blanket relicensing statement.
    version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", (ROOT / 'maildesk/__init__.py').read_text())[1]
    payload = {'version': version, 'application_license': 'MIT', 'packages': packages, 'license_files': sorted(license_paths),
               'additional_components': ['CPython 3.14.5', 'WebView2 Loader 1.0.4258.31',
                                         'Antiword (see docs/third_party/antiword)', 'TeleMail native bridge'],
               'source_delivery': f'telemail-{version}-third-party-sources.tar (same Release)'}
    (bundle / 'docs').mkdir(parents=True, exist_ok=True)
    (bundle / 'docs/WINDOWS_RUNTIME_PACKAGES.json').write_text(json.dumps(payload, indent=2) + '\n')
    return payload
