"""Modern native composer layout and accessible viewport policy regressions."""
import unittest
import xml.etree.ElementTree as ET
from maildesk.composer_layout import composer_xml, composer_geometry

# ==========================================
# Function: Verify real native layout definitions without a display connection.
# Method: Parse GtkBuilder markup and test small, normal and expanded viewport geometry.
# ==========================================
class ModernComposerTests(unittest.TestCase):
    # ==========================================
    # Function: Retain all editable state while replacing the generic form surface.
    # Method: Inspect the actual GtkBuilder layout consumed by Composer.
    # ==========================================
    def test_modern_layout_has_one_footer_and_editable_body(self):
        root=ET.fromstring(composer_xml([('demo','demo@example.com')]))
        objects={node.get('id'):node for node in root.iter('object') if node.get('id')}
        self.assertEqual(objects['body'].get('class'),'GtkTextView')
        self.assertTrue({'account','to','cc','bcc','subject','body','due','followup','note'}<=objects.keys())
        self.assertEqual(objects['composer_footer'].get('class'),'GtkBox')
        self.assertFalse(any(node.get('class')=='GtkFlowBox' for node in root.iter('object')))
        for key in ('cc_row','bcc_row','schedule_state'):
            values={p.get('name'):p.text for p in objects[key].findall('property')}
            self.assertEqual(values['no-show-all'],'True')
        self.assertIn(objects['body'],list(objects['body_scroll'].iter('object')))
    # ==========================================
    # Function: Keep a useful editing area and reachable footer across reply viewport sizes.
    # Method: Bound inline height to available reader space and let full composition expand.
    # ==========================================
    def test_geometry_reserves_real_body_and_footer_space(self):
        ordinary=composer_geometry(700,True)
        self.assertGreaterEqual(ordinary['body_height'],180)
        self.assertLessEqual(ordinary['height'],600)
        self.assertGreaterEqual(ordinary['height']-ordinary['body_height'],120)
        short=composer_geometry(350,True)
        self.assertGreaterEqual(short['body_height'],130)
        self.assertLessEqual(short['height'],330)
        full=composer_geometry(800,False)
        self.assertTrue(full['expand']);self.assertEqual(full['height'],-1)

    # ==========================================
    # Function: Reserve inline reply space using the actual conversation clip, not its taller parent.
    # Method: Model a small high-scale window where title/toolbars reduce the visible scroller height.
    # ==========================================
    def test_inline_viewport_uses_clipped_conversation_height(self):
        from types import SimpleNamespace
        from maildesk.composer_layout import composer_viewport
        g=SimpleNamespace(gtk_widget_get_allocated_width=lambda widget:800,gtk_widget_get_allocated_height=lambda widget:383 if widget==4 else 550,
            gtk_widget_get_ancestor=lambda *args:3,gtk_scrolled_window_get_type=lambda:9,gtk_bin_get_child=lambda widget:4)
        self.assertEqual(composer_viewport(g,1,2,True),(800,383))
        self.assertEqual(composer_viewport(g,1,2,False),(800,550))
        g.gtk_widget_get_allocated_height=lambda widget:1 if widget==4 else 550
        self.assertEqual(composer_viewport(g,1,2,True),(800,550))

    # ==========================================
    # Function: Coalesce allocation work and reject delayed sizing after editor destruction.
    # Method: Drive the production deferred-size callback with a recording native timer boundary.
    # ==========================================
    def test_deferred_size_coalesces_and_does_not_touch_closed_editor(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import ctypes as C
        from maildesk.composer_layout import ComposerLayout
        editor=ComposerLayout();editor.closed=False;editor.layout_size_timer=0
        editor.size_surface=MagicMock();editor.layout_size_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(editor.apply_surface_size)
        timer=MagicMock(return_value=7);editor.g=SimpleNamespace(g_timeout_add=timer)
        editor.queue_surface_size();editor.queue_surface_size();self.assertEqual(timer.call_count,1)
        self.assertEqual(editor.apply_surface_size(),0);editor.size_surface.assert_called_once();self.assertEqual(editor.layout_size_timer,0)
        editor.closed=True;editor.apply_surface_size();editor.queue_surface_size();self.assertEqual(editor.size_surface.call_count,1);self.assertEqual(timer.call_count,1)

# ==========================================
# Function: Verify bounded reader draining without a graphical process or real mailbox.
# Method: Exercise the same clock/process policy used by the native shutdown timer.
# ==========================================
class ReaderShutdownTests(unittest.TestCase):
    # ==========================================
    # Function: Wait for owned renderers and a quiet period while enforcing a hard deadline.
    # Method: Model late children disappearance and stalled processes with deterministic timestamps.
    # ==========================================
    def test_renderer_quiet_window_and_deadline(self):
        from maildesk.reader_shutdown import ReaderDrain
        drain=ReaderDrain(10)
        self.assertFalse(drain.ready(10.1,{123}))
        self.assertFalse(drain.ready(10.3,set()))
        self.assertFalse(drain.ready(10.4,set()))
        self.assertTrue(drain.ready(10.6,set()))
        self.assertTrue(ReaderDrain(10).ready(12.1,{123}))
    # ==========================================
    # Function: Close HTML engines only once and before destroying document widgets.
    # Method: Use a recording native facade around the actual reader cleanup implementation.
    # ==========================================
    def test_html_close_is_idempotent(self):
        from maildesk.document_reader import WebKitHTMLReader as HTMLReader
        from types import SimpleNamespace
        calls=[];reader=HTMLReader.__new__(HTMLReader);reader.widget=1;reader.view=2;reader.group='html';reader.closed=False
        reader.lib=SimpleNamespace(webkit_web_view_stop_loading=lambda widget:calls.append('stop'))
        reader.g=SimpleNamespace(disconnect=lambda group:calls.append('disconnect'))
        reader.close();reader.close();self.assertEqual(calls,['stop','disconnect'])
    # ==========================================
    # Function: Limit renderer observation to owned descendants and ignore zombies.
    # Method: Project a synthetic proc tree containing unrelated and already-exited processes.
    # ==========================================
    def test_owned_renderer_scope(self):
        from maildesk.reader_shutdown import owned_renderers
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from unittest.mock import patch
        with TemporaryDirectory() as temporary:
            root=Path(temporary)
            for pid,name,children,state in [(100,'maildesk','101 102','S'),(101,'WebKitWebProces','103','S'),(102,'unrelated','','S'),(103,'WebKitNetworkPr','','Z'),(200,'WebKitWebProces','','S')]:
                base=root/str(pid);(base/'task'/str(pid)).mkdir(parents=True)
                (base/'task'/str(pid)/'children').write_text(children);(base/'comm').write_text(name)
                (base/'status').write_text('Name:\t'+name+'\nState:\t'+state+' (synthetic)\n')
            with patch('maildesk.reader_shutdown.Path',return_value=root),patch('maildesk.reader_shutdown.os.name','posix'):self.assertEqual(owned_renderers(100),{101})
    # ==========================================
    # Function: Restrict renderer termination to an explicit application-shutdown fallback.
    # Method: Verify normal close is graceful and each shutdown command reaches WebKit at most once.
    # ==========================================
    def test_shutdown_handshake_is_explicit_and_idempotent(self):
        from maildesk.document_reader import WebKitHTMLReader as HTMLReader
        from types import SimpleNamespace
        calls=[];reader=HTMLReader.__new__(HTMLReader);reader.widget=1;reader.view=2;reader.group='html';reader.closed=False
        reader.lib=SimpleNamespace(webkit_web_view_stop_loading=lambda widget:calls.append('stop'),
            webkit_web_view_try_close=lambda widget:calls.append('try-close'),
            webkit_web_view_terminate_web_process=lambda widget:calls.append('terminate'))
        reader.g=SimpleNamespace(disconnect=lambda group:calls.append('disconnect'))
        reader.close();self.assertNotIn('terminate',calls)
        reader.begin_shutdown();reader.begin_shutdown();self.assertEqual(calls,['stop','disconnect','try-close'])
        reader.finish_shutdown();reader.finish_shutdown();self.assertEqual(calls,['stop','disconnect','try-close','terminate'])
    # ==========================================
    # Function: Ignore OS mail activations once shutdown has begun.
    # Method: Exercise both public entry points without permitting URI parsing, activation or native calls.
    # ==========================================
    def test_closing_ignores_mailto_and_os_open(self):
        from maildesk.desktop_general import GeneralUI
        from types import SimpleNamespace
        from unittest.mock import patch
        calls=[];app=SimpleNamespace(closing=True,activate=lambda:calls.append('activate'),
            run_action=lambda action:calls.append('run-action'),open_composer=lambda *args:calls.append('composer'))
        with patch('maildesk.desktop_general.bind',side_effect=AssertionError('native API during close')),patch('maildesk.desktop_general.parse_mailto',side_effect=AssertionError('parse during close')):
            GeneralUI.open_files(app,None,None,1,None,None)
            GeneralUI.open_mailto(app,'mailto:synthetic@example.invalid')
        self.assertEqual(calls,[])
    # ==========================================
    # Function: Reveal populated and explicitly requested secondary recipient widgets completely.
    # Method: Invoke the actual layout disclosure with a native facade that records child-show operations.
    # ==========================================
    def test_secondary_recipients_show_entry_children(self):
        from maildesk.composer_layout import ComposerLayout
        from types import SimpleNamespace
        calls=[];values={'cc':'copy@example.invalid','bcc':''}
        native=SimpleNamespace(object=lambda builder,key:key,
            gtk_widget_set_no_show_all=lambda row,value:calls.append(('no-show-all',row,value)),
            gtk_widget_set_visible=lambda row,value:calls.append(('visible',row,value)),
            gtk_widget_show_all=lambda row:calls.append(('show-all',row)))
        editor=SimpleNamespace(g=native,builder=1,value=lambda key:values[key],size_surface=lambda:None)
        ComposerLayout.reveal_recipients(editor,False)
        self.assertIn(('show-all','cc_row'),calls);self.assertNotIn(('show-all','bcc_row'),calls)
        self.assertIn(('no-show-all','bcc_row',True),calls)
        calls.clear();ComposerLayout.reveal_recipients(editor,True)
        self.assertIn(('show-all','cc_row'),calls);self.assertIn(('show-all','bcc_row'),calls)
        self.assertIn(('no-show-all','bcc_row',False),calls)
    # ==========================================
    # Function: Keep retired HTML widgets outside a parent's recursive destruction tree.
    # Method: Distinguish the bounded GTK surface from its inner WebView using a recording native facade.
    # ==========================================
    def test_reader_retirement_reparents_and_reuses_owned_widget(self):
        from maildesk.document_reader import WebKitHTMLReader as HTMLReader
        from types import SimpleNamespace
        calls=[];native=SimpleNamespace(disconnect=lambda group:calls.append(('disconnect',group)),
            gtk_widget_set_opacity=lambda *args:None,
            gtk_box_new=lambda *args:99,g_object_ref_sink=lambda widget:calls.append(('sink',widget)),
            gtk_widget_get_parent=lambda widget:7,gtk_widget_reparent=lambda widget,parent:calls.append(('reparent',widget,parent)),
            gtk_container_add=lambda parent,widget:calls.append(('add',parent,widget)),
            g_object_ref=lambda widget:calls.append(('ref',widget)),g_object_unref=lambda widget:calls.append(('unref',widget)),
            gtk_container_remove=lambda parent,widget:calls.append(('remove',parent,widget)))
        app=SimpleNamespace(g=native,closing=False)
        reader=HTMLReader.__new__(HTMLReader);reader.app=app;reader.g=native;reader.widget=1;reader.view=2;reader.group='old';reader.closed=False
        reader.source='private old message';reader.original=('private old message',False,None);reader.detached_ref=False
        reader.document_ready=True;reader.pending_image=2;reader.image_navigation=True
        reader.lib=SimpleNamespace(webkit_web_view_stop_loading=lambda widget:calls.append(('stop',widget)),webkit_web_view_load_html=lambda *args:calls.append(('blank',args[0])))
        reader.close();reader.close()
        self.assertEqual(app.reader_idle,[reader]);self.assertIn(('reparent',1,99),calls);self.assertIn(('blank',2),calls)
        self.assertEqual(reader.source,'');self.assertEqual(reader.original,('',False,None))
        self.assertFalse(reader.document_ready);self.assertFalse(reader.image_navigation);self.assertIsNone(reader.pending_image)
        reused=HTMLReader.__new__(HTMLReader);reused.app=app;reused.g=native;reused.lib=reader.lib
        self.assertTrue(reused.take_cached_view());self.assertEqual(reused.widget,1);self.assertEqual(reused.view,2);self.assertEqual(app.reader_idle,[])
        self.assertIn(('remove',99,1),calls);self.assertTrue(reused.detached_ref)
        reused.attached();reused.attached();self.assertEqual(calls.count(('unref',1)),1)
    # ==========================================
    # Function: Keep old pixels hidden until the current document generation finishes.
    # Method: Drive real load callbacks with stale, current and already-closed lease states.
    # ==========================================
    def test_reused_reader_reveals_only_current_load(self):
        from maildesk.document_reader import WebKitHTMLReader as HTMLReader
        from types import SimpleNamespace
        opacities=[];reader=HTMLReader.__new__(HTMLReader);reader.closed=False;reader.widget=1;reader.view=2;reader.source='new document'
        reader.load_generation=2;reader.started_generation=1;reader.expected_title='new-document';current_uri=[b'old-document']
        reader.lib=SimpleNamespace(webkit_web_view_get_title=lambda widget:current_uri[0]);reader.g=SimpleNamespace(gtk_widget_set_opacity=lambda widget,value:opacities.append(value))
        reader.loaded(1,0,None);reader.loaded(1,3,None);self.assertEqual(opacities,[])
        current_uri[0]=b'new-document'
        reader.loaded(1,0,None);reader.loaded(1,3,None);self.assertEqual(opacities,[0,1])
        reader.image_navigation=True;reader.loaded(1,0,None)
        current_uri[0]=b'about:blank#mail-image-1';reader.loaded(1,3,None);self.assertEqual(opacities,[0,1,1,1])
        reader.closed=True;reader.loaded(1,3,None);self.assertEqual(opacities,[0,1,1,1])
