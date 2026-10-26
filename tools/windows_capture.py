"""Capture only an owned visible native GTK window, including WebView2 child surfaces."""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import struct
import time
import zlib

# ==========================================
# Function: Save a real Windows on-screen client image rather than unsupported GDK capture pixels.
# Method: Foreground the test-owned HWND, copy its exact client rectangle, and encode RGB PNG.
# ==========================================
def screenshot(g, widget, destination):
    handle = g.libs['gdk'].gdk_win32_window_get_handle
    handle.argtypes = [C.c_void_p]; handle.restype = C.c_void_p
    hwnd = handle(g.gtk_widget_get_window(widget))
    if not hwnd:
        raise ValueError('Test widget has no native top-level HWND')
    user = C.WinDLL('user32', use_last_error=True); gdi = C.WinDLL('gdi32', use_last_error=True)
    user.SetForegroundWindow.argtypes = [W.HWND]; user.GetForegroundWindow.restype = W.HWND
    user.ShowWindow.argtypes = [W.HWND, C.c_int]
    user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
    user.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
    user.GetDC.argtypes = [W.HWND]; user.GetDC.restype = W.HDC
    user.ReleaseDC.argtypes = [W.HWND, W.HDC]
    gdi.CreateCompatibleDC.argtypes = [W.HDC]; gdi.CreateCompatibleDC.restype = W.HDC
    gdi.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]; gdi.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]; gdi.SelectObject.restype = W.HGDIOBJ
    gdi.BitBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]
    gdi.DeleteObject.argtypes = [W.HGDIOBJ]; gdi.DeleteDC.argtypes = [W.HDC]
    gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT]
    # Join only input queues briefly to satisfy Windows' foreground-lock policy.
    # No messages or input are sent to the unrelated foreground application.
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    user.GetWindowThreadProcessId.restype = W.DWORD
    user.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]
    user.BringWindowToTop.argtypes = [W.HWND]
    kernel = C.WinDLL('kernel32'); kernel.GetCurrentThreadId.restype = W.DWORD
    current_thread = kernel.GetCurrentThreadId()
    foreground_thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
    attached = bool(foreground_thread and foreground_thread != current_thread and
                    user.AttachThreadInput(current_thread, foreground_thread, True))
    try:
        user.ShowWindow(hwnd, 9); user.BringWindowToTop(hwnd); user.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user.AttachThreadInput(current_thread, foreground_thread, False)
    C.WinDLL('dwmapi').DwmFlush()
    foreground = user.GetForegroundWindow()
    if foreground != hwnd:
        user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        pid = W.DWORD(); user.GetWindowThreadProcessId(foreground, C.byref(pid))
        from verify_windows_native import descendants
        if pid.value != os.getpid() and pid.value not in descendants(os.getpid()):
            raise RuntimeError('Refusing to capture while another application is foreground; pid=' + str(pid.value))
    rect = W.RECT(); origin = W.POINT()
    if not user.GetClientRect(hwnd, C.byref(rect)) or not user.ClientToScreen(hwnd, C.byref(origin)):
        raise C.WinError(C.get_last_error())
    # GTK's client-side shadow/corner padding is transparent on Windows. Exclude it
    # so an owned-window proof never captures another application's background pixels.
    scale = g.libs['gdk'].gdk_window_get_scale_factor
    scale.argtypes = [C.c_void_p]; scale.restype = C.c_int
    inset = 12 * max(1, scale(g.gtk_widget_get_window(widget)))
    width, height = rect.right - inset * 2, rect.bottom - inset * 2
    origin.x += inset; origin.y += inset
    if width < 100 or height < 100:
        raise ValueError('No painted client-sized native surface')
    screen = user.GetDC(None); memory = gdi.CreateCompatibleDC(screen)
    bitmap = gdi.CreateCompatibleBitmap(screen, width, height); old = gdi.SelectObject(memory, bitmap)
    try:
        if not gdi.BitBlt(memory, 0, 0, width, height, screen, origin.x, origin.y, 0x00CC0020 | 0x40000000):
            raise C.WinError(C.get_last_error())
        header = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
        info = C.create_string_buffer(header + b'\0' * 16); pixels = C.create_string_buffer(width * height * 4)
        gdi.SelectObject(memory, old)
        if not gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0):
            raise C.WinError(C.get_last_error())
        raw = pixels.raw; scan = bytearray()
        for y in range(height):
            scan.append(0)
            row = raw[y * width * 4:(y + 1) * width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3] = row[2::4]; rgb[1::3] = row[1::4]; rgb[2::3] = row[0::4]
            scan.extend(rgb)
        if len(set(raw[::101])) <= 1:
            raise AssertionError('Native capture contains only blank pixels')
        chunks = []
        for kind, payload in ((b'IHDR', struct.pack('>2I5B', width, height, 8, 2, 0, 0, 0)),
                              (b'IDAT', zlib.compress(scan)), (b'IEND', b'')):
            chunks.append(struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload)))
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_bytes(b'\x89PNG\r\n\x1a\n' + b''.join(chunks))
    finally:
        gdi.SelectObject(memory, old); gdi.DeleteObject(bitmap); gdi.DeleteDC(memory); user.ReleaseDC(None, screen)
