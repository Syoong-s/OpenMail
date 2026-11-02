"""Native isolated acceptance for local mail actions, navigation and first fitted paint."""
import argparse
import ctypes as C
from email.message import EmailMessage
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


# ==========================================
# Function: Drive real native widgets through synthetic mailbox interactions.
# Method: Wait for explicit completion states, preserving timings independently of network work.
# ==========================================
class Scenario:
    # ==========================================
    # Function: Own one finite acceptance state machine and its native callback.
    # Method: Retain only synthetic IDs, widget references and anonymous metrics.
    # ==========================================
    def __init__(self,app,output):
        self.app=app;self.output=output;self.step=0;self.deadline=time.monotonic()+120
        self.metrics={};self.checks=[];self.error='';self.complete=False;self.read_index=0;self.logged_step=None
        self.callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.tick)

    # ==========================================
    # Function: Begin acceptance after the app's own activation initializes native widgets.
    # Method: Schedule a short nonblocking timer on the same GTK main loop.
    # ==========================================
    def start(self,*unused):self.app.g.g_timeout_add(25,C.cast(self.callback,C.c_void_p),None)

    # ==========================================
    # Function: Begin one measured navigation without timing setup or message generation.
    # Method: Record a monotonic timestamp immediately before invoking production navigation.
    # ==========================================
    def read(self):
        self.started=time.perf_counter();self.app.read(self.ids[self.read_index]);self.next_diagnostic=time.monotonic()+5
        print('Open synthetic mail',self.read_index,flush=True)

    # ==========================================
    # Function: Recognize a fully applied mailbox projection.
    # Method: Require the current scope and an idle native renderer and query channel.
    # ==========================================
    def list_ready(self):
        app=self.app;channel=app.local_loader.channels.get('list',{})
        return not channel.get('running') and not channel.get('wanted') and not getattr(app,'list_renderer',None) and getattr(app,'rendered_mail_context',None)==app.mail_list_context()

    # ==========================================
    # Function: Exercise first paint, row retention, folder caching, sidebar state and chat removals.
    # Method: Use only application entry points and real native widgets over disposable demo data.
    # ==========================================
    def tick(self,*unused):
        app=self.app;g=app.g
        try:
            if self.step!=self.logged_step:self.logged_step=self.step;print('Mail responsiveness step',self.step,flush=True)
            assert time.monotonic()<self.deadline,('timeout',self.step)
            if not app.service:return 1
            store=app.service.store
            if self.step==0:
                for key,value in (('notifications','off'),('close_to_tray',False),('mark_read_on_open',False),('motion','off'),('active_inbox_view','classic')):store.set_preference(key,value)
                sources=[]
                for index in range(160):
                    message=EmailMessage();message['From']='Fixture Sender <fixture@example.invalid>';message['To']='demo@example.com'
                    message['Message-ID']=f'<responsiveness-{index}@example.invalid>';message['Subject']=f'Synthetic mail {index}'
                    message.set_content('Synthetic plain content')
                    message.add_alternative('<table style="width:560px;border:1px solid #888"><tr><td><h2>Local mail fixture</h2><p>'+('排版测试 synthetic text '*8)+'</p></td></tr></table><div style="height:900px"><br></div><script>window.ATTACK=1</script>',subtype='html')
                    sources.append({'uid':str(index+1),'raw':message.as_bytes()})
                identities=store.ingest_many('demo','INBOX','responsive',sources);self.ids=identities[-4:]
                app.service.update(identities[0],{'pinned':True});app.service.update(identities[1],{'category':'verification'})
                app.set_view('inbox');self.step=1
            elif self.step==1:
                if not self.list_ready():return 1
                self.metrics['initial_list']=getattr(app,'last_projection_timing',{})
                self.read();self.step=2
            elif self.step==2:
                card=app.conversation_cards.get(self.ids[self.read_index]);reader=card.get('reader') if card else None
                if time.monotonic()>self.next_diagnostic:
                    self.next_diagnostic=time.monotonic()+5
                    print('Reader wait',self.read_index,{'selected':app.selected==self.ids[self.read_index],'card':bool(card),'reader':bool(reader),'ready':getattr(reader,'document_ready',None),'fitted':getattr(reader,'layout_ready',None),'height':getattr(reader,'fit_height',None),'query':getattr(reader,'fit_query',None),'closed':getattr(reader,'closed',None),'measurement':getattr(reader,'fit_last_measurement',None),'allocation':g.gtk_widget_get_allocated_height(reader.widget) if reader else None},flush=True)
                if not reader or not reader.document_ready or not getattr(reader,'layout_ready',True):return 1
                self.metrics.setdefault('open_seconds',[]).append(time.perf_counter()-self.started)
                self.metrics.setdefault('read_preparation',[]).append(app.last_read_timing)
                self.read_index+=1
                if self.read_index<4:self.read();return 1
                self.reader=reader;self.reader_handle=getattr(reader,'handle',None);self.rows=dict(app.rows)
                self.identity=self.ids[-1];self.started=time.perf_counter();app.quick_action(self.identity,'seen');self.step=3
            elif self.step==3:
                if not store.state(self.identity)['seen'] or not self.list_ready() or not app.current['seen']:return 1
                assert self.rows==app.rows,'Read action rebuilt mailbox rows'
                assert app.conversation_cards[self.identity]['reader'] is self.reader,'Read action replaced rich reader'
                self.metrics['read_action_seconds']=time.perf_counter()-self.started
                self.metrics['reader_reused']=getattr(app,'reader_pool_reused',0)
                self.checks.append('local-read-keeps-native-rows-and-rich-reader')
                app.quick_action(self.identity,'done');self.step=4
            elif self.step==4:
                if store.state(self.identity)['folder']!='Archive' or not self.list_ready() or self.identity in app.rows.values():return 1
                assert store.state(self.identity)['done']
                self.checks.append('done-is-archive-with-immediate-row-removal')
                app.service.store.set_preference('active_inbox_view','focused');app.set_view('inbox');self.step=5
            elif self.step==5:
                if not self.list_ready():return 1
                assert 'verification' in app.summary_rows and 'pinned' in app.summary_rows
                app.open_folder('demo','Archive');self.step=6
            elif self.step==6:
                if not self.list_ready():return 1
                self.started=time.perf_counter();app.set_view('inbox');self.step=7
            elif self.step==7:
                if 'verification' in app.summary_rows and 'pinned' in app.summary_rows:self.metrics.setdefault('focused_cards_seconds',time.perf_counter()-self.started)
                if not self.list_ready():return 1
                self.metrics['focused_return_seconds']=time.perf_counter()-self.started
                self.metrics['native_rows_reused']=getattr(app,'mail_rows_reused',0)
                self.metrics['focused_return_render']=app.last_projection_timing
                assert 'verification' in app.summary_rows and 'pinned' in app.summary_rows
                self.checks.append('focused-cards-return-from-cached-projection')
                store.folder_options('demo','Archive',subscribed=False)
                app.open_folder('demo','Archive');self.step=8
            elif self.step==8:
                if not self.list_ready():return 1
                app.open_navigation('folders_menu');entry=app.folder_row_widgets[('demo','Archive')]
                self.check_sidebar(entry)
                self.until=time.monotonic()+.15;self.step=81
            elif self.step==81:
                if time.monotonic()<self.until:return 1
                self.snapshot('folders.png')
                app.open_navigation('navigation_menu')
                self.until=time.monotonic()+.15;self.step=82
            elif self.step==82:
                if time.monotonic()<self.until:return 1
                opacity=g.libs['gtk'].gtk_widget_get_opacity;opacity.restype=C.c_double;opacity.argtypes=[C.c_void_p]
                assert opacity(app.view_pin_buttons['done'])==1
                self.checks.append('sidebar-single-selection-full-color-and-persistent-pin')
                self.snapshot('sidebar.png')
                app.close_navigation();store.set_preference('active_inbox_view','conversations');app.set_view('inbox');self.step=9
            elif self.step==9:
                if not self.list_ready():return 1
                item=next((row for row in app.items if row.get('contact_address')=='fixture@example.invalid'),None)
                if not item:return 1
                self.key=item['key'];self.unread=item['unread_count'];app.read_chat(self.key);self.step=10
            elif self.step==10:
                if app.chat_loading or not app.chat_items:return 1
                self.target=next(row['id'] for row in reversed(app.chat_items) if not row['seen']);self.chat_rows=dict(app.rows)
                app.quick_action(self.target,'seen');self.step=11
            elif self.step==11:
                if not self.list_ready() or app.chat_loading:return 1
                item=next(row for row in app.items if row.get('key')==self.key)
                if item['unread_count']!=self.unread-1:return 1
                assert app.rows==self.chat_rows,'Read badge update recreated contact rows'
                card=app.chat_surface.conversation_cards[self.target]
                has_class=g.libs['gtk'].gtk_style_context_has_class;has_class.argtypes=[C.c_void_p,C.c_char_p];has_class.restype=C.c_int
                assert card['metadata']['seen'];assert has_class(g.gtk_widget_get_style_context(card['state_buttons']['seen']),b'state-enabled')
                self.checks.append('contact-unread-badge-and-card-state-update-locally')
                app.quick_action(self.target,'trash');self.step=12
            elif self.step==12:
                if not self.list_ready() or app.chat_loading or any(row['id']==self.target for row in app.chat_items):return 1
                assert self.target not in app.chat_surface.conversation_cards
                self.checks.append('trashed-bubble-removed-from-retained-timeline')
                app.open_folder('demo','Archive');self.step=13
            elif self.step==13:
                if not self.list_ready():return 1
                app.read(self.identity);self.step=14
            elif self.step==14:
                if app.pending_read_identity or not app.current or app.current['id']!=self.identity:return 1
                app.local_loader.action(lambda:app.service.permanently_delete(self.identity),lambda result:app.mail_changed([self.identity]),app.show_error)
                self.step=15
            elif self.step==15:
                if not self.list_ready() or app.current:return 1
                assert self.identity not in app.conversation_cards
                self.checks.append('removed-source-clears-selected-reader')
                self.complete=True;app.on_delete(force=True);return 0
        except Exception as error:
            import traceback
            traceback.print_exc();self.error=repr(error);app.on_delete(force=True);return 0
        return 1

    # ==========================================
    # Function: Inspect actual computed GTK backgrounds and unsubscribe opacity.
    # Method: Query native style contexts at current state rather than matching CSS source text.
    # ==========================================
    def check_sidebar(self,entry):
        g=self.app.g;gtk=g.libs['gtk']
        rgba=C.c_double*4
        color=gtk.gtk_style_context_get_background_color;color.argtypes=[C.c_void_p,C.c_int,C.c_void_p];color.restype=None
        state=gtk.gtk_style_context_get_state;state.argtypes=[C.c_void_p];state.restype=C.c_int
        opacity=gtk.gtk_widget_get_opacity;opacity.restype=C.c_double;opacity.argtypes=[C.c_void_p]
        self.metrics['sidebar_colors']={}
        for name in ('button','line'):
            context=g.gtk_widget_get_style_context(entry[name]);value=rgba();color(context,state(context),C.byref(value))
            self.metrics['sidebar_colors'][name]=list(value)
        assert self.metrics['sidebar_colors']['button'][3]==0,self.metrics['sidebar_colors']
        assert self.metrics['sidebar_colors']['line'][3]>0,self.metrics['sidebar_colors']
        assert opacity(entry['button'])==1

    # ==========================================
    # Function: Save the GTK sidebar rendering even when Windows drawable capture returns black.
    # Method: Draw native GTK controls to Cairo; this diagnostic intentionally excludes native browser HWNDs.
    # ==========================================
    def snapshot(self,name):
        from maildesk.platform_native import load_library
        cairo=load_library('cairo');g=self.app.g;pointer=C.c_void_p;integer=C.c_int
        signatures={'cairo_image_surface_create':(pointer,integer,integer,integer),'cairo_create':(pointer,pointer),
                    'cairo_surface_write_to_png':(integer,pointer,C.c_char_p),'cairo_destroy':(None,pointer),'cairo_surface_destroy':(None,pointer)}
        for key,value in signatures.items():function=getattr(cairo,key);function.restype=value[0];function.argtypes=value[1:]
        draw=g.libs['gtk'].gtk_widget_draw;draw.restype=None;draw.argtypes=[pointer,pointer]
        surface=cairo.cairo_image_surface_create(0,g.gtk_widget_get_allocated_width(self.app.window),g.gtk_widget_get_allocated_height(self.app.window));context=cairo.cairo_create(surface)
        try:draw(self.app.window,context);assert cairo.cairo_surface_write_to_png(surface,str(self.output/name).encode())==0
        finally:cairo.cairo_destroy(context);cairo.cairo_surface_destroy(surface)


