"""Native regression for instant focused cards, direct trash and compact reply routing."""
import ctypes as C
from email.message import EmailMessage
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_mail_responsiveness import Scenario,main


# ==========================================
# Function: Verify focused navigation under deliberately slow queries and real composer layout.
# Method: Reuse the isolated Windows/Linux runner while driving only synthetic messages/accounts.
# ==========================================
class FocusComposerScenario(Scenario):
    # ==========================================
    # Function: Exercise retained cards, group navigation, recipient disclosure and icon activation.
    # Method: Delay worker completion by one second while allowing the real GTK loop to draw.
    # ==========================================
    def tick(self,*unused):
        app=self.app;g=app.g
        try:
            if self.step!=self.logged_step:self.logged_step=self.step;print('Focus/composer step',self.step,flush=True)
            assert time.monotonic()<self.deadline,('timeout',self.step)
            if not app.service:return 1
            store=app.service.store
            if self.step==0:
                for key,value in (('notifications','off'),('close_to_tray',False),('mark_read_on_open',False),('motion','off'),('active_inbox_view','focused')):store.set_preference(key,value)
                sources=[]
                for index in range(40):
                    mail=EmailMessage();mail['From']='Research Team <research@example.invalid>';mail['To']='demo@example.com'
                    mail['Message-ID']=f'<focused-ui-{index}@example.invalid>';mail['Subject']=f'Synthetic focused mail {index}'
                    mail.set_content('Synthetic local-only acceptance message.');sources.append({'uid':str(index+1),'raw':mail.as_bytes()})
                self.ids=store.ingest_many('demo','INBOX','focus-ui',sources)
                for identity,changes in zip(self.ids,({'pinned':True},{'category':'verification'},{'category':'notification'},{'category':'newsletter'})):app.service.update(identity,changes)
                app.set_view('inbox');self.step=1
            elif self.step==1:
                if not self.list_ready():return 1
                self.cards={key:entry['row'] for key,entry in app.summary_rows.items()}
                self.pinned_unread=app.summary_rows['pinned']['section']['unread']
                assert set(self.cards)=={'pinned','verification','notification','newsletter'}
                app.open_folder('demo','Archive');self.step=2
            elif self.step==2:
                if not self.list_ready():return 1
                app.service.update(self.ids[0],{'seen':True});app.local_loader.projections.clear()
                from maildesk.desktop_loading import mailbox_projection
                self.release=threading.Event();self.entered=threading.Event()

                # ==========================================
                # Function: Emulate a busy local database without blocking native event delivery.
                # Method: Hold only the worker; the GTK timer releases it after observing visible cards.
                # ==========================================
                def slow_projection(*args):
                    self.entered.set();assert self.release.wait(5),'Native loop failed to release projection'
                    return mailbox_projection(*args)
                self.query_patch=patch('maildesk.desktop_loading.mailbox_projection',side_effect=slow_projection);self.query_patch.start()
                self.started=time.perf_counter();app.set_view('inbox')
                self.metrics['focused_dispatch_seconds']=time.perf_counter()-self.started
                assert self.cards=={key:entry['row'] for key,entry in app.summary_rows.items()},'Return rebuilt focused cards'
                assert g.gtk_widget_get_visible(app.widget('focus_summaries'))
                self.step=3
            elif self.step==3:
                mapped=g.libs['gtk'].gtk_widget_get_mapped;mapped.restype=C.c_int;mapped.argtypes=[C.c_void_p]
                if all(mapped(row) for row in self.cards.values()):self.metrics.setdefault('focused_mapped_seconds',time.perf_counter()-self.started)
                if time.perf_counter()-self.started<1:return 1
                assert self.entered.is_set() and not self.list_ready()
                assert self.metrics['focused_mapped_seconds']<.3,self.metrics
                self.snapshot('focused-during-slow-query.png');self.release.set();self.query_patch.stop();self.query_patch=None;self.step=4
            elif self.step==4:
                if not self.list_ready():return 1
                self.metrics['slow_projection_complete_seconds']=time.perf_counter()-self.started
                assert self.cards=={key:entry['row'] for key,entry in app.summary_rows.items()}
                assert app.summary_rows['pinned']['section']['unread']==self.pinned_unread-1
                assert g.gtk_widget_get_visible(app.widget('messages'))
                self.checks.append('focused-cards-map-before-one-second-query-and-update-in-place')
                g.gtk_button_clicked(app.summary_rows['verification']['button']);self.step=5
            elif self.step==5:
                if not self.list_ready():return 1
                assert app.focus_group=='verification' and self.ids[1] in app.rows.values()
                assert not g.gtk_widget_get_visible(app.widget('focus_summaries'))
                app.close_focus_group();assert g.gtk_widget_get_visible(app.widget('focus_summaries'));self.step=6
            elif self.step==6:
                if not self.list_ready():return 1
                self.checks.append('retained-card-opens-group-and-returns-with-correct-visibility')
                store.set_preference('active_inbox_view','conversations');app.set_view('inbox');self.step=7
            elif self.step==7:
                if not self.list_ready():return 1
                assert g.gtk_widget_get_visible(app.widget('messages'))
                item=next((item for item in app.items if item.get('contact_address')=='research@example.invalid'),None)
                if not item:return 1
                app.read_chat(item['key']);self.step=8
            elif self.step==8:
                editor=app.chat_composer
                if app.chat_loading or not editor:return 1
                from maildesk.config import Account
                account=Account('fixture','long.research.account@example.edu','imap.example.invalid','smtp.example.invalid',title='研究邮箱')
                app.service.accounts[account.id]=account
                g.gtk_combo_box_text_append(editor.account,account.id.encode(),account.email.encode());g.gtk_combo_box_set_active_id(editor.account,account.id.encode())
                g.text(editor.fields['to'],'Research Team <research@example.invalid>, colleague@example.invalid')
                g.text(editor.fields['cc'],'reviewer@example.invalid')
                g.text(editor.fields['subject'],'Re: 计算任务进度与数据传输确认 / A long subject stays separate from the recipients')
                g.text(editor.body,'已收到，我会在完成核对后回复。',view=True);g.gtk_widget_grab_focus(editor.body);editor.expand()
                self.editor=editor;self.until=time.monotonic()+.35;self.step=9
            elif self.step==9:
                if time.monotonic()<self.until:return 1
                editor=self.editor
                label_text=g.libs['gtk'].gtk_label_get_text;label_text.restype=C.c_char_p;label_text.argtypes=[C.c_void_p]
                assert label_text(editor.summary).decode()=='收件人  research@example.invalid  +1 · 抄送'
                assert label_text(editor.subject_summary).decode()==g.text(editor.fields['subject'])
                assert label_text(editor.account_choice.label).decode()=='研究邮箱'
                assert editor.payload()['account']=='fixture' and 'colleague@example.invalid' in editor.payload()['to']
                button=editor.send_button;glyph=editor.send_glyph;x,y=C.c_int(),C.c_int()
                assert g.gtk_widget_translate_coordinates(glyph,button,0,0,C.byref(x),C.byref(y))
                width=g.gtk_widget_get_allocated_width(button);height=g.gtk_widget_get_allocated_height(button)
                dx=x.value+g.gtk_widget_get_allocated_width(glyph)/2-width/2;dy=y.value+g.gtk_widget_get_allocated_height(glyph)/2-height/2
                self.metrics['send_button']={'width':width,'height':height,'center_offset':[dx,dy]}
                assert width==height and abs(dx)<=.5 and abs(dy)<=.5,self.metrics['send_button']
                # Show the enabled appearance for this screenshot only; demo still forbids sending.
                g.gtk_widget_set_sensitive(button,1);self.until=time.monotonic()+.15;self.step=10
            elif self.step==10:
                if time.monotonic()<self.until:return 1
                self.snapshot('composer-dark.png');self.editor.update_state()
                g.gtk_button_clicked(self.editor.route_button)
                assert all(g.gtk_widget_get_visible(row) for row in self.editor.field_rows.values())
                g.gtk_button_clicked(self.editor.route_button)
                self.checks.append('compact-routing-keeps-exact-payload-and-editable-recipients')
                self.checks.append('vector-send-arrow-centered-in-square-button')
                from maildesk.config import Account
                other=Account('other','another.long.account@example.org','imap.example.invalid','smtp.example.invalid')
                app.service.accounts[other.id]=other;g.gtk_combo_box_text_append(self.editor.account,other.id.encode(),other.email.encode())
                self.editor.account_choice.select(other.id)
                label_text=g.libs['gtk'].gtk_label_get_text
                assert label_text(self.editor.account_choice.label).decode()=='example.org'
                assert self.editor.payload()['account']=='other' and self.editor.payload()['body']=='已收到，我会在完成核对后回复。'
                self.checks.append('short-sender-label-follows-real-account-selection-without-changing-body')
                store.set_preference('theme','light');app.apply_appearance();g.gtk_widget_set_sensitive(self.editor.send_button,1)
                self.until=time.monotonic()+.2;self.step=101
            elif self.step==101:
                if time.monotonic()<self.until:return 1
                self.snapshot('composer-light.png');self.editor.update_state()
                self.target=next(iter(app.chat_surface.conversation_cards));card=app.chat_surface.conversation_cards[self.target]
                g.gtk_button_clicked(card['trash_button']);self.step=11
            elif self.step==11:
                if app.chat_loading or not self.list_ready() or self.target in app.chat_surface.conversation_cards:return 1
                assert store.state(self.target)['folder']=='Trash'
                self.checks.append('direct-trash-icon-removes-source-bubble')
                self.complete=True;app.on_delete(force=True);return 0
        except Exception as error:
            import traceback
            traceback.print_exc();self.error=repr(error)
            if getattr(self,'release',None):self.release.set()
            if getattr(self,'query_patch',None):self.query_patch.stop()
            app.on_delete(force=True);return 0
        return 1


if __name__=='__main__':raise SystemExit(main(FocusComposerScenario))
