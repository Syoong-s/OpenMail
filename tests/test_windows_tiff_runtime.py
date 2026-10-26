"""Real ABI/decoder checks for the Windows libtiff with restored JBIG support."""
import ctypes as C
from pathlib import Path
import struct
import tempfile
import unittest

from maildesk import platform_native as native


# ==========================================
# Function: Verify the actual runtime codec boundary and ordinary TIFF compatibility.
# Method: Load the packaged DLL and decode a generated RGB TIFF through GdkPixbuf.
# ==========================================
@unittest.skipUnless(native.WINDOWS, 'Windows packaged libtiff runtime')
class WindowsTiffTests(unittest.TestCase):
    # ==========================================
    # Function: Confirm JBIG is enabled along with the existing lossless and JPEG codecs.
    # Method: Query libtiff codec registration directly through its stable C ABI.
    # ==========================================
    def test_codec_registration(self):
        native.prepare_windows()
        library = C.CDLL(str(native.runtime_root() / 'bin/libtiff-6.dll'))
        codec = library.TIFFIsCODECConfigured
        codec.argtypes = [C.c_uint16]
        codec.restype = C.c_int
        self.assertEqual(codec(34661), 1)
        for value in (1, 5, 7, 8):
            self.assertEqual(codec(value), 1)

    # ==========================================
    # Function: Ensure GTK's image dependency still accepts ordinary TIFF pixels.
    # Method: Write an uncompressed 2-by-2 RGB fixture and inspect native decoded geometry.
    # ==========================================
    def test_gdk_decodes_ordinary_tiff(self):
        native.prepare_windows()
        runtime = native.runtime_root()
        pixbuf = C.CDLL(str(runtime / 'bin/libgdk_pixbuf-2.0-0.dll'))
        pixbuf.gdk_pixbuf_new_from_file.argtypes = [C.c_char_p, C.c_void_p]
        pixbuf.gdk_pixbuf_new_from_file.restype = C.c_void_p
        for name in ('gdk_pixbuf_get_width', 'gdk_pixbuf_get_height'):
            getattr(pixbuf, name).argtypes = [C.c_void_p]
            getattr(pixbuf, name).restype = C.c_int
        entries = [(256, 4, 1, 2), (257, 4, 1, 2), (258, 3, 3, 134), (259, 3, 1, 1),
                   (262, 3, 1, 2), (273, 4, 1, 140), (277, 3, 1, 3), (278, 4, 1, 2),
                   (279, 4, 1, 12), (284, 3, 1, 1)]
        data = b'II' + struct.pack('<HIH', 42, 8, len(entries))
        data += b''.join(struct.pack('<HHII', *entry) for entry in entries)
        data += struct.pack('<I3H', 0, 8, 8, 8) + bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 255, 255])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.tiff'
            path.write_bytes(data)
            handle = pixbuf.gdk_pixbuf_new_from_file(str(path).encode('utf-8'), None)
            self.assertTrue(handle)
            try:
                self.assertEqual(pixbuf.gdk_pixbuf_get_width(handle), 2)
                self.assertEqual(pixbuf.gdk_pixbuf_get_height(handle), 2)
            finally:
                objects = native.load_library('object')
                objects.g_object_unref.argtypes = [C.c_void_p]
                objects.g_object_unref(handle)

    # ==========================================
    # Function: Confirm restored JBIG-compressed TIFF actually renders through GTK.
    # Method: Encode a synthetic bilevel strip with libtiff, then decode it through GdkPixbuf.
    # ==========================================
    def test_gdk_decodes_jbig_compressed_tiff(self):
        native.prepare_windows()
        runtime = native.runtime_root()
        tiff = C.CDLL(str(runtime / 'bin/libtiff-6.dll'))
        tiff.TIFFOpen.argtypes = [C.c_char_p, C.c_char_p]
        tiff.TIFFOpen.restype = C.c_void_p
        tiff.TIFFSetField.argtypes = [C.c_void_p, C.c_uint32]
        tiff.TIFFSetField.restype = C.c_int
        tiff.TIFFWriteEncodedStrip.argtypes = [C.c_void_p, C.c_uint32, C.c_void_p, C.c_ssize_t]
        tiff.TIFFWriteEncodedStrip.restype = C.c_ssize_t
        tiff.TIFFClose.argtypes = [C.c_void_p]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic-jbig.tiff'
            handle = tiff.TIFFOpen(str(path).encode('utf-8'), b'w')
            self.assertTrue(handle)
            try:
                for tag, value in [(256, 16), (257, 8), (258, 1), (277, 1), (262, 1), (278, 8), (259, 34661)]:
                    self.assertEqual(tiff.TIFFSetField(handle, tag, C.c_uint32(value)), 1)
                pixels = C.create_string_buffer(b'\xaa\x55' * 8)
                self.assertEqual(tiff.TIFFWriteEncodedStrip(handle, 0, pixels, 16), 16)
            finally:
                tiff.TIFFClose(handle)
            pixbuf = native.load_library('pixbuf')
            pixbuf.gdk_pixbuf_new_from_file.argtypes = [C.c_char_p, C.c_void_p]
            pixbuf.gdk_pixbuf_new_from_file.restype = C.c_void_p
            image = pixbuf.gdk_pixbuf_new_from_file(str(path).encode('utf-8'), None)
            self.assertTrue(image)
            try:
                for name, expected in [('gdk_pixbuf_get_width', 16), ('gdk_pixbuf_get_height', 8)]:
                    method = getattr(pixbuf, name)
                    method.argtypes = [C.c_void_p]
                    method.restype = C.c_int
                    self.assertEqual(method(image), expected)
            finally:
                objects = native.load_library('object')
                objects.g_object_unref.argtypes = [C.c_void_p]
                objects.g_object_unref(image)
