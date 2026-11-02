"""Native bilingual acceptance and README captures using isolated synthetic mail."""
import argparse
import ctypes as C
from datetime import date,datetime,timedelta,time as civil_time
from email.message import EmailMessage
from email.utils import format_datetime
import os
from pathlib import Path
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_mail_responsiveness import Scenario,main


# ==========================================
# Function: Inspect actual bilingual widgets without accessing any real mailbox.
# Method: Generate local fixtures, visit every settings page and inspect visible labels before capturing README images.
# ==========================================
class LocalizationScenario(Scenario):
    # ==========================================
    # Function: Build matching Chinese and English demo history for documentation.
    # Method: Use local synthetic envelopes; the provider calls remain blocked by the shared runner.
    # ==========================================
    def seed(self):
        from maildesk.i18n import language
        self.lang=language();en=self.lang=='en';store=self.app.service.store
        with store.db() as db:db.execute('DELETE FROM messages')
        people= [('Alex Chen','alex@example.invalid','Notes for our next research session'),('Studio North','studio@example.invalid','A calmer workspace, down to the details'),('Maya Lin','maya@example.invalid','The new data and project notes are ready'),('Field Notes','notes@example.invalid','This week: a different view of the universe')] if en else [('陈舟','alex@example.invalid','下一次研究讨论：准备与安排'),('北岸设计','studio@example.invalid','更舒适的工作空间，从细节开始'),('林夏','maya@example.invalid','新的数据与项目笔记已整理完成'),('深空周刊','notes@example.invalid','本周精选：换个角度看宇宙')]
        incoming=[];outgoing=[];today=date.today()
        for index in range(620):
            days=0 if index<8 else 2+(index*29)%363
            if index>=8 and (days%7 in (0,6) or index%11<3):continue
            sent=index%4==1;name,address,subject=people[index%4];mail=EmailMessage()
            mail['From']=('Me' if en else '我')+' <demo@example.com>' if sent else f'{name} <{address}>'
            mail['To']=f'{name} <{address}>' if sent else 'demo@example.com';mail['Subject']=('Re: ' if sent else '')+subject
            mail['Message-ID']=f'<readme-{index}@example.invalid>';mail['Date']=format_datetime(datetime.combine(today-timedelta(days=days),civil_time(16-index%8,24)).astimezone())
            mail.set_content('I have collected the key points from our discussion. Take a look when you have a moment; we can follow up at the next meeting.' if en else '已整理好这次讨论的要点，方便时请查看。我们可以在下次会议继续交流。')
            (outgoing if sent else incoming).append({'uid':str(1000+index),'raw':mail.as_bytes(),'seen':index%3==0})
        self.ids=store.ingest_many('demo','INBOX','readme',incoming);store.ingest_many('demo','Sent','readme',outgoing)
        for identity,changes in zip(self.ids[:4],({'pinned':True},{'category':'verification'},{'category':'notification'},{'category':'newsletter'})):self.app.service.update(identity,changes)

    # ==========================================
    # Function: Read native visible labels and tooltips without translating user content implicitly.
    # Method: Walk public GTK container children and inspect presentation values from real widgets.
    # ==========================================
    def inspect(self,root):
        g=self.app.g;gtk=g.libs['gtk'];getter=gtk.gtk_label_get_text;getter.restype=C.c_char_p;getter.argtypes=[C.c_void_p]
        container_type=gtk.gtk_container_get_type;container_type.restype=C.c_size_t;container_type.argtypes=[]
        tips=gtk.gtk_widget_get_tooltip_text;tips.restype=C.c_void_p;tips.argtypes=[C.c_void_p]
        pending=[root];strings=[]
        while pending:
            widget=pending.pop()
            if not g.gtk_widget_get_mapped(widget):continue
            if g.g_type_check_instance_is_a(widget,g.gtk_label_get_type()):strings.append((getter(widget) or b'').decode())
            tooltip=tips(widget)
            if tooltip:
                strings.append(C.string_at(tooltip).decode());g.g_free(tooltip)
            if g.g_type_check_instance_is_a(widget,container_type()):
                head=g.gtk_container_get_children(widget);cursor=head
                while cursor:pending.append(cursor.contents.data);cursor=cursor.contents.next
                g.g_list_free(head)
        return strings

    # ==========================================
    # Function: Reject untranslated interface text in English captures.
    # Method: Exempt only the Chinese language's self-name; mail fixtures use the requested documentation language.
    # ==========================================
    def audit(self,name):
        strings=self.inspect(self.app.window)
        if self.lang=='en':
            leftover=[text for text in strings if re.search('[\u4e00-\u9fff]',text) and text!='简体中文']
            assert not leftover,(name,leftover)
        self.checks.append(name)

    # ==========================================
    # Function: Visit primary surfaces and every settings route in the chosen language.
    # Method: Wait for completed projections and GTK allocation, save actual screenshots and exercise persisted language selection.
    # ==========================================
    def tick(self,*unused):
        app=self.app;g=app.g
        try:
            if self.step!=self.logged_step:self.logged_step=self.step;print('Localization step',self.step,flush=True)
            assert time.monotonic()<self.deadline,('timeout',self.step)
            if not app.service:return 1
            store=app.service.store
            if self.step==0:
                self.seed()
                for key,value in (('interface_language',self.lang),('notifications','off'),('close_to_tray',False),('mark_read_on_open',False),('motion','off'),('active_inbox_view','focused')):store.set_preference(key,value)
                app.apply_appearance();app.set_view('inbox');self.step=1
            elif self.step==1:
                if not self.list_ready() or not app.activity.data or app.activity.pending:return 1
                self.until=time.monotonic()+.3;self.step=2
            elif self.step==2:
                if time.monotonic()<self.until:return 1
                self.audit('main-'+self.lang);self.snapshot('main-'+self.lang+'.png')
                app.open_navigation('navigation_menu');self.until=time.monotonic()+.2;self.step=3
            elif self.step==3:
                if time.monotonic()<self.until:return 1
                self.audit('mailboxes-'+self.lang);app.close_navigation();app.read(self.ids[0]);self.step=4
            elif self.step==4:
                if app.pending_read_identity or not app.current:return 1
                g.gtk_toggle_button_set_active(app.widget('more_actions'),1);self.until=time.monotonic()+.2;self.step=5
            elif self.step==5:
                if time.monotonic()<self.until:return 1
                self.audit('reader-menu-'+self.lang);self.snapshot('reader-menu-'+self.lang+'.png')
                g.gtk_toggle_button_set_active(app.widget('more_actions'),0);app.close_mail()
                from maildesk.desktop_settings import settings_dialog,PAGES
                self.pages=[key for key,title in PAGES];self.page_index=0
                app.queue.put((lambda unused:settings_dialog(app,self.pages[0]),None));self.step=6
            elif self.step==6:
                if not getattr(app,'settings_form',None):return 1
                self.until=time.monotonic()+.3;self.step=7
            elif self.step==7:
                if time.monotonic()<self.until:return 1
                self.audit('settings-'+self.pages[self.page_index]+'-'+self.lang)
                if self.pages[self.page_index]=='appearance':
                    assert app.settings_form.value('interface_language')==self.lang
                    self.snapshot('settings-'+self.lang+'.png')
                self.page_index+=1
                if self.page_index<len(self.pages):
                    g.gtk_stack_set_visible_child_name(g.object(app.settings_form.builder,'settings_stack'),self.pages[self.page_index].encode());self.until=time.monotonic()+.2
                else:
                    app.settings_form.value('interface_language','zh_CN' if self.lang=='en' else 'en')
                    g.gtk_dialog_response(app.settings_form.window,1);self.step=8
            elif self.step==8:
                if getattr(app,'settings_form',None):return 1
                assert store.preference('interface_language')==('zh_CN' if self.lang=='en' else 'en')
                from maildesk.i18n import language
                assert language()==self.lang,'Language changed before restart'
                self.checks.append('language-saved-without-changing-open-session')
                app.open_composer();self.until=time.monotonic()+.3;self.step=9
            elif self.step==9:
                if time.monotonic()<self.until:return 1
                self.audit('composer-'+self.lang);self.snapshot('composer-'+self.lang+'.png')
                app.composer.value('subject','收件箱');assert app.composer.value('subject')=='收件箱'
                app.composer.value('subject','');app.composer.close();app.composer=None
                from maildesk.scheduling import choose_schedule
                app.queue.put((lambda unused:choose_schedule(app),None));self.until=time.monotonic()+.3;self.step=10
            elif self.step==10:
                if not app.active_forms:return 1
                self.until=time.monotonic()+.8;self.step=11
            elif self.step==11:
                if time.monotonic()<self.until:return 1
                self.snapshot('schedule-'+self.lang+'.png')
                if (self.output/('schedule-'+self.lang+'.png')).stat().st_size<10000:
                    self.until=time.monotonic()+.25;return 1
                self.audit('schedule-'+self.lang)
                g.gtk_dialog_response(app.active_forms[-1].window,-6);self.step=12
            elif self.step==12:
                if app.active_forms:return 1
                self.complete=True;app.on_delete(force=True);return 0
        except Exception as error:
            import traceback
            traceback.print_exc();self.error=repr(error);app.on_delete(force=True);return 0
        return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--language',choices=['en','zh_CN'],required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    os.environ['TELEMAIL_LANGUAGE']=args.language;sys.argv=[sys.argv[0],'--output',args.output]
    raise SystemExit(main(LocalizationScenario))
