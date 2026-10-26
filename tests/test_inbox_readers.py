"""View persistence, grouping and inert document regressions."""
from pathlib import Path
import tempfile
import time
import unittest
from maildesk.store import Store
from maildesk.inbox_views import InboxViews
from maildesk.document_content import reader_document, markdown_html

# ==========================================
# Function: Validate independent inbox layouts against durable cached messages.
# Method: Exercise scope, pagination, card projection and state persistence on SQLite.
# ==========================================
class InboxViewTests(unittest.TestCase):
    # ==========================================
    # Function: Build an isolated mailbox with mixed read, category and account states.
    # Method: Ingest real MIME messages through the normal store boundary.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'mail.db'
        self.store=Store(self.path);self.views=InboxViews(self.store)
        self.identities=[]
        for index in range(12):
            raw=f'From: Sender <sender{index%3}@example.com>\r\nTo: test@example.com\r\nSubject: Mail {index}\r\n\r\nbody'.encode()
            identity=self.store.ingest('one' if index<9 else 'two','INBOX','v1',str(index),raw)
            self.store.update(identity,{'seen':index%2==0,'category':('personal','notification','newsletter')[index%3],'pinned':index==0})
            self.identities.append(identity)

    # ==========================================
    # Function: Remove temporary mailbox data after each regression.
    # Method: Close SQLite contexts before directory cleanup.
    # ==========================================
    def tearDown(self):
        self.temp.cleanup()

    # ==========================================
    # Function: Preserve view creation, edits, selection and safe deletion across restart.
    # Method: Reopen the SQLite store and compare stable saved definitions.
    # ==========================================
    def test_persistence_and_validation(self):
        value=self.views.definition('smart','工作未读');value.update(accounts=['one'],limit=3,grouping='sender',collapsed=['personal'])
        self.views.save(value);self.store.set_preference('active_inbox_view',value['id'])
        reopened=InboxViews(Store(self.path));self.assertEqual(reopened.active()['id'],value['id']);self.assertEqual(reopened.active()['accounts'],['one'])
        with self.assertRaises(ValueError):self.views.save({**value,'limit':-3})
        self.views.delete(value['id']);self.assertNotEqual(self.views.active()['id'],value['id'])
        for row in self.views.all()[1:]:self.views.delete(row['id'])
        with self.assertRaises(ValueError):self.views.delete(self.views.active()['id'])

    # ==========================================
    # Function: Keep each mode behavior distinct and every message unique.
    # Method: Compare section projections from the same cached metadata.
    # ==========================================
    def test_modes_counts_and_unread_cards(self):
        rows=self.store.list_messages()['items']
        classic=self.views.sections(rows,self.views.definition('classic'))
        self.assertEqual(len(classic),1);self.assertEqual(len(classic[0]['items']),12)
        smart=self.views.definition('smart');smart['limit']=3
        sections=self.views.sections(rows,smart)
        self.assertTrue(all(len(section['shown'])<=3 for section in sections))
        for section in sections:self.assertTrue(all(bool(row['seen'])==(section['key']=='seen') for row in section['items']))
        ids=[r['id'] for section in sections for r in section['items']];self.assertEqual(len(set(ids)),12)
        focused=self.views.sections(rows,self.views.definition('focused'))
        self.assertIn('pinned',[section['key'] for section in focused]);self.assertNotIn('seen',[section['key'] for section in focused])

    # ==========================================
    # Function: Apply account scope in SQL before paging and respect hidden/collapsed cards.
    # Method: Assert counts and projections including a nonmatching account intersection.
    # ==========================================
    def test_account_scope_and_card_settings(self):
        result=self.store.list_messages(account=('two',),limit=2)
        self.assertEqual(result['total'],3);self.assertEqual(len(result['items']),2)
        self.assertEqual(self.store.list_messages(account=())['total'],0)
        value=self.views.definition('smart');value.update(accounts=['one'],disabled=['seen'],collapsed=['notification'])
        sections=self.views.sections(self.store.list_messages()['items'],value)
        self.assertTrue(all(row['account']=='one' for section in sections for row in section['items']))
        self.assertNotIn('seen',[section['key'] for section in sections])
        self.assertTrue(next(s for s in sections if s['key']=='notification')['collapsed'])

    # ==========================================
    # Function: Keep card overrides isolated while preserving single message membership.
    # Method: Apply different grouping, account and display settings to two categories.
    # ==========================================
    def test_independent_card_configuration(self):
        value=self.views.definition('smart')
        value['cards']={'notification':{'enabled':True,'grouping':'account','accounts':['one'],'limit':3,'action':'done'},
                        'newsletter':{'enabled':False,'grouping':'category','accounts':[],'limit':5,'action':'seen'}}
        value=self.views.save(value);sections=self.views.sections(self.store.list_messages()['items'],value)
        self.assertFalse(any(section.get('base')=='newsletter' for section in sections))
        card=next(section for section in sections if section.get('base')=='notification')
        self.assertEqual(card['key'],'notification:account:one');self.assertEqual(card['action'],'done')
        self.assertTrue(all(row['account']=='one' for row in card['items']))
        self.assertEqual(next(s for s in sections if s['key']=='seen')['action'],'seen')
        ids=self.views.group_identities('notification:account:one',value)
        self.assertEqual(set(ids),{row['id'] for row in card['items']})
        self.assertEqual(self.views.group_identities('notification:account:one',value,'two'),[])

# ==========================================
# Function: Verify readable documents cannot introduce scripts or remote resource loads.
# Method: Feed malformed and active HTML plus realistic Markdown through preparation.
# ==========================================
class ReaderContentTests(unittest.TestCase):
    # ==========================================
    # Function: Preserve readable structure while excluding active document elements.
    # Method: Assert CSP placement and removal of scripts, events, bases and remote images.
    # ==========================================
    def test_offline_html(self):
        value=reader_document('<base href="https://evil.test"><script>secret()</script><iframe>bad</iframe><p onclick="run()">你好</p><img src="https://tracker.test/x"><a href="javascript:bad()">link</a><table><tr><td>cell</td></tr></table>')
        self.assertNotIn('<script',value);self.assertNotIn('secret()',value);self.assertNotIn('onclick',value)
        self.assertNotIn('tracker.test',value);self.assertNotIn('javascript:',value);self.assertNotIn('<base ',value)
        self.assertIn('你好',value);self.assertIn('<table>',value);self.assertIn("default-src 'none'",value)
        self.assertLess(value.index('Content-Security-Policy'),value.index('<table>'))

    # ==========================================
    # Function: Render headings, tables, lists, code blocks and safe links from Markdown.
    # Method: Check semantic HTML and ensure raw active markup stays ordinary text.
    # ==========================================
    def test_markdown_blocks(self):
        value=reader_document('# 标题\n\n**bold** and *italic*\n- one\n- two\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n```python\nprint("hi")\n```\n<script>alert(1)</script>\n[site](https://example.com)',markdown=True)
        for token in ('<h1>','<strong>bold</strong>','<em>italic</em>','<ul>','<table>','<pre><code>','href="https://example.com"'):self.assertIn(token,value)
        self.assertNotIn('<script>',value);self.assertIn('&lt;script&gt;',value)
