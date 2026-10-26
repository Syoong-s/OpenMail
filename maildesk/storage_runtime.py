"""Native post-shutdown storage migration and ownership-safe desktop restart."""
import ctypes as C
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading

# ==========================================
# Function: Ask the application to drain before one deliberate storage operation.
# Method: Clear refused requests immediately so a later ordinary quit cannot migrate.
# ==========================================
def request_storage_migration(app,plan):
    if getattr(app,'closing',False):
        app.message('应用正在关闭，未安排迁移');return False
    app.pending_storage_migration=plan
    try:app.on_delete(force=True)
    except Exception:
        app.pending_storage_migration=None;raise
    if not app.closing:
        app.pending_storage_migration=None
        app.message('邮件仍在保存，迁移尚未开始；请稍后重新选择迁移并重新启动')
        return False
    return True

# ==========================================
# Function: Display migration after the mailbox and all native readers have closed.
# Method: Own an independent GtkWindow/GMainLoop and marshal worker events through a queue.
# ==========================================
class StorageProgress:
    # ==========================================
    # Function: Build a standalone progress window independent of destroyed Form parents.
    # Method: Keep native titlebar styling, explicit recovery actions and cancellation ownership.
    # ==========================================
    def __init__(self,app,plan=None,error=None):
        self.app,self.g,self.plan=app,app.g,plan;g=self.g
        self.events=queue.Queue();self.cancel_event=threading.Event();self.worker=None
        self.finished=bool(error);self.restart=False;self.result=None;self.timer=0
        self.window=g.gtk_window_new(0);self.group='storage-progress-'+str(self.window)
        g.gtk_window_set_title(self.window,'TeleMail · 储存空间'.encode());g.gtk_window_set_default_size(self.window,580,240)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.window),b'dark')
        g.gtk_window_set_icon_from_file(self.window,str(Path(__file__).parent/'desktop_assets/icon.svg').encode(),None)
        box=g.gtk_box_new(1,16);g.gtk_container_set_border_width(box,24);g.gtk_container_add(self.window,box)
        self.label=g.gtk_label_new(('迁移未开始：'+str(error) if error else '正在准备复制与校验；原目录保留。').encode())
        g.gtk_label_set_xalign(self.label,0);g.gtk_label_set_line_wrap(self.label,1);g.gtk_label_set_max_width_chars(self.label,64)
        g.gtk_box_pack_start(box,self.label,1,1,0)
        self.bar=g.gtk_progress_bar_new();g.gtk_box_pack_start(box,self.bar,0,1,0)
        buttons=g.gtk_box_new(0,8);g.gtk_box_pack_start(box,buttons,0,1,0)
        self.cancel=g.gtk_button_new_with_label(('关闭' if error else '取消迁移').encode())
        self.back=g.gtk_button_new_with_label('返回应用'.encode())
        g.gtk_box_pack_start(buttons,self.cancel,0,0,0);g.gtk_box_pack_start(buttons,self.back,0,0,0)
        g.connect(self.cancel,'clicked',self.cancel_or_close,group=self.group)
        g.connect(self.back,'clicked',self.return_to_app,group=self.group)
        g.connect(self.window,'delete-event',self.delete,count=3,returns=True,group=self.group)
        from .windows_frame import bind_window_frame
        bind_window_frame(app,self.window,self.group)
        self.loop=g.g_main_loop_new(None,0)
        g.gtk_widget_show_all(self.window);g.gtk_widget_set_visible(self.back,int(self.finished))
        if error:g.gtk_widget_hide(self.bar)

    # ==========================================
    # Function: Execute the core copy with no GTK calls from the worker thread.
    # Method: Send progress and one terminal result through a bounded polling queue.
    # ==========================================
    def copy(self):
        from .storage_migration import execute_migration,MigrationCancelled
        try:
            result=execute_migration(self.plan,self.cancel_event,self.events.put)
            self.events.put(('complete',result))
        except MigrationCancelled:self.events.put(('error','迁移已取消，原储存位置保持不变。'))
        except Exception as error:self.events.put(('error','迁移失败，原储存位置保持不变：'+str(error)))

    # ==========================================
    # Function: Translate queued byte/phase progress on the GTK thread.
    # Method: Coalesce intermediate events and require explicit recovery after error or cancel.
    # ==========================================
    def poll(self,unused):
        latest=None;terminal=None
        for unused in range(200):
            try:item=self.events.get_nowait()
            except queue.Empty:break
            if isinstance(item,tuple):terminal=item;break
            latest=item
        if latest:
            phases={'scan':'扫描文件','copy':'复制文件','verify':'校验副本','database':'备份邮件数据库','verified':'校验完成','publish':'切换储存位置','complete':'迁移完成'}
            total=latest.get('total',0);completed=latest.get('completed',0)
            text=phases.get(latest.get('phase'),'正在迁移')
            if total:text+=' · '+str(round(completed/1024/1024,1))+' / '+str(round(total/1024/1024,1))+' MiB'
            path=str(latest.get('path',''))
            if path:text+='\n'+path
            self.g.label(self.label,text)
            if total:self.g.gtk_progress_bar_set_fraction(self.bar,max(0,min(1,completed/total)))
            else:self.g.gtk_progress_bar_pulse(self.bar)
        if terminal:
            self.finished=True
            if terminal[0]=='complete':
                self.result=terminal[1];self.restart=True;self.g.g_main_loop_quit(self.loop)
            else:
                self.g.label(self.label,terminal[1]);self.g.gtk_widget_hide(self.bar)
                self.g.gtk_button_set_label(self.cancel,'关闭'.encode());self.g.gtk_widget_set_sensitive(self.cancel,1)
                self.g.gtk_widget_show(self.back)
        return 1

    # ==========================================
    # Function: Cancel before the atomic switch or close an already finished recovery window.
    # Method: Keep the loop and original ownership alive until the worker acknowledges completion.
    # ==========================================
    def cancel_or_close(self,*unused):
        if self.finished:self.g.g_main_loop_quit(self.loop);return
        self.cancel_event.set();self.g.label(self.label,'正在取消；等待当前校验步骤结束…')
        self.g.gtk_widget_set_sensitive(self.cancel,0)

    # ==========================================
    # Function: Respect window close while retaining copy-worker lifetime.
    # Method: Treat the native close control exactly like Cancel and suppress immediate destruction.
    # ==========================================
    def delete(self,*unused):
        self.cancel_or_close();return True

    # ==========================================
    # Function: Reopen the original route only after the user chooses to return.
    # Method: Refuse restart while any timed-out mail worker can still access the database.
    # ==========================================
    def return_to_app(self,*unused):
        worker=getattr(getattr(self.app,'service',None),'worker',None)
        if worker and worker.is_alive():
            self.g.label(self.label,'后台服务仍在结束，尚不能返回。请稍后重试；原位置保持不变。');return
        self.restart=True;self.g.g_main_loop_quit(self.loop)

    # ==========================================
    # Function: Keep native input responsive until migration or recovery choice completes.
    # Method: Join the already-completed worker before destroying callbacks, loop and window.
    # ==========================================
    def run(self):
        try:
            self.callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.poll)
            self.timer=self.g.g_timeout_add(50,C.cast(self.callback,C.c_void_p),None)
            if not self.finished:
                self.worker=threading.Thread(target=self.copy,name='maildesk-storage',daemon=False);self.worker.start()
            self.g.g_main_loop_run(self.loop)
            return self.restart
        finally:
            self.cancel_event.set()
            if self.worker:self.worker.join()
            if self.timer:self.g.g_source_remove(self.timer)
            self.g.disconnect(self.group);self.g.gtk_widget_destroy(self.window);self.g.g_main_loop_unref(self.loop)

