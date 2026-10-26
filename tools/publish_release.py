"""Publish verified CI artifacts with GitHub CLI; local use supports dry-run only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from release_context import provenance, validate_tag

ROOT = Path(__file__).resolve().parents[1]


# ==========================================
# Function: Validate checksums and final workflow provenance before any GitHub write.
# Method: Allow only the exact asset allowlist approved by the current verification report.
# ==========================================
def release_inputs(tag, repository, dry_run=False):
    validate_tag(tag)
    report_path = ROOT / 'dist/RELEASE_VERIFICATION.json'
    report = json.loads(report_path.read_text())
    if not report.get('ok') or report.get('application_license') != 'MIT' or tag != 'v' + report['version']:
        raise ValueError('Release report is failed or has a different version/license')
    expected = provenance()
    if not dry_run:
        if os.environ.get('GITHUB_ACTIONS') != 'true' or repository != os.environ.get('GITHUB_REPOSITORY'):
            raise ValueError('Publication is restricted to this GitHub Actions repository')
        if (not expected['source_revision'] or not expected['github_run_id']
                or report['provenance']['source_revision'] != expected['source_revision']
                or report['provenance']['github_run_id'] != expected['github_run_id']):
            raise ValueError('Release report is from a different workflow run or commit')
    names = set(report['artifacts']) | {'RELEASE_VERIFICATION.json'}
    checksums = {}
    for line in (ROOT / 'dist/SHA256SUMS').read_text().splitlines():
        value, name = line.split('  ', 1)
        if Path(name).name != name or name in checksums:
            raise ValueError('Unsafe or duplicate checksum filename')
        checksums[name] = value
    if names != set(checksums):
        raise ValueError('Release checksum coverage mismatch')
    for name in names:
        with (ROOT / 'dist' / name).open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != checksums[name] or name in report['artifacts'] and actual != report['artifacts'][name]['sha256']:
            raise ValueError('Release artifact changed: ' + name)
    return report, [ROOT / 'dist' / name for name in sorted(names | {'SHA256SUMS'})]


# ==========================================
# Function: Create a complete draft release and publish only after every upload succeeds.
# Method: Use scoped GITHUB_TOKEN through gh, refuse existing release replacement, and retain failed drafts.
# ==========================================
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', default=os.environ.get('RELEASE_TAG'), required=not bool(os.environ.get('RELEASE_TAG')))
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'), required=not bool(os.environ.get('GITHUB_REPOSITORY')))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    report, assets = release_inputs(args.tag, args.repository, args.dry_run)
    if args.dry_run:
        print(json.dumps({'publication_performed': False, 'tag': args.tag, 'assets': [p.name for p in assets]}, indent=2))
        return
    notes = ROOT / '.runtime/release-notes.md'
    lines = ['TeleMail ' + report['version'], '',
             '项目自有代码采用 MIT；Windows 含 GPL JBIG-KIT，组合分发按 GPLv3-or-later 条件提供，第三方保留原许可。完整对应源码随附件提供。', '',
             '- Windows：解压 ZIP 后运行 TeleMail.exe；需要 WebView2 Evergreen Runtime。',
             '- Linux：提供 DEB 和 tar.gz；tar.gz 需要系统 Python/GTK/WebKitGTK 依赖。',
             '- Windows 保留普通 TIFF 与 JBIG 压缩 TIFF 阅读，PDF、PNG/JPEG/GIF/WebP/BMP/SVG 功能保留。',
             '- 自动整理默认会把超过 365 天且未置顶的收件箱邮件移入服务器垃圾箱，请先检查设置。', '',
             '本次提交：' + report['provenance']['source_revision'], '']
    for platform, result in report['tests'].items():
        backend = result['backend']
        lines.append(f"- {platform}: {backend['run']} backend tests, {backend['skipped']} skips, 9 native PDF checks.")
    lines += ['', '源码与许可证边界、librsvg 源码超集说明见源码包 docs/THIRD_PARTY.md。',
              '请同时保留第三方源码附件；使用 SHA256SUMS 校验下载。']
    notes.write_text('\n'.join(lines) + '\n')
    subprocess.run(['gh', 'release', 'create', args.tag, '--repo', args.repository, '--verify-tag', '--draft',
                    '--title', 'TeleMail ' + report['version'], '--notes-file', str(notes), *map(str, assets)], check=True)
    subprocess.run(['gh', 'release', 'edit', args.tag, '--repo', args.repository, '--draft=false'], check=True)


if __name__ == '__main__':
    main()
