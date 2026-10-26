"""Application-local Windows11 frame colors for native GTK top-level windows."""
import ctypes as C
from functools import lru_cache
import sys

# ==========================================
# Function: Load only documented per-window DWM and native handle APIs when running on Windows.
# Method: Cache typed functions from the existing private GDK runtime and Windows system DLLs.
# ==========================================
@lru_cache(maxsize=1)
def _native_api():
    from .platform_native import load_library
    gdk=load_library('gdk');dwm=C.WinDLL('dwmapi',use_last_error=True);user=C.WinDLL('user32',use_last_error=True)
    handle=gdk.gdk_win32_window_get_handle;handle.restype=C.c_void_p;handle.argtypes=[C.c_void_p]
    attribute=dwm.DwmSetWindowAttribute;attribute.restype=C.c_int32;attribute.argtypes=[C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint32]
    contrast=user.SystemParametersInfoW;contrast.restype=C.c_int;contrast.argtypes=[C.c_uint32,C.c_uint32,C.c_void_p,C.c_uint32]
    return handle,attribute,contrast

# ==========================================
# Function: Match a native window's caption, border and text to its current TeleMail theme.
# Method: Apply DWM attributes20/33/34/35/36 only to this HWND and respect system high-contrast colors.
# ==========================================
def apply_window_frame(app,window):
    if sys.platform!='win32' or not window:return
    from .desktop_preferences import resolved_theme
    dark=resolved_theme(app)=='dark' if app.service else True
    g=app.g;context=g.gtk_widget_get_style_context(window)
    g.gtk_style_context_remove_class(context,b'light' if dark else b'dark')
    g.gtk_style_context_add_class(context,b'dark' if dark else b'light')
    native=g.gtk_widget_get_window(window)
    if not native:return
    try:
        handle,attribute,contrast=_native_api();hwnd=handle(native)
        if not hwnd:return
        # ==========================================
        # Function: Match the public HIGHCONTRASTW structure without changing accessibility settings.
        # Method: Query the current flag so explicit app colors never override system high contrast.
        # ==========================================
        class HighContrast(C.Structure):
            _fields_=[('size',C.c_uint32),('flags',C.c_uint32),('scheme',C.c_wchar_p)]
        accessibility=HighContrast();accessibility.size=C.sizeof(accessibility)
        high=bool(contrast(0x42,accessibility.size,C.byref(accessibility),0) and accessibility.flags&1)
        corners=C.c_int(2);attribute(hwnd,33,C.byref(corners),C.sizeof(corners))
        enabled=C.c_int(int(dark and not high));attribute(hwnd,20,C.byref(enabled),C.sizeof(enabled))
        # COLORREF stores red in the low byte: border, caption, caption text.
        colors=(0x00383230,0x001d1a18,0x00ede8e6) if dark else (0x00e5ddd9,0x00f4f0ee,0x00332a25)
        for kind,color in zip((34,35,36),colors):
            value=C.c_uint32(0xffffffff if high else color)
            attribute(hwnd,kind,C.byref(value),C.sizeof(value))
    except (OSError,AttributeError):
        # An unavailable API leaves the operating system's normal frame intact.
        return

# ==========================================
# Function: Theme every new application dialog before it becomes visible and after it remaps.
# Method: Keep signal ownership in the caller's existing form or window callback group.
# ==========================================
def bind_window_frame(app,window,group='app'):
    if sys.platform!='win32':return
    if window==app.window:app.g.gtk_style_context_add_class(app.g.gtk_widget_get_style_context(window),b'solid-csd')
    for signal in ('realize','map'):
        app.g.connect(window,signal,lambda *unused:apply_window_frame(app,window),group=group)
    apply_window_frame(app,window)

# ==========================================
# Function: Update all currently owned top-level frames when the application's theme changes.
# Method: Traverse GTK's borrowed application window list, including detached editors and conversation windows.
# ==========================================
def refresh_window_frames(app):
    if sys.platform!='win32':return
    cursor=app.g.gtk_application_get_windows(app.application)
    while cursor:
        apply_window_frame(app,cursor.contents.data);cursor=cursor.contents.next

# ==========================================
# Function: Provide explicit mouse resize targets for the undecorated GTK client edges.
# Method: Route capture-phase edge presses through GTK's standard window-manager resize operation.
# ==========================================
class WindowResize:
    # ==========================================
    # Function: Retain one edge observer on the main application window.
    # Method: Keep normal titlebar dragging/buttons untouched outside a six-pixel perimeter.
    # ==========================================
    def __init__(self,app):
        self.app,self.g=app,app.g;g=self.g;g.gtk_window_set_resizable(app.window,1)
        self.gesture=g.gtk_gesture_multi_press_new(app.window);g.gtk_gesture_single_set_button(self.gesture,1);g.gtk_event_controller_set_propagation_phase(self.gesture,1)
        g.connect(self.gesture,'pressed',lambda widget,count,x,y,data:self.pressed(count,x,y),types=[C.c_void_p,C.c_int,C.c_double,C.c_double,C.c_void_p],group='workspace-geometry')

    # ==========================================
    # Function: Translate edge and corner positions to the public GdkWindowEdge enumeration.
    # Method: Ignore maximized windows and claim only genuine perimeter clicks before starting native resizing.
    # ==========================================
    def pressed(self,count,x,y):
        g=self.g;window=self.app.window
        if count!=1 or g.gtk_window_is_maximized(window):return
        width=g.gtk_widget_get_allocated_width(window);height=g.gtk_widget_get_allocated_height(window)
        left,right=x<6,x>=width-6;top,bottom=y<6,y>=height-6
        edge=(0 if left else 2 if right else 1) if top else (5 if left else 7 if right else 6) if bottom else 3 if left else 4 if right else None
        if edge is None:return
        event=g.gtk_gesture_get_last_event(self.gesture,None);rx,ry=C.c_double(),C.c_double()
        if not event or not g.gdk_event_get_root_coords(event,C.byref(rx),C.byref(ry)):return
        g.gtk_gesture_set_state(self.gesture,1);g.gtk_window_begin_resize_drag(window,edge,1,int(rx.value),int(ry.value),g.gdk_event_get_time(event))

    # ==========================================
    # Function: Release the retained resize gesture after callback disconnection.
    # Method: Share the workspace geometry lifetime so widget destruction cannot call stale trampolines.
    # ==========================================
    def close(self):
        if self.gesture:self.g.g_object_unref(self.gesture);self.gesture=None