# ==========================================
# Function: Run the current checkout with existing native runtimes and isolated mailbox storage.
# Method: Redirect profile roots, forbid provider access and save only synthetic diagnostics.
# ==========================================
def main(scenario_type=Scenario):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':os.environ.setdefault('TELEMAIL_WINDOWS_RUNTIME',str(Path(sys.executable).resolve().parent.parent))
    with tempfile.TemporaryDirectory(prefix='telemail-responsive-') as temporary:
        root=Path(temporary)
        for key in ('APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
            (root/key).mkdir();os.environ[key]=str(root/key)
        from maildesk.desktop import DesktopApp
        from maildesk.gtk_native import GtkNative
        fonts=GtkNative.fonts
        font_path=Path(sys.executable).resolve().parents[2]/'app/maildesk/desktop_assets/fonts' if os.name=='nt' else None
        options=SimpleNamespace(demo=True,config=root/'accounts.json',data=root/'mail',self_test=False,report=None,screenshot=None)
        with patch('maildesk.transport.imap_connection',side_effect=AssertionError('Unexpected provider access')) as provider,patch('maildesk.transport.deliver',side_effect=AssertionError('Unexpected SMTP')):
            if font_path and font_path.is_dir():
                with patch.object(GtkNative,'fonts',lambda native,path:fonts(native,font_path)):app=DesktopApp(options)
            else:app=DesktopApp(options)
            scenario=scenario_type(app,args.output);app.g.connect(app.application,'activate',scenario.start)
            app.run();assert not provider.called
        report={'ok':scenario.complete,'error':scenario.error,'checks':scenario.checks,'metrics':scenario.metrics,'python':sys.version.split()[0],'platform':sys.platform,'real_provider_calls':0}
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,ensure_ascii=True));return 0 if scenario.complete else 1


if __name__=='__main__':raise SystemExit(main())
