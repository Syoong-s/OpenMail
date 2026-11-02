"""Regression coverage for event-driven activity caching with real SQLite transactions."""
from contextlib import contextmanager
from datetime import timedelta
from maildesk.activity_cache import ActivityCache,HISTORY
from unittest import TestCase
from test_mail_activity import MailActivityFixture


# ==========================================
# Function: Verify cached and uncached activity agree while avoiding repeated annual reads.
# Method: Reuse real mail fixtures, trace SQL and inspect committed event delivery rather than timing mocks.
# ==========================================
class ActivityCacheTests(MailActivityFixture,TestCase):
    # ==========================================
    # Function: Collect SQL while preserving normal commit notifications and rollback behavior.
    # Method: Temporarily wrap the existing store connection factory and restore it on exit.
    # ==========================================
    @contextmanager
    def trace(self):
        original=self.store.db;queries=[]

        # ==========================================
        # Function: Attach a trace to each real short-lived SQLite connection.
        # Method: Remove it before closing and leave transaction semantics untouched.
        # ==========================================
        @contextmanager
        def traced():
            with original() as db:
                db.set_trace_callback(queries.append)
                try:yield db
                finally:db.set_trace_callback(None)
        self.store.db=traced
        try:yield queries
        finally:self.store.db=original

    # ==========================================
    # Function: Reuse the annual index on repeated display, date/account navigation and pagination.
    # Method: Assert a single full metadata load and no envelope queries after warming the cache.
    # ==========================================
    def test_navigation_reuses_envelopes_and_previews(self):
        first=self.add();self.add(day=self.today-timedelta(days=1),mid='yesterday');self.add(account='two',mid='other')
        cache=ActivityCache(self.store)
        with self.trace() as queries:
            cache.snapshot(self.accounts,today=self.today)
            cache.snapshot(self.accounts,selected=self.today-timedelta(days=1),today=self.today)
            cache.snapshot(self.accounts,scope=('two',),today=self.today)
            result=cache.snapshot(self.accounts,scope=('one',),limit=120,today=self.today)
        self.assertEqual([item['id'] for item in result['items']],[first]);self.assertEqual(cache.full_loads,1)
        self.assertEqual(sum('FROM messages m LEFT JOIN folders' in sql for sql in queries),1)
        with self.trace() as queries:cache.snapshot(self.accounts,today=self.today)
        self.assertFalse(any('FROM messages' in sql for sql in queries))

    # ==========================================
    # Function: Patch new, changed, deleted and remote-missing mail without rescanning the year.
    # Method: Check duplicate visibility and mutable previews against fresh uncached projections after each commit.
    # ==========================================
    def test_incremental_changes_match_authoritative_snapshot(self):
        from maildesk.mail_activity import activity_snapshot
        first=self.add();copy=self.add('All');other=self.add(mid='other');cache=ActivityCache(self.store)
        cache.snapshot(self.accounts,today=self.today)
        operations=[('UPDATE messages SET seen=1 WHERE id=?',(first,)),
                    ('UPDATE messages SET folder=\'Archive\',archived=1,done=1 WHERE id=?',(first,)),
                    ('UPDATE messages SET body=\'New preview\',subject=\'Changed subject\' WHERE id=?',(other,)),
                    ('UPDATE messages SET trashed=1 WHERE id=?',(first,)),
                    ('UPDATE messages SET remote_gone=1 WHERE id=?',(other,)),
                    ('DELETE FROM messages WHERE id=?',(copy,))]
        for sql,args in operations:
            with self.store.db() as db:db.execute(sql,args)
            with self.trace() as queries:actual=cache.snapshot(self.accounts,today=self.today)
            self.assertEqual(actual,activity_snapshot(self.store,self.accounts,today=self.today))
            envelope_queries=[query for query in queries if 'FROM messages m LEFT JOIN folders' in query]
            self.assertTrue(all('m.id IN (' in query for query in envelope_queries))
        new=self.add(mid='new');self.assertIn(new,[row['id'] for row in cache.snapshot(self.accounts,today=self.today)['items']])
        self.assertEqual(cache.full_loads,1)

    # ==========================================
    # Function: Notify only for committed activity changes, including imports outside UI action callbacks.
    # Method: Exercise preference writes, no-op updates, rollback and batched ingest on the real store.
    # ==========================================
    def test_events_follow_commits_and_ignore_unrelated_writes(self):
        events=[];self.store.activity_listeners.add(events.append);identity=self.add();self.assertTrue(events);events.clear()
        self.store.set_preference('theme','light')
        with self.store.db() as db:db.execute('UPDATE messages SET seen=seen WHERE id=?',(identity,))
        with self.assertRaises(ValueError):
            with self.store.db() as db:
                db.execute('UPDATE messages SET trashed=1 WHERE id=?',(identity,));raise ValueError('rollback')
        self.assertEqual(events,[])
        with self.store.db() as db:
            db.execute('UPDATE messages SET seen=1 WHERE id=?',(identity,));db.execute('UPDATE messages SET seen=0 WHERE id=?',(identity,))
        self.assertEqual(len(events),1)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM activity_changes WHERE message=?',(identity,)).fetchone()[0],1)

    # ==========================================
    # Function: Reclassify cached copies when provider folder mappings or display metadata change.
    # Method: Update compact projection tables directly to model background mapping and migration work.
    # ==========================================
    def test_folder_mapping_and_display_metadata_update_cache(self):
        identity=self.add('Archive');cache=ActivityCache(self.store);cache.snapshot(self.accounts,today=self.today)
        with self.store.db() as db:
            db.execute("UPDATE message_display SET sender_name='Updated sender' WHERE message=?",(identity,))
            db.execute("UPDATE folders SET special='sent' WHERE account='one' AND folder='Archive'")
        result=cache.snapshot(self.accounts,today=self.today)
        self.assertEqual(result['sent'],1);self.assertEqual(result['items'][0]['sender_name'],'Updated sender');self.assertEqual(cache.full_loads,1)

    # ==========================================
    # Function: Slide the date window and recover safely from an expired bounded journal.
    # Method: Admit only the new day at midnight and rebuild once if revisions have actually been pruned.
    # ==========================================
    def test_midnight_slides_window_and_history_expiry_rebuilds_once(self):
        self.add();tomorrow=self.today+timedelta(days=1);self.add(day=tomorrow,mid='tomorrow')
        cache=ActivityCache(self.store);cache.snapshot(self.accounts,today=self.today)
        self.assertEqual(cache.snapshot(self.accounts,today=tomorrow)['received'],2)
        self.assertEqual(cache.full_loads,1)
        with self.store.db() as db:db.execute("UPDATE navigation_revision SET value=value+? WHERE topic='activity'",(HISTORY+1,))
        self.assertEqual(cache.snapshot(self.accounts,today=tomorrow)['received'],2)
        cache.snapshot(self.accounts,today=tomorrow);self.assertEqual(cache.full_loads,2)
