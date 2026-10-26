"""Conversation components, focused summaries and durable editor close regressions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from maildesk.store import Store
from maildesk.inbox_views import InboxViews
from maildesk.desktop_forms import Composer

# ==========================================
# Function: Verify account-safe reference traversal and editor persistence boundaries.
# Method: Use synthetic MIME and a failing storage facade without native UI or providers.
# ==========================================
class ConversationTests(TestCase):
    # ==========================================
    # Function: Build isolated SQLite mail state.
    # Method: Keep every fixture inside a temporary Linux directory.
    # ==========================================
    def setUp(self):self.temp=TemporaryDirectory();self.store=Store(Path(self.temp.name)/'mail.db')
    # ==========================================
    # Function: Release synthetic state.
    # Method: Close transaction scopes before deleting the temporary directory.
    # ==========================================
    def tearDown(self):self.temp.cleanup()
    # ==========================================
    # Function: Cache a realistic reference-bearing email.
    # Method: Preserve explicit account, folder and Message-ID inputs.
    # ==========================================
    def mail(self,uid,mid,reply='',account='a',folder='INBOX'):
        raw=(f'From: {uid}@example.com\r\nTo: me@example.com\r\nSubject: same subject\r\nMessage-ID: <{mid}>\r\n'+(f'In-Reply-To: <{reply}>\r\n' if reply else '')+'\r\nbody').encode()
        return self.store.ingest(account,folder,'1',uid,raw)
    # ==========================================
    # Function: Recover indirect and out-of-order replies while deduplicating sent copies.
    # Method: Resolve references through missing parents independently of arrival order.
    # ==========================================
    def test_reference_component_and_provider_copy(self):
        c=self.mail('3','c','b');a=self.mail('1','a');b=self.mail('2','b','a',folder='@sent')
        duplicate=self.mail('4','b','a',folder='Sent');unrelated=self.mail('5','x');other=self.mail('6','a',account='b')
        result=self.store.thread(c)
        self.assertEqual(len(result),3)
        self.assertEqual({r['id'] for r in result},{a,b,c})
        self.assertNotIn(unrelated,{r['id'] for r in result});self.assertNotIn(other,{r['id'] for r in result})
        self.assertNotIn(duplicate,{r['id'] for r in result})
        self.assertEqual(len(Store(self.store.path).thread(a)),3)
    # ==========================================
    # Function: Project compact recent-sender summaries without truncating membership.
    # Method: Verify chronological unique identities, unread totals and focused-only behavior.
    # ==========================================
    def test_sender_summaries(self):
        views=InboxViews(self.store);rows=[]
        for i in range(12):
            rows.append({'id':str(i),'account':'a','sender':f'{i%6}@example.com','sender_name':str(i%6),'timestamp':i,'seen':i%2,'pinned':False,'priority':False,'category':'notification'})
        section=views.sections(rows,views.definition('focused'))[0]
        self.assertTrue(section['summary']);self.assertEqual(section['title'],'通知');self.assertEqual(len(section['items']),12)
        self.assertEqual([r['sender'] for r in section['recent_senders']],[f'{i}@example.com' for i in (5,4,3,2,1)])
        self.assertEqual(section['unread'],6)
        self.assertFalse(views.sections(rows,views.definition('smart'))[0].get('summary',False))
    # ==========================================
    # Function: Keep editor contents alive after an unsuccessful durable save.
    # Method: Exercise the real close callback with failing storage and native-label facades.
    # ==========================================
    def test_failed_autosave_blocks_close(self):
        editor=Composer.__new__(Composer);editor.busy=False;editor.closed=False;editor.last_autosave=0;editor.last_snapshot='';editor.identity='draft';editor.attachments=[];editor.reply={};editor.note=0;editor.editor_baseline={}
        editor.fields={};editor.value=lambda key: {'account':'gone','body':'unsaved','due':'','followup':''}.get(key,'')
        editor.rich=SimpleNamespace(html=lambda:'<p>unsaved</p>');editor.g=SimpleNamespace(label=lambda *args:None)
        editor.app=SimpleNamespace(service=SimpleNamespace(compose=lambda data: (_ for _ in ()).throw(OSError('disk full'))),composer=editor)
        editor.close=lambda:setattr(editor,'closed',True)
        self.assertFalse(editor.autosave(force=True));editor.on_delete();self.assertFalse(editor.closed);self.assertIs(editor.app.composer,editor)

    # ==========================================
    # Function: Recover an interrupted reference migration without permanently missing old links.
    # Method: Roll back a partial backfill after its durable table creation and retry initialization.
    # ==========================================
    def test_interrupted_reference_migration_resumes(self):
        from unittest.mock import patch
        from maildesk.thread_graph import record_links
        a=self.mail('1','parent');b=self.mail('2','child','parent')
        with self.store.db() as db:
            db.execute('DROP TABLE thread_links');db.execute('DROP TABLE thread_graph_migrations')
        # ==========================================
        # Function: Simulate termination after a backfilled row but before its completion marker.
        # Method: Raise inside the migration transaction so only committed schema survives.
        # ==========================================
        def interrupted(db,account,message):
            record_links(db,account,message);raise OSError('synthetic interrupted migration')
        with patch('maildesk.thread_graph.record_links',interrupted):
            with self.assertRaises(OSError):Store(self.store.path)
        restored=Store(self.store.path)
        self.assertEqual({row['id'] for row in restored.thread(b)},{a,b})
        self.assertEqual(len(Store(self.store.path).thread(a)),2)

    # ==========================================
    # Function: Cache encapsulated emails once without exposing nested attachments as siblings.
    # Method: Use the same parsed MIME index contract as the reader and upgrade an old completion marker.
    # ==========================================
    def test_encapsulated_attachment_auto_cache(self):
        from email.message import EmailMessage
        import hashlib
        from maildesk.desktop_preferences import cached_attachments
        child=EmailMessage();child['From']='inside@example.com';child.set_content('attached original')
        child.add_attachment(b'nested secret',maintype='text',subtype='plain',filename='nested.txt')
        message=EmailMessage();message['From']='parent@example.com';message.set_content('parent text');message.add_attachment(child,filename='attached.eml')
        raw=message.as_bytes();identity=self.store.ingest('a','INBOX','1','attached',raw)
        self.assertEqual([a['name'] for a in self.store.get(identity)['parsed']['attachments']],['attached.eml'])
        self.store.cache_dir=Path(self.temp.name)/'private-cache'
        target=self.store.cache_dir/'attachments'/hashlib.sha256(raw).hexdigest();target.mkdir(parents=True);(target/'.complete').touch()
        self.store.set_preference('autodownload_attachments',True);self.assertEqual(cached_attachments(self.store),1)
        self.assertEqual(len(list(target.glob('*attached.eml'))),1);self.assertFalse(list(target.glob('*nested*')))
        self.assertEqual(cached_attachments(self.store),0)

    # ==========================================
    # Function: Keep quick-action origins and navigation stable while asynchronous work runs.
    # Method: Dispatch real store mutations through a delayed UI facade and move selection before completion.
    # ==========================================
    def test_quick_action_snapshot_and_success_navigation(self):
        from maildesk.desktop_focus import FocusUI
        a=self.mail('1','a');b=self.mail('2','b');c=self.mail('3','c')
        self.store.update(b,{'pinned':True});self.store.set_preference('main_action_policy','next')
        pending=[]
        app=SimpleNamespace(service=SimpleNamespace(store=self.store,update=self.store.update),items=[{'id':a},{'id':b},{'id':c}],selected=b,close_document=lambda:True,refresh=lambda:None)
        app.background=lambda operation,success:pending.append((operation,success))
        FocusUI.quick_action(app,b,'done');operation,success=pending.pop();app.selected=a;success(operation())
        self.assertTrue(self.store.get(b)['done']);self.assertFalse(self.store.get(b)['pinned']);self.assertEqual(app.selected,a)
        self.store.organize(b,done=False);app.selected=b;FocusUI.quick_action(app,b,'done');operation,success=pending.pop();success(operation())
        self.assertEqual(app.selected,c)
        app.selected=a;FocusUI.quick_action(app,c,'seen');operation,success=pending.pop();success(operation())
        self.assertTrue(self.store.get(c)['seen']);self.assertEqual(app.selected,a)

    # ==========================================
    # Function: Keep all reference-linked cached headers available as lightweight metadata.
    # Method: Query the actual account-isolated RFC graph for a thirty-five-message conversation.
    # ==========================================
    def test_continuous_thread_metadata_has_no_hidden_range(self):
        ids=[self.mail(str(index),'continuous-'+str(index),'continuous-'+str(index-1) if index else '') for index in range(35)]
        rows=self.store.thread(ids[-1]);self.assertEqual({row['id'] for row in rows},set(ids))
        self.assertTrue(all('preview' in row and 'recipients' in row and 'sender_name' in row for row in rows))
        self.assertEqual(len(rows),35)

    # ==========================================
    # Function: Apply mutable labels, flags, avatars and colors without replacing body widgets.
    # Method: Invoke the actual metadata updater using retained native-operation facades.
    # ==========================================
    def test_card_metadata_refresh_keeps_renderer(self):
        from maildesk.desktop_conversation import ConversationUI
        from maildesk.identity_colors import IdentityColors
        identity=self.mail('1','metadata');visible={};texts={};styles=[];reloads=[]
        colors=IdentityColors(self.store)
        native=SimpleNamespace(label=lambda widget,value:texts.update({widget:value}),gtk_widget_set_no_show_all=lambda *args:None,
            gtk_widget_set_visible=lambda widget,value:visible.update({widget:value}),
            style=lambda widget,source,provider:styles.append(source) or provider,
            gtk_widget_set_size_request=lambda *args:None,gtk_widget_get_style_context=lambda widget:widget,
            gtk_style_context_add_class=lambda *args:None,gtk_style_context_remove_class=lambda *args:None)
        reader=SimpleNamespace(reload=lambda:reloads.append(True),widget='html',message_own=False)
        card={'root':'card-root','labels_widget':'labels','avatar':'avatar','avatar_provider':'provider','reader':reader,'body_readers':[reader],'quote_cards':[],'metadata':self.store.thread(identity)[0]}
        app=SimpleNamespace(service=SimpleNamespace(store=self.store,accounts={}),profile=SimpleNamespace(demo=False),g=native,identity_colors=colors,conversation_cards={identity:card})
        ConversationUI.update_conversation_metadata(app);self.assertTrue(visible['avatar']);self.assertFalse(visible['labels'])
        self.store.organize(identity,labels=['研究'],done=True);self.store.update(identity,{'pinned':True})
        self.store.set_preference('labels_system',True);self.store.set_preference('avatars_mode','none')
        self.store.set_preference('account_colors',{'a':'#e69c46'})
        card['metadata']=self.store.thread(identity)[0]
        ConversationUI.update_conversation_metadata(app,reload=True)
        self.assertFalse(visible['avatar']);self.assertIn('研究',texts['labels']);self.assertIn('已完成',texts['labels']);self.assertIn('已置顶',texts['labels'])
        self.assertTrue(any('#e69c46' in style for style in styles));self.assertEqual(reloads,[True]);self.assertIs(card['reader'],reader)

    # ==========================================
    # Function: Retain the user's collapsed card when a passive refresh has no topology changes.
    # Method: Exercise the actual renderer fast path without constructing any substitute UI model.
    # ==========================================
    def test_passive_refresh_does_not_expand_selected_card(self):
        from maildesk.desktop_conversation import ConversationUI
        from maildesk.identity_colors import IdentityColors
        from test_conversation_bubbles import NativeOwnership
        from unittest.mock import patch
        identity=self.mail('1','collapse');g=NativeOwnership();app=ConversationUI();app.g=g;app.composer=None
        app.service=SimpleNamespace(store=self.store,accounts={},mark_opened=lambda identity:False);app.profile=SimpleNamespace(demo=False);app.identity_colors=IdentityColors(self.store)
        widgets={key:g.new() for key in ('conversation_host','reader_content','composer_host','reader_stack')};app.widget=lambda key:widgets[key]
        app.apply_avatar=lambda *args:1;app.selected=identity
        with patch('maildesk.document_reader.HTMLReader',side_effect=RuntimeError('synthetic fallback')):
            app.render_conversation(identity);root=app.conversation_cards[identity]['root'];app.toggle_conversation_card(identity,False)
            app.render_conversation(identity)
            self.assertEqual(app.conversation_cards[identity]['root'],root);self.assertFalse(app.conversation_cards[identity]['expanded'])

    # ==========================================
    # Function: Open the next captured message even when it is represented only by a sender summary.
    # Method: Simulate the real refresh clearing an absent native row before explicit target reading.
    # ==========================================
    def test_finishing_navigation_reads_hidden_summary_member(self):
        from maildesk.desktop_focus import FocusUI
        a=self.mail('1','shown');b=self.mail('2','summary-member')
        self.store.set_preference('main_action_policy','next');reads=[]
        app=SimpleNamespace(service=SimpleNamespace(store=self.store,update=self.store.update),items=[{'id':a},{'id':b}],selected=a,close_document=lambda:True)
        app.refresh=lambda:setattr(app,'selected','')
        app.read=lambda identity:(reads.append(identity),setattr(app,'selected',identity))
        app.background=lambda operation,success:success(operation())
        FocusUI.quick_action(app,a,'done')
        self.assertEqual(reads,[b]);self.assertEqual(app.selected,b);self.assertIsNone(app.layout_override)
