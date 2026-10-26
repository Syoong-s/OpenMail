"""Native Windows notification-area icon and local notification balloons."""
import ctypes as C
import os
from .gtk_native import P,I,U

# ==========================================
# Function: Keep one recoverable native Windows tray entry for this application.
# Method: Use a private HWND serviced by GTK's Windows message loop and owned Shell_NotifyIcon data.
# ==========================================
class WindowsTray:
    # ==========================================
    # Function: Create a hidden notification callback window and native icon.
    # Method: Declare every pointer-sized Win32 ABI before registering the window class.
    # ==========================================
    def __init__(self,app):
        self.app=app;self.user=C.WinDLL('user32',use_last_error=True);self.shell=C.WinDLL('shell32',use_last_error=True)
        self.kernel=C.WinDLL('kernel32',use_last_error=True);self.closed=False;self.available=False
        self.theme_timer=0;self.theme_callback=C.CFUNCTYPE(I,P)(self.theme_changed)
        self.proc_type=C.WINFUNCTYPE(C.c_ssize_t,P,U,C.c_size_t,C.c_ssize_t)
        # ==========================================
        # Function: Match the documented native WindowClass structure layout.
        # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
        # ==========================================
        class WindowClass(C.Structure):
            _fields_=[('style',U),('proc',P),('cls_extra',I),('wnd_extra',I),('instance',P),('icon',P),('cursor',P),('background',P),('menu',C.c_wchar_p),('name',C.c_wchar_p)]
        # ==========================================
        # Function: Match the documented native NotifyData structure layout.
        # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
        # ==========================================
        class NotifyData(C.Structure):
            _fields_=[('size',U),('window',P),('id',U),('flags',U),('message',U),('icon',P),('tip',C.c_wchar*128),('state',U),('state_mask',U),('info',C.c_wchar*256),('version',U),('title',C.c_wchar*64),('info_flags',U),('guid',C.c_ubyte*16),('balloon_icon',P)]
        self.NotifyData=NotifyData
        signatures={'DefWindowProcW':(C.c_ssize_t,P,U,C.c_size_t,C.c_ssize_t),
            'RegisterClassW':(C.c_ushort,P),'UnregisterClassW':(I,C.c_wchar_p,P),
            'CreateWindowExW':(P,U,C.c_wchar_p,C.c_wchar_p,U,I,I,I,I,P,P,P,P),
            'DestroyWindow':(I,P),'LoadIconW':(P,P,P),'CreatePopupMenu':(P,),
            'AppendMenuW':(I,P,U,C.c_size_t,C.c_wchar_p),'DestroyMenu':(I,P),
            'SetForegroundWindow':(I,P),'GetCursorPos':(I,P),'TrackPopupMenu':(U,P,U,I,I,I,P,P),
            'RegisterWindowMessageW':(U,C.c_wchar_p)}
        for name,signature in signatures.items():
            fn=getattr(self.user,name);fn.restype,fn.argtypes=signature[0],signature[1:]
        self.kernel.GetModuleHandleW.argtypes=[C.c_wchar_p];self.kernel.GetModuleHandleW.restype=P
        self.shell.Shell_NotifyIconW.argtypes=[U,P];self.shell.Shell_NotifyIconW.restype=I
        self.shell.ExtractIconW.argtypes=[P,C.c_wchar_p,U];self.shell.ExtractIconW.restype=P
        self.instance=self.kernel.GetModuleHandleW(None);self.classname='TeleMailTray'+str(os.getpid())
        self.callback=self.proc_type(self.dispatch);definition=WindowClass();definition.proc=C.cast(self.callback,P);definition.instance=self.instance;definition.name=self.classname
        self.user.RegisterClassW(C.byref(definition))
        self.window=self.user.CreateWindowExW(0,self.classname,'TeleMail',0,0,0,0,0,None,None,self.instance,None)
        self.taskbar_created=self.user.RegisterWindowMessageW('TaskbarCreated')
        self.data=NotifyData();self.data.size=C.sizeof(NotifyData);self.data.window=self.window;self.data.id=1;self.data.flags=1|2|4;self.data.message=0x8000+51
        self.data.icon=self.shell.ExtractIconW(self.instance,os.environ.get('TELEMAIL_LAUNCHER',''),0)
        self.owned_icon=bool(self.data.icon and self.data.icon>1)
        if not self.owned_icon:self.data.icon=self.user.LoadIconW(None,P(32512))
        self.data.tip='TeleMail · 点击恢复，右键打开菜单'
        self.available=bool(self.window and self.shell.Shell_NotifyIconW(0,C.byref(self.data)))

    # ==========================================
    # Function: Dispatch native tray clicks without unwinding Python errors through Win32.
    # Method: Restore on primary click, show explicit exit on secondary click, and re-add after Explorer restart.
    # ==========================================
    def dispatch(self,window,message,wparam,lparam):
        try:
            if message in (0x001a,0x031a):
                if not self.closed and getattr(self.app,'window',None) and getattr(self.app,'service',None) and not self.theme_timer:
                    self.theme_timer=self.app.g.g_timeout_add(80,C.cast(self.theme_callback,P),None)
                return 0
            if message==getattr(self,'taskbar_created',-1):
                self.available=bool(self.shell.Shell_NotifyIconW(0,C.byref(self.data)))
                if not self.available:self.app.restore_window()
                return 0
            if message==0x8000+51:
                if lparam in (0x0202,0x0203,0x0405):self.app.restore_window()
                elif lparam==0x0205:self.popup()
                return 0
        except Exception as error:self.app.message('通知区域操作失败：'+str(error))
        return self.user.DefWindowProcW(window,message,wparam,lparam)

    # ==========================================
    # Function: Follow a changed Windows app theme without reentering GTK from a window procedure.
    # Method: Coalesce native appearance broadcasts into one retained main-loop callback.
    # ==========================================
    def theme_changed(self,*unused):
        self.theme_timer=0
        if not self.closed and not getattr(self.app,'closing',False):self.app.system_theme_changed()
        return 0

    # ==========================================
    # Function: Offer discoverable restore and exit commands in the native notification area.
    # Method: Track a short-lived Win32 menu on the same GTK thread.
    # ==========================================
    def popup(self):
        # ==========================================
        # Function: Match the documented native Point structure layout.
        # Method: Use pointer-sized handles and fixed-width Windows scalar fields.
        # ==========================================
        class Point(C.Structure):_fields_=[('x',C.c_long),('y',C.c_long)]
        position=Point();self.user.GetCursorPos(C.byref(position));menu=self.user.CreatePopupMenu()
        try:
            self.user.AppendMenuW(menu,0,1,'打开 TeleMail');self.user.AppendMenuW(menu,0,2,'退出 TeleMail')
            self.user.SetForegroundWindow(self.window)
            result=self.user.TrackPopupMenu(menu,0x0100|0x0002,position.x,position.y,0,self.window,None)
            if result==1:self.app.restore_window()
            elif result==2:self.app.on_delete(force=True)
        finally:self.user.DestroyMenu(menu)

    # ==========================================
    # Function: Present a local Windows notification without cloud registration or secrets.
    # Method: Update only the owned notification-area icon using a bounded text balloon.
    # ==========================================
    def notify(self,title,text):
        if self.closed or not self.available:return
        self.data.flags=0x10;self.data.title=str(title)[:63];self.data.info=str(text)[:255];self.data.info_flags=1
        self.shell.Shell_NotifyIconW(1,C.byref(self.data));self.data.flags=1|2|4

    # ==========================================
    # Function: Remove the owned tray icon and hidden window at application shutdown.
    # Method: Keep callback references valid until DestroyWindow has returned.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True
        if self.theme_timer:self.app.g.g_source_remove(self.theme_timer);self.theme_timer=0
        self.shell.Shell_NotifyIconW(2,C.byref(self.data));self.available=False
        if self.window:self.user.DestroyWindow(self.window);self.window=None
        self.user.UnregisterClassW(self.classname,self.instance)
        if self.owned_icon:
            self.user.DestroyIcon.argtypes=[P];self.user.DestroyIcon.restype=I;self.user.DestroyIcon(self.data.icon)
