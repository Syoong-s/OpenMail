"""Coherent whole-window Windows DPI handling for the bundled GTK 3 runtime."""
import ctypes as C
from ctypes import wintypes as W
from functools import lru_cache
import os
import time
from types import SimpleNamespace

# ==========================================
# Function: Bind documented Windows display APIs with pointer-safe signatures.
# Method: Cache handles without changing desktop settings or another application's DPI mode.
# ==========================================
@lru_cache(maxsize=1)
def api():
    user=C.WinDLL('user32',use_last_error=True)
    signatures={
        'SetThreadDpiAwarenessContext':(W.HANDLE,W.HANDLE),
        'GetDpiForSystem':(W.UINT,),
        'MonitorFromWindow':(W.HANDLE,W.HWND,W.DWORD),
        'GetMonitorInfoW':(W.BOOL,W.HANDLE,C.c_void_p),
        'GetWindowRect':(W.BOOL,W.HWND,C.POINTER(W.RECT)),
        'GetClientRect':(W.BOOL,W.HWND,C.POINTER(W.RECT)),
        'SetWindowPos':(W.BOOL,W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT)}
    for name,signature in signatures.items():
        function=getattr(user,name);function.restype=signature[0];function.argtypes=signature[1:]
    return user

# ==========================================
# Function: Keep GTK's entire coordinate system stable across 100/150/200 percent displays.
# Method: Render at one system-DPI resolution and let Windows scale complete windows together.
# ==========================================
def configure():
    user=api();dpi=max(96,user.GetDpiForSystem())
    os.environ['GDK_SCALE']=str(max(1,(dpi+95)//96))
    os.environ['GDK_DPI_SCALE']='1'
    if not user.SetThreadDpiAwarenessContext(C.c_void_p(-2)):
        raise C.WinError(C.get_last_error())
    return {'mode':'system-aware-whole-window','system_dpi':dpi,'gtk_scale':int(os.environ['GDK_SCALE'])}

# ==========================================
# Function: Read physical window/work-area bounds despite DPI virtualization.
# Method: Temporarily change only the querying thread context, then restore it before GTK dispatch.
# ==========================================
def geometry(g,window):
    native=g.gtk_widget_get_window(window)
    if not native:return None
    handle=g.libs['gdk'].gdk_win32_window_get_handle;handle.restype=C.c_void_p;handle.argtypes=[C.c_void_p]
    hwnd=handle(native);user=api()
    class MonitorInfo(C.Structure):
        _fields_=[('size',W.DWORD),('monitor',W.RECT),('work',W.RECT),('flags',W.DWORD)]
    previous=user.SetThreadDpiAwarenessContext(C.c_void_p(-4))
    try:
        info=MonitorInfo();info.size=C.sizeof(info);rect=W.RECT();client=W.RECT()
        if not (user.GetMonitorInfoW(user.MonitorFromWindow(hwnd,2),C.byref(info)) and user.GetWindowRect(hwnd,C.byref(rect)) and user.GetClientRect(hwnd,C.byref(client))):return None
        width=g.gtk_widget_get_allocated_width(window);height=g.gtk_widget_get_allocated_height(window)
        if min(width,height,client.right,client.bottom)<=1:return None
        scale=client.right/width
        border_w=rect.right-rect.left-client.right;border_h=rect.bottom-rect.top-client.bottom
        return SimpleNamespace(hwnd=hwnd,rect=rect,work=info.work,scale=scale,border=(border_w,border_h),budget=(max(320,int((info.work.right-info.work.left-border_w)/scale)-16),max(240,int((info.work.bottom-info.work.top-border_h)/scale)-16)))
    finally:user.SetThreadDpiAwarenessContext(previous)

# ==========================================
# Function: Read or request one native client's logical GTK dimensions.
# Method: Reuse the bundled GTK C APIs without changing stored mailbox geometry preferences.
# ==========================================
def window_size(g,window,requested=None):
    if requested is not None:
        resize=g.libs['gtk'].gtk_window_resize;resize.restype=None;resize.argtypes=[C.c_void_p,C.c_int,C.c_int];resize(window,*requested)
    width,height=C.c_int(),C.c_int();getter=g.libs['gtk'].gtk_window_get_size;getter.restype=None;getter.argtypes=[C.c_void_p,C.POINTER(C.c_int),C.POINTER(C.c_int)];getter(window,C.byref(width),C.byref(height))
    return width.value,height.value

# ==========================================
# Function: Expand the owning client when a larger editor needs more desktop space.
# Method: Bound growth to the current monitor and retain a reversible, per-root receipt.
# ==========================================
def fit_dialog(surfaces,state,width,height):
    g=surfaces.g;window=state['root'];root=surfaces.roots.get(window)
    if not root or g.gtk_window_is_maximized(window):return
    bounds=geometry(g,window)
    if not bounds:return
    current=window_size(g,window);overlay=root['overlay']
    allocated=(g.gtk_widget_get_allocated_width(window),g.gtk_widget_get_allocated_height(window))
    decoration=(max(0,g.gtk_widget_get_allocated_width(window)-current[0]),max(0,g.gtk_widget_get_allocated_height(window)-current[1]))
    budget=(max(320,bounds.budget[0]-decoration[0]),max(240,bounds.budget[1]-decoration[1]))
    inset=(max(0,current[0]-g.gtk_widget_get_allocated_width(overlay)),max(0,current[1]-g.gtk_widget_get_allocated_height(overlay)))
    receipt=root.get('dialog_growth')
    if receipt:
        if receipt.get('manual'):return
        if receipt.get('monitor')!=tuple((bounds.work.left,bounds.work.top,bounds.work.right,bounds.work.bottom)):
            receipt['moved']=True
        if time.monotonic()-receipt.get('requested_at',0)>1 and not any(all(abs(a-b)<=3 for a,b in zip(allocated,expected)) for expected in (receipt['allocated_target'],receipt['allocated_before'])):
            receipt['manual']=True;return
        if receipt.get('applied_position') and any(abs(a-b)>8 for a,b in zip((bounds.rect.left,bounds.rect.top),receipt['applied_position'])):receipt['moved']=True
    target=(min(budget[0],max(current[0],int(width+24+inset[0]))),min(budget[1],max(current[1],int(height+24+inset[1]))))
    if target==current:
        if receipt:receipt['target']=current;receipt['allocated_target']=allocated
        return
    if not receipt:
        receipt={'before':current,'allocated_before':allocated,'position':(bounds.rect.left,bounds.rect.top)};root['dialog_growth']=receipt
    receipt['target']=target;receipt['allocated_target']=(target[0]+decoration[0],target[1]+decoration[1]);receipt['requested_at']=time.monotonic();receipt['monitor']=(bounds.work.left,bounds.work.top,bounds.work.right,bounds.work.bottom);window_size(g,window,target)
    physical=((target[0]+decoration[0])*bounds.scale+bounds.border[0],(target[1]+decoration[1])*bounds.scale+bounds.border[1])
    x=max(bounds.work.left,min(bounds.rect.left,int(bounds.work.right-physical[0])));y=max(bounds.work.top,min(bounds.rect.top,int(bounds.work.bottom-physical[1])))
    previous=api().SetThreadDpiAwarenessContext(C.c_void_p(-4))
    try:api().SetWindowPos(bounds.hwnd,None,x,y,0,0,0x15)
    finally:api().SetThreadDpiAwarenessContext(previous)
    receipt['applied_position']=(x,y)

# ==========================================
# Function: Restore automatic popup growth without undoing the user's own window resize.
# Method: Restore only after the last editor closes and only if its accepted size still matches.
# ==========================================
def restore_dialog(surfaces,window):
    root=surfaces.roots.get(window)
    if not root or any(surfaces.states[key]['kind']=='dialog' and surfaces.states[key]['root']==window for key in surfaces.opened):return
    receipt=root.pop('dialog_growth',None);g=surfaces.g
    if not receipt or receipt.get('manual') or g.gtk_window_is_maximized(window):return
    current=(g.gtk_widget_get_allocated_width(window),g.gtk_widget_get_allocated_height(window))
    if not any(all(abs(a-b)<=3 for a,b in zip(current,expected)) for expected in (receipt['allocated_target'],receipt['allocated_before'])):return
    bounds=geometry(g,window);window_size(g,window,receipt['before'])
    if bounds and not receipt.get('moved') and all(abs(a-b)<=3 for a,b in zip((bounds.rect.left,bounds.rect.top),receipt['applied_position'])):
        previous=api().SetThreadDpiAwarenessContext(C.c_void_p(-4))
        try:api().SetWindowPos(bounds.hwnd,None,*receipt['position'],0,0,0x15)
        finally:api().SetThreadDpiAwarenessContext(previous)
