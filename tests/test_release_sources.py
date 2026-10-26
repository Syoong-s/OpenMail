"""Exercise locked source downloads in an empty cache without external network access."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_release_sources as sources


# ==========================================
# Function: Verify release source names and checksums independently of existing local caches.
# Method: Feed real download code controlled network streams and disposable source directories.
# ==========================================
class ReleaseSourceTests(unittest.TestCase):
    # ==========================================
    # Function: Model a locked upstream archive whose URL basename differs from its filename.
    # Method: Use the repository's actual PDF.js URL and filename with a small known payload digest.
    # ==========================================
    def upstream(self, payload=b'locked source fixture'):
        record = json.loads((sources.ROOT / 'third_party/upstream-sources.lock.json').read_text())['sources'][1]
        return dict(record, sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))

    # ==========================================
    # Function: Retrieve a locked upstream source through the normal collector path.
    # Method: Preserve its explicit filename while replacing only the network response body.
    # ==========================================
    def fetch(self, record, directory, payload):
        with patch.object(sources, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(payload)):
            return sources.fetch(dict(record, source_tarball_url=record['url'], kind='upstream'),
                                 directory, {record['filename']: record})

    # ==========================================
    # Function: Save fresh codeload downloads under the name required by release assembly.
    # Method: Start with an empty directory and require exactly one canonical, verified archive.
    # ==========================================
    def test_empty_cache_uses_locked_filename(self):
        payload = b'locked source fixture'
        record = self.upstream(payload)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            result = self.fetch(record, directory, payload)
            self.assertEqual(result['filename'], record['filename'])
            self.assertEqual(result['sha256'], record['sha256'])
            self.assertEqual([p.name for p in directory.iterdir()], [record['filename']])
            self.assertEqual((directory / record['filename']).read_bytes(), payload)

    # ==========================================
    # Function: Reject incorrect upstream bytes before promoting them into the canonical cache.
    # Method: Download a corrupt stream against the explicit locked filename and SHA-256.
    # ==========================================
    def test_download_hash_mismatch_is_rejected(self):
        record = self.upstream()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'Downloaded source hash mismatch'):
                self.fetch(record, directory, b'corrupt source')
            self.assertFalse((directory / record['filename']).exists())

    # ==========================================
    # Function: Refuse a corrupted pre-existing source instead of silently downloading an alias.
    # Method: Seed only the locked cache path and require checksum rejection without network access.
    # ==========================================
    def test_cached_hash_mismatch_is_rejected(self):
        record = self.upstream()
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / record['filename']).write_bytes(b'corrupt cached source')
            with patch.object(sources, 'urlopen') as download:
                with self.assertRaisesRegex(ValueError, 'Cached source hash mismatch'):
                    sources.fetch(dict(record, source_tarball_url=record['url'], kind='upstream'),
                                  directory, {record['filename']: record})
                download.assert_not_called()

    # ==========================================
    # Function: Preserve existing MSYS2 package name and archive validation behavior.
    # Method: Download a minimal real tar with recipe/source members using a URL-derived filename.
    # ==========================================
    def test_msys2_url_filename_still_validates_archive(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for name in ('package/PKGBUILD', 'package/upstream.tar.gz'):
                data = b'source fixture'
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        payload = buffer.getvalue()
        name = 'package-1.src.tar.gz'
        record = {'source_tarball_url': 'https://repo.msys2.org/sources/' + name}
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(sources, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(payload)):
                result = sources.fetch(record, Path(folder), {name: {'sha256': hashlib.sha256(payload).hexdigest()}})
            self.assertEqual(result['filename'], name)
            self.assertEqual(result['recipes'], ['package/PKGBUILD'])

    # ==========================================
    # Function: Keep explicitly named downloads within the intended cache directory.
    # Method: Reject both parent traversal and platform-specific separators before network access.
    # ==========================================
    def test_unsafe_filename_is_rejected(self):
        for name in ('../outside.tar.gz', '/outside.tar.gz', 'nested/archive.tar.gz', r'nested\archive.tar.gz'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                record = dict(self.upstream(), filename=name)
                with self.assertRaisesRegex(ValueError, 'Invalid source filename'):
                    self.fetch(record, Path(folder), b'locked source fixture')

    # ==========================================
    # Function: Collect all upstream sources by their lock names through the CLI entry point.
    # Method: Run main in a disposable repository with empty runtime cache and controlled HTTP bytes.
    # ==========================================
    def test_main_passes_upstream_filename_from_lock(self):
        payload = b'locked source fixture'
        record = self.upstream(payload)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'third_party').mkdir()
            (root / 'third_party/upstream-sources.lock.json').write_text(json.dumps({'sources': [record]}))
            packages = root / 'packages.json'
            packages.write_text('{"packages": []}')
            with patch.object(sources, 'ROOT', root), patch.object(sources, 'LOCK', root / 'absent-lock.json'):
                with patch.object(sys, 'argv', ['prepare_release_sources.py', '--packages', str(packages)]):
                    with patch.object(sources, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(payload)):
                        with contextlib.redirect_stdout(io.StringIO()):
                            sources.main()
            cache = root / '.runtime/corresponding-sources'
            self.assertEqual([p.name for p in cache.iterdir()], [record['filename']])
            self.assertEqual((cache / record['filename']).read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
