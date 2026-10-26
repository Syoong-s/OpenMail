"""Global/account filing, durable once-only delivery, previews and local learning regressions."""
from datetime import datetime,timezone
from email.message import EmailMessage
from pathlib import Path
from tempfile import TemporaryDirectory
import json,threading,time,unittest
from unittest.mock import patch
from maildesk import filter_rules as rules,filter_runner as runner,filter_smart as smart,transport,address_book
from maildesk.config import Account
from maildesk.filter_match import first_match
from maildesk.service import MailService
from maildesk.store import Store
from test_sync_performance import Provider,Session

# ==========================================
# Function: Verify real cache/service filtering while isolating every provider and user profile.
# Method: Use synthetic MIME, UID-shaped provider sessions and persistent SQLite transactions throughout.
# ==========================================
class FilterTests(unittest.TestCase):
    # ==========================================
    # Function: Seed selectable folders on two accounts and an independent local mailbox.
    # Method: Construct an actual service without starting its network worker.
    # ==========================================
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name);self.account=Account('test','me@example.invalid','imap.invalid','smtp.invalid');self.other=Account('other','other@example.invalid','imap.invalid','smtp.invalid');self.service=MailService(self.root,[self.account,self.other]);self.store=self.service.store;self.serial=0;self.store.set_preference('mail_retention_enabled',False)
        for account in ('test','other'):
            self.store.save_folders(account,[{'name':path,'delimiter':'/','selectable':True,'special':'inbox' if path=='INBOX' else ''} for path in ('INBOX','Work','Work/Child','Workshop','Archive','Other')])
        self.network_guard=patch('maildesk.transport.imap_connection',side_effect=AssertionError('Live provider access forbidden in filter tests'));self.network_guard.start()
    # ==========================================
    # Function: Remove isolated data after every bounded offline test.
    # Method: Stop the unstarted service and close all short-lived Store connections first.
    # ==========================================
    def tearDown(self):self.service.close();self.network_guard.stop();self.temp.cleanup()
    # ==========================================
    # Function: Produce a source with controllable address, MIME/header and RFC identity evidence.
    # Method: Ingest actual email bytes so headers, contact stars, references and attachment matching use production models.
    # ==========================================
    def mail(self,folder='INBOX',account='test',subject='Project report',body='Ordinary personal project discussion',sender='person@example.invalid',headers=None,attachment=None,message_id=None,uid=None,received_at=None):
        self.serial+=1;mail=EmailMessage();mail['From']=sender;mail['To']='Me <me@example.invalid>';mail['Cc']='team@example.invalid';mail['Subject']=subject;mail['Date']=datetime.now(timezone.utc);mail['Message-ID']=message_id or '<filter-'+str(self.serial)+'@example.invalid>'
        for key,value in (headers or {}).items():mail[key]=value
        mail.set_content(body)
        if attachment:mail.add_attachment(b'fixture',maintype='application',subtype='pdf',filename=attachment)
        return self.store.ingest(account,folder,'77',uid or str(self.serial),mail.as_bytes(),_received_at=time.time() if received_at is None else received_at)
    # ==========================================
    # Function: Save one minimally scoped configurable rule for a test.
    # Method: Use the same production validator and durable order as the native editor.
    # ==========================================
    def rule(self,**changes):
        value={'name':'Project filing','account':'','enabled':True,'mode':'all','conditions':[{'field':'subject','op':'contains','value':'project'}],'source_mode':'all','sources':{},'subfolders':False,'destinations':{'test':'Archive','other':'Other'}};value.update(changes);identity=rules.save(self.store,value);return next(rule for rule in rules.rules(self.store) if rule['id']==identity)
    # ==========================================
    # Function: Respect accepted account-first/global-fallback and first-match order.
    # Method: Match identical content on two accounts, reorder account rules and disable an earlier winner.
    # ==========================================
    def test_account_precedence_order_and_global_destinations(self):
        global_rule=self.rule();specific=self.rule(account='test',destinations={'test':'Other'});later=self.rule(account='test',destinations={'test':'Work'});identity=self.mail();other=self.mail(account='other')
        self.assertEqual(first_match(runner.source(self.store,identity),rules.rules(self.store),runner.context(self.store))['rule'],specific['id'])
        self.assertEqual(first_match(runner.source(self.store,other),rules.rules(self.store),runner.context(self.store))['destination'],'Other')
        rules.arrange(self.store,later['id'],'up');self.assertEqual(self.service.preview_filters('test')['entries'][0]['rule'],later['id'])
        rules.save(self.store,later|{'enabled':False});rules.save(self.store,specific|{'enabled':False});self.assertEqual(self.service.preview_filters('test')['entries'][0]['rule'],global_rule['id'])
    # ==========================================
    # Function: Make all/any text conditions multilingual and address-aware rather than display-name substring guesses.
    # Method: Combine NFKC case folding, wildcards, parsed recipients and exact sender domains.
    # ==========================================
    def test_conditions_any_all_unicode_addresses_and_globs(self):
        identity=self.mail(subject='ＰＲＯＪＥＣＴ 财务',sender='Example <PERSON@Example.Invalid>');conditions=[{'field':'domain','op':'is','value':'example.invalid'},{'field':'subject','op':'matches','value':'project*财务'},{'field':'to','op':'is','value':'me@example.invalid'},{'field':'cc','op':'contains','value':'team@'}];rule=self.rule(conditions=conditions)
        self.assertEqual(len(self.service.preview_filters('test')['entries']),1)
        rules.save(self.store,rule|{'conditions':conditions+[{'field':'body','op':'contains','value':'missing'}]});self.assertFalse(self.service.preview_filters('test')['entries'])
        rules.save(self.store,rule|{'mode':'any','conditions':[{'field':'body','op':'contains','value':'missing'},conditions[0]]});self.assertEqual(len(self.service.preview_filters('test')['entries']),1)
    # ==========================================
    # Function: Include/exclude real descendants without confusing similarly prefixed sibling names.
    # Method: Evaluate Work, Work/Child and Workshop against an explicit account-relative source list.
    # ==========================================
    def test_source_folder_scopes_and_descendants(self):
        a=self.mail(folder='Work');b=self.mail(folder='Work/Child');c=self.mail(folder='Workshop');rule=self.rule(source_mode='include',sources={'test':['Work']},subfolders=True)
        self.assertEqual({entry['id'] for entry in self.service.preview_filters('test')['entries']},{a,b})
        rules.save(self.store,rule|{'source_mode':'exclude'});self.assertEqual([entry['id'] for entry in self.service.preview_filters('test')['entries']],[c])
        self.assertEqual({entry['id'] for entry in self.service.preview_filters('test','Work',True)['entries']},set())
    # ==========================================
    # Function: Match headers, actual attachment metadata, stars and bounded numeric sizes together.
    # Method: Use real parsed MIME plus a durable person star, then remove the star to change the result.
    # ==========================================
    def test_headers_attachments_size_state_and_starred_contacts(self):
        identity=self.mail(headers={'List-Id':'project.example.invalid'},attachment='invoice.pdf');person=address_book.sender_detail(self.store,'person@example.invalid')['id'];address_book.star_many(self.store,[person],True)
        conditions=[{'field':'header','header':'List-Id','op':'contains','value':'project'},{'field':'attachment_name','op':'matches','value':'*.pdf'},{'field':'attachment_type','op':'is','value':'application/pdf'},{'field':'has_attachment','op':'is','value':'true'},{'field':'seen','op':'is','value':'false'},{'field':'size_kb','op':'gt','value':'0'},{'field':'starred_contact','op':'is','value':'true'}]
        self.rule(conditions=conditions);self.assertEqual(len(self.service.preview_filters('test')['entries']),1);address_book.star_many(self.store,[person],False);self.assertFalse(self.service.preview_filters('test')['entries'])
    # ==========================================
    # Function: Recognize standard subscription/automatic/calendar cues and existing verification evidence.
    # Method: Require explicit message/header signals and avoid describing invoice notifications as ordinary personal mail.
    # ==========================================
    def test_explainable_smart_types(self):
        invoice=runner.source(self.store,self.mail(subject='电子发票 Invoice 2026'));calendar=runner.source(self.store,self.mail(subject='Meeting',attachment='invite.ics'));reply=runner.source(self.store,self.mail(headers={'Auto-Submitted':'auto-replied'}));newsletter=runner.source(self.store,self.mail(headers={'List-Unsubscribe':'<mailto:leave@example.invalid>'}))
        self.assertIn('invoice',smart.recognize(invoice));self.assertNotIn('personal',smart.recognize(invoice));self.assertIn('calendar',smart.recognize(calendar));self.assertIn('auto_reply',smart.recognize(reply));self.assertIn('newsletter',smart.recognize(newsletter))
    # ==========================================
    # Function: Reject unsafe/empty/cross-account rule structures before saving any mutation.
    # Method: Try unsupported operators, invalid header names, broad empty source selections and foreign target mappings.
    # ==========================================
    def test_rule_validation_boundaries(self):
        rule=self.rule()
        for value in (rule|{'conditions':[]},rule|{'destinations':{}},rule|{'account':'test'},rule|{'source_mode':'include','sources':{}},rule|{'conditions':[{'field':'header','header':'x\r\nbad','op':'contains','value':'x'}]},rule|{'conditions':[{'field':'subject','op':'regex','value':'(a+)+$'}]}):
            with self.subTest(value=value),self.assertRaises(ValueError):rules.save(self.store,value)
        with self.assertRaises(ValueError):self.service.save_filter(rule|{'destinations':{'test':'Missing'}})
    # ==========================================
    # Function: Keep first-seen mailbox contents historical and admit later arrivals in any folder only once.
    # Method: Set a fixed baseline then ingest post-boundary sources, duplicates and an independent account copy.
    # ==========================================
    def test_arrival_baseline_any_folder_and_logical_identity(self):
        rules.baseline(self.store,'test','Work','77',['1','5']);self.mail(folder='Work',uid='4');fresh=self.mail(folder='Work',uid='6',message_id='<new@fixture>');self.mail(folder='Other',uid='8',message_id='<new@fixture>');rules.baseline(self.store,'other','Work','77',[]);second=self.mail(folder='Work',account='other',uid='6',message_id='<new@fixture>')
        with self.store.db() as db:self.assertEqual({row[0] for row in db.execute('SELECT message FROM mail_filter_queue')},{fresh,second})
        rules.baseline(self.store,'test','Work','77',['1','5','6','9']);later=self.mail(folder='Work',uid='7')
        with self.store.db() as db:self.assertTrue(db.execute('SELECT 1 FROM mail_filter_queue WHERE message=?',(later,)).fetchone())
    # ==========================================
    # Function: Reset only the physical UID baseline when the server changes generation.
    # Method: Preserve logical once-only decisions and leave the new generation's initial snapshot historical.
    # ==========================================
    def test_uidvalidity_reset_does_not_refilter_history(self):
        rules.baseline(self.store,'test','Work','77',[]);identity=self.mail(folder='Work',message_id='<same@fixture>');raw=self.store.get(identity,raw=True)['raw'];rules.baseline(self.store,'test','Work','88',['1','2'])
        self.store.ingest('test','Work','88','2',raw)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM mail_filter_queue').fetchone()[0],1)
    # ==========================================
    # Function: Persist unprocessed arrivals across restart and refuse automatic replay after an uncertain remote move.
    # Method: Reopen queued state first, then simulate a crash after the durable moving marker.
    # ==========================================
    def test_restart_preserves_queue_but_quarantines_inflight_move(self):
        rules.baseline(self.store,'test','Work','77',[]);identity=self.mail(folder='Work');reopened=Store(self.store.path)
        with reopened.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM mail_filter_queue').fetchone()[0],1)
        message=runner.source(self.store,identity);runner.finish(self.store,message,{'rule':'rule','destination':'Archive'},'moving','fixture interruption');reopened=Store(self.store.path)
        with reopened.db() as db:
            self.assertEqual(db.execute('SELECT state FROM mail_filter_seen WHERE account=? AND message_id=?',('test',message['message_id'])).fetchone()[0],'uncertain');self.assertEqual(db.execute('SELECT count(*) FROM mail_filter_queue').fetchone()[0],0)
    # ==========================================
    # Function: Keep previews network-free and manual runs limited to their exact reviewed sources.
    # Method: Preview historical sources in Work, add another source afterwards and execute only the prepared IDs.
    # ==========================================
    def test_manual_preview_historical_folder_scope_and_snapshot(self):
        a=self.mail(folder='Work');self.mail(folder='Work/Child');self.mail(folder='Workshop');self.rule();provider=Provider(0)
        with patch('maildesk.transport.imap_connection',side_effect=AssertionError('preview must be local')):plan=self.service.preview_filters('test','Work')
        self.assertEqual([entry['id'] for entry in plan['entries']],[a]);new=self.mail(folder='Work')
        with patch('maildesk.transport.imap_connection',provider.connection),patch('maildesk.filter_runner.execute',return_value=('moved','fixture')) as move:result=self.service.run_filter_plan(plan)
        self.assertEqual(result['moved'],1);self.assertEqual(move.call_args.args[1]['id'],a);self.assertNotEqual(move.call_args.args[1]['id'],new)
    # ==========================================
    # Function: Invalidate old previews after rule reorder/edit or model changes.
    # Method: Compare durable fingerprints before making any provider connection.
    # ==========================================
    def test_preview_revision_guard(self):
        self.mail();rule=self.rule();plan=self.service.preview_filters('test');rules.save(self.store,rule|{'name':'Changed'})
        with patch('maildesk.transport.imap_connection',side_effect=AssertionError('must reject before network')),self.assertRaisesRegex(ValueError,'重新预览'):self.service.run_filter_plan(plan)
    # ==========================================
    # Function: Use the same first-match semantics when manually selecting a particular rule.
    # Method: A selected global fallback cannot override a matching higher-priority account rule.
    # ==========================================
    def test_selected_manual_rule_respects_account_precedence(self):
        self.mail();global_rule=self.rule();self.rule(account='test',destinations={'test':'Other'});self.assertFalse(self.service.preview_filters('test',rule_id=global_rule['id'])['entries'])
    # ==========================================
    # Function: Preserve exact per-account rule paths when folders move within a hierarchy.
    # Method: Rename Work only on one account, including children but not Workshop or the same path elsewhere.
    # ==========================================
    def test_folder_rename_rewrites_rules_at_delimiter_boundaries(self):
        rule=self.rule(destinations={'test':'Work/Child','other':'Work'},source_mode='include',sources={'test':['Work','Workshop'],'other':['Work']});self.store.rename_folder('test','Work','Projects','/')
        current=next(item for item in rules.rules(self.store) if item['id']==rule['id']);self.assertEqual(current['destinations'],{'test':'Projects/Child','other':'Work'});self.assertEqual(current['sources'],{'test':['Projects','Workshop'],'other':['Work']})
    # ==========================================
    # Function: Require explicit adequate training samples and retain model isolation by account and destination.
    # Method: Train invoice examples against personal chat, score new content and invalidate only a changed target's model.
    # ==========================================
    def test_local_bayesian_training_and_destination_invalidation(self):
        rule=self.rule(conditions=[{'field':'learned','op':'gte','value':'95'}])
        with self.assertRaisesRegex(ValueError,'至少'):self.service.train_filter(rule['id'],'test')
        for index in range(8):
            self.mail(folder='Archive',subject='Invoice billing payment receipt '+str(index),body='Finance statement tax invoice paid amount monthly',sender='billing@finance.example.invalid')
            self.mail(folder='Other',subject='Family dinner weekend '+str(index),body='Hello friend lunch birthday hiking garden',sender='friend@family.example.invalid')
        result=self.service.train_filter(rule['id'],'test');self.assertEqual((result['positive'],result['negative']),(8,8));ctx=runner.context(self.store);model=ctx['models'][(rule['id'],'test')]
        positive=runner.source(self.store,self.mail(subject='Invoice billing payment receipt',body='Finance statement tax invoice paid amount monthly',sender='billing@finance.example.invalid'));negative=runner.source(self.store,self.mail(subject='Family dinner weekend',body='Hello friend lunch birthday hiking garden',sender='friend@family.example.invalid'))
        self.assertGreater(smart.score(model,positive),95);self.assertLess(smart.score(model,negative),5);self.assertIsNone(ctx['models'].get((rule['id'],'other')))
        rules.save(self.store,rule|{'destinations':{'test':'Other','other':'Other'}});self.assertFalse(runner.context(self.store)['models'])
    # ==========================================
    # Function: Execute automatic folder rules once and never cascade destination copies into an inverse rule.
    # Method: Sync an empty baseline, receive mail in Work, then resync its moved Archive copy twice.
    # ==========================================
    def test_sync_auto_filters_new_folder_arrivals_once_without_loop(self):
        provider=Provider(0);provider.boxes['Work']={};self.rule(account='test',destinations={'test':'Archive'},source_mode='include',sources={'test':['Work']});self.rule(account='test',destinations={'test':'Work'},source_mode='include',sources={'test':['Archive']})
        with patch('maildesk.transport.imap_connection',provider.connection):
            transport.sync_account(self.account,self.store);identity=self.mail(folder='Other',subject='Project new delivery');raw=self.store.get(identity,raw=True)['raw']
            # This raw fixture identity must not have been observed on this account before delivery.
            raw=raw.replace(b'Message-ID: <filter-',b'Message-ID: <arrival-');provider.boxes['Work']['1']={'raw':raw,'flags':set()};result=transport.sync_account(self.account,self.store);self.assertEqual(result['filters']['moved'],1);transport.sync_account(self.account,self.store);transport.sync_account(self.account,self.store)
        self.assertEqual(len(provider.boxes['Archive']),1);self.assertFalse(provider.boxes['Work']);self.assertEqual(sum(row[0]=='MOVE' for row in provider.commands),1)
    # ==========================================
    # Function: Leave initial received cache/history alone even when an enabled rule would match it.
    # Method: Discover a populated first snapshot and then verify a later source alone is eligible.
    # ==========================================
    def test_first_enable_history_only_manual(self):
        provider=Provider(2);self.rule(conditions=[{'field':'subject','op':'contains','value':'fixture'}])
        with patch('maildesk.transport.imap_connection',provider.connection):result=transport.sync_account(self.account,self.store)
        self.assertEqual(result['filters']['moved'],0);self.assertEqual(len(provider.boxes['INBOX']),2);self.assertEqual(len(self.service.preview_filters('test','INBOX')['entries']),2)
    # ==========================================
    # Function: Do not automatically replay a MOVE whose response was lost.
    # Method: Raise after a synthetic provider mutation boundary and verify both restart and subsequent polls retain the ambiguity guard.
    # ==========================================
    def test_ambiguous_move_is_logged_and_not_replayed(self):
        provider=Provider(0);self.rule(conditions=[{'field':'subject','op':'contains','value':'project'}]);rules.baseline(self.store,'test','INBOX','77',[]);identity=self.mail();message=runner.source(self.store,identity);provider.boxes['INBOX'][message['uid']]={'raw':self.store.get(identity,raw=True)['raw'],'flags':set()}
        with patch('maildesk.folders.transfer_selected',side_effect=OSError('lost response')) as move:
            result=runner.automatic(self.account,self.store,Session(provider));self.assertEqual(result['failed'],1);runner.automatic(self.account,self.store,Session(provider));self.assertEqual(move.call_count,1)
        self.assertEqual(self.service.preview_filters('test')['uncertain'],1)
    # ==========================================
    # Function: Keep a failed destination from falling through to a different global filing rule.
    # Method: Remove an account rule's target after saving and assert failure is recorded with no cloud mutation.
    # ==========================================
    def test_missing_destination_stops_fallback_and_can_manual_retry(self):
        self.rule(account='test',destinations={'test':'Work'});self.rule();rules.baseline(self.store,'test','INBOX','77',[]);self.mail();self.store.remove_folder('test','Work');provider=Provider(0)
        with patch('maildesk.folders.transfer_selected') as move:result=runner.automatic(self.account,self.store,Session(provider))
        self.assertEqual(result['failed'],1);move.assert_not_called()
        with self.store.db() as db:self.assertEqual(db.execute("SELECT count(*) FROM mail_filter_seen WHERE state='failed'").fetchone()[0],1)
    # ==========================================
    # Function: Keep no-rule automatic handling cheap while still remembering that the arrival was evaluated once.
    # Method: Drain queued metadata without parsing source bodies, then add a rule and verify it does not retroactively enqueue.
    # ==========================================
    def test_no_rules_drains_metadata_without_retroactive_matching(self):
        rules.baseline(self.store,'test','Work','77',[]);self.mail(folder='Work')
        with patch('maildesk.filter_runner.source',side_effect=AssertionError('no body read')):result=runner.automatic(self.account,self.store,None)
        self.assertEqual(result['processed'],1);self.rule();self.assertEqual(runner.automatic(self.account,self.store,None)['processed'],0)

    # ==========================================
    # Function: Honor cancellation received while a manual run is still waiting behind another user operation.
    # Method: Hold the operation gate, cancel the queued run and require completion without opening a provider connection.
    # ==========================================
    def test_cancel_while_waiting_never_opens_connection(self):
        self.mail();self.rule();plan=self.service.preview_filters('test');results=[];errors=[]
        # ==========================================
        # Function: Run the real manual service under the test's default hard provider guard.
        # Method: Capture cancellation and errors after the foreground gate is released.
        # ==========================================
        def run():
            try:results.append(self.service.run_filter_plan(plan))
            except Exception as error:errors.append(error)
        with self.service.lock:
            worker=threading.Thread(target=run);worker.start();deadline=time.monotonic()+2
            while not self.service.status.get('filters',{}).get('running') and time.monotonic()<deadline:time.sleep(.001)
            self.assertTrue(self.service.status['filters']['running']);self.service.filter_cancel_event.set()
        worker.join(2);self.assertFalse(worker.is_alive());self.assertFalse(errors,errors);self.assertTrue(results[0]['cancelled']);self.assertEqual(results[0]['moved'],0)

    # ==========================================
    # Function: Release an ambiguous logical filter guard after an explicitly confirmed ordinary move.
    # Method: Let the user resolve the source through the existing UID-safe move path, then allow later manual filtering without auto replay.
    # ==========================================
    def test_ordinary_confirmed_move_resolves_uncertain_filter_guard(self):
        identity=self.mail(uid='1');message=runner.source(self.store,identity);self.rule(destinations={'test':'Other'});runner.finish(self.store,message,{'rule':'rule','destination':'Archive'},'uncertain','lost reply');provider=Provider(0);provider.boxes['INBOX']['1']={'raw':self.store.get(identity,raw=True)['raw'],'flags':set()}
        with patch('maildesk.transport.imap_connection',provider.connection):self.service.move_message(identity,'Archive')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT state FROM mail_filter_seen WHERE account=? AND message_id=?',('test',message['message_id'])).fetchone()[0],'manual')
        self.assertEqual(len(self.service.preview_filters('test')['entries']),1);self.assertEqual(runner.automatic(self.account,self.store,None)['processed'],0)

    # ==========================================
    # Function: Keep an externally copied old message from masquerading as a newly delivered UID.
    # Method: Compare server receipt time to the account baseline, ignoring the message's sender-controlled Date header.
    # ==========================================
    def test_old_internal_date_new_uid_is_historical(self):
        rules.baseline(self.store,'test','Work','77',[]);old=self.mail(folder='Work',uid='9',received_at=time.time()-86400);new=self.mail(folder='Work',uid='10')
        with self.store.db() as db:self.assertEqual({row[0] for row in db.execute('SELECT message FROM mail_filter_queue')},{new})
        self.assertNotEqual(old,new)

    # ==========================================
    # Function: Parse receipt timestamps correctly across offsets and reject incomplete provider metadata.
    # Method: Use known UTC equivalence, an invalid date and an absent INTERNALDATE value.
    # ==========================================
    def test_internal_date_parser_and_missing_metadata(self):
        from maildesk.sync_batches import received_time
        a=received_time(b'1 (UID 9 INTERNALDATE "25-Oct-2026 12:00:00 +0800")');b=received_time(b'2 (UID 10 INTERNALDATE "25-Oct-2026 04:00:00 +0000")');self.assertEqual(a,b);self.assertIsNotNone(a);self.assertIsNone(received_time(b'1 (UID 9)'));self.assertIsNone(received_time(b'1 (INTERNALDATE "40-Oct-2026 12:00:00 +0800")'))

    # ==========================================
    # Function: Prevent two stale arrival snapshots from issuing the same remote MOVE after simultaneous preflight.
    # Method: Synchronize both source FETCH responses at a barrier and require exactly one provider mutation and target copy.
    # ==========================================
    def test_competing_arrival_snapshots_claim_one_remote_move(self):
        rules.baseline(self.store,'test','INBOX','77',[]);identity=self.mail(uid='1');message=runner.source(self.store,identity);self.rule();match=first_match(message,rules.rules(self.store),runner.context(self.store));provider=Provider(0);provider.boxes['INBOX']['1']={'raw':self.store.get(identity,raw=True)['raw'],'flags':set()};barrier=threading.Barrier(2);results=[];errors=[]
        # ==========================================
        # Function: Run independent real execution paths with both preflights completed before ownership is claimed.
        # Method: Alter only synthetic response timing and retain real ledger transactions, move adapter and cache updates.
        # ==========================================
        def run():
            client=Session(provider);original=client.uid
            # ==========================================
            # Function: Release both preflight responses together to expose a duplicate-attempt race.
            # Method: Keep normal synthetic UID/FLAGS output while waiting at one finite synchronization point.
            # ==========================================
            def uid(operation,*args):
                result=original(operation,*args)
                if operation=='FETCH':barrier.wait(2)
                return result
            client.uid=uid
            try:results.append(runner.execute(self.store,dict(message),match,client)[0])
            except Exception as error:errors.append(error)
        workers=[threading.Thread(target=run) for unused in range(2)]
        for worker in workers:worker.start()
        for worker in workers:worker.join(3)
        self.assertFalse(any(worker.is_alive() for worker in workers));self.assertFalse(errors,errors);self.assertEqual(results.count('moved'),1);self.assertEqual(sum(row[0]=='MOVE' for row in provider.commands),1);self.assertEqual(len(provider.boxes['Archive']),1)

if __name__=='__main__':unittest.main()
