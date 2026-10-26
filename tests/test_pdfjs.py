"""Security and native-adapter contracts for offline PDF.js without any provider access."""
import http.client
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from maildesk.pdf_resources import PDFSession, resource_names, CSP
from maildesk.pdf_reader import PDFReader

# ==========================================
# Function: Verify the resource capability cannot expose arbitrary files or accept cross-origin input.
# Method: Exercise a real loopback HTTP listener with forged hosts, paths, origins and methods.
# ==========================================
class ResourceTests(unittest.TestCase):
    # ==========================================
    # Function: Create one synthetic PDF session for HTTP boundary checks.
    # Method: Use minimal signature bytes without constructing a native renderer.
    # ==========================================
    def setUp(self):
        self.session = PDFSession(b'%PDF-1.7\nsynthetic test bytes')
        self.addCleanup(self.session.close)

    # ==========================================
    # Function: Issue one real request against the isolated test listener.
    # Method: Return status, headers and bytes after closing the connection.
    # ==========================================
    def request(self, name, headers=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', self.session.server.server_port, timeout=3)
        connection.request(method, name, headers=headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    # ==========================================
    # Function: Serve only the admitted PDF and trusted local viewer resources.
    # Method: Check actual bytes/MIME, restrictive CSP, no cache and disabled CORS.
    # ==========================================
    def test_pdf_and_viewer_headers(self):
        prefix = self.session.server.prefix
        status, headers, data = self.request(prefix + 'document.pdf')
        self.assertEqual(status, 200)
        self.assertEqual(data, b'%PDF-1.7\nsynthetic test bytes')
        self.assertEqual(headers['Content-Type'], 'application/pdf')
        status, headers, data = self.request(prefix + 'viewer.html')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Security-Policy'], CSP)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertNotIn(b'<script>', data)
        self.assertIn(b'bootstrap.mjs', data)
        self.assertEqual(self.request(prefix + 'vendor/build/pdf.worker.mjs')[0], 200)
        self.assertEqual(self.request(prefix + 'document.pdf', method='HEAD')[2], b'')

    # ==========================================
    # Function: Refuse capability guessing, path traversal and executable or unrelated local resources.
    # Method: Send raw traversal/encoding/query variations to the actual HTTP handler.
    # ==========================================
    def test_paths_are_exact_allowlist(self):
        prefix = self.session.server.prefix
        for path in ('/document.pdf', '/wrong/viewer.html', prefix + '../config.json',
                     prefix + '%2e%2e/config.json', prefix + 'viewer.html?file=https://example.com',
                     prefix + 'vendor/build/pdf.sandbox.mjs', prefix + 'vendor/SOURCE.json'):
            self.assertIn(self.request(path)[0], (403, 404), path)
        self.assertEqual(self.request(prefix + 'document.pdf', method='POST')[0], 501)

    # ==========================================
    # Function: Prevent DNS rebinding and browser cross-site access to the document listener.
    # Method: Forge Host, Origin and Fetch Metadata headers independently.
    # ==========================================
    def test_host_and_origin_rejected(self):
        path = self.session.server.prefix + 'document.pdf'
        for headers in ({'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'},
                        {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.request(path, headers)[0], 403)

    # ==========================================
    # Function: Release the capability, listener and document bytes on retirement.
    # Method: Close twice and require the owned thread to exit and secret bytes to disappear.
    # ==========================================
    def test_close_releases_document(self):
        self.session.close()
        self.session.close()
        self.assertFalse(self.session.thread.is_alive())
        self.assertEqual(self.session.server.pdf_data, b'')
        self.assertTrue(self.session.server.retired)

    # ==========================================
    # Function: Refuse malformed input and verify all vendored assets against upstream provenance.
    # Method: Check signature limits plus every pinned resource hash without executing vendor JavaScript.
    # ==========================================
    def test_admission_and_vendor_integrity(self):
        import hashlib
        from maildesk.pdf_resources import ASSETS
        for value in (b'', b'not a PDF'):
            with self.assertRaises(ValueError):
                PDFSession(value)
        manifest = json.loads((ASSETS / 'vendor/SOURCE.json').read_text())
        for name, digest in manifest['files'].items():
            self.assertEqual(hashlib.sha256((ASSETS / 'vendor' / name).read_bytes()).hexdigest(), digest, name)
        self.assertNotIn('vendor/build/pdf.sandbox.mjs', resource_names())

# ==========================================
# Function: Verify asynchronous viewer state cannot spoof another document or execute toolbar strings.
# Method: Replace only the native browser, keeping a real capability session and state validator.
# ==========================================
class AdapterTests(unittest.TestCase):
    # ==========================================
    # Function: Initialize the adapter with a synthetic browser surface.
    # Method: Retain the real session lifetime while recording only application-generated commands.
    # ==========================================
    def setUp(self):
        self.app = Mock()
        self.changed = Mock()
        with patch('maildesk.pdf_reader.create_pdf_surface') as create:
            self.surface = create.return_value
            self.reader = PDFReader(self.app, b'%PDF-1.7\nfixture', 'pdf', self.changed)
        self.addCleanup(self.reader.close)
        self.state = dict(token=self.reader.session.token, count=2, index=0, zoom=1,
                          matches=0, rendered=1, error='', ready=True)

    # ==========================================
    # Function: Deliver a state message using the same title protocol as both native platforms.
    # Method: Serialize bounded test metadata with optional hostile overrides.
    # ==========================================
    def publish(self, **changes):
        self.reader.state_changed('TeleMailPDF:' + json.dumps(self.state | changes))

    # ==========================================
    # Function: Reject stale or hostile metadata before it reaches native controls.
    # Method: Try other tokens, invalid indices, booleans, infinity and excessive counts.
    # ==========================================
    def test_metadata_is_identity_and_bounds_checked(self):
        for changes in ({'token': 'old'}, {'count': True}, {'index': 3}, {'zoom': float('inf')},
                        {'count': 100001}, {'matches': -1}, {'ready': 'true'}):
            self.publish(**changes)
            self.assertEqual(self.reader.count, 0)
        self.publish()
        self.assertEqual(self.reader.count, 2)
        self.assertTrue(self.reader.document_ready)
        self.assertEqual(self.changed.call_count, 1)

    # ==========================================
    # Function: Preserve early toolbar input and encode arbitrary search text as inert JSON data.
    # Method: Queue until first render, then decode the exact command argument that would execute.
    # ==========================================
    def test_queued_commands_and_literal_search(self):
        query = '\");window.ATTACK=1;//\n搜索'
        self.reader.find(query)
        self.reader.fit(600)
        self.surface.execute.assert_not_called()
        self.publish()
        calls = [call.args[0] for call in self.surface.execute.call_args_list]
        self.assertEqual(json.loads(calls[0][len('window.maildeskPdf?.command('):-1]),
                         {'action': 'find', 'value': query})
        self.assertEqual(len(calls), 2)
        self.reader.close()
        self.reader.scale(1.2)
        self.assertEqual(self.surface.execute.call_count, 2)

    # ==========================================
    # Function: Report native creation failure without leaking the document listener.
    # Method: Fail the surface boundary and verify the real session is closed once.
    # ==========================================
    def test_native_failure_closes_session(self):
        session = Mock()
        with patch('maildesk.pdf_reader.PDFSession', return_value=session), patch(
                'maildesk.pdf_reader.create_pdf_surface', side_effect=RuntimeError('native unavailable')):
            with self.assertRaises(RuntimeError):
                PDFReader(self.app, b'%PDF-1.7\nfixture', 'pdf', self.changed)
        session.close.assert_called_once()

if __name__ == '__main__':
    unittest.main()
