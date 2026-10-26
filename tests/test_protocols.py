"""Real stdlib IMAP/SMTP clients exercised against loopback TLS protocol fixtures."""
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from pathlib import Path
import socketserver
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from maildesk.config import Account
from maildesk.mime import compose
from maildesk.store import Store
from maildesk import transport

# ==========================================
# Function: Host deterministic mail protocol responses over verified TLS.
# Method: Wrap accepted sockets with the fixture certificate and retain observable state.
# ==========================================
class TLSServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    # ==========================================
    # Function: Accept and encrypt a loopback client socket.
    # Method: Apply the server-side SSL context before protocol handling begins.
    # ==========================================
    def get_request(self):
        sock, address = super().get_request()
        return self.context.wrap_socket(sock, server_side=True), address

# ==========================================
# Function: Exercise SMTP authentication, RCPT acceptance and DATA transfer.
# Method: Implement a tiny standards-shaped server that records received MIME bytes.
# ==========================================
class SMTPHandler(socketserver.StreamRequestHandler):
    # ==========================================
    # Function: Serve a single SMTP conversation.
    # Method: Reply deterministically without contacting external recipients.
    # ==========================================
    def handle(self):
        self.wfile.write(b'220 localhost test\r\n')
        while line := self.rfile.readline():
            self.server.commands.append(line)
            upper = line.upper()
            if upper.startswith(b'EHLO'):
                self.wfile.write(b'250-localhost\r\n250 AUTH PLAIN LOGIN\r\n')
            elif upper.startswith(b'AUTH'):
                self.wfile.write(b'235 authenticated\r\n')
            elif upper.startswith(b'MAIL'):
                self.wfile.write(b'250 sender ok\r\n')
            elif upper.startswith(b'RCPT'):
                self.wfile.write(b'550 rejected\r\n' if b'refused@' in line else b'250 recipient ok\r\n')
            elif upper.startswith(b'DATA'):
                self.wfile.write(b'354 send content\r\n')
                raw = bytearray()
                while (part := self.rfile.readline()) != b'.\r\n':
                    if not part:
                        return
                    raw.extend(part[1:] if part.startswith(b'..') else part)
                self.server.received.append(bytes(raw))
                if getattr(self.server, 'drop_response', False):
                    return
                self.wfile.write(b'250 accepted\r\n')
            elif upper.startswith(b'QUIT'):
                self.wfile.write(b'221 goodbye\r\n')
                return
            else:
                self.wfile.write(b'250 ok\r\n')

# ==========================================
# Function: Exercise UID-based IMAP receive and flags using real wire parsing.
# Method: Respond to capability, selection, UID FETCH/STORE and APPEND commands.
# ==========================================
class IMAPHandler(socketserver.StreamRequestHandler):
    # ==========================================
    # Function: Serve one IMAP session.
    # Method: Use tagged replies and literal MIME bytes, including UIDVALIDITY changes.
    # ==========================================
    def handle(self):
        self.wfile.write(b'* OK test IMAP ready\r\n')
        while line := self.rfile.readline():
            self.server.commands.append(line)
            parts = line.rstrip().split(b' ', 2)
            if len(parts) < 2:
                return
            tag, command = parts[:2]
            tail = parts[2] if len(parts) > 2 else b''
            if command == b'CAPABILITY':
                self.wfile.write(b'* CAPABILITY IMAP4rev1 UIDPLUS AUTH=PLAIN\r\n')
            elif command in (b'SELECT', b'EXAMINE'):
                self.wfile.write(b'* FLAGS (\\Seen)\r\n* 1 EXISTS\r\n* OK [UIDVALIDITY ' + self.server.validity + b'] generation\r\n')
            elif command == b'UID' and tail.startswith(b'SEARCH'):
                self.wfile.write(b'* SEARCH 8\r\n')
            elif command == b'UID' and tail.startswith(b'FETCH'):
                if b'RFC822.SIZE' in tail:
                    self.wfile.write(b'* 1 FETCH (UID 8 RFC822.SIZE ' + str(len(self.server.raw)).encode() + b')\r\n')
                elif b'BODY.PEEK[]' in tail:
                    self.wfile.write(b'* 1 FETCH (UID 8 FLAGS () BODY[] {' + str(len(self.server.raw)).encode() + b'}\r\n' + self.server.raw + b')\r\n')
                else:
                    self.wfile.write(b'* 1 FETCH (UID 8 FLAGS (' + (b'\\Seen' if self.server.seen else b'') + b'))\r\n')
            elif command == b'UID' and tail.startswith(b'STORE'):
                self.server.seen = b'+FLAGS' in tail
            elif command == b'APPEND':
                count = int(tail.rsplit(b'{', 1)[1].rstrip(b'}'))
                self.wfile.write(b'+ literal ready\r\n')
                self.server.received.append(self.rfile.read(count))
                self.rfile.read(2)
            elif command == b'LOGOUT':
                self.wfile.write(b'* BYE goodbye\r\n' + tag + b' OK logout complete\r\n')
                return
            self.wfile.write(tag + b' OK complete\r\n')

