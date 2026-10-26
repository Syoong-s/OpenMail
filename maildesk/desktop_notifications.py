"""Branded nonactivating native desktop notices with bounded lifetime."""
import ctypes as C
import os
import time
from pathlib import Path

P=C.c_void_p

# ==========================================
# Function: Honor Windows quiet/locked/presentation/full-screen notification restrictions.
# Method: Query the documented shell state and conservatively suppress when it is unavailable.
# ==========================================
def notifications_allowed():
    if os.name!='nt':return True
    try:
        function=C.WinDLL('shell32').SHQueryUserNotificationState;function.restype=C.c_int32;function.argtypes=[C.POINTER(C.c_int)];state=C.c_int();return function(C.byref(state))==0 and state.value==5
    except (OSError,AttributeError):return False

# ==========================================
# Function: Match a public GdkRectangle for logical work-area positioning.
# Method: Respect the monitor containing the main client and the desktop taskbar inset.
# ==========================================
class WorkArea(C.Structure):
    _fields_=[('x',C.c_int),('y',C.c_int),('width',C.c_int),('height',C.c_int)]

# ==========================================
# Function: Present a bounded stack of branded desktop cards without stealing focus.
# Method: Reuse one undecorated native window and expire at most three in-memory notices.
# ==========================================
class NotificationCards:
    # ==========================================
    # Function: Prepare lazy desktop notification ownership.
    # Method: Create no window or timer until an enabled event actually arrives.
    # ==========================================
    def __init__(self,app):
        self.app,self.g=app,app.g;self.window=None;self.host=None;self.cards=[];self.timer=0;self.sequence=0;self.callback=C.CFUNCTYPE(C.c_int,P)(self.tick)

    # ==========================================
    # Function: Allocate an unfocused tool window scoped to the application's own notices.
    # Method: Disable focus acceptance/taskbar entry and let GTK manage native DPI coordinates.
    # ==========================================
    def create(self):
        g=self.g;self.window=g.gtk_window_new(0);g.gtk_window_set_title(self.window,b'TeleMail notifications');g.gtk_window_set_decorated(self.window,0);g.gtk_window_set_resizable(self.window,0);g.gtk_window_set_accept_focus(self.window,0);g.gtk_window_set_focus_on_map(self.window,0);g.gtk_window_set_skip_taskbar_hint(self.window,1);g.gtk_window_set_skip_pager_hint(self.window,1);g.gtk_window_set_keep_above(self.window,1);g.gtk_window_set_type_hint(self.window,11)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.window),b'desktop-notifications');self.host=g.gtk_box_new(1,8);g.gtk_container_add(self.window,self.host)
        g.connect(self.window,'delete-event',lambda *unused:(self.close(),True)[1],count=3,returns=True,group='notification-window')
        g.connect(self.window,'size-allocate',lambda *unused:self.position(),count=3,group='notification-window')

    # ==========================================
    # Function: Show one bounded plain-text card with an app icon and explicit restore/close actions.
    # Method: Honor suppression for real notices, cap the stack and keep all text local in memory.
    # ==========================================
    def show(self,title,text,preview=True,duration=8,explicit=False):
        if self.app.closing or (not explicit and not notifications_allowed()):return False
        if not self.window:self.create()
        if len(self.cards)>=3:self.dismiss(self.cards[0]['id'],hide_empty=False)
        self.sequence+=1;identity=self.sequence;g=self.g;group='notification-card-'+str(identity);card=g.gtk_box_new(1,9);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(card),b'notification-card');g.gtk_widget_set_size_request(card,354,-1);header=g.gtk_box_new(0,9);g.gtk_box_pack_start(card,header,0,1,0)
        g.gtk_box_pack_start(header,g.image_file(Path(__file__).parent/'desktop_assets/icon.svg',22),0,0,0);brand=g.gtk_label_new('TeleMail'.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(brand),b'notification-brand');g.gtk_box_pack_start(header,brand,1,1,0)
        stamp=g.gtk_label_new(time.strftime('%H:%M').encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(stamp),b'muted');g.gtk_box_pack_start(header,stamp,0,0,0)
        from .ui_actions import icon_action
        close=icon_action(g,g.gtk_button_new(),'关闭通知','composer-close',14);g.gtk_box_pack_start(header,close,0,0,0);g.connect(close,'clicked',lambda *unused:self.dismiss(identity),group=group)
        for source,style,lines in [(str(title)[:240],'notification-title',2),(str(text)[:600] if preview else '你有新的邮件动态，打开 TeleMail 查看。','notification-body',3)]:
            label=g.gtk_label_new(source.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_line_wrap(label,1);g.gtk_label_set_lines(label,lines);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,39);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),style.encode());g.gtk_box_pack_start(card,label,0,1,0)
        open_button=g.gtk_button_new_with_label('打开 TeleMail  ›'.encode());g.gtk_widget_set_halign(open_button,2);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(open_button),b'notification-open');g.gtk_box_pack_start(card,open_button,0,0,0);g.connect(open_button,'clicked',lambda *unused:self.open_client(identity),group=group)
        self.cards.append({'id':identity,'widget':card,'group':group,'expires':time.monotonic()+min(60,max(3,int(duration)))})
        g.gtk_box_pack_start(self.host,card,0,1,0);g.gtk_widget_show_all(self.window);self.position()
        if not self.timer:self.timer=g.g_timeout_add(200,C.cast(self.callback,P),None)
        return True

    # ==========================================
    # Function: Place notice cards inside the main monitor's usable work area.
    # Method: Fall back to the primary monitor without changing focus or the user's screen configuration.
    # ==========================================
    def position(self):
        if not self.window:return
        gdk=self.g.libs['gdk']
        # ==========================================
        # Function: Bind one public monitor query using the existing native library.
        # Method: Declare pointer-safe signatures before querying logical work areas.
        # ==========================================
        def native(name,result,args):
            fn=getattr(gdk,name);fn.restype=result;fn.argtypes=args;return fn
        display=native('gdk_display_get_default',P,[])();monitor=native('gdk_display_get_monitor_at_window',P,[P,P])(display,self.g.gtk_widget_get_window(self.app.window))
        if not monitor:monitor=native('gdk_display_get_primary_monitor',P,[P])(display)
        if not monitor:return
        area=WorkArea();native('gdk_monitor_get_workarea',None,[P,P])(monitor,C.byref(area));width=max(354,self.g.gtk_widget_get_allocated_width(self.window));height=max(150,self.g.gtk_widget_get_allocated_height(self.window));self.g.gtk_window_move(self.window,area.x+max(0,area.width-width-20),area.y+max(0,area.height-height-20))

    # ==========================================
    # Function: Pause expiry while the pointer reads a card and remove expired notices.
    # Method: Keep one short timer only while the owned notification window is visible.
    # ==========================================
    def tick(self,unused):
        if not self.window or self.app.closing:self.timer=0;self.close();return 0
        x,y=C.c_int(),C.c_int();self.g.gtk_widget_get_pointer(self.window,C.byref(x),C.byref(y));hover=0<=x.value<self.g.gtk_widget_get_allocated_width(self.window) and 0<=y.value<self.g.gtk_widget_get_allocated_height(self.window)
        now=time.monotonic()
        for card in list(self.cards):
            if hover:card['expires']+=.2
            elif now>=card['expires']:self.dismiss(card['id'])
        if not self.cards:self.timer=0;return 0
        return 1

    # ==========================================
    # Function: Restore the client only after an explicit notification action.
    # Method: Remove that card and reuse the existing tray restore behavior.
    # ==========================================
    def open_client(self,identity):self.dismiss(identity);self.app.restore_window()

    # ==========================================
    # Function: Remove exactly one notice and release callbacks before native destruction.
    # Method: Preserve the remaining cards and hide the reusable window when empty.
    # ==========================================
    def dismiss(self,identity,hide_empty=True):
        card=next((item for item in self.cards if item['id']==identity),None)
        if not card:return
        self.cards.remove(card);self.g.surfaces.retire(card['group']);self.g.gtk_widget_destroy(card['widget'])
        if not self.cards and hide_empty and self.window:self.g.gtk_widget_hide(self.window)

    # ==========================================
    # Function: Release the notification stack before desktop shutdown.
    # Method: Stop its timer, disconnect native callbacks and destroy only its own window.
    # ==========================================
    def close(self):
        if self.timer:self.g.g_source_remove(self.timer);self.timer=0
        for card in list(self.cards):self.dismiss(card['id'])
        self.g.surfaces.retire('notification-window')
        if self.window:self.g.gtk_widget_destroy(self.window);self.window=None;self.host=None

# ==========================================
# Function: Preview a selected notification style without touching real messages.
# Method: Explicit user preview bypasses quiet-state suppression and contains only sample text.
# ==========================================
def preview_notification(app,style='cards',preview=True,duration=8):
    if style=='system' and os.name=='nt':
        tray=getattr(app,'windows_tray',None)
        if tray:tray.notify('TeleMail · 通知预览','这是一条示例通知，不会发送或读取邮件。')
        return
    if not getattr(app,'notification_cards',None):app.notification_cards=NotificationCards(app)
    app.notification_cards.show('新的邮件动态','专属通知卡片 · 悬停可暂停消失，点击打开 TeleMail。',preview,duration,explicit=True)
