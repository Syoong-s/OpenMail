"""Bounded acceptance scenario for isolated native GTK demo windows."""
import json
import ctypes as C
from pathlib import Path
import sys
import time

# ==========================================
# Function: Exercise actual GTK activation and selection signals.
# Method: Advance a timed scenario through the native application event loop.
# ==========================================
class NativeSmoke:
    # ==========================================
    # Function: Initialize isolated acceptance state.
    # Method: Set a deadline and record completed assertions only.
    # ==========================================
    def __init__(self, app):
        self.app, self.step, self.done = app, 0, False
        self.deadline, self.checks, self.saved_id = time.monotonic() + 85, [], None

    # ==========================================
    # Function: Select the first native list row.
    # Method: Emit GtkListBox's public selection signal.
    # ==========================================
    def select_first(self):
        app = self.app
        row = app.g.gtk_list_box_get_row_at_index(app.widget('messages'), 0)
        assert row, 'No native row'
        app.g.gtk_list_box_select_row(app.widget('messages'), row)

    # ==========================================
    # Function: Execute one nonblocking native acceptance step.
    # Method: Activate real controls and wait for background operation completion.
    # ==========================================
    def tick(self):
        if self.done:
            return
        app, g = self.app, self.app.g
        try:
            assert time.monotonic() <= self.deadline, f'Timeout at step {self.step}'
            if self.step == 0:
                assert app.total == 8 and len(app.items) == 8
                assert 'maildesk.web' not in sys.modules and 'http.server' not in sys.modules
                assert g.gtk_widget_get_allocated_width(app.window) > 900
                self.select_first()
                self.checks += ['linux-native-window','no-browser-or-http','inbox-8']
                self.step = 1
            elif self.step == 1:
                if app.reader_fade:return
                assert '研究讨论' in app.current['subject']
                header=g.gtk_list_box_row_get_header(g.gtk_list_box_get_row_at_index(app.widget('messages'),0))
                assert header and g.gtk_widget_get_allocated_height(header)>0
                self.checks+=['native-persistent-group-headers']
                assert len(app.service.store.thread(app.selected)) == 2
                assert '你好' in g.text(app.widget('body'), view=True)
                if app.options.screenshot:
                    g.screenshot(app.window, app.options.screenshot)
                self.checks += ['native-reader','reference-thread']
                if app.options.screenshot:
                    self.checks.append('native-window-screenshot')
                g.gtk_combo_box_set_active_id(app.widget('category_filter'), b'newsletter')
                self.step = 2
            elif self.step == 2:
                assert app.total == 2
                g.gtk_combo_box_set_active_id(app.widget('category_filter'), b'all')
                g.text(app.widget('search'), '登录提醒')
                assert app.total == 1
                self.select_first()
                g.gtk_combo_box_set_active_id(app.widget('message_category'), b'personal')
                g.gtk_toggle_button_set_active(app.widget('learn'), 1)
                g.gtk_button_clicked(app.widget('apply_category'))
                self.checks += ['native-category-filter','native-search']
                self.step = 3
            elif self.step == 3:
                if not app.current or app.current.get('category') != 'personal':
                    return
                assert app.service.store.sender_rules('demo')['no-reply@security.example.com'] == 'personal'
                g.text(app.widget('search'), '')
                g.gtk_button_clicked(app.widget('compose'))
                assert app.composer
                app.composer.value('to','test@example.com')
                app.composer.value('subject','Linux 原生窗口验证草稿')
                app.composer.value('body','在 GTK 原生撰写窗口保存，不向外发送。')
                self.saved_id = app.composer.identity
                g.gtk_button_clicked(app.composer.save_button)
                self.checks += ['native-sender-correction','native-composer']
                self.step = 4
            elif self.step == 4:
                if app.composer is not None:
                    return
                assert app.service.store.job(self.saved_id)['state'] == 'draft'
                g.gtk_button_clicked(app.widget('nav_drafts'))
                self.select_first()
                g.gtk_button_clicked(app.widget('edit_draft'))
                assert app.composer.value('body') == '在 GTK 原生撰写窗口保存，不向外发送。'
                app.composer.close()
                app.composer = None
                self.checks += ['native-draft-save','native-draft-edit','demo-no-send']
                self.step=5
            elif self.step==5:
                self.dialog('folders_manage',{'account':'demo','operation':'create','path':'工作/界面验收'})
                self.step=6
            elif self.step==6:
                if not any(r['folder']=='工作/界面验收' for r in app.service.store.list_folders('demo')):return
                app.set_view('inbox');self.select_first()
                self.moved_subject=app.current['subject']
                self.dialog('move',{'folder':'工作/界面验收'})
                self.checks+=['native-create-folder-dialog'];self.step=7
            elif self.step==7:
                if app.service.store.list_messages(folder='工作/界面验收',account='demo')['total']!=1:return
                g.gtk_button_clicked(app.folder_buttons[('demo','工作/界面验收')]);self.select_first()
                assert app.current['subject']==self.moved_subject and app.total==1
                self.dialog('folders_manage',{'account':'demo','folder':'工作/界面验收','path':'工作/界面验收','operation':'rename','target':'工作/验收完成'})
                self.checks+=['native-move-dialog','native-folder-tree-open'];self.step=8
            elif self.step==8:
                if not any(r['folder']=='工作/验收完成' for r in app.service.store.list_folders('demo')):return
                g.gtk_button_clicked(app.folder_buttons[('demo','工作/验收完成')]);self.select_first()
                assert app.total==1 and app.current['subject']==self.moved_subject
                self.dialog('labels',{'labels':'验收, 研究'})
                self.checks+=['native-rename-preserves-mail'];self.step=9
            elif self.step==9:
                if '验收' not in app.service.store.get(app.selected)['labels']:return
                self.dialog('smart_add',{'name':'验收智能文件夹','query':'label:验收','account':''})
                item=next(r for r in app.service.store.smart_folders() if r['name']=='验收智能文件夹')
                app.open_smart(item);self.select_first();assert app.total==1
                self.dialog('snooze',{'when':__import__('datetime').datetime.fromtimestamp(time.time()+3600).isoformat(timespec='minutes')})
                self.checks+=['native-label-dialog','native-smart-folder-query'];self.step=10
            elif self.step==10:
                if app.service.store.list_messages(view='snoozed')['total']!=1:return
                app.set_view('snoozed');self.select_first();assert app.current['snoozed_until']>time.time()
                self.dialog('reminder',{'when':__import__('datetime').datetime.fromtimestamp(time.time()+3600).isoformat(timespec='minutes')})
                self.checks+=['native-snooze-dialog'];self.step=11
            elif self.step==11:
                if app.service.store.list_messages(view='reminders')['total']!=1:return
                app.set_view('inbox');self.select_first();g.gtk_button_clicked(app.widget('selection'))
                g.gtk_list_box_select_row(app.widget('messages'),g.gtk_list_box_get_row_at_index(app.widget('messages'),1))
                assert len(app.selected_ids())==2
                g.gtk_button_clicked(app.widget('bulk_done'));self.step=12
            elif self.step==12:
                if app.service.store.list_messages(view='done')['total']!=2:return
                app.toggle_selection();app.set_view('done');self.select_first()
                self.checks+=['native-reminder-dialog','native-bulk-selection-and-done']
                from .desktop_print import print_message
                output=app.profile.data/'native-print.pdf';print_message(app,app.current,output)
                assert output.read_bytes().startswith(b'%PDF-') and output.stat().st_size>1000
                self.dialog('preferences',{'theme':'dark','motion':'off','signature':'TeleMail 验收签名'})
                self.checks+=['native-pdf-print','native-preferences-dialog'];self.step=13
            elif self.step==13:
                if app.options.screenshot:
                    g.screenshot(app.window,app.options.screenshot.with_name(app.options.screenshot.stem+'-dark.png'))
                assert not app.motion
                self.dialog('contacts',{'name':'测试联系人','email':'contact@example.com'},response=2)
                assert app.service.store.preference('contacts',{})['contact@example.com']=='测试联系人'
                app.open_composer();app.composer.value('to','test@example.com');app.composer.value('subject','富文本草稿');app.composer.value('body','富文本正文')
                rich=app.composer.rich;rich.gtk.gtk_text_buffer_apply_tag(rich.buffer,rich.tags['bold'],rich.iterator(0),rich.iterator(3))
                self.rich_id=app.composer.identity;g.gtk_button_clicked(app.composer.save_button)
                self.checks+=['native-dark-theme','native-reduced-motion','native-address-book'];self.step=14
            elif self.step==14:
                if app.composer is not None:return
                draft=app.service.store.job(self.rich_id)['draft'];assert '<strong>' in draft['html'] and draft['body']=='富文本正文'
                app.service.store.set_preference('theme','light');app.service.store.set_preference('motion','on');app.apply_appearance()
                app.set_view('inbox');self.select_first()
                self.checks+=['native-rich-text-save','native-signature-preference']
                attachment_mail=app.service.store.list_messages(view='all',search='has:attachment')['items'][0]
                app.read(attachment_mail['id']);attachment=app.current['parsed']['attachments'][0]
                app.preview_attachment(app.selected,attachment)
                assert app.document and '项目笔记' in app.document.text_source
                assert g.gtk_stack_get_visible_child_name(app.widget('reader_stack'))==b'document'
                g.gtk_button_clicked(app.document.back_button)
                app.open_composer();app.composer.value('to','autosave@example.com');app.composer.value('subject','自动保存验证');app.composer.value('body','关闭前保存')
                identity=app.composer.identity;app.composer.on_delete()
                assert app.service.store.job(identity)['draft']['body']=='关闭前保存'
                self.checks+=['native-attachment-preview','native-close-autosaves-draft']
                self.finish(True)
        except Exception as error:
            self.finish(False, f'Step {self.step}: {type(error).__name__}: {error}')

    # ==========================================
    # Function: Drive a genuine modal GTK form using its actual response button path.
    # Method: Schedule a separate GLib callback before entering the nested native dialog loop.
    # ==========================================
    def dialog(self,button,values,response=1):
        app=self.app
        self.dialog_error=None
        # ==========================================
        # Function: Fill the newly created form and emit an actual native response.
        # Method: Wait for the public test-only form reference, then let the normal handler persist it.
        # ==========================================
        def fill(unused):
            form=app.testing_form
            try:
                for key,value in values.items():form.value(key,value)
                self.dialog_snapshot={key:form.value(key) for key in form.fields}
                app.g.gtk_dialog_response(form.window,response)
            except Exception as error:
                self.dialog_error=error;app.g.gtk_dialog_response(form.window,-6)
            return 0
        self.dialog_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(fill)
        app.g.g_timeout_add(80,C.cast(self.dialog_callback,C.c_void_p),None)
        if callable(button):button()
        else:app.g.gtk_button_clicked(app.widget(button))
        if self.dialog_error:raise self.dialog_error

    # ==========================================
    # Function: Save structured evidence and close only the test application.
    # Method: Return explicit success/failure through JSON and process exit status.
    # ==========================================
    def finish(self, ok, error=''):
        self.done = True
        report = {'ok':ok,'platform':sys.platform,'ui':'GTK 3 native widgets','checks':self.checks,'error':error}
        if self.app.options.report:
            path = Path(self.app.options.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False), flush=True)
        self.app.exit_code = 0 if ok else 1
        self.app.on_delete()
