"""Local daily statistics, mailbox copy handling and metadata-only pagination."""
from contextlib import contextmanager
from datetime import date,datetime,time,timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from maildesk.store import Store
from maildesk.mail_activity import activity_snapshot,calendar_bounds


# ==========================================
# Function: Validate statistics independently of graphical libraries and real account providers.
# Method: Use real local SQLite and RFC messages with deterministic civil dates and folder mappings.
# ==========================================
class MailActivityTests(TestCase):
    # ==========================================
    # Function: Create isolated accounts and system folders for activity classification.
    # Method: Avoid profile defaults, provider connections and wall-clock-dependent message dates.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.store=Store(Path(self.temp.name)/'mail.db');self.today=date(2026,11,2);self.serial=0
        self.accounts={'one':'me@example.invalid','two':'second@example.invalid'}
        for account in self.accounts:
            self.store.save_folders(account,[{'name':name,'special':special,'delimiter':'/','flags':[],'selectable':True,'subscribed':True} for name,special in (('INBOX','inbox'),('Sent','sent'),('Archive','archive'),('All','all'),('Trash','trash'),('Spam','spam'),('Drafts','drafts'))])

    # ==========================================
    # Function: Release all temporary mailbox files after each independent regression.
    # Method: Store operations use short-lived connections, allowing deterministic directory cleanup.
    # ==========================================
    def tearDown(self):self.temp.cleanup()

    # ==========================================
    # Function: Insert one controlled mail envelope into any fixture mailbox.
    # Method: Express dates in local civil time and permit intentionally missing Message-ID values.
    # ==========================================
    def add(self,folder='INBOX',account='one',day=None,sender='peer@example.invalid',mid='message',hour=12):
        self.serial+=1;message=EmailMessage();message['From']=sender;message['To']=self.accounts[account];message['Subject']='Synthetic activity'
        if mid:message['Message-ID']='<'+mid+'@example.invalid>'
        message['Date']=format_datetime(datetime.combine(day or self.today,time(hour)).astimezone());message.set_content('A small preview.\n'*100)
        return self.store.ingest(account,folder,'1',str(self.serial),message.as_bytes())

    # ==========================================
    # Function: Count received/sent mail without drafts, junk, trash or repeated folder copies.
    # Method: Include archived mail, missing IDs and a second account's independent copy in the same day.
    # ==========================================
    def test_counts_scope_copies_and_real_archive(self):
        source=self.add();self.add('All');self.add('Archive',mid='archived')
        self.add('Sent',sender='me@example.invalid',mid='sent');self.add('Sent',sender='alias@example.invalid',mid='alias-sent')
        self.add('Drafts',mid='draft');self.add('Trash',mid='trash');self.add('Spam',mid='spam')
        self.add(mid='');self.add(mid='');self.add(account='two')
        result=activity_snapshot(self.store,self.accounts,today=self.today)
        self.assertEqual((result['received'],result['sent'],result['total']),(5,2,7))
        self.assertEqual(len(next(row['copy_ids'] for row in result['items'] if row['id']==source)),2)
        self.assertTrue(next(row['done'] for row in result['items'] if row['folder']=='Archive'))
        self.assertEqual(activity_snapshot(self.store,self.accounts,scope=('two',),today=self.today)['total'],1)
        self.assertEqual(activity_snapshot(self.store,self.accounts,scope=(),today=self.today)['total'],0)

    # ==========================================
    # Function: Keep incoming mail to another owned account distinct from its original sent copy.
    # Method: Resolve sender ownership per account rather than treating every configured address as outgoing everywhere.
    # ==========================================
    def test_account_direction_and_local_day_boundaries(self):
        self.add('Sent',sender='me@example.invalid',mid='between-accounts')
        self.add(account='two',sender='me@example.invalid',mid='between-accounts')
        self.add(day=self.today-timedelta(days=1),mid='late',hour=23)
        self.add(day=self.today,mid='early',hour=0)
        self.add(day=self.today+timedelta(days=1),mid='future',hour=0)
        result=activity_snapshot(self.store,self.accounts,today=self.today)
        self.assertEqual(result['days'][self.today.isoformat()],{'received':2,'sent':1})
        previous=activity_snapshot(self.store,self.accounts,selected=self.today-timedelta(days=1),today=self.today)
        self.assertEqual(previous['total'],1);self.assertEqual(previous['items'][0]['message_id'],'<late@example.invalid>')

    # ==========================================
    # Function: Limit only day widgets and previews while retaining complete calendar statistics.
    # Method: Trace real SQLite to ensure no raw MIME/parsed payloads are read and previews use one bounded query.
    # ==========================================
    def test_pagination_is_metadata_only_and_keeps_full_totals(self):
        for index in range(75):self.add(mid=str(index))
        queries=[];original=self.store.db

        # ==========================================
        # Function: Observe database reads without replacing any query results.
        # Method: Wrap the real connection context and restore tracing after the projection completes.
        # ==========================================
        @contextmanager
        def traced():
            with original() as db:
                db.set_trace_callback(queries.append)
                try:yield db
                finally:db.set_trace_callback(None)
        self.store.db=traced
        result=activity_snapshot(self.store,self.accounts,limit=20,today=self.today)
        self.assertEqual((result['received'],result['total'],len(result['items'])),(75,75,20))
        selects=[query.lower() for query in queries if query.lstrip().lower().startswith('select')]
        self.assertEqual(len(selects),2)
        self.assertTrue(all('raw' not in query and 'parsed' not in query for query in selects))
        self.assertTrue(all(len(row['preview'])<=160 for row in result['items']))

    # ==========================================
    # Function: Hide a locally trashed message while its duplicate All Mail location awaits remote sync.
    # Method: Keep duplicate grouping scoped to account, sender, subject and timestamp.
    # ==========================================
    def test_trash_and_missing_remote_sources_do_not_resurrect_activity(self):
        source=self.add();self.add('All');other=self.add(account='two')
        self.store.organize(source,trashed=True)
        result=activity_snapshot(self.store,self.accounts,today=self.today)
        self.assertEqual([row['id'] for row in result['items']],[other])
        with self.store.db() as db:db.execute('UPDATE messages SET remote_gone=1 WHERE id=?',(other,))
        self.assertEqual(activity_snapshot(self.store,self.accounts,today=self.today)['total'],0)

    # ==========================================
    # Function: Fit every displayed day into 53 Monday-based columns across leap years.
    # Method: Check civil-date arithmetic at month/year edges rather than assuming 365 fixed UTC days.
    # ==========================================
    def test_calendar_contains_today_and_exact_midnights(self):
        for today in (date(2024,2,29),date(2026,1,1),date(2026,11,2),date(2026,11,8)):
            start,lower,upper=calendar_bounds(today)
            self.assertEqual(start.weekday(),0);self.assertLess((today-start).days,371)
            self.assertEqual(datetime.fromtimestamp(lower).date(),start)
            self.assertEqual(datetime.fromtimestamp(upper).date(),today+timedelta(days=1))
