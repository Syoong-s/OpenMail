"""Isolated native acceptance and design captures for the overview and reader menu."""
import ctypes as C
from datetime import date,datetime,timedelta,time as civil_time
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_mail_responsiveness import Scenario,main


# ==========================================
# Function: Verify the overview with realistic synthetic activity and no provider access.
# Method: Exercise actual GTK buttons, account/date scopes and live menu state before saving design captures.
# ==========================================
class ActivityScenario(Scenario):
    # ==========================================
    # Function: Generate deterministic received/sent history for the native calendar.
    # Method: Keep all data in the runner's disposable demo store and avoid random screenshot variation.
    # ==========================================
    def seed(self):
        store=self.app.service.store;today=date.today();incoming=[];outgoing=[]
        people=[('林夏','linxia@example.invalid','研究讨论的后续安排'),('设计团队','design@example.invalid','新版界面：细节与反馈'),('陈舟','chen@example.invalid','项目笔记与数据已更新'),('深空周刊','space@example.invalid','本周精选：探索宇宙的新视角')]
        for index in range(620):
            days=0 if index<8 else 2+(index*29)%363
            if index>=8 and days%7 in (0,6):continue
            sent=index%4==1;name,address,subject=people[index%4]
            mail=EmailMessage();mail['From']='我 <demo@example.com>' if sent else f'{name} <{address}>'
            mail['To']=f'{name} <{address}>' if sent else '我 <demo@example.com>';mail['Subject']=('Re: ' if sent else '')+subject
            mail['Message-ID']=f'<activity-native-{index}@example.invalid>'
            mail['Date']=format_datetime(datetime.combine(today-timedelta(days=days),civil_time(16-index%8,24)).astimezone())
            mail.set_content('已整理好这次讨论的要点，方便时请查看。我们可以在下次会议继续交流。')
            (outgoing if sent else incoming).append({'uid':str(1000+index),'raw':mail.as_bytes()})
        self.ids=store.ingest_many('demo','INBOX','activity',incoming)
        store.ingest_many('demo','Sent','activity',outgoing)

    # ==========================================
    # Function: Recognize a current visible overview after its latest-only metadata request.
    # Method: Require a painted calendar and a matching completed local revision.
    # ==========================================
    def ready(self):
        activity=self.app.activity
        return activity.visible and activity.data and not activity.pending and len(activity.heatmap.cells)>360 and self.app.g.gtk_stack_get_visible_child_name(self.app.widget('reader_stack'))==b'activity' and self.app.g.gtk_widget_get_mapped(activity.root)

    # ==========================================
    # Function: Inspect actual selected styling instead of asserting CSS source strings.
    # Method: Query the live button style context and native short caption.
    # ==========================================
    def menu_active(self,key):
        entry=self.app.mail_menu_entries[key];g=self.app.g
        has=g.libs['gtk'].gtk_style_context_has_class;has.restype=C.c_int;has.argtypes=[C.c_void_p,C.c_char_p]
        return bool(has(g.gtk_widget_get_style_context(entry['button']),b'mail-menu-selected'))

    # ==========================================
    # Function: Run dashboard actions, day navigation, menu toggles and dark/light visual captures.
    # Method: Retain widget IDs across local actions and wait for explicit completion states, never arbitrary network timing.
    # ==========================================
    def tick(self,*unused):
        app=self.app;g=app.g
        try:
            if self.step!=self.logged_step:self.logged_step=self.step;print('Activity step',self.step,flush=True)
            assert time.monotonic()<self.deadline,('timeout',self.step)
            if not app.service:return 1
            assert hasattr(app,'activity'),'Overview failed to initialize'
            store=app.service.store;activity=app.activity
            if self.step==0:
                for key,value in (('notifications','off'),('close_to_tray',False),('mark_read_on_open',False),('motion','off'),('active_inbox_view','classic')):store.set_preference(key,value)
                self.seed();app.apply_appearance();self.started=time.perf_counter();app.set_view('inbox');self.step=1
            elif self.step==1:
                if not self.ready() or not self.list_ready():return 1
                self.metrics['first_overview_seconds']=time.perf_counter()-self.started
                assert g.gtk_stack_get_visible_child_name(app.widget('reader_stack'))==b'activity'
                assert activity.data['sent']>0 and activity.data['received']>0
                self.until=time.monotonic()+.2;self.step=2
            elif self.step==2:
                if time.monotonic()<self.until:return 1
                self.snapshot('overview-dark.png');self.checks.append('idle-reader-shows-painted-calendar-and-real-daily-counts')
                self.target=self.ids[0];entry=activity.rows[self.target];self.row_handle=entry['root'];self.old_seen=entry['item']['seen']
                self.action_started=time.perf_counter();g.gtk_button_clicked(entry['seen']);self.step=3
            elif self.step==3:
                if not self.ready() or activity.rows[self.target]['item']['seen']==self.old_seen:return 1
                assert activity.rows[self.target]['root']==self.row_handle
                self.metrics['overview_read_action_seconds']=time.perf_counter()-self.action_started
                assert not app.selected,'Overview action changed reader selection'
                g.gtk_button_clicked(activity.rows[self.target]['done']);self.step=4
            elif self.step==4:
                if not self.ready() or not activity.rows[self.target]['item']['done']:return 1
                assert store.state(self.target)['folder']=='Archive'
                assert activity.rows[self.target]['root']==self.row_handle
                g.gtk_button_clicked(activity.rows[self.target]['trash']);self.step=5
            elif self.step==5:
                if not self.ready() or self.target in activity.rows:return 1
                self.checks.append('read-and-archive-update-retained-timeline-trash-removes-only-target')
                g.gtk_button_clicked(activity.previous);self.step=6
            elif self.step==6:
                if not self.ready():return 1
                assert activity.selected==date.today()-timedelta(days=1)
                assert activity.data['total']==0 and g.gtk_widget_get_visible(activity.empty)
                self.checks.append('date-navigation-shows-honest-empty-day')
                g.gtk_button_clicked(activity.today_button);self.step=7
            elif self.step==7:
                if not self.ready():return 1
                self.target=next(row['id'] for row in activity.data['items'] if row['direction']=='received')
                g.gtk_button_clicked(activity.rows[self.target]['open']);self.step=8
            elif self.step==8:
                if app.pending_read_identity or not app.current or app.current['id']!=self.target:return 1
                assert not activity.visible
                g.gtk_button_clicked(app.widget('aside'));self.step=9
            elif self.step==9:
                if not app.current.get('aside'):return 1
                assert self.menu_active('aside')
                store.organize(self.target,labels=['项目'],reminder=time.time()+3600);app.mail_changed([self.target])
                assert self.menu_active('labels') and self.menu_active('reminder')
                g.gtk_revealer_set_reveal_child(app.widget('toast_revealer'),0)
                g.gtk_toggle_button_set_active(app.widget('more_actions'),1);self.until=time.monotonic()+.2;self.step=10
            elif self.step==10:
                if time.monotonic()<self.until:return 1
                self.snapshot('reader-menu-dark.png')
                g.gtk_button_clicked(app.widget('aside'));self.step=11
            elif self.step==11:
                if app.current.get('aside'):return 1
                assert not self.menu_active('aside');self.checks.append('short-menu-labels-highlight-aside-reminder-and-labels-live')
                app.service.move_message(self.target,special='spam');app.open_folder('demo','Spam');app.read(self.target);self.step=12
            elif self.step==12:
                if app.pending_read_identity or not app.current or app.current['id']!=self.target:return 1
                assert self.menu_active('spam');g.gtk_button_clicked(app.widget('spam'));self.step=13
            elif self.step==13:
                if store.state(self.target)['folder']!='INBOX' or app.current.get('spam') or self.menu_active('spam'):return 1
                self.checks.append('junk-menu-toggle-restores-real-inbox-location')
                app.close_mail();app.set_view('inbox');store.set_preference('theme','light');app.apply_appearance()
                g.gtk_revealer_set_reveal_child(app.widget('toast_revealer'),0);self.step=14
            elif self.step==14:
                if not self.ready() or not self.list_ready():return 1
                self.until=time.monotonic()+.2;self.step=15
            elif self.step==15:
                if time.monotonic()<self.until:return 1
                assert self.ready() and g.gtk_widget_get_mapped(activity.body)
                getter=g.libs['gtk'].gtk_adjustment_get_value;getter.restype=C.c_double;getter.argtypes=[C.c_void_p]
                self.metrics['light_page']={'stack':g.gtk_stack_get_visible_child_name(app.widget('reader_stack')).decode(),'body_height':g.gtk_widget_get_allocated_height(activity.body),'scroll':getter(g.gtk_scrolled_window_get_vadjustment(activity.root))}
                self.snapshot('overview-light.png');self.checks.append('closing-reader-restores-overview-with-light-theme')
                resize=g.libs['gtk'].gtk_window_resize;resize.restype=None;resize.argtypes=[C.c_void_p,C.c_int,C.c_int]
                resize(app.window,1050,750);self.until=time.monotonic()+.3;self.step=16
            elif self.step==16:
                if time.monotonic()<self.until:return 1
                width=g.gtk_widget_get_allocated_width(activity.heatmap.widget)
                assert max(left+size for day,left,top,size in activity.heatmap.cells)<=width
                self.metrics['narrow_calendar']={'width':width,'height':g.gtk_widget_get_allocated_height(activity.heatmap.widget),'requested_height':activity.heatmap.height}
                assert g.gtk_widget_get_allocated_height(activity.heatmap.widget)<=activity.heatmap.height+2,self.metrics['narrow_calendar']
                self.snapshot('overview-narrow.png');self.checks.append('calendar-remains-within-narrow-reader-width')
                store.set_preference('active_inbox_view','conversations');app.set_view('inbox');self.step=17
            elif self.step==17:
                if not self.list_ready() or not self.ready():return 1
                contact=next(item for item in app.items if item.get('contact_address')=='linxia@example.invalid')
                app.read_chat(contact['key']);self.step=18
            elif self.step==18:
                if app.chat_loading or not app.chat_composer:return 1
                assert not activity.visible;app.close_mail();self.step=19
            elif self.step==19:
                if not self.ready():return 1
                assert not app.selected_chat and not app.selected
                self.checks.append('empty-contact-view-and-closed-chat-return-to-overview')
                self.complete=True;app.on_delete(force=True);return 0
        except Exception as error:
            import traceback
            traceback.print_exc();self.error=repr(error);app.on_delete(force=True);return 0
        return 1


if __name__=='__main__':raise SystemExit(main(ActivityScenario))
