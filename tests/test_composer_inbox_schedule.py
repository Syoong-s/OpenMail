"""Local Spark-style inbox/editor/scheduling behavior without real provider access."""
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage,Message
from email.parser import BytesParser
from email import policy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from maildesk.config import Account
from maildesk.service import MailService
from maildesk.store import Store
from maildesk.inbox_views import InboxViews
from maildesk.scheduling import preset_time,schedule_timestamp
from maildesk.composer_options import outgoing_options,validated_addresses,render_template,rule_sender,recipient_suggestions,recipient_token_start
from maildesk.mime import compose

# ==========================================
# Function: Exercise durable queue, filtering and outgoing-message policies end to end.
# Method: Use real SQLite/MIME with mocked SMTP acceptance and explicit clock boundaries.
# ==========================================
class ComposerInboxTests(unittest.TestCase):
    # ==========================================
    # Function: Prepare an isolated service and validated synthetic account.
    # Method: Keep all account and mail data inside a temporary native Linux directory.
    # ==========================================
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        self.account=Account('test','you@example.com','imap.example.com','smtp.example.com')
        self.service=MailService(self.path,[self.account]);self.store=self.service.store

    # ==========================================
    # Function: Remove only temporary synthetic mailbox state.
    # Method: Ensure every SQLite context has closed before cleanup.
    # ==========================================
    def tearDown(self):self.temp.cleanup()

    # ==========================================
    # Function: Ingest a realistic small message with stable IDs and optional headers.
    # Method: Exercise normal MIME decoding and account-scoped cache generation keys.
    # ==========================================
    def mail(self,uid,sender='person@example.com',headers='',body='hello',account='test'):
        raw=(f'From: {sender}\r\nTo: you@example.com\r\nSubject: Mail {uid}\r\nMessage-ID: <{uid}@local>\r\n'+headers+'\r\n'+body).encode()
        return self.store.ingest(account,'INBOX','1',str(uid),raw)

    # ==========================================
    # Function: Resolve local send-later preset dates and reject invalid schedule boundaries.
    # Method: Compare fixed calendar values, expired times and timezone-aware timestamps.
    # ==========================================
    def test_calendar_presets_and_validation(self):
        now=datetime(2026,10,19,21,0)
        self.assertEqual(preset_time('tomorrow',self.store,now),datetime(2026,10,20,9))
        self.assertEqual(preset_time('tonight',self.store,now),datetime(2026,10,20,20))
        self.assertEqual(preset_time('weekend',self.store,now),datetime(2026,10,24,9))
        self.store.set_preference('schedule_morning','10:30')
        self.assertEqual(preset_time('next_week',self.store,now),datetime(2026,10,26,10,30))
        value=datetime(2030,1,1,tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(schedule_timestamp(value,now=value.timestamp()-3600),value.timestamp())
        with self.assertRaises(ValueError):schedule_timestamp(value,now=value.timestamp()+1)
        with self.assertRaises(ValueError):schedule_timestamp(value,now=value.timestamp()-367*86400)

    # ==========================================
    # Function: Keep queued MIME identity across reschedule/restart and prevent replay after claim.
    # Method: Compare actual stored bytes and exercise compare-and-update state guards.
    # ==========================================
    def test_reschedule_now_cancel_and_restart(self):
        job=self.service.compose({'account':'test','to':'friend@example.com','body':'future','due':time.time()+3600},True)['id']
        with self.store.db() as db:raw=bytes(db.execute('SELECT raw FROM jobs WHERE id=?',(job,)).fetchone()[0])
        self.assertIsNone(self.store.claim())
        self.service.reschedule(job,time.time()+7200)
        restarted=Store(self.store.path);self.assertEqual(restarted.job(job)['state'],'queued')
        restarted.reschedule(job,time.time());claimed=restarted.claim();self.assertEqual(claimed['raw'],raw)
        with self.assertRaises(ValueError):restarted.reschedule(job,time.time()+1)
        another=self.service.compose({'account':'test','to':'friend@example.com','body':'cancel','due':time.time()+3600},True)['id']
        self.store.cancel(another);self.assertEqual(self.store.job(another)['state'],'draft')

    # ==========================================
    # Function: Recover overdue persisted delivery after a closed-client interval exactly once.
    # Method: Advance the claim clock and simulate confirmed SMTP without live email delivery.
    # ==========================================
    def test_overdue_job_delivered_once(self):
        now=time.time();job=self.service.compose({'account':'test','to':'friend@example.com','body':'later','due':now+3600},True)['id']
        restarted=MailService(self.path,[self.account])
        with patch('maildesk.store.time.time',return_value=now+7200),patch('maildesk.transport.deliver',return_value={}) as send,patch('maildesk.transport.append_sent',return_value='local'):
            self.assertTrue(restarted.process_one());self.assertFalse(restarted.process_one());send.assert_called_once()
        self.assertEqual(restarted.store.job(job)['state'],'sent')

    # ==========================================
    # Function: Apply account-scoped copy/receipt policies without exposing BCC in MIME headers.
    # Method: Inspect the real MIME bytes and envelope, including recipient deduplication.
    # ==========================================
    def test_copy_bcc_receipt_and_tagline(self):
        self.store.set_preference('auto_copy',{'test':{'enabled':True,'mode':'bcc','addresses':'copy@example.com, friend@example.com'}})
        self.store.set_preference('request_receipt',True);self.store.set_preference('composer_tagline',True)
        job=self.service.compose({'account':'test','to':'friend@example.com','body':'text'},True)['id']
        with self.store.db() as db:row=db.execute('SELECT raw,envelope FROM jobs WHERE id=?',(job,)).fetchone()
        mail=BytesParser(policy=policy.default).parsebytes(row['raw'])
        self.assertIsNone(mail['Bcc']);self.assertEqual(json.loads(row['envelope']),['friend@example.com','copy@example.com'])
        self.assertEqual(str(mail['Disposition-Notification-To']),'you@example.com')
        self.assertIn('Sent with TeleMail',mail.get_body(preferencelist=('plain',)).get_content())
        with self.assertRaises(ValueError):validated_addresses('invalid, friend@example.com')

    # ==========================================
    # Function: Mark replied conversations complete only after confirmed full SMTP acceptance.
    # Method: Compare successful versus uncertain outcomes using the same service path.
    # ==========================================
    def test_done_after_reply_only_on_success(self):
        source=self.mail('original');self.store.set_preference('done_after_reply',True)
        self.service.compose({'account':'test','to':'friend@example.com','body':'reply','reply_source':source},True)
        from maildesk.transport import DeliveryError
        with patch('maildesk.transport.deliver',side_effect=DeliveryError('uncertain',uncertain=True)):
            self.service.process_one()
        self.assertFalse(self.store.get(source)['done'])
        self.service.compose({'account':'test','to':'friend@example.com','body':'reply again','reply_source':source},True)
        with patch('maildesk.transport.deliver',return_value={}),patch('maildesk.transport.append_sent',return_value='local'):
            self.service.process_one()
        self.assertTrue(self.store.get(source)['done'])

    # ==========================================
    # Function: Stop an outgoing follow-up reminder after a real reply references the sent mail.
    # Method: Create a sent copy with a deadline then ingest an actual referenced response.
    # ==========================================
    def test_followup_clears_on_reply(self):
        job=self.service.compose({'account':'test','to':'friend@example.com','body':'question','remind_at':time.time()+86400},True)['id']
        with patch('maildesk.transport.deliver',return_value={}),patch('maildesk.transport.append_sent',return_value='local'):self.service.process_one()
        sent=self.store.list_messages(view='sent')['items'][0];message=self.store.get(sent['id'])
        self.assertGreater(message['reminder'],time.time())
        self.mail('reply',headers='In-Reply-To: '+message['parsed']['message_id']+'\r\n')
        self.assertEqual(self.store.get(sent['id'])['reminder'],0)

    # ==========================================
    # Function: Correlate only requested displayed MDNs from the intended envelope recipient.
    # Method: Ingest real multipart/report MIME and reject mismatched account/sender/state cases.
    # ==========================================
    def test_read_receipt_correlation(self):
        self.store.set_preference('request_receipt',True)
        job=self.service.compose({'account':'test','to':'friend@example.com','body':'receipt','remind_at':time.time()+86400},True)['id']
        with patch('maildesk.transport.deliver',return_value={}),patch('maildesk.transport.append_sent',return_value='local'):self.service.process_one()
        with self.store.db() as db:message_id=db.execute('SELECT message_id FROM jobs WHERE id=?',(job,)).fetchone()[0]
        report=EmailMessage();report['From']='friend@example.com';report['To']='you@example.com';report.set_type('multipart/report');report.set_param('report-type','disposition-notification')
        text=EmailMessage();text.set_content('Displayed receipt');report.attach(text)
        part=Message();part.set_type('message/disposition-notification');fields=Message()
        fields['Original-Message-ID']=message_id;fields['Final-Recipient']='rfc822; friend@example.com';fields['Disposition']='manual-action/MDN-sent-manually; displayed'
        part.set_payload([fields]);report.attach(part)
        self.store.ingest('other','INBOX','1','mdn-other',report.as_bytes());self.assertEqual(self.store.job(job)['receipts'],0)
        self.store.ingest('test','INBOX','1','mdn',report.as_bytes());self.assertEqual(self.store.job(job)['receipts'],1)
        self.store.ingest('test','INBOX','1','mdn-duplicate',report.as_bytes());self.assertEqual(self.store.job(job)['receipts'],1)
        sent=self.store.list_messages(view='sent')['items'][0];self.assertGreater(self.store.get(sent['id'])['reminder'],0)

    # ==========================================
    # Function: Honor all Gatekeeper modes while retaining explicit blocks and account scope.
    # Method: Compare actual inbox/new-sender queries around accept/domain/block decisions.
    # ==========================================
    def test_gatekeeper_modes_and_scoping(self):
        first=self.mail('new');other=self.mail('other',account='other')
        self.store.set_preference('gatekeeper_mode','explicit');self.assertEqual(self.store.list_messages(view='inbox')['total'],0)
        self.assertEqual(self.store.list_messages(view='new_senders')['total'],2)
        self.store.organize(first,sender_policy='domain:accepted')
        self.assertEqual([r['id'] for r in self.store.list_messages(view='inbox')['items']],[first])
        self.store.set_preference('gatekeeper_mode','inThread');self.assertEqual(self.store.list_messages(view='inbox')['total'],2)
        self.store.organize(first,sender_policy='blocked');self.store.set_preference('gatekeeper_mode','off')
        self.assertEqual([r['id'] for r in self.store.list_messages(view='inbox')['items']],[other])

    # ==========================================
    # Function: Keep sender priority independent of blocking and apply a visible inbox limit.
    # Method: Group effective SQL priorities and verify toggles never destroy saved decisions.
    # ==========================================
    def test_priority_people_limit_and_disable(self):
        ids=[self.mail(str(i)) for i in range(6)];self.store.set_priority_sender('test','@example.com')
        items=self.store.list_messages(view='inbox')['items'];self.assertTrue(all(row['priority'] for row in items))
        views=InboxViews(self.store);self.store.set_preference('priority_limit',3)
        group=next(row for row in views.sections(items) if row['key']=='priority');self.assertEqual(len(group['shown']),3)
        self.store.set_preference('priority_enabled',False);self.assertFalse(any(row['key']=='priority' for row in views.sections(items)))
        self.store.organize(ids[0],sender_policy='blocked');self.assertEqual(self.store.list_messages(view='inbox')['total'],0)
        self.store.set_priority_sender('test','@example.com',False);self.assertEqual(self.store.priority_senders('test'),[])

    # ==========================================
    # Function: Use explainable classification with account/domain corrections and an off mode.
    # Method: Reclassify actual stored messages while preserving explicit per-message overrides.
    # ==========================================
    def test_recognition_rules_and_off(self):
        identity=self.mail('newsletter',headers='List-ID: list.example.com\r\n')
        self.assertEqual(self.store.get(identity)['category'],'newsletter')
        self.store.set_preference('recognition_enabled',False);self.store.reclassify()
        self.assertEqual(self.store.get(identity)['category'],'personal')
        self.store.category_rule('test','@example.com','notification');self.store.reclassify()
        self.assertEqual(self.store.get(identity)['category'],'notification')
        self.store.update(identity,{'category':'newsletter'});self.store.category_rule('test','@example.com','personal');self.store.reclassify()
        self.assertEqual(self.store.get(identity)['category'],'newsletter')

    # ==========================================
    # Function: Apply sender grouping or ungrouping independently for subscriptions.
    # Method: Keep every underlying message exactly once in each resulting layout projection.
    # ==========================================
    def test_grouping_options(self):
        self.mail('one','one@example.com','List-ID: a\r\n');self.mail('two','two@example.com','List-ID: a\r\n')
        views=InboxViews(self.store);items=self.store.list_messages()['items']
        self.store.set_preference('group_newsletter','sender');self.assertEqual(len(views.sections(items)),2)
        self.store.set_preference('group_newsletter','none');sections=views.sections(items)
        self.assertEqual(len(sections),1);self.assertEqual(sum(len(row['items']) for row in sections),2)

    # ==========================================
    # Function: Preserve reusable template identity/order and safely substitute variables.
    # Method: Duplicate independent text, reorder IDs and leave executable-looking placeholders inert.
    # ==========================================
    def test_templates_duplicate_order_and_variables(self):
        first=self.store.save_template('A','Hello {{name}}','Date {{date}}, {{custom}}')
        second=self.store.arrange_template(first,'duplicate');self.assertNotEqual(first,second)
        self.store.arrange_template(second,'up');self.assertEqual(self.store.templates()[0]['id'],second)
        result,missing=render_template(self.store.templates()[0],{'name':'同学','date':'2026-10-19'})
        self.assertEqual(missing,['custom']);self.assertEqual(result['subject'],'Hello 同学')
        result,missing=render_template({'body':'{{__import__("os")}} {{custom}}'},{'custom':'<literal>'})
        self.assertIn('__import__',result['body']);self.assertIn('<literal>',result['body'])

    # ==========================================
    # Function: Match display-name rules through a shared canonical sender key.
    # Method: Compare actual sender/domain priority and classification with strict invalid-input rejection.
    # ==========================================
    def test_rule_identity_normalization(self):
        identity=self.mail('canonical','alice@example.com')
        self.store.set_priority_sender('test','Alice <ALICE@example.com>')
        self.assertEqual(self.store.priority_senders('test'),['alice@example.com'])
        self.assertTrue(self.store.list_messages()['items'][0]['priority'])
        self.store.category_rule('test','Alice <alice@example.com>','newsletter');self.store.reclassify()
        self.assertEqual(self.store.get(identity)['category'],'newsletter')
        self.assertEqual(rule_sender('Alice <ALICE@example.com>'),'alice@example.com')
        for invalid in ('@bad..com','@-bad.com','@bad.com/path','a@example.com,b@example.com','@bad.com\n'):
            with self.assertRaises(ValueError):rule_sender(invalid)

    # ==========================================
    # Function: Keep recipient display names valid for MIME and completion token replacement.
    # Method: Round-trip commas, quotes and Unicode contacts through the actual composer.
    # ==========================================
    def test_completion_quoted_display_names(self):
        self.store.set_preference('contacts',{'john@example.com':'Doe, John','friend@example.com':'张 "同学"'})
        for address,text in recipient_suggestions(self.store):
            raw,envelope=compose(self.account,{'to':text,'body':'hello'})
            self.assertEqual(envelope,[address])
        value='"Doe, John" <john@example.com>, 张'
        self.assertEqual(value[recipient_token_start(value):].strip(),'张')
        self.assertEqual(recipient_token_start('"Doe, J'),0)
        self.assertEqual('"Doe, John" <john@example.com>'[recipient_token_start('"Doe, John" <john@example.com>'):],'"Doe, John" <john@example.com>')

    # ==========================================
    # Function: Notify sender/domain priority through the same projection used by inbox rows.
    # Method: Invoke real notification filtering with a disposable store and inert desktop facade.
    # ==========================================
    def test_priority_sender_notifications(self):
        from types import SimpleNamespace
        from maildesk.desktop_organization import OrganizationUI
        notices=[];self.store.set_preference('notify_priority_only',True)
        app=SimpleNamespace(service=self.service,known_messages=set(),notify=lambda *args:notices.append(args),refresh=lambda:None)
        identity=self.mail('priority-notice');self.store.set_priority_sender('test','@example.com')
        self.assertTrue(self.store.get(identity)['effective_priority'])
        OrganizationUI.check_notifications(app);self.assertEqual(len(notices),1)
        notices.clear();self.mail('ordinary','other@ordinary.com');OrganizationUI.check_notifications(app)
        self.assertEqual(notices,[])

if __name__=='__main__':unittest.main()
