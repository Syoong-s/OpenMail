"""Domain regression tests for mail parsing, state, classification and delivery."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from maildesk.classifier import classify
from maildesk.config import Account, load_accounts
from maildesk.mime import compose, parse_message
from maildesk.service import MailService
from maildesk.store import Store
from maildesk.transport import DeliveryError, mailbox_name

# ==========================================
# Function: Build reproducible MIME inputs for domain tests.
# Method: Use the independent composer, then add selected incoming header fixtures.
# ==========================================
def raw_mail(sender='friend@example.com', subject='Hello 世界', message_id='<root@example.com>', headers=None):
    message, _ = compose(sender, {'to': 'me@example.com', 'subject': subject, 'body': '正文 café\n你好'}, message_id)
    for key, value in (headers or {}).items():
        message[key] = value
    return message.as_bytes()

# ==========================================
# Function: Check persistent domain behavior and safe failure handling.
# Method: Isolated temporary databases and controlled protocol boundaries.
# ==========================================
class CoreTests(unittest.TestCase):
    # ==========================================
    # Function: Create a clean isolated mailbox per test.
    # Method: Use a temporary native filesystem directory and example account.
    # ==========================================
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'test.sqlite3')
        self.account = Account('work', 'me@example.com', 'imap.example.com', 'smtp.example.com')

    # ==========================================
    # Function: Remove test mail and database files.
    # Method: Clean the temporary directory after connections have closed.
    # ==========================================
    def tearDown(self):
        self.temp.cleanup()

    # ==========================================
    # Function: Verify UTF-8 MIME, attachment and Bcc envelope handling.
    # Method: Round-trip a multipart outgoing message through the incoming parser.
    # ==========================================
    def test_mime_and_bcc(self):
        msg, recipients = compose('me@example.com', {'to': '林 <lin@example.com>', 'bcc': 'hidden@example.com', 'subject': '你好', 'body': 'héllo 你好', 'attachments': [{'name': '笔记.txt', 'data': b'notes'}]})
        parsed = parse_message(msg.as_bytes())
        self.assertEqual(parsed['subject'], '你好')
        self.assertIn('héllo', parsed['body'])
        self.assertEqual(parsed['attachments'][0]['name'], '笔记.txt')
        self.assertIn('hidden@example.com', recipients)
        self.assertNotIn(b'Bcc:', msg.as_bytes())

    # ==========================================
    # Function: Ensure HTML mail cannot load or execute active content.
    # Method: Parse HTML-only input containing scripts and remote tracking images.
    # ==========================================
    def test_html_inert(self):
        raw = b'From: x@example.com\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>Hello</p><script>steal()</script><img src="https://tracker.example/x">'
        result = parse_message(raw)
        self.assertEqual(result['body'], 'Hello')
        self.assertNotIn('steal', result['body'])

    # ==========================================
    # Function: Keep attached messages out of the parent body.
    # Method: Parse a nested RFC attachment alongside multipart alternatives.
    # ==========================================
    def test_nested_attachment_and_alternatives(self):
        from email.message import EmailMessage
        outer = EmailMessage()
        outer['From'] = 'x@example.com'
        outer.set_content('Parent body')
        outer.add_alternative('<p>Parent HTML</p>', subtype='html')
        nested = EmailMessage()
        nested.set_content('Attached private body')
        outer.add_attachment(nested, filename='forwarded.eml')
        result = parse_message(outer.as_bytes())
        self.assertEqual(result['body'], 'Parent body')
        self.assertEqual(result['attachments'][0]['name'], 'forwarded.eml')
        self.assertGreater(result['attachments'][0]['size'], 0)

    # ==========================================
    # Function: Verify classification precedence and readable reasons.
    # Method: Assert sender correction > custom rule > MIME heuristics > personal.
    # ==========================================
    def test_classification_precedence(self):
        message = parse_message(raw_mail(headers={'List-ID': '<weekly.example.com>'}))
        self.assertEqual(classify(message)[0], 'newsletter')
        self.assertEqual(classify(message, {'friend@example.com': 'personal'})[0], 'personal')
        self.assertEqual(classify(message, rules=[{'field': 'subject', 'contains': 'Hello', 'category': 'notification'}])[0], 'notification')
        self.assertEqual(classify(parse_message(raw_mail(headers={'Auto-Submitted': 'auto-generated'})))[0], 'notification')
        self.assertEqual(classify(parse_message(raw_mail()))[0], 'personal')

    # ==========================================
    # Function: Verify idempotent receive, reference threading and account isolation.
    # Method: Reinsert one UID, add a reply, and reuse identifiers in another account.
    # ==========================================
    def test_uid_and_threads(self):
        first = self.store.ingest('work', 'INBOX', '1', '9', raw_mail())
        self.assertEqual(first, self.store.ingest('work', 'INBOX', '1', '9', raw_mail()))
        reply = self.store.ingest('work', 'INBOX', '1', '10', raw_mail(message_id='<reply@example.com>', headers={'References': '<root@example.com>'}))
        self.store.ingest('personal', 'INBOX', '1', '9', raw_mail())
        self.assertEqual(len(self.store.thread(reply)), 2)
        self.assertEqual(self.store.list_messages()['total'], 3)
        self.store.mailbox('work', 'INBOX', '2')
        self.assertEqual(self.store.list_messages()['total'], 1)
        self.assertEqual(self.store.get(first)['remote_gone'], 1)

    # ==========================================
    # Function: Confirm sender learning respects individual message overrides.
    # Method: Correct two messages differently, then import a future sender message.
    # ==========================================
    def test_sender_learning_and_override(self):
        first = self.store.ingest('work', 'INBOX', '1', '1', raw_mail())
        second = self.store.ingest('work', 'INBOX', '1', '2', raw_mail(message_id='<2@example.com>'))
        self.store.update(first, {'category': 'notification'})
        self.store.update(second, {'category': 'newsletter', 'learn_sender': True})
        third = self.store.ingest('work', 'INBOX', '1', '3', raw_mail(message_id='<3@example.com>'))
        self.store.reclassify()
        self.assertEqual(self.store.get(first)['category'], 'notification')
        self.assertEqual(self.store.get(third)['category'], 'newsletter')
        self.store.update(third, {'pinned': True, 'priority': True, 'archived': True})
        self.assertEqual(self.store.list_messages(view='archive')['total'], 1)
        self.assertEqual(self.store.list_messages(search='café')['total'], 2)

    # ==========================================
    # Function: Protect credentials and reject insecure or malformed configuration.
    # Method: Validate TLS modes and duplicate IDs; resolve only an environment secret.
    # ==========================================
    def test_configuration_validation(self):
        with self.assertRaises(ValueError):
            Account('x', 'x@example.com', 'imap', 'smtp', smtp_security='none')
        with patch.dict('os.environ', {'MAIL_PASSWORD': 'test-only'}):
            self.assertEqual(self.account.secret(), 'test-only')
        p = self.root / 'config.json'
        item = {'id': 'work', 'email': 'me@example.com', 'imap_host': 'imap', 'smtp_host': 'smtp'}
        p.write_text(json.dumps({'accounts': [item, item]}))
        with self.assertRaises(ValueError):
            load_accounts(p)
        self.assertEqual(mailbox_name('收件箱 & more'), '"&ZTZO9nux- &- more"')

    # ==========================================
    # Function: Reject recipient and subject header injection.
    # Method: Attempt embedded CRLF before SMTP is reached.
    # ==========================================
    def test_header_injection(self):
        for draft in ({'to': 'x@example.com\r\nBcc: bad@example.com'}, {'to': 'x@example.com', 'subject': 'hi\r\nX-Inject: bad'}):
            with self.assertRaises(ValueError):
                compose('me@example.com', draft)

    # ==========================================
    # Function: Preserve drafts, scheduling and cancel semantics through restarts.
    # Method: Queue a future item, recover it as draft, then simulate a crashed send.
    # ==========================================
    def test_durable_outbox(self):
        service = MailService(self.root / 'service', [self.account])
        result = service.compose({'account': 'work', 'to': 'you@example.com', 'subject': 'future', 'due': time.time() + 100}, send=True)
        self.assertIsNone(service.store.claim())
        service.store.cancel(result['id'])
        self.assertEqual(service.store.jobs()[0]['state'], 'draft')
        service.compose({'id': result['id'], 'account': 'work', 'to': 'you@example.com', 'subject': 'now'}, send=True)
        self.assertIsNotNone(service.store.claim())
        restored = Store(self.root / 'service/mail.sqlite3')
        self.assertEqual(restored.jobs()[0]['state'], 'uncertain')
        self.assertIsNone(restored.claim())

    # ==========================================
    # Function: Prevent duplicate delivery after sent-copy errors or ambiguous DATA.
    # Method: Inject controlled outcomes and assert terminal states never requeue.
    # ==========================================
    def test_delivery_outcomes(self):
        for outcome in ('success', 'partial', 'uncertain', 'failed'):
            with self.subTest(outcome=outcome):
                service = MailService(self.root / outcome, [self.account])
                service.compose({'account': 'work', 'to': 'you@example.com', 'subject': outcome}, send=True)
                error = DeliveryError('test', uncertain=outcome == 'uncertain') if outcome in ('uncertain', 'failed') else None
                with patch('maildesk.transport.deliver', return_value={'bad@example.com': (550, b'no')} if outcome == 'partial' else {}, side_effect=error) as deliver, patch('maildesk.transport.append_sent', side_effect=RuntimeError('copy failed')):
                    self.assertTrue(service.process_one())
                    self.assertFalse(service.process_one())
                    self.assertEqual(deliver.call_count, 1)
                expected = {'success': 'sent', 'partial': 'partial', 'uncertain': 'uncertain', 'failed': 'failed'}[outcome]
                self.assertEqual(service.store.jobs()[0]['state'], expected)

    # ==========================================
    # Function: Prevent a repeated send request from creating duplicate deliveries.
    # Method: Reuse the composer's stable draft ID after the first queue transition.
    # ==========================================
    def test_duplicate_submission_and_lazy_attachments(self):
        service = MailService(self.root / 'dedup', [self.account])
        payload = {'id': 'stable-id', 'account': 'work', 'to': 'you@example.com', 'subject': 'one', 'attachments': [{'name': 'test.txt', 'base64': 'dGVzdA=='}]}
        service.compose(payload, send=True)
        with self.assertRaises(ValueError):
            service.compose(payload, send=True)
        self.assertEqual(len(service.store.jobs()), 1)
        self.assertNotIn('base64', service.store.jobs()[0]['draft']['attachments'][0])
        self.assertEqual(service.store.job('stable-id')['draft']['attachments'][0]['base64'], 'dGVzdA==')

    # ==========================================
    # Function: Ensure demo mode never calls a delivery provider.
    # Method: Attempt explicit sending against the demo service.
    # ==========================================
    def test_demo_no_send(self):
        service = MailService(self.root / 'demo', demo=True)
        with patch('maildesk.transport.deliver') as deliver:
            with self.assertRaises(ValueError):
                service.compose({'account': 'demo', 'to': 'x@example.com'}, send=True)
            self.assertFalse(service.process_one())
            deliver.assert_not_called()

if __name__ == '__main__':
    unittest.main()
