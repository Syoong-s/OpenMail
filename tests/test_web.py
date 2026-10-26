"""HTTP integration tests for session boundaries and user mail operations."""
import base64
from http.cookiejar import CookieJar
import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request

from maildesk.demo import seed
from maildesk.service import MailService
from maildesk.web import MailServer

# ==========================================
# Function: Test the complete local HTTP boundary with a synthetic inbox.
# Method: Use an ephemeral server and a cookie-aware client, without external traffic.
# ==========================================
class WebTests(unittest.TestCase):
    # ==========================================
    # Function: Start one isolated authenticated demo server.
    # Method: Seed synthetic messages and bootstrap the homepage session cookie.
    # ==========================================
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = MailService(self.temp.name, demo=True)
        seed(self.service.store)
        self.server = MailServer(0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.client = build_opener(HTTPCookieProcessor(CookieJar()))
        self.client.open(self.base + '/').read()
        self.csrf = self.request('/api/session')['csrf']

    # ==========================================
    # Function: Tear down all HTTP and storage fixtures.
    # Method: Stop the listener and clean temporary mail files.
    # ==========================================
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    # ==========================================
    # Function: Send authenticated fixture API requests.
    # Method: Add the app's exact Origin and CSRF header for JSON mutations.
    # ==========================================
    def request(self, path, data=None, headers=None):
        options = {} if data is None else {'data': json.dumps(data).encode(), 'headers': {'Content-Type': 'application/json', 'Origin': self.base, 'X-TeleMail-CSRF': self.csrf}}
        options.setdefault('headers', {}).update(headers or {})
        with self.client.open(Request(self.base + path, **options)) as response:
            return json.loads(response.read())

    # ==========================================
    # Function: Verify Host, cookie and CSRF checks reject forged requests.
    # Method: Alter each boundary independently and assert a non-success response.
    # ==========================================
    def test_session_and_csrf(self):
        for request in (Request(self.base + '/api/messages', headers={'Host': 'evil.example'}), Request(self.base + '/api/messages'), Request(self.base + '/api/sync', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'http://evil.example'})):
            with self.subTest(url=request.full_url), self.assertRaises(HTTPError) as failure:
                build_opener().open(request)
            self.assertIn(failure.exception.code, (401, 403))
            failure.exception.close()
        with self.assertRaises(HTTPError) as failure:
            self.request('/api/sync', {}, headers={'X-TeleMail-CSRF': 'wrong'})
        self.assertEqual(failure.exception.code, 403)
        failure.exception.close()

    # ==========================================
    # Function: Verify read/update/filter and sender learning end to end.
    # Method: Categorize a message and retrieve the updated view and thread.
    # ==========================================
    def test_mail_actions(self):
        data = self.request('/api/messages')
        self.assertEqual(data['total'], 8)
        identity = data['items'][0]['id']
        self.request('/api/update', {'id': identity, 'changes': {'category': 'newsletter', 'learn_sender': True, 'seen': True}})
        self.assertEqual(self.request('/api/messages?category=newsletter')['total'], 4)
        self.assertEqual(len(self.request('/api/message?id=' + identity)['thread']), 2)
        self.request('/api/update', {'id': identity, 'changes': {'archived': True}})
        self.assertEqual(self.request('/api/messages?view=archive')['total'], 1)

    # ==========================================
    # Function: Verify draft persistence and demo external-send rejection.
    # Method: Save through the UI API and attempt the matching send endpoint.
    # ==========================================
    def test_draft_and_demo_block(self):
        payload = {'account': 'demo', 'to': 'you@example.com', 'subject': 'draft', 'body': 'saved'}
        result = self.request('/api/draft', payload)
        self.assertEqual(self.request('/api/jobs')[0]['id'], result['id'])
        with self.assertRaises(HTTPError) as failure:
            self.request('/api/send', payload)
        self.assertEqual(failure.exception.code, 400)
        failure.exception.close()
        self.assertEqual(self.request('/api/jobs')[0]['state'], 'draft')

    # ==========================================
    # Function: Verify attachment bytes and EML import/export integrity.
    # Method: Download the demo MIME, reimport it, and compare its raw export.
    # ==========================================
    def test_attachments_and_import(self):
        messages = self.request('/api/messages')['items']
        message = next(m for m in messages if '附件' in m['subject'])
        detail = self.request('/api/message?id=' + message['id'])['message']
        index = detail['parsed']['attachments'][0]['index']
        with self.client.open(self.base + f'/api/attachment?id={message["id"]}&index={index}') as response:
            self.assertIn('attachment;', response.headers['Content-Disposition'])
            self.assertIn('合成附件'.encode(), response.read())
        raw = self.client.open(self.base + '/api/export?id=' + message['id']).read()
        imported = self.request('/api/import', {'base64': base64.b64encode(raw).decode()})
        self.assertEqual(self.client.open(self.base + '/api/export?id=' + imported['id']).read(), raw)

if __name__ == '__main__':
    unittest.main()