# ==========================================
# Function: Restart the selected scope after every original ownership reference is released.
# Method: Reuse normalized original launch arguments and omit background/mailto replay.
# ==========================================
def restart_command(profile):
    arguments=[]
    if profile.demo:arguments.append('--demo')
    if profile.original_config is not None:arguments.extend(['--config',str(profile.original_config)])
    if profile.original_data is not None:arguments.extend(['--data',str(profile.original_data)])
    launcher=os.environ.get('TELEMAIL_LAUNCHER')
    if launcher:return [launcher,*arguments]
    root=str(Path(__file__).resolve().parent.parent)
    return [sys.executable,'-I','-B','-Xutf8','-c','import sys;sys.path.insert(0,sys.argv.pop(1));from maildesk.desktop import main;raise SystemExit(main())',root,*arguments]

# ==========================================
# Function: Surface restart spawn errors instead of losing a successfully relocated session.
# Method: Offer a standalone explicit retry after the old GTK application and locks are freed.
# ==========================================
def restart_desktop(app):
    while True:
        try:
            subprocess.Popen(restart_command(app.profile),start_new_session=True)
            return 0
        except (OSError,ValueError) as error:
            print('TeleMail: 重新启动失败：'+str(error),file=sys.stderr)
            if not StorageProgress(app,error='重新启动失败：'+str(error)+'\n点击“返回应用”重试。').run():return 1

# ==========================================
# Function: Surface unavailable storage before a desktop window can be constructed.
# Method: Use a typed Windows error message box when the graphical launcher has no visible stderr.
# ==========================================
def show_startup_error(error):
    if sys.platform!='win32':return
    try:
        user=C.WinDLL('user32',use_last_error=True)
        message=user.MessageBoxW;message.argtypes=[C.c_void_p,C.c_wchar_p,C.c_wchar_p,C.c_uint];message.restype=C.c_int
        message(None,'无法启动 TeleMail：'+str(error),'TeleMail · 无法打开储存位置',0x10|0x10000)
    except OSError:pass
