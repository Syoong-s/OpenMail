"""Bounded desktop work over synthetic large local mailboxes."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from maildesk.store import Store
from maildesk.inbox_views import InboxViews

# ==========================================
# Function: Measure desktop metadata access without native widgets or providers.
# Method: Count real SQLite statements over an isolated synthetic cache.
# ==========================================
class PerformanceTests(TestCase):
    # ==========================================
    # Function: Keep settings reads bounded as focused mailbox membership grows.
    # Method: Compare 500 synthetic summaries against a fixed query budget.
    # ==========================================
    def test_sections_settings_are_constant_work(self):
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'mail.db');views=InboxViews(store);definition=views.definition('focused')
            rows=[{'id':str(i),'account':'a','sender':f'{i%9}@example.com','timestamp':i,'seen':i%2,'pinned':False,'priority':False,'category':'notification'} for i in range(500)]
            queries=[];original=store.db
            # ==========================================
            # Function: Observe actual statements in independent transactions.
            # Method: Install a trace callback on each short-lived real connection.
            # ==========================================
            @contextmanager
            def counted():
                with original() as db:
                    db.set_trace_callback(queries.append);yield db
            store.db=counted
            result=views.sections(rows,definition)
            self.assertEqual(len(result[0]['items']),500)
            self.assertLessEqual(len(queries),8,'Focused grouping must not read SQLite preferences for every mail')

    # ==========================================
    # Function: Read one mail without opening a second connection or repeatedly inspecting schema.
    # Method: Trace actual SQLite statements and connection ownership after construction/migration.
    # ==========================================
    def test_message_projection_uses_one_connection(self):
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'mail.db')
            identity=store.ingest('one','INBOX','1','1',b'From: a@example.test\r\nSubject: trace\r\n\r\nbody')
            store.organize(identity,labels=['z-last','a-first'])
            original=store.db;queries=[];connections=[]
            # ==========================================
            # Function: Count real per-message I/O while preserving production SQLite behavior.
            # Method: Wrap the existing transaction factory and install its public trace callback.
            # ==========================================
            @contextmanager
            def counted():
                connections.append(1)
                with original() as db:
                    db.set_trace_callback(queries.append);yield db
            store.db=counted;message=store.get(identity)
            self.assertEqual(len(connections),1)
            self.assertFalse(any('PRAGMA' in query.upper() for query in queries))
            self.assertEqual(sum(query.lstrip().upper().startswith('SELECT') for query in queries),2)
            self.assertNotIn('raw',message)
            self.assertEqual(message['labels'],['a-first','z-last'])

    # ==========================================
    # Function: Retain exact sender policy precedence, account isolation and raw MIME fidelity.
    # Method: Modify rules between reads and reopen the store to catch stale metadata or cached state.
    # ==========================================
    def test_message_projection_retains_policy_and_raw(self):
        with TemporaryDirectory() as directory:
            path=Path(directory)/'mail.db';store=Store(path)
            raw=b'From: a@example.test\r\nMessage-ID: <projected>\r\nSubject: fidelity\r\n\r\nunchanged MIME'
            identity=store.ingest('one','INBOX','1','1',raw)
            with store.db() as db:
                db.executemany('INSERT INTO sender_policy VALUES(?,?,?)',[
                    ('one','@example.test','blocked'),('one','a@example.test','accepted'),('two','a@example.test','priority')])
            self.assertEqual(store.get(identity)['sender_policy'],'accepted')
            self.assertEqual(store.get(identity)['effective_priority'],0)
            with store.db() as db:db.execute("DELETE FROM sender_policy WHERE account='one' AND sender='a@example.test'")
            self.assertEqual(store.get(identity)['sender_policy'],'blocked')
            with store.db() as db:db.execute("UPDATE sender_policy SET policy='priority' WHERE account='one'")
            reopened=Store(path);message=reopened.get(identity,raw=True)
            self.assertEqual(message['sender_policy'],'priority');self.assertEqual(message['effective_priority'],1)
            self.assertEqual(message['raw'],raw);self.assertEqual(message['parsed']['subject'],'fidelity')
            quoted=reopened.ingest('one','INBOX','1','2',b'From: Name <"a@b"@example.test>\r\nSubject: quoted localpart\r\n\r\nbody')
            self.assertEqual(reopened.get(quoted)['sender_policy'],'priority','domain matching must use the final @ as before optimization')

    # ==========================================
    # Function: Snapshot preferences only for one operation and one thread.
    # Method: Preserve caller mutation isolation, nested scopes and subsequent persisted updates.
    # ==========================================
    def test_preference_scope_is_local_and_fresh(self):
        from concurrent.futures import ThreadPoolExecutor
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'mail.db');store.set_preference('value',{'x':1})
            with store.preference_snapshot():
                store.preference('value')['x']=9
                self.assertEqual(store.preference('value'),{'x':1})
                with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(store.set_preference,'value',{'x':2}).result()
                self.assertEqual(store.preference('value'),{'x':1})
                store.set_preference('value',{'x':3})
                with store.preference_snapshot():self.assertEqual(store.preference('value'),{'x':3})
            self.assertEqual(store.preference('value'),{'x':3})

    # ==========================================
    # Function: Read complete focused membership without loading raw mail or per-row labels.
    # Method: Verify one full projection and batched label lookup retain every scoped row.
    # ==========================================
    def test_complete_metadata_and_batch_labels(self):
        with TemporaryDirectory() as directory:
            store=Store(Path(directory)/'mail.db')
            for i in range(205):
                store.ingest('a','INBOX','1',str(i),f'From: a@example.com\r\nTo: me@example.com\r\nMessage-ID: <{i}>\r\nSubject: Item {i}\r\n\r\nbody'.encode())
            result=store.list_messages(all_items=True)
            self.assertEqual(result['total'],205);self.assertEqual(len(result['items']),205)
            self.assertNotIn('raw',result['items'][0]);self.assertNotIn('parsed',result['items'][0])
            identity=result['items'][0]['id'];store.organize(identity,labels=['标签'])
            self.assertEqual(store.labels_for([row['id'] for row in result['items']])[identity],['标签'])

    # ==========================================
    # Function: Bound ordinary GTK rows without truncating category membership or recent senders.
    # Method: Project a hundred personal rows plus all summary rows from full scoped sections.
    # ==========================================
    def test_focused_render_budget_preserves_summaries(self):
        from maildesk.desktop_focus import focused_render_items
        sections=[{'key':'today','items':[{'id':str(i)} for i in range(600)],'shown':[{'id':str(i)} for i in range(600)],'collapsed':False},
            {'key':'notification','summary':True,'items':[{'id':'n'+str(i)} for i in range(500)]},
            {'key':'earlier','items':[{'id':'old'+str(i)} for i in range(40)],'shown':[{'id':'old'+str(i)} for i in range(40)],'collapsed':False}]
        rows,has_more=focused_render_items(sections,100)
        self.assertEqual(sum('_summary' not in row for row in rows),100);self.assertTrue(has_more)
        self.assertEqual(len(next(row['_summary']['items'] for row in rows if '_summary' in row)),500)
        full,more=focused_render_items(sections,700)
        self.assertEqual(sum('_summary' not in row for row in full),640);self.assertFalse(more)

    # ==========================================
    # Function: Decode repeated SVG assets once without sharing parented image widgets.
    # Method: Exercise the native adapter with counted decoder and reference-release facades.
    # ==========================================
    def test_icon_pixels_cached_and_released(self):
        from maildesk.gtk_native import GtkNative
        adapter=GtkNative.__new__(GtkNative);decoded=[];released=[];widgets=[]
        adapter.gdk_pixbuf_new_from_file_at_scale=lambda *args:decoded.append(args) or 900
        adapter.gtk_image_new_from_pixbuf=lambda pixels:widgets.append(pixels) or len(widgets)
        adapter.g_object_unref=released.append
        result=[adapter.image_file(Path('/synthetic/icon.svg'),12) for _ in range(300)]
        self.assertEqual(len(decoded),1);self.assertEqual(len(set(result)),300)
        adapter.close_icons();adapter.close_icons();self.assertEqual(released,[900])

    # ==========================================
    # Function: Keep the legacy X11 tray constructor away from Wayland displays.
    # Method: Check the real GType dispatch contract with deterministic backend facades.
    # ==========================================
    def test_legacy_tray_checks_active_display(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from maildesk.desktop_general import GeneralUI
        app=GeneralUI();app.g=SimpleNamespace(libs={'gdk':SimpleNamespace(gdk_x11_display_get_type=True)})
        results={'gdk_display_get_default':30,'gdk_x11_display_get_type':99,'g_type_check_instance_is_a':0}
        with patch('maildesk.desktop_general.bind',side_effect=lambda app,library,name,*args:lambda *values:results[name]),patch('maildesk.desktop_general.os.name','posix'):
            self.assertFalse(app.legacy_tray_supported())
            results['g_type_check_instance_is_a']=1;self.assertTrue(app.legacy_tray_supported())

    # ==========================================
    # Function: Scope safe software rendering to WSLg and explicit local overrides.
    # Method: Verify native Linux auto mode and preserve intentional subprocess environment choices.
    # ==========================================
    def test_reader_graphics_scope_and_override(self):
        import os
        from unittest.mock import patch
        from maildesk.reader_runtime import reader_software_graphics,prepare_reader_graphics
        with patch.dict(os.environ,{},clear=True),patch('maildesk.reader_runtime.Path.is_dir',return_value=False):
            self.assertFalse(reader_software_graphics());prepare_reader_graphics()
            self.assertNotIn('WEBKIT_DISABLE_DMABUF_RENDERER',os.environ)
            self.assertNotIn('LIBGL_ALWAYS_SOFTWARE',os.environ);self.assertNotIn('GALLIUM_DRIVER',os.environ)
            os.environ['WSL_DISTRO_NAME']='Ubuntu';self.assertTrue(reader_software_graphics());prepare_reader_graphics()
            self.assertEqual(os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'],'1')
            self.assertEqual(os.environ['LIBGL_ALWAYS_SOFTWARE'],'1');self.assertEqual(os.environ['GALLIUM_DRIVER'],'llvmpipe')
            os.environ['TELEMAIL_WEBKIT_ACCELERATION']='hardware';self.assertFalse(reader_software_graphics())
            os.environ['TELEMAIL_WEBKIT_ACCELERATION']='software';self.assertTrue(reader_software_graphics())
            os.environ['WEBKIT_DISABLE_DMABUF_RENDERER']='0'
            os.environ['LIBGL_ALWAYS_SOFTWARE']='0';os.environ['GALLIUM_DRIVER']='d3d12';prepare_reader_graphics()
            self.assertEqual(os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'],'0')
            self.assertEqual(os.environ['LIBGL_ALWAYS_SOFTWARE'],'0');self.assertEqual(os.environ['GALLIUM_DRIVER'],'d3d12')

    # ==========================================
    # Function: Reopen an image's exact historical card instead of using a destroyed renderer alias.
    # Method: Simulate paging the selected mail out, then require a newly resolved live engine.
    # ==========================================
    def test_image_lookup_recovers_paged_card(self):
        from types import SimpleNamespace
        from maildesk.desktop_conversation import ConversationUI
        events=[];live=object();stale=object()
        app=SimpleNamespace(selected='selected',conversation_cards={},html_reader=stale)
        # ==========================================
        # Function: Reconstruct only the explicitly requested source card.
        # Method: Supply a distinct engine so stale fallback use is observable.
        # ==========================================
        def render(identity):
            events.append(identity);app.conversation_focus=identity
            app.conversation_cards[identity]={'reader':live,'origin':identity}
        app.render_conversation=render;app.toggle_conversation_card=lambda identity,state:events.append((identity,state))
        app.read=lambda identity:None
        self.assertIs(ConversationUI.image_reader_for(app,'selected'),live)
        self.assertEqual(events,['selected',('selected',True)])
        app.conversation_cards={};events.clear()
        self.assertIsNone(ConversationUI.image_reader_for(app,'blocked-other-mail'))
        self.assertEqual(events,[])

    # ==========================================
    # Function: Clear borrowed renderer aliases before releasing conversation native widgets.
    # Method: Observe the alias from the engine close callback to detect a dangling pointer window.
    # ==========================================
    def test_conversation_clear_releases_renderer_alias(self):
        from types import SimpleNamespace
        from maildesk.desktop_conversation import ConversationUI
        app=SimpleNamespace(html_reader=object(),legacy_html_reader=object())
        reader=SimpleNamespace(close=lambda:self.assertIs(app.html_reader,app.legacy_html_reader))
        app.conversation_cards={'a':{'reader':reader,'body_readers':[reader],'quote_cards':[],'origin':'a','group':'conversation-card-a'}}
        app.release_card_readers=lambda card:ConversationUI.release_card_readers(app,card)
        app.g=SimpleNamespace(disconnect=lambda *args:None,clear=lambda *args:None)
        app.clear_reply_reserve=lambda:None
        app.widget=lambda name:1
        ConversationUI.clear_conversation(app)
        self.assertEqual(app.conversation_cards,{})
