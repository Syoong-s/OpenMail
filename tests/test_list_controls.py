"""Compact native list metadata and contact preference transaction regressions."""
from datetime import datetime,timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import contextlib,sqlite3
from unittest.mock import patch
from maildesk import address_book
from maildesk.contact_policies import get,save_many,toggle_many
from maildesk.mail_list_visuals import history_counts
from maildesk.store import Store

# ==========================================
# Function: Verify shared contact writes and list metadata without any provider or native window.
# Method: Use a real temporary Store with actual MIME references, attachments and independent physical copies.
# ==========================================
class ListControlsTests(unittest.TestCase):
    # ==========================================
    # Function: Isolate all cached data and people from the actual account profile.
    # Method: Create an empty temporary database and stable explicit contact identities.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.store=Store(Path(self.temp.name)/'mail.sqlite3');self.serial=0
        for person in ('alice','bob'):address_book.save(self.store,person,person,[person+'@example.invalid'])
    # ==========================================
    # Function: Release temporary test data after each independent behavior assertion.
    # Method: Close short-lived Store connections automatically before removing its directory.
    # ==========================================
    def tearDown(self):self.temp.cleanup()
    # ==========================================
    # Function: Produce source mail with controllable RFC identity, account and folder membership.
    # Method: Parse real MIME through ingest so graph edges and attachment metadata use production logic.
    # ==========================================
    def mail(self,mid,refs='',account='one',folder='INBOX',attachment=False):
        self.serial+=1;m=EmailMessage();m['From']='Alice <alice@example.invalid>';m['To']='self@example.invalid';m['Subject']='Row '+str(self.serial);m['Message-ID']=mid;m['Date']=datetime.now(timezone.utc)
        if refs:m['References']=refs
        m.set_content('Ordinary mail')
        if attachment:m.add_attachment(b'fixture',maintype='application',subtype='octet-stream',filename='sample.bin')
        return self.store.ingest(account,folder,'1',str(self.serial),m.as_bytes())
    # ==========================================
    # Function: Toggle whole mixed selections without losing their other policies or independent stars.
    # Method: Validate mute/pin/block off/on behavior on the same persistent people.
    # ==========================================
    def test_bulk_partial_policy_toggles(self):
        save_many(self.store,{'alice':{'muted':True,'pinned':False,'blocked':False,'starred':True}})
        self.assertTrue(toggle_many(self.store,['alice','bob'],'muted'));self.assertTrue(get(self.store,'bob')['muted'])
        self.assertTrue(toggle_many(self.store,['alice','bob'],'pinned'));self.assertFalse(toggle_many(self.store,['alice','bob'],'muted'))
        self.assertTrue(all(get(self.store,p)['pinned'] for p in ('alice','bob')))
        self.assertTrue(address_book.sender_detail(self.store,person='alice')['starred'])
        self.assertTrue(toggle_many(self.store,['alice','bob'],'blocked'));self.assertFalse(toggle_many(self.store,['alice','bob'],'blocked'))
    # ==========================================
    # Function: Reject stale bulk selections atomically rather than partially mutating valid contacts.
    # Method: Include one absent person and verify a previously saved independent flag remains intact.
    # ==========================================
    def test_bulk_rejects_stale_selection(self):
        with self.assertRaises(ValueError):toggle_many(self.store,['alice','missing'],'muted')
        self.assertFalse(get(self.store,'alice')['muted'])
        with self.assertRaises(ValueError):toggle_many(self.store,['alice'],'starred')
    # ==========================================
    # Function: Save stars from shared details while preserving the legacy three-policy caller contract.
    # Method: Reopen the database and update old-style values after a four-field save.
    # ==========================================
    def test_shared_details_star_persistence_and_legacy_save(self):
        save_many(self.store,{'alice':{'muted':True,'pinned':True,'blocked':False,'starred':True}})
        reopened=Store(self.store.path);self.assertTrue(address_book.sender_detail(reopened,person='alice')['starred'])
        save_many(reopened,{'alice':{'muted':False,'pinned':True,'blocked':False}})
        self.assertTrue(address_book.sender_detail(reopened,person='alice')['starred']);self.assertFalse(get(reopened,'alice')['muted'])
    # ==========================================
    # Function: Keep shared detail flags and star changes atomic if any selected contact is invalid.
    # Method: Roll back an earlier valid person in a batch whose later identity is missing.
    # ==========================================
    def test_details_star_transaction_rollback(self):
        values={'muted':True,'pinned':True,'blocked':False,'starred':True}
        with self.assertRaises(ValueError):save_many(self.store,{'alice':values,'missing':values})
        self.assertFalse(get(self.store,'alice')['muted']);self.assertFalse(address_book.sender_detail(self.store,person='alice')['starred'])
    # ==========================================
    # Function: Count connected RFC history with out-of-order links and physical duplicates across folders.
    # Method: Preserve account isolation, omit gone copies and treat isolated messages as a single source.
    # ==========================================
    def test_history_counts_reference_graph_and_duplicate_copies(self):
        child=self.mail('<child@fixture>','<middle@fixture>');root=self.mail('<root@fixture>');middle=self.mail('<middle@fixture>','<root@fixture>')
        self.mail('<root@fixture>',folder='Sent');self.mail('<root@fixture>',account='two');isolated=self.mail('<other@fixture>')
        self.assertEqual(history_counts(self.store,[child,root,middle,isolated]),{child:3,root:3,middle:3,isolated:1})
        with self.store.db() as db:db.execute('UPDATE messages SET remote_gone=1 WHERE id=?',(middle,))
        self.assertEqual(history_counts(self.store,[child])[child],2)
    # ==========================================
    # Function: Expose only compact attachment presence to ordinary native rows.
    # Method: Read the normal list result and confirm no raw/parsed body fields are hydrated.
    # ==========================================
    def test_list_attachment_metadata(self):
        attached=self.mail('<attachment@fixture>',attachment=True);plain=self.mail('<plain@fixture>')
        rows={item['id']:item for item in self.store.list_messages()['items']}
        self.assertEqual(rows[attached]['attachments_count'],1);self.assertEqual(rows[plain]['attachments_count'],0)
        self.assertNotIn('raw',rows[attached]);self.assertNotIn('parsed',rows[attached])

    # ==========================================
    # Function: Keep avatar history counting independent of message bodies and MIME hydration.
    # Method: Deny access to large text/blob columns using SQLite's authorizer while traversing real reference links.
    # ==========================================
    def test_history_counts_reads_metadata_only(self):
        root=self.mail('<root@metadata>');child=self.mail('<child@metadata>','<root@metadata>')
        original=self.store.db
        # ==========================================
        # Function: Refuse heavyweight message column reads during the production metadata query.
        # Method: Let SQLite enforce the access restriction rather than matching the query's implementation text.
        # ==========================================
        def authorize(action,table,column,*unused):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='messages' and column in ('raw','parsed','body') else sqlite3.SQLITE_OK
        # ==========================================
        # Function: Attach the body-read guard to each actual Store connection used by the query.
        # Method: Wrap the original context manager and restore the authorizer before closing.
        # ==========================================
        @contextlib.contextmanager
        def guarded():
            with original() as db:
                db.set_authorizer(authorize)
                try:yield db
                finally:db.set_authorizer(None)
        with patch.object(self.store,'db',guarded):self.assertEqual(history_counts(self.store,[root,child]),{root:2,child:2})

if __name__=='__main__':unittest.main()
