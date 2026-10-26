"""Native Linux SVG build probes, including the loader-cache failure seen on Ubuntu 24.04."""
import ctypes.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "import sys;sys.path.insert(0,'tools');from build_windows import render_icon;render_icon(sys.argv[1],sys.argv[2])"

# ==========================================
# Function: Validate actual host icon decoding independently of the Windows SDK and desktop session.
# Method: Run each native loader in a fresh process so loader caches cannot leak between scenarios.
# ==========================================
@unittest.skipUnless(sys.platform.startswith('linux') and ctypes.util.find_library('gdk_pixbuf-2.0'), 'Linux host GdkPixbuf required')
class BuildIconTests(unittest.TestCase):
    # ==========================================
    # Function: Run one real native decode/encode with controlled loader environment.
    # Method: Pass filenames as argv and bound execution without importing application runtime settings.
    # ==========================================
    def render(self, source, target, cache=None):
        environment = dict(os.environ)
        for name in ('GDK_PIXBUF_MODULE_FILE', 'GDK_PIXBUF_MODULEDIR'):
            environment.pop(name, None)
        if cache is not None:
            environment['GDK_PIXBUF_MODULE_FILE'] = str(cache)
        return subprocess.run([sys.executable, '-B', '-c', SCRIPT, str(source), str(target)], cwd=ROOT,
                              env=environment, capture_output=True, text=True, timeout=30)

    # ==========================================
    # Function: Produce a usable Windows icon image through the actual Linux SVG decoder.
    # Method: Validate the PNG signature and IHDR dimensions using the standard library.
    # ==========================================
    def test_real_svg_encodes_128px_png(self):
        with tempfile.TemporaryDirectory(prefix='telemail-icon-') as folder:
            target = Path(folder)/'图标/icon.png'
            result = self.render(ROOT/'maildesk/desktop_assets/icon.svg', target)
            self.assertEqual(result.returncode, 0, result.stderr)
            data = target.read_bytes()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
            self.assertEqual(struct.unpack_from('>II', data, 16), (128, 128))
            self.assertGreater(len(data), 500)

    # ==========================================
    # Function: Preserve the concrete native error when the input cannot be decoded.
    # Method: Submit malformed SVG and require both filename and decoder setup guidance.
    # ==========================================
    def test_invalid_image_reports_native_detail(self):
        with tempfile.TemporaryDirectory(prefix='telemail-icon-') as folder:
            source = Path(folder)/'malformed.svg'
            source.write_text('not an image')
            result = self.render(source, Path(folder)/'icon.png')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Cannot render application icon', result.stderr)
            self.assertIn(str(source), result.stderr)
            self.assertIn('librsvg2-common', result.stderr)
            self.assertNotIn('native image library returned no diagnostic', result.stderr)

    # ==========================================
    # Function: Reproduce missing SVG modules on the Ubuntu 24.04 loader architecture.
    # Method: Hide external loaders in a fresh process; newer built-in SVG decoders explicitly skip this scenario.
    # ==========================================
    def test_missing_svg_loader_reports_actionable_error(self):
        with tempfile.TemporaryDirectory(prefix='telemail-icon-') as folder:
            cache = Path(folder)/'loaders.cache'
            cache.write_text('')
            result = self.render(ROOT/'maildesk/desktop_assets/icon.svg', Path(folder)/'icon.png', cache)
            if result.returncode == 0:
                self.skipTest('This GdkPixbuf provides SVG without the external loader cache')
            self.assertIn('Cannot render application icon', result.stderr)
            self.assertIn('librsvg2-common', result.stderr)
            self.assertNotIn('native image library returned no diagnostic', result.stderr)

if __name__ == '__main__':
    unittest.main()
