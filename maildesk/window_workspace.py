"""Screen-bounded native window growth for an independent attachment column."""
import ctypes as C

# ==========================================
# Function: Validate a requested file-column opening width in logical pixels.
# Method: Preserve a700px default while accepting280–2000px from appearance settings.
# ==========================================
def attachment_width(value):
    try:return min(2000,max(280,int(value)))
    except (TypeError,ValueError,OverflowError):return 700

# ==========================================
# Function: Grow the current native client before allocating the new file column.
# Method: Use GDK logical monitor work area, preserve height and bound/reposition the window on its current screen.
# ==========================================
def expand_for_attachment(app,requested,receipt=None):
    g=app.g;gtk=g.libs['gtk'];gdk=g.libs['gdk'];width,height=C.c_int(),C.c_int();x,y=C.c_int(),C.c_int()
    size=gtk.gtk_window_get_size;size.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int)];size.restype=None;size(app.window,C.byref(width),C.byref(height))
    if g.gtk_window_is_maximized(app.window):return 0
    position=gtk.gtk_window_get_position;position.argtypes=size.argtypes;position.restype=None;position(app.window,C.byref(x),C.byref(y))
    # ==========================================
    # Function: Match the public monitor work-area structure in GDK logical coordinates.
    # Method: Keep Windows DPI scaling out of width preference arithmetic.
    # ==========================================
    class Rectangle(C.Structure):_fields_=[('x',C.c_int),('y',C.c_int),('width',C.c_int),('height',C.c_int)]
    display=gdk.gdk_display_get_default;display.argtypes=[];display.restype=C.c_void_p
    monitor=gdk.gdk_display_get_monitor_at_window;monitor.argtypes=[C.c_void_p,C.c_void_p];monitor.restype=C.c_void_p
    workarea=gdk.gdk_monitor_get_workarea;workarea.argtypes=[C.c_void_p,C.POINTER(Rectangle)];workarea.restype=None
    screen=monitor(display(),g.gtk_widget_get_window(app.window));bounds=Rectangle()
    if not screen:return 0
    workarea(screen,C.byref(bounds));target=min(width.value+requested+1,max(width.value,bounds.width-2))
    if target<=width.value:return 0
    move=gtk.gtk_window_move;move.argtypes=[C.c_void_p,C.c_int,C.c_int];move.restype=None
    expanded_x=max(bounds.x,min(x.value,bounds.x+bounds.width-target-2))
    if receipt is not None:receipt.update(before_width=width.value,before_x=x.value,expanded_x=expanded_x,added=target-width.value,settled=False)
    move(app.window,expanded_x,y.value)
    resize=gtk.gtk_window_resize;resize.argtypes=[C.c_void_p,C.c_int,C.c_int];resize.restype=None;resize(app.window,target,height.value)
    return target-width.value

# ==========================================
# Function: Record the actual logical width accepted by GTK after a pending expansion.
# Method: Settle one receipt only after allocation differs from its pre-open size.
# ==========================================
def settle_expansion(app,receipt):
    if not receipt or receipt.get('settled'):return
    size=app.g.libs['gtk'].gtk_window_get_size;size.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int)];size.restype=None;width,height=C.c_int(),C.c_int();size(app.window,C.byref(width),C.byref(height))
    if width.value!=receipt['before_width']:
        receipt['added']=max(0,width.value-receipt['before_width']);receipt['settled']=True

# ==========================================
# Function: Remove exactly the current preview session's automatic expansion on close.
# Method: Preserve unrelated manual width/position changes, cancel unopened pending growth and never unmaximize a window.
# ==========================================
def restore_after_attachment(app,receipt):
    if not receipt or app.closing or app.g.gtk_window_is_maximized(app.window):return
    g=app.g;gtk=g.libs['gtk'];size=gtk.gtk_window_get_size;size.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int)];size.restype=None;width,height=C.c_int(),C.c_int();size(app.window,C.byref(width),C.byref(height))
    settle_expansion(app,receipt)
    target=max(640,width.value-receipt['added']) if receipt.get('settled') else receipt['before_width']
    resize=gtk.gtk_window_resize;resize.argtypes=[C.c_void_p,C.c_int,C.c_int];resize.restype=None;resize(app.window,target,height.value)
    position=gtk.gtk_window_get_position;position.argtypes=size.argtypes;position.restype=None;x,y=C.c_int(),C.c_int();position(app.window,C.byref(x),C.byref(y))
    if abs(x.value-receipt['expanded_x'])<=2:
        move=gtk.gtk_window_move;move.argtypes=[C.c_void_p,C.c_int,C.c_int];move.restype=None;move(app.window,receipt['before_x'],y.value)
