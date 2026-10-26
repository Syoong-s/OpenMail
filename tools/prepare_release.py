"""Verify public source/bundles and create same-release source archives (Python 3.14+)."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


# ==========================================
# Function: Compute artifact integrity without loading large source archives in memory.
# Method: Stream SHA-256 from the saved file bytes.
# ==========================================
def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# ==========================================
# Function: Enumerate only Git-visible public source and reject private content or secrets.
# Method: Honor ignore rules, check paths and scan text for recognizable credential formats.
# ==========================================
def public_files():
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    names = sorted(set(raw.decode().strip('\0').split('\0')))
    forbidden = {'.git', '.runtime', 'dist', '.planning', '.analysis', 'evidence', '__pycache__'}
    credentials = {'accounts.json', 'logins.json', 'device.key', 'config.json'}
    patterns = [rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                rb'gh[pousr]_[A-Za-z0-9]{30,}', rb'github_pat_[A-Za-z0-9_]{40,}',
                rb'AIza[A-Za-z0-9_-]{35}']
    result = []
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or forbidden.intersection(path.parts):
            raise ValueError('Private/unsafe Git path: ' + name)
        if path.name in credentials or path.suffix.lower() in ('.eml', '.mbox', '.sqlite', '.sqlite3', '.log', '.key', '.pem'):
            raise ValueError('Private data filename in source: ' + name)
        target = ROOT / name
        if target.is_symlink() or not target.is_file():
            raise ValueError('Source must be a regular file: ' + name)
        data = target.read_bytes()
        if b'\0' not in data and any(re.search(pattern, data) for pattern in patterns):
            raise ValueError('Potential credential in source: ' + name)
        result.append(target)
    if not result or not (ROOT / 'LICENSE').is_file():
        raise ValueError('Missing public source or license')
    return result


# ==========================================
# Function: Verify bundle bytes, current application resources and release-only documents.
# Method: Check every manifest entry and reject unlisted or retired/private payloads.
# ==========================================
def verify_bundle(bundle, version):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    if manifest.get('name') != 'TeleMail' or manifest['version'] != version or manifest.get('application_license') != 'MIT' or 'PDF.js 6.4.299' not in manifest['pdf_engine']:
        raise ValueError('Bundle version/PDF engine mismatch')
    if digest(bundle / 'LICENSE') != digest(ROOT / 'LICENSE'):
        raise ValueError('Bundle license differs from MIT source license')
    if manifest['os'] == 'windows':
        if not any('jbig' in name.lower() and name.lower().endswith('.dll') for name in manifest['sha256']):
            raise ValueError('Missing restored JBIG runtime')
        if not manifest.get('binary_combination_license', '').startswith('GPL-3.0'):
            raise ValueError('Missing Windows combination distribution notice')
    actual = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if actual != set(manifest['sha256']) | {'manifest.json'}:
        raise ValueError('Unlisted bundle files: ' + bundle.name)
    for name, expected in manifest['sha256'].items():
        if digest(bundle / name) != expected:
            raise ValueError('Bundle hash mismatch: ' + name)
        parts = PurePosixPath(name).parts
        if 'evidence' in parts or '__pycache__' in parts or any('poppler' in part.lower() for part in parts):
            raise ValueError('Retired/private bundle payload: ' + name)
    for source in (ROOT / 'maildesk').rglob('*'):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
            continue
        shipped = bundle / 'app/maildesk' / source.relative_to(ROOT / 'maildesk')
        if not shipped.is_file() or digest(source) != digest(shipped):
            raise ValueError('Source/bundle mismatch: ' + str(source.relative_to(ROOT)))
    return {'files': len(manifest['sha256']), 'sha256': digest(bundle / 'manifest.json')}


# ==========================================
# Function: Assemble verified application and third-party corresponding-source attachments.
# Method: Require both backend/native reports and exact locked sources before final checksums.
# ==========================================
def main():
    from release_context import version as current_version, validate_tag, validate_reports, provenance
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stage-only', action='store_true', help='Build verified source attachments before remote Windows QA; does not approve publication')
    modes.add_argument('--use-existing-sources', action='store_true', help='Verify source attachments transferred from the build job')
    parser.add_argument('--require-ci-provenance', action='store_true')
    parser.add_argument('--expected-tag')
    args = parser.parse_args()
    if args.expected_tag:
        validate_tag(args.expected_tag)
    if args.require_ci_provenance and args.stage_only:
        parser.error('A staging build is not final CI approval')
    version = current_version()
    dist = ROOT / 'dist'
    files = public_files()
    bundles = {platform: verify_bundle(dist / ('TeleMail-' + platform + '-amd64'), version) for platform in ('Windows', 'Linux')}
    reports = {}
    if not args.stage_only:
        for platform in ('linux', 'windows'):
            backend = json.loads((ROOT / '.runtime' / (platform + '-tests/report.json')).read_text())
            gui = json.loads((ROOT / '.runtime' / (platform + '-gui/report.json')).read_text())
            validate_reports(backend, gui, dist / ('TeleMail-' + platform.title() + '-amd64'), args.require_ci_provenance)
            reports[platform] = {'backend': backend, 'native_checks': gui['checks'], 'native_provenance': gui['provenance'], 'real_provider_calls': gui['real_provider_calls']}
    packages = json.loads((dist / 'TeleMail-Windows-amd64/docs/WINDOWS_RUNTIME_PACKAGES.json').read_text())['packages']
    lock = json.loads((ROOT / 'third_party/windows/sources.lock.json').read_text())['sources']
    required = {item['source_tarball_url'].rsplit('/', 1)[1] for item in packages}
    if not required.issubset(lock):
        raise ValueError('Runtime/source lock coverage mismatch')
    sources = {name: lock[name] for name in required}
    for item in json.loads((ROOT / 'third_party/upstream-sources.lock.json').read_text())['sources']:
        sources[item['filename']] = item
    source_archive = dist / f'telemail-{version}-source.tar.gz'
    dependency_archive = dist / f'telemail-{version}-third-party-sources.tar'
    rust_lock = json.loads((ROOT / 'third_party/librsvg-rust.lock.json').read_text())
    crates = rust_lock['crates']
    if not args.use_existing_sources:
        cache = ROOT / '.runtime/corresponding-sources'
        for name, item in sources.items():
            if digest(cache / name) != item['sha256']:
                raise ValueError('Source snapshot hash mismatch: ' + name)
        for item in crates:
            if digest(ROOT / '.runtime/rust-sources' / item['filename']) != item['sha256']:
                raise ValueError('Rust source checksum mismatch: ' + item['filename'])
        with tarfile.open(source_archive, 'w:gz') as stream:
            for path in files:
                stream.add(path, arcname='telemail-' + version + '/' + path.relative_to(ROOT).as_posix(), recursive=False)
        with tarfile.open(dependency_archive, 'w') as stream:
            for name in sorted(sources):
                stream.add(cache / name, arcname='sources/' + name, recursive=False)
            for item in crates:
                stream.add(ROOT / '.runtime/rust-sources' / item['filename'], arcname='rust/' + item['filename'], recursive=False)
            for extra in (ROOT / 'third_party/supplemental-licenses').glob('*'):
                stream.add(extra, arcname=extra.relative_to(ROOT).as_posix(), recursive=False)
            for license_file in sorted((ROOT / 'third_party/licenses').glob('*')):
                stream.add(license_file, arcname=license_file.relative_to(ROOT).as_posix(), recursive=False)
            stream.add(ROOT / 'third_party/supplemental-licenses.json', arcname='third_party/supplemental-licenses.json', recursive=False)
            for path in ('third_party/librsvg-rust.lock.json', 'third_party/librsvg-Cargo.lock', 'third_party/librsvg-rust-NOTICES.txt', 'third_party/windows/sources.lock.json', 'third_party/upstream-sources.lock.json',
                         'docs/THIRD_PARTY.md', 'docs/BUILDING.md', 'tools/build_windows.py', 'tools/build_legacy_doc.py'):
                stream.add(ROOT / path, arcname=path, recursive=False)
    with tarfile.open(source_archive) as archive:
        expected_files = {'telemail-' + version + '/' + path.relative_to(ROOT).as_posix(): path for path in files}
        members = {item.name: item for item in archive if item.isfile()}
        if set(members) != set(expected_files):
            raise ValueError('Source archive file coverage mismatch')
        for name, path in expected_files.items():
            if hashlib.file_digest(archive.extractfile(members[name]), 'sha256').hexdigest() != digest(path):
                raise ValueError('Source archive differs from checked-out commit: ' + name)
    with tarfile.open(dependency_archive) as archive:
        members = {item.name: item for item in archive if item.isfile()}
        for prefix, records in [('sources/', list(sources.values())), ('rust/', crates)]:
            expected_names = {prefix + item['filename'] for item in records}
            if {name for name in members if name.startswith(prefix)} != expected_names:
                raise ValueError('Dependency source coverage mismatch: ' + prefix)
            for item in records:
                name = prefix + item['filename']
                if hashlib.file_digest(archive.extractfile(members[name]), 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('Dependency source bytes differ from locked snapshot: ' + name)
        for name, member in members.items():
            if name.startswith(('sources/', 'rust/')):
                continue
            local = ROOT / name
            if not local.is_file() or hashlib.file_digest(archive.extractfile(member), 'sha256').hexdigest() != digest(local):
                raise ValueError('Dependency source metadata differs: ' + name)
    windows_zip = dist / f'telemail-{version}-windows-amd64.zip'
    with zipfile.ZipFile(windows_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError('Invalid ZIP CRC')
        expected = {path.relative_to(dist).as_posix(): path for path in (dist / 'TeleMail-Windows-amd64').rglob('*') if path.is_file()}
        if set(archive.namelist()) != set(expected):
            raise ValueError('Windows ZIP file coverage mismatch')
        for name, path in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest(path):
                raise ValueError('Windows ZIP differs from verified bundle: ' + name)
    linux_tar = dist / f'telemail-{version}-linux-amd64.tar.gz'
    linux_bundle = dist / 'TeleMail-Linux-amd64'
    with tarfile.open(linux_tar) as archive:
        expected = {p.relative_to(dist).as_posix(): p for p in linux_bundle.rglob('*') if p.is_file()}
        members = {item.name: item for item in archive if item.isfile()}
        if set(members) != set(expected):
            raise ValueError('Linux tar file coverage mismatch')
        for name, path in expected.items():
            if hashlib.file_digest(archive.extractfile(members[name]), 'sha256').hexdigest() != digest(path):
                raise ValueError('Linux tar differs from verified bundle: ' + name)
    deb = dist / f'telemail-desktop_{version}_amd64.deb'
    dependencies = subprocess.check_output(['dpkg-deb', '-f', str(deb), 'Depends'], text=True).strip()
    if 'poppler' in dependencies.lower():
        raise ValueError('Retired PDF dependency in Debian package')
    with tempfile.TemporaryDirectory(prefix='maildesk-deb-check-', dir=ROOT / '.runtime') as temporary:
        subprocess.run(['dpkg-deb', '-x', str(deb), temporary], check=True)
        extracted = Path(temporary) / 'opt/telemail'
        verify_bundle(extracted, version)
        if digest(extracted / 'manifest.json') != digest(linux_bundle / 'manifest.json'):
            raise ValueError('Debian package differs from verified Linux bundle')
    artifacts = [windows_zip, dist / f'telemail-{version}-linux-amd64.tar.gz',
                 dist / f'telemail-desktop_{version}_amd64.deb', source_archive, dependency_archive]
    if args.stage_only:
        print(json.dumps({'mode': 'build-stage-only', 'publication_approved': False, 'version': version, 'source_attachments': [source_archive.name, dependency_archive.name]}, indent=2))
        return
    report = {'ok': True, 'version': version, 'application_license': 'MIT', 'windows_binary_combination_license': 'GPL-3.0-or-later; third-party terms retained', 'provenance': provenance(), 'public_source_files': len(files), 'public_source_bytes': sum(p.stat().st_size for p in files),
              'source_scan': 'Git-visible path and recognizable-token checks; not a complete provenance/security/legal audit',
              'bundles': bundles, 'tests': reports, 'source_snapshots': len(sources), 'rust_source_crates': len(crates), 'rust_source_scope': rust_lock['scope'],
              'rust_upstream_manifest_only_notices': [item['filename'] for item in crates if item.get('manifest_only_notice')],
              'debian_dependencies': dependencies,
              'artifacts': {p.name: {'bytes': p.stat().st_size, 'sha256': digest(p)} for p in artifacts},
              'publication': {'pushed': False, 'publication_channel': 'GitHub Actions' if args.require_ci_provenance else 'local', 'remote_configured': bool(subprocess.check_output(['git', 'remote'], cwd=ROOT).strip()),
                              'windows_authenticode_signed': False, 'oauth_registration_provided': False},
              'known_limitations': ['WSLg WebKit may emit a GLib/GIO warning at shutdown with successful exit',
                                    'Windows UNC GUI QA uses byte-identical font files from an existing local install',
                                    'No claim of complete cross-platform feature parity or all-distribution certification']}
    report_path = dist / 'RELEASE_VERIFICATION.json'
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    (dist / 'SHA256SUMS').write_text(''.join(digest(path) + '  ' + path.name + '\n' for path in artifacts + [report_path]))
    print(json.dumps({'ok': True, 'version': version, 'source_files': len(files), 'source_snapshots': len(sources), 'rust_source_crates': len(crates), 'rust_source_scope': rust_lock['scope'],
              'rust_upstream_manifest_only_notices': [item['filename'] for item in crates if item.get('manifest_only_notice')],
                      'release_files': [p.name for p in artifacts] + ['RELEASE_VERIFICATION.json', 'SHA256SUMS']}, indent=2))


if __name__ == '__main__':
    main()