# ==========================================
# Function: Verify TLS wire behavior without sending any real mail.
# Method: Trust only an ephemeral test certificate for loopback fixtures.
# ==========================================
class ProtocolTests(unittest.TestCase):
    # ==========================================
    # Function: Create a test-only local CA/server certificate.
    # Method: Generate a one-day self-signed loopback certificate using system OpenSSL.
    # ==========================================
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.cert, cls.key = cls.root / 'cert.pem', cls.root / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-keyout', str(cls.key), '-out', str(cls.cert), '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        cls.trusted = ssl.create_default_context(cafile=str(cls.cert))

    # ==========================================
    # Function: Remove ephemeral certificate material.
    # Method: Delete the temporary fixture directory after all tests.
    # ==========================================
    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    # ==========================================
    # Function: Start and stop a bounded TLS test server.
    # Method: Use an ephemeral IPv4 loopback port and daemon request threads.
    # ==========================================
    @contextmanager
    def fixture(self, handler):
        server = TLSServer(('127.0.0.1', 0), handler)
        server.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server.context.load_cert_chain(self.cert, self.key)
        server.commands, server.received, server.validity, server.seen = [], [], b'77', False
        msg, _ = compose('friend@example.com', {'to': 'me@example.com', 'subject': 'Local TLS test', 'body': '测试邮件'}, '<tls@example.com>')
        server.raw = msg.as_bytes()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch('maildesk.transport.ssl.create_default_context', return_value=self.trusted), patch.dict('os.environ', {'TEST_PASSWORD': 'synthetic-password'}):
                yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    # ==========================================
    # Function: Verify SMTP MIME transfer and partial recipient handling.
    # Method: Submit to the fixture, accept one address, and reject another.
    # ==========================================
    def test_smtp_tls_and_partial(self):
        with self.fixture(SMTPHandler) as server:
            account = Account('test', 'me@example.com', '127.0.0.1', '127.0.0.1', smtp_port=server.server_address[1], secret_env='TEST_PASSWORD')
            msg, targets = compose(account.email, {'to': 'ok@example.com, refused@example.com', 'body': '本地测试', 'bcc': 'hidden@example.com'})
            refused = transport.deliver(account, msg.as_bytes(), targets)
            self.assertIn('refused@example.com', refused)
            self.assertEqual(len(server.received), 1)
            received = BytesParser(policy=policy.default).parsebytes(server.received[0])
            self.assertNotIn('Bcc', received)
            self.assertIn('本地测试', received.get_content())
            self.assertTrue(any(c.startswith(b'AUTH') for c in server.commands))

    # ==========================================
    # Function: Detect ambiguous delivery when DATA is received but confirmation is lost.
    # Method: Drop the TLS connection after recording MIME bytes and before SMTP 250.
    # ==========================================
    def test_smtp_lost_confirmation_is_uncertain(self):
        with self.fixture(SMTPHandler) as server:
            server.drop_response = True
            account = Account('test', 'me@example.com', '127.0.0.1', '127.0.0.1', smtp_port=server.server_address[1], secret_env='TEST_PASSWORD')
            with self.assertRaises(transport.DeliveryError) as failure:
                transport.deliver(account, server.raw, ['you@example.com'])
            self.assertTrue(failure.exception.uncertain)
            self.assertEqual(len(server.received), 1)

    # ==========================================
    # Function: Verify incremental IMAP receive, read flags and generation mismatch.
    # Method: Sync twice over TLS and assert BODY.PEEK occurs only for uncached UIDs.
    # ==========================================
    def test_imap_tls_incremental_flags_generation(self):
        with self.fixture(IMAPHandler) as server, tempfile.TemporaryDirectory() as cache:
            account = Account('test', 'me@example.com', '127.0.0.1', '127.0.0.1', imap_port=server.server_address[1], secret_env='TEST_PASSWORD', sent_folder='Sent')
            store = Store(Path(cache) / 'mail.db')
            self.assertEqual(transport.sync_account(account, store)['imported'], 1)
            self.assertEqual(transport.sync_account(account, store)['imported'], 0)
            self.assertEqual(sum(b'BODY.PEEK[]' in c for c in server.commands), 1)
            message = store.get(store.list_messages()['items'][0]['id'])
            transport.set_seen(account, message, True)
            transport.sync_account(account, store)
            self.assertEqual(store.get(message['id'])['seen'], 1)
            transport.append_sent(account, server.raw)
            self.assertEqual(server.received, [server.raw])
            server.validity = b'78'
            count = sum(b' STORE ' in c for c in server.commands)
            with self.assertRaises(ValueError):
                transport.set_seen(account, message, False)
            self.assertEqual(sum(b' STORE ' in c for c in server.commands), count)

if __name__ == '__main__':
    unittest.main()
