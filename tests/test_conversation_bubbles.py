"""Conversation history, envelope disclosure and live reply ownership regressions."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import ctypes as C
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from maildesk.desktop_conversation import ConversationUI, conversation_details
from maildesk.desktop_forms import Composer
from maildesk.identity_colors import IdentityColors
from maildesk.store import Store


# ==========================================
# Function: Model native ownership for actual renderer and composer method regressions.
# Method: Retain widget parents, recursive destruction, visibility and connected callback groups.
# ==========================================
class NativeOwnership:
    # ==========================================
    # Function: Initialize a deterministic isolated widget graph.
    # Method: Allocate numeric handles and record operations relevant to ownership and paging.
    # ==========================================
    def __init__(self):
        self.accessible_setter=C.CFUNCTYPE(None,C.c_void_p,C.c_char_p,C.c_char_p,C.c_void_p)(lambda *unused:None)
        self.libs={'gtk':self,'object':SimpleNamespace(g_object_set=self.accessible_setter)};self.no_show_all={};self.next=0;self.parents={};self.children={};self.dead=set();self.labels={};self.visible={};self.enabled={};self.groups={};self.focus=None;self.clamps=[]

    # ==========================================
    # Function: Allocate a synthetic widget retaining its native ownership attributes.
    # Method: Assign a unique numeric pointer without a graphical connection.
    # ==========================================
    def new(self,*unused):
        self.next+=1;self.children[self.next]=[];self.visible[self.next]=False;self.enabled[self.next]=True;return self.next

    # ==========================================
    # Function: Reparent a child while preserving its pointer and descendants.
    # Method: Remove previous ownership before recording its new parent.
    # ==========================================
    def add(self,parent,child,*unused):
        previous=self.parents.get(child)
        if previous:self.children[previous].remove(child)
        self.parents[child]=parent;self.children[parent].append(child)

    # ==========================================
    # Function: Destroy a widget and exactly its currently owned descendants.
    # Method: Recursively follow the graph to catch accidental live-editor destruction.
    # ==========================================
    def destroy(self,widget):
        self.clear(widget);self.dead.add(widget)
        previous=self.parents.pop(widget,None)
        if previous:self.children[previous].remove(widget)

    # ==========================================
    # Function: Clear a native container's children.
    # Method: Invoke recursive destruction rather than treating clear as a harmless log call.
    # ==========================================
    def clear(self,widget):
        for child in list(self.children[widget]):self.destroy(child)

    # ==========================================
    # Function: Match GTK recursive visibility while honoring independent no-show-all guards.
    # Method: Skip guarded subtrees and show only descendants whose own guard permits it.
    # ==========================================
    def show_all(self,widget):
        if self.no_show_all.get(widget,False):return
        self.visible[widget]=True
        for child in self.children[widget]:self.show_all(child)

    # ==========================================
    # Function: Register callbacks in the same named lifecycle scopes as production.
    # Method: Retain a deterministic group inventory for page and clear assertions.
    # ==========================================
    def connect(self,widget,signal,callback,group=None,**unused):
        self.groups.setdefault(group,[]).append((widget,signal,callback))

    # ==========================================
    # Function: Return bounded native facades consumed by real conversation methods.
    # Method: Record ownership and visible state while ignoring only visual decoration setters.
    # ==========================================
    def __getattr__(self,name):
        if name=='gtk_event_box_new':return self.new
        if name=='gtk_event_box_set_visible_window':return lambda *unused:None
        if name in ('gtk_box_new','gtk_label_new','gtk_button_new','gtk_button_new_with_label','gtk_menu_button_new','gtk_popover_new','gtk_flow_box_new','gtk_image_new_from_icon_name','image_file'):return self.new
        if name in ('gtk_box_pack_start','gtk_container_add'):return self.add
        if name=='gtk_widget_reparent':return lambda child,parent:self.add(parent,child)
        if name=='gtk_widget_destroy':return self.destroy
        if name=='gtk_widget_get_parent':return lambda widget:self.parents.get(widget)
        if name=='gtk_widget_get_style_context':return lambda widget:widget
        if name=='gtk_bin_get_child':return lambda widget:self.children[widget][0] if self.children[widget] else self.new()
        if name=='disconnect':return lambda group:self.groups.pop(group,None)
        if name=='gtk_widget_show_all':return self.show_all
        if name=='gtk_widget_set_no_show_all':return lambda widget,value:self.no_show_all.update({widget:bool(value)})
        if name=='gtk_widget_set_visible':return lambda widget,value:self.visible.update({widget:bool(value)})
        if name=='gtk_widget_set_sensitive':return lambda widget,value:self.enabled.update({widget:bool(value)})
        if name=='gtk_widget_get_sensitive':return lambda widget:self.enabled[widget]
        if name=='gtk_widget_grab_focus':return lambda widget:setattr(self,'focus',widget)
        if name=='label':return lambda widget,value,**unused:self.labels.update({widget:value})
        if name=='gtk_widget_get_accessible':return lambda widget:0
        if name=='gtk_widget_get_ancestor':return lambda *unused:0
        if name=='gtk_scrolled_window_get_type':return lambda:1
        if name=='style':return lambda *unused:1
        if name.startswith(('gtk_widget_set_','gtk_label_set_','gtk_button_set_','gtk_menu_button_set_','gtk_flow_box_set_','gtk_style_context_','gtk_container_set_','gtk_stack_set_')) or name in ('gtk_widget_show_all','gtk_box_reorder_child'):return lambda *unused:None
        raise AttributeError(name)


# ==========================================
# Function: Verify actual rendering and persistence behavior with temporary MIME messages.
# Method: Exercise production conversation methods against an ownership-aware native facade.
# ==========================================
class ConversationBubbleTests(TestCase):
    # ==========================================
    # Function: Create a temporary mailbox and usable ConversationUI instance.
    # Method: Disable HTML construction while retaining actual store, renderer and callback lifecycles.
    # ==========================================
    def setUp(self):
        self.temporary=TemporaryDirectory();self.store=Store(Path(self.temporary.name)/'mail.db')
        self.g=NativeOwnership();self.app=ConversationUI();self.app.g=self.g;self.app.composer=None
        self.app.service=SimpleNamespace(store=self.store,accounts={},mark_opened=lambda identity:False)
        self.app.profile=SimpleNamespace(demo=False)
        self.app.identity_colors=IdentityColors(self.store)
        self.widgets={name:self.g.new() for name in ('conversation_host','reader_content','composer_host','reader_stack')}
        self.app.widget=lambda name:self.widgets[name];self.app.apply_avatar=lambda *unused:1
        self.messages=[];self.app.message=self.messages.append
        self.app.run_action=lambda action:action()
        self.html=patch('maildesk.document_reader.HTMLReader',side_effect=RuntimeError('synthetic text renderer'));self.html.start()
        self.ids=[self.mail(i) for i in range(35)];self.app.selected=self.ids[-1]

    # ==========================================
    # Function: Keep explicit focus reveal pending while native Windows allocations settle.
    # Method: Model an initially unallocated header, then late scroll extent and visible stable geometry.
    # ==========================================
    def test_focus_reveal_waits_for_native_allocation_and_respects_manual_scroll(self):
        from unittest.mock import Mock
        state={'now':1.2,'height':1,'offset':0,'top':3500,'child_height':4000};clamps=[];signals={}
        # ==========================================
        # Function: Project changing native positions through the actual ctypes pointer ABI.
        # Method: Distinguish content coordinates from viewport coordinates after adjustment changes.
        # ==========================================
        def translate(target,parent,x,y,out_x,out_y):
            out_x._obj.value=0;out_y._obj.value=int(state['top']-(state['offset'] if parent==20 else 0));return 1
        # ==========================================
        # Function: Apply a recorded native scroll adjustment to the simulated viewport.
        # Method: Preserve actual clamp-page behavior while allowing slow allocation transitions.
        # ==========================================
        def clamp(adjustment,lower,upper):
            clamps.append((lower,upper));state['offset']=lower
        native=SimpleNamespace(gtk_widget_get_ancestor=lambda *args:10,gtk_scrolled_window_get_type=lambda:1,
            gtk_bin_get_child=lambda widget:20 if widget==10 else 30,
            gtk_widget_get_allocated_width=lambda widget:700,
            gtk_widget_get_allocated_height=lambda widget:state['height'] if widget==40 else (state['child_height'] if widget==30 else 500),
            gtk_widget_translate_coordinates=translate,gtk_scrolled_window_get_vadjustment=lambda widget:50,
            gtk_adjustment_clamp_page=clamp,disconnect=lambda group:None,
            connect=lambda widget,event,callback,**kwargs:signals.update({event:callback}))
        app=ConversationUI();app.g=native;app.composer=None;app.conversation_cards={'focus':{'header':40}};app.conversation_focus='focus'
        app.pending_conversation_reveal=('focus',1.0)
        with patch('maildesk.desktop_conversation.time.monotonic',side_effect=lambda:state['now']):
            app.reveal_conversation_card();self.assertIsNotNone(app.pending_conversation_reveal);self.assertFalse(clamps)
            state['height']=38;state['now']=1.4;app.reveal_conversation_card();self.assertIsNotNone(app.pending_conversation_reveal)
            state['now']=1.5;app.reveal_conversation_card();self.assertIsNone(app.pending_conversation_reveal)
            self.assertTrue(clamps);count=len(clamps);state['offset']=0
            app.reveal_conversation_card();self.assertEqual(len(clamps),count)
            app.pending_conversation_reveal=('focus',2.0);state['now']=2.2;app.reveal_conversation_card()
            signals['scroll-event'](None,None,None);state['now']=2.3;app.reveal_conversation_card()
            self.assertIsNone(app.pending_conversation_reveal);self.assertEqual(len(clamps),count+1)

    # ==========================================
    # Function: Release all temporary state and patched renderer construction.
    # Method: Restore production imports before deleting the disposable database.
    # ==========================================
    def tearDown(self):
        self.html.stop();self.temporary.cleanup()

    # ==========================================
    # Function: Cache chronological source-bound messages with full envelope fields.
    # Method: Link Message-IDs and preserve source-specific attachment indexes.
    # ==========================================
    def mail(self,index):
        message=EmailMessage();message['From']=f'Sender {index} <sender{index}@example.invalid>'
        message['To']='me@example.invalid';message['Cc']='copy@example.invalid';message['Reply-To']='reply@example.invalid'
        message['Date']=format_datetime(datetime(2026,10,20,0,index,tzinfo=timezone.utc));message['Subject']='Conversation'
        message['Message-ID']=f'<conversation-{index}@example.invalid>'
        if index:message['In-Reply-To']=f'<conversation-{index-1}@example.invalid>'
        message.set_content(f'Body source {index}')
        message.add_attachment(str(index).encode(),maintype='text',subtype='plain',filename='same-name.txt')
        return self.store.ingest('a','INBOX','1',str(index),message.as_bytes())

    # ==========================================
    # Function: Keep every cached member present with only requested native bodies loaded.
    # Method: Inspect full metadata membership and preserve independent local disclosure choices.
    # ==========================================
    def test_continuous_cards_all_present_and_lazy(self):
        app=self.app
        with patch.object(self.store,'get',wraps=self.store.get) as fetched:app.render_conversation(app.selected)
        self.assertEqual(list(app.conversation_cards),self.ids)
        self.assertLess(len(fetched.call_args_list),10)
        self.assertEqual(sum(card['expanded'] for card in app.conversation_cards.values()),1)
        self.assertEqual(sum(card['body_loaded'] for card in app.conversation_cards.values()),1)
        self.assertIsNone(app.conversation_tools)
        self.assertFalse(hasattr(app,'conversation_range_label'))
        roots={identity:card['root'] for identity,card in app.conversation_cards.items()}
        for identity in self.ids[:6]:app.toggle_conversation_card(identity)
        self.assertEqual(sum(card['expanded'] for card in app.conversation_cards.values()),7)
        app.render_conversation(app.selected)
        self.assertEqual(roots,{identity:card['root'] for identity,card in app.conversation_cards.items()})
        self.assertTrue(all(app.conversation_cards[identity]['expanded'] for identity in self.ids[:6]))

    # ==========================================
    # Function: Preserve an actual mounted editor across autosave-preview and metadata refresh.
    # Method: Let native clear recursively destroy children and ensure only draft_host is cleared.
    # ==========================================
    def test_preview_refresh_does_not_destroy_or_duplicate_live_bubble(self):
        app=self.app;app.render_conversation(app.selected);origin=self.ids[-2];card=app.conversation_cards[origin]
        window=self.g.new();body=self.g.new();self.g.add(window,body);self.g.add(card['reply_host'],window)
        values={'account':'a','to':'sender@example.invalid','subject':'Re: Conversation','body':'Keep exact live buffer'}
        editor=SimpleNamespace(closed=False,inline=True,detached=False,floating=False,identity='live-draft',reply={'reply_source':origin},window=window,value=lambda key:values[key],size_surface=lambda:None)
        app.composer=editor
        for _ in range(3):app.update_reply_draft_cards();app.render_conversation(app.selected)
        self.assertEqual(self.g.parents[window],card['reply_host']);self.assertNotIn(window,self.g.dead);self.assertNotIn(body,self.g.dead)
        self.assertFalse(card['draft_cards'])
        app.toggle_conversation_card(origin,False);self.assertEqual(self.g.parents[window],card['reply_host'])
        snapshot=list(app.conversation_cards);self.mail(35);app.render_conversation(app.selected)
        self.assertEqual(list(app.conversation_cards)[:-1],snapshot);self.assertNotIn(body,self.g.dead)

    # ==========================================
    # Function: Resume saved source-bound draft previews without clearing the editor container.
    # Method: Persist a real job, render its bubble and refresh while checking attachment identity.
    # ==========================================
    def test_saved_reply_preview_keeps_source_and_attachment_identity(self):
        app=self.app;app.render_conversation(app.selected);origin=self.ids[-3]
        self.store.save_draft('a',{'reply_source':origin,'body':'Saved on this device','to':'sender@example.invalid'},'saved-reply')
        app.update_reply_draft_cards();card=app.conversation_cards[origin]
        self.assertIn('saved-reply',card['draft_cards'])
        app.toggle_conversation_card(origin,True)
        attachment=next(iter(card['attachments'].values()));app.update_reply_draft_cards()
        self.assertNotIn(attachment,self.g.dead);self.assertEqual(self.g.parents[card['reply_host']],card['root'])

    # ==========================================
    # Function: Rescue a mounted live editor before a reader clear destroys its source card.
    # Method: Track operation order and preserve the exact child graph in the full composer host.
    # ==========================================
    def test_clear_parks_editor_before_destroying_cards(self):
        app=self.app;app.render_conversation(app.selected);card=app.conversation_cards[self.ids[-1]];window=self.g.new();body=self.g.new()
        self.g.add(window,body);self.g.add(card['reply_host'],window)
        editor=SimpleNamespace(closed=False,inline=True,detached=False,floating=False,window=window,
            reparent_surface=lambda parent:self.g.add(parent,window),size_surface=lambda:None)
        app.composer=editor;app.clear_conversation()
        self.assertFalse(editor.inline);self.assertFalse(editor.floating);self.assertEqual(self.g.parents[window],self.widgets['composer_host'])
        self.assertNotIn(window,self.g.dead);self.assertNotIn(body,self.g.dead);self.assertFalse(app.conversation_cards)

    # ==========================================
    # Function: Preserve source details and disclose body context when a historical mail is collapsed.
    # Method: Read real parsed MIME headers and toggle retained widgets without recreating attachments.
    # ==========================================
    def test_details_and_collapsed_snippet_retain_exact_origin(self):
        app=self.app;app.render_conversation(app.selected);origin=self.ids[-4];card=app.conversation_cards[origin]
        details=conversation_details(self.store.get(origin)['parsed'])
        self.assertIn('sender31@example.invalid',details);self.assertIn('copy@example.invalid',details);self.assertIn('reply@example.invalid',details)
        self.assertIn('2026',details);self.assertNotIn('密送',details)
        app.toggle_conversation_card(origin,False);self.assertTrue(self.g.visible[card['snippet']]);self.assertFalse(self.g.visible[card['content']])
        app.toggle_conversation_card(origin,True);self.assertFalse(self.g.visible[card['snippet']]);self.assertTrue(self.g.visible[card['content']])

    # ==========================================
    # Function: Preserve manual card states while arrivals and automatic-collapse preferences change.
    # Method: Refresh the real conversation renderer against newly ingested source messages.
    # ==========================================
    def test_local_disclosure_survives_arrival_and_minimize_setting(self):
        app=self.app;app.render_conversation(app.selected);origin=self.ids[3]
        app.toggle_conversation_card(origin,True);app.toggle_conversation_card(app.selected,False)
        newest=self.mail(35);app.render_conversation(app.selected)
        self.assertIn(newest,app.conversation_cards);self.assertTrue(app.conversation_cards[origin]['expanded'])
        self.assertFalse(app.conversation_cards[app.selected]['expanded'])
        self.store.set_preference('minimize_old_emails',False);app.render_conversation(app.selected)
        self.store.set_preference('minimize_old_emails',True);app.render_conversation(app.selected)
        self.assertFalse(app.conversation_cards[origin]['expanded'])

    # ==========================================
    # Function: Keep the live rich editor intact when switching between inline and expanded surfaces.
    # Method: Exercise real composer surface transitions with stable draft, buffer and attachments.
    # ==========================================
    def test_expand_return_and_missing_source_fallback_keep_live_state(self):
        app=self.app;app.render_conversation(app.selected);origin=self.ids[-2]
        editor=Composer.__new__(Composer);editor.embedded=True;editor.inline=True;editor.floating=False;editor.detached=False
        editor.app=app;editor.g=self.g;editor.reply={'reply_source':origin};editor.window=self.g.new()
        editor.identity='same-draft';editor.rich=object();editor.attachments=[{'name':'same.txt'}]
        editor.size_surface=lambda:None;editor.scroll_into_view=lambda:None;editor.reparent_surface=lambda parent:self.g.add(parent,editor.window)
        app.apply_layout=lambda:None;app.update_reply_draft_cards=lambda:None
        original=(editor.identity,editor.rich,editor.attachments)
        editor.toggle_surface();self.assertFalse(editor.inline);self.assertEqual(self.g.parents[editor.window],self.widgets['composer_host'])
        editor.toggle_surface();self.assertTrue(editor.inline);self.assertEqual(self.g.parents[editor.window],app.conversation_cards[origin]['reply_host'])
        del app.conversation_cards[origin];editor.toggle_surface();self.assertFalse(editor.inline)
        self.assertEqual((editor.identity,editor.rich,editor.attachments),original)

    # ==========================================
    # Function: Hide history navigation for a genuinely single-message conversation.
    # Method: Render an unrelated source and observe actual toolbar visibility updates.
    # ==========================================
    def test_single_message_has_no_history_toolbar(self):
        identity=self.store.ingest('a','INBOX','1','single',b'From: single@example.invalid\r\nTo: me@example.invalid\r\nMessage-ID: <single>\r\n\r\nSingle body')
        self.app.selected=identity;self.app.render_conversation(identity)
        self.assertIsNone(self.app.conversation_tools);self.assertEqual(list(self.app.conversation_cards),[identity])

    # ==========================================
    # Function: Expose saved and error states only after real local persistence results.
    # Method: Exercise the actual autosave method with temporary storage and a deliberate write failure.
    # ==========================================
    def test_draft_state_tracks_edits_success_and_write_failure(self):
        editor=Composer.__new__(Composer);editor.closed=False;editor.busy=False;editor.last_autosave=0;editor.last_snapshot=''
        editor.identity='status-draft';editor.attachments=[];editor.reply={'reply_source':self.ids[-1]};editor.editor_baseline={};editor.note=self.g.new();editor.g=self.g
        values={'account':'a','to':'sender@example.invalid','cc':'','bcc':'','subject':'Re: Conversation','body':'Important local reply','due':'','followup':''}
        editor.value=lambda key:values[key];editor.rich=SimpleNamespace(html=lambda:'<p>'+values['body']+'</p>')
        editor.app=SimpleNamespace(service=SimpleNamespace(store=self.store,compose=lambda data:self.store.save_draft(data['account'],data,data['id'])),update_reply_draft_cards=lambda:None)
        editor.draft_changed();self.assertEqual(editor.draft_state,'dirty')
        self.assertTrue(editor.autosave(force=True));self.assertEqual(editor.draft_state,'saved')
        self.assertEqual(self.store.job(editor.identity)['draft']['body'],values['body'])
        values['body']='Later unsaved change';editor.draft_changed()
        with patch.object(editor.app.service,'compose',side_effect=OSError('synthetic disk full')):
            self.assertFalse(editor.autosave(force=True))
        self.assertEqual(editor.draft_state,'error');self.assertIn('synthetic disk full',self.g.labels[editor.note])
        self.assertFalse(editor.closed);self.assertEqual(editor.value('body'),'Later unsaved change')
        self.assertEqual(self.store.job(editor.identity)['draft']['body'],'Important local reply')
        self.assertTrue(editor.autosave(force=True));self.assertEqual(editor.draft_state,'saved')

    # ==========================================
    # Function: Mark tag-only formatting and attachment selection as unsaved immediately.
    # Method: Invoke actual response commands without relying on GtkTextBuffer text insertion signals.
    # ==========================================
    def test_formatting_and_attachment_commands_mark_dirty(self):
        editor=Composer.__new__(Composer);editor.closed=False;editor.busy=False;editor.g=self.g;editor.note=self.g.new();editor.attachments=[]
        editor.rich=SimpleNamespace(toggle=lambda kind:None);editor.app=SimpleNamespace(window=1)
        editor.draft_state='saved';editor.response(None,7,None);self.assertEqual(editor.draft_state,'dirty')
        editor.refresh_chips=lambda:None;editor.size_surface=lambda:None;editor.embedded=True
        attachment=Path(self.temporary.name)/'note.txt';attachment.write_text('local attachment')
        editor.g.choose=lambda *unused:attachment;editor.draft_state='saved';editor.response(None,3,None)
        self.assertEqual(editor.draft_state,'dirty');self.assertEqual(editor.attachments[0]['name'],'note.txt')

    # ==========================================
    # Function: Append a third continuous card while preserving the exact two existing roots and live editor.
    # Method: Refresh the actual renderer and compare exact card roots, editor ownership and full membership.
    # ==========================================
    def test_short_history_append_while_editing_keeps_exact_roots(self):
        short=[]
        for index in range(2):
            raw=(f'From: sender{index}@example.invalid\r\nTo: me@example.invalid\r\nMessage-ID: <short-{index}>\r\n'+
                 ('In-Reply-To: <short-0>\r\n' if index else '')+'\r\nShort conversation').encode()
            short.append(self.store.ingest('a','INBOX','1','short-'+str(index),raw))
        app=self.app;app.selected=short[-1];app.render_conversation(app.selected)
        roots={identity:card['root'] for identity,card in app.conversation_cards.items()}
        source=app.conversation_cards[short[0]];window=self.g.new();body=self.g.new();self.g.add(window,body);self.g.add(source['reply_host'],window)
        values={'account':'a','to':'sender0@example.invalid','subject':'Re: Short','body':'Keep my short-thread reply'}
        editor=SimpleNamespace(closed=False,inline=True,detached=False,floating=False,identity='short-draft',reply={'reply_source':short[0]},
            window=window,value=lambda key:values[key],size_surface=lambda:None)
        app.composer=editor
        newest=self.store.ingest('a','INBOX','1','short-2',b'From: new@example.invalid\r\nTo: me@example.invalid\r\nMessage-ID: <short-2>\r\nIn-Reply-To: <short-1>\r\n\r\nNew reply')
        app.render_conversation(app.selected)
        self.assertEqual(roots,{identity:card['root'] for identity,card in app.conversation_cards.items() if identity in roots})
        self.assertIs(app.composer,editor);self.assertEqual(self.g.parents[window],source['reply_host']);self.assertNotIn(body,self.g.dead)
        self.assertIn(newest,app.conversation_cards);self.assertEqual(len(app.conversation_cards),3)

    # ==========================================
    # Function: Keep independent flat quote callbacks and readers alive across neighboring collapse.
    # Method: Open the current history gate and verify sibling wrappers, saved disclosure and teardown.
    # ==========================================
    def test_flat_quotes_keep_independent_lifetimes_and_preserve_states(self):
        message=EmailMessage();message['From']='source@example.invalid';message['To']='me@example.invalid';message['Message-ID']='<nested>'
        message.set_content('Now');message.add_alternative('<p>Now</p><div class="gmail_quote"><p>Previous</p><blockquote type="cite"><b>Older</b></blockquote></div>',subtype='html')
        identity=self.store.ingest('a','INBOX','1','nested',message.as_bytes());app=self.app;app.selected=identity;app.render_conversation(identity);app.toggle_card_history(identity,True)
        card=app.conversation_cards[identity];outer=card['quote_cards'][0];base_groups=len(self.g.groups)
        for _ in range(4):
            app.toggle_quote_card(identity,outer['path'],True);nested=card['quote_cards'][-1]
            self.assertEqual(len(card['quote_cards']),2);self.assertIn(nested['group'],self.g.groups)
            app.toggle_quote_card(identity,nested['path'],True);app.toggle_quote_card(identity,outer['path'],False)
            self.assertIn(nested['group'],self.g.groups);self.assertTrue(nested['expanded']);self.assertEqual(len(self.g.groups),base_groups)
            self.assertEqual(self.g.parents[outer['root']],outer['wrapper'])
            self.assertEqual(self.g.parents[nested['root']],nested['wrapper'])
            self.assertEqual(self.g.parents[outer['wrapper']],card['history_host'])
            self.assertEqual(self.g.parents[nested['wrapper']],card['history_host'])
        app.toggle_quote_card(identity,outer['path'],True)
        self.assertTrue(card['quote_cards'][-1]['expanded'])
        app.toggle_conversation_card(identity,False);self.assertFalse(card['body_loaded'])
        self.assertFalse(card['quote_cards'][-1]['expanded']);self.assertTrue(card['quote_states'][card['quote_cards'][-1]['path']])
        app.toggle_conversation_card(identity,True);app.toggle_card_history(identity,True);self.assertTrue(card['quote_cards'][0]['expanded'])
        groups=[quote['group'] for quote in card['quote_cards']];app.clear_conversation()
        self.assertTrue(all(group not in self.g.groups for group in groups))

    # ==========================================
    # Function: Reveal newly created quote descendants on the first native disclosure.
    # Method: Emulate GTK no-show-all behavior and initially hidden WebViews without a second refresh.
    # ==========================================
    def test_first_quote_expansion_shows_new_reader_descendants(self):
        app=self.app;g=self.g
        # ==========================================
        # Function: Emulate the initial hidden state of an actual newly constructed native reader.
        # Method: Require production show-all ordering to reveal every reader widget.
        # ==========================================
        class HiddenReader:
            # ==========================================
            # Function: Allocate a hidden native reader child.
            # Method: Retain its native widget and closed state for disclosure assertions.
            # ==========================================
            def __init__(self,unused_app,group):
                self.widget=g.new();g.visible[self.widget]=False;self.closed=False
            # ==========================================
            # Function: Retain inert source as a reader would during asynchronous load.
            # Method: Track source without changing GTK visibility.
            # ==========================================
            def load(self,source,images=None):
                self.source=source
            # ==========================================
            # Function: Complete simulated native ownership transfer.
            # Method: Leave visibility entirely under the real conversation renderer's control.
            # ==========================================
            def attached(self):pass
            # ==========================================
            # Function: Mark a released reader closed.
            # Method: Preserve exact-reader lifecycle assertions across nested collapse and reopen.
            # ==========================================
            def close(self):self.closed=True
        message=EmailMessage();message['From']='source@example.invalid';message['To']='me@example.invalid';message['Message-ID']='<first-expansion>'
        message.set_content('Now');message.add_alternative('<p>Now</p><div class="gmail_quote"><p>Previous</p><blockquote type="cite"><b>Nested</b></blockquote></div>',subtype='html')
        identity=self.store.ingest('a','INBOX','1','first-expand',message.as_bytes());app.selected=identity
        with patch('maildesk.document_reader.HTMLReader',HiddenReader):
            app.render_conversation(identity);app.toggle_card_history(identity,True);card=app.conversation_cards[identity];outer=card['quote_cards'][0]
            self.assertTrue(g.no_show_all[outer['body_host']]);self.assertFalse(outer['expanded'])
            app.toggle_quote_card(identity,outer['path'],True)
            self.assertTrue(outer['expanded']);self.assertTrue(outer['readers'])
            self.assertTrue(all(g.visible[reader.widget] for reader in outer['readers']))
            nested=card['quote_cards'][-1];self.assertFalse(nested['expanded']);self.assertTrue(g.no_show_all[nested['body_host']])
            app.toggle_quote_card(identity,nested['path'],True)
            self.assertTrue(all(g.visible[reader.widget] for reader in nested['readers']))
            old_reader=nested['readers'][0];app.toggle_quote_card(identity,outer['path'],False);self.assertFalse(old_reader.closed)
            app.toggle_quote_card(identity,nested['path'],False);self.assertTrue(old_reader.closed)
            app.toggle_quote_card(identity,nested['path'],True)
            app.toggle_quote_card(identity,outer['path'],True)
            self.assertTrue(all(g.visible[reader.widget] for quote in card['quote_cards'] for reader in quote['readers']))
