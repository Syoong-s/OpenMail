"""Inline image placement, cache-only decoding and durable identity regression tests."""
import base64
from email.message import EmailMessage
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from maildesk.document_content import reader_document
from maildesk.document_reader import document_text
from maildesk.mail_images import image_type,image_uri,message_images
from maildesk.identity_colors import sender_color,IdentityColors
from maildesk.store import Store

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=')

# ==========================================
# Function: Verify inline attachment placement and safe local image handling.
# Method: Generate actual MIME documents and inspect inert rendered HTML.
# ==========================================
class ImageTests(unittest.TestCase):
    # ==========================================
    # Function: Put an unnamed CID image between its surrounding paragraphs exactly once.
    # Method: Resolve the raw related part and compare source ordering and duplicate counts.
    # ==========================================
    def test_cid_placement_and_no_duplicate(self):
        mail=EmailMessage();mail.set_content('Before <img src="cid:photo%40local"> After',subtype='html')
        mail.add_related(PNG,maintype='image',subtype='png',cid='<photo@local>')
        images=message_images(mail.as_bytes());self.assertEqual(len(images),1)
        value=reader_document('Before <img src="cid:photo%40local"> After',images=images)
        self.assertLess(value.index('Before'),value.index('data:image/png'))
        self.assertLess(value.index('data:image/png'),value.index(' After'))
        self.assertEqual(value.count('data:image/png'),1);self.assertIn('id="mail-image-',value)

    # ==========================================
    # Function: Append attached pictures once and retain safe filenames without remote requests.
    # Method: Mix a local raster attachment with tracking markup and a hostile filename.
    # ==========================================
    def test_attached_image_and_remote_block(self):
        mail=EmailMessage();mail.set_content('body');mail.add_attachment(PNG,maintype='image',subtype='png',filename='<picture>.png')
        images=message_images(mail.as_bytes());value=reader_document('body<img src="https://tracker.invalid/x">',images=images)
        self.assertIn('<figure id="mail-image-',value);self.assertIn('&lt;picture&gt;.png',value)
        self.assertNotIn('tracker.invalid',value);self.assertNotIn('<picture>',value)
        self.assertEqual(base64.b64decode(images[0]['uri'].split(',',1)[1]),PNG)

    # ==========================================
    # Function: Reject active files disguised as raster images and separate nested attached mail.
    # Method: Require byte signatures and avoid surfacing another message's images in the parent.
    # ==========================================
    def test_spoof_and_nested_attachment(self):
        self.assertEqual(image_type(b'<svg onload="bad()"/>'),'')
        with self.assertRaises(ValueError):image_uri(b'<html>image.png</html>')
        inner=EmailMessage();inner.set_content('inner');inner.add_attachment(PNG,maintype='image',subtype='png',filename='private.png')
        outer=EmailMessage();outer.set_content('outer');outer.add_attachment(inner)
        self.assertEqual(message_images(outer.as_bytes()),[])

    # ==========================================
    # Function: Render common Chinese text encodings as readable local documents.
    # Method: Verify Unicode BOMs and declared HTML charsets without lossy UTF-8 assumptions.
    # ==========================================
    def test_chinese_document_encoding(self):
        self.assertEqual(document_text('中文'.encode('utf-16')),'中文')
        self.assertIn('中文',document_text('<meta charset="gbk">中文'.encode('gbk')))
        self.assertEqual(document_text('中文'.encode('utf-8')),'中文')

# ==========================================
# Function: Preserve independent sender and account color identities across launches.
# Method: Reopen SQLite preferences and run a fresh interpreter with a different hash seed.
# ==========================================
class IdentityTests(unittest.TestCase):
    # ==========================================
    # Function: Keep one sender fill stable across case, display-name and process changes.
    # Method: Compare normalized identities and a fresh interpreter's actual result.
    # ==========================================
    def test_stable_sender_identity(self):
        expected=sender_color('sender@example.com')
        self.assertEqual(expected,sender_color('Name <SENDER@EXAMPLE.COM>'))
        self.assertNotEqual(expected,sender_color('another@example.com'))
        result=subprocess.check_output([sys.executable,'-c','from maildesk.identity_colors import sender_color;print(sender_color("sender@example.com"))'],text=True).strip()
        self.assertEqual(expected,result)

    # ==========================================
    # Function: Keep account outlines distinct and durable without changing sender fill.
    # Method: Allocate two accounts, reopen preferences, then add a third and disable outlines.
    # ==========================================
    def test_account_outline_persistence_and_override(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'mail.db');colors=IdentityColors(store)
            first=colors.style('sender@example.com','one');second=colors.style('sender@example.com','two')
            self.assertEqual(first['background'],second['background']);self.assertNotEqual(first['border'],second['border'])
            reopened=IdentityColors(Store(store.path));reopened.account_color('three')
            self.assertEqual(reopened.account_color('one'),first['border'])
            assigned=[reopened.account_color('account-'+str(index)) for index in range(16)]
            self.assertEqual(len(set(assigned)),16)
            reopened.set_account_color('two','#ffcc00');self.assertEqual(reopened.account_color('two'),'#ffcc00')
            with self.assertRaises(ValueError):reopened.set_account_color('one','red; background: white')
            store.set_preference('account_colors_enabled',False)
            self.assertEqual(reopened.style('sender@example.com','one'),{'background':first['background'],'border':'transparent'})

    # ==========================================
    # Function: Maintain readable white initials across the generated sender color range.
    # Method: Check relative-luminance contrast over many distinct sender identities.
    # ==========================================
    def test_sender_color_contrast(self):
        values=set()
        for index in range(128):
            color=sender_color(f'sender{index}@example.com');values.add(color)
            rgb=[int(color[start:start+2],16)/255 for start in (1,3,5)]
            channels=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
            luminance=sum(v*w for v,w in zip(channels,(.2126,.7152,.0722)))
            self.assertGreaterEqual(1.05/(luminance+.05),4.5)
        self.assertGreater(len(values),100)
