"""Shared native icon actions with explicit accessible names and restrained styling."""
import ctypes as C
from pathlib import Path

ICONS=Path(__file__).parent/'desktop_assets/icons'

# ==========================================
# Function: Turn a repetitive action into a compact, named and keyboard-accessible icon button.
# Method: Reuse packaged SVGs, preserve its signal/response, and set tooltip plus native ATK name.
# ==========================================
def icon_action(g,button,title,icon,size=18):
    focus=g.libs['gtk'].gtk_button_set_focus_on_click;focus.argtypes=[C.c_void_p,C.c_int];focus.restype=None;focus(button,0)
    g.gtk_button_set_label(button,b'')
    g.gtk_button_set_image(button,g.image_file(ICONS/(icon+'.svg'),size))
    g.gtk_button_set_always_show_image(button,1)
    g.gtk_widget_set_tooltip_text(button,title.encode())
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'compact-action')
    accessible=g.gtk_widget_get_accessible(button)
    setter=C.CFUNCTYPE(None,C.c_void_p,C.c_char_p,C.c_char_p,C.c_void_p)(C.cast(g.libs['object'].g_object_set,C.c_void_p).value)
    setter(accessible,b'accessible-name',title.encode(),None)
    return button

# ==========================================
# Function: Reflect a durable toggled state with a yellow icon and a neutral active surface.
# Method: Select the packaged active SVG explicitly so full-color file icons honor state independently of theme tinting.
# ==========================================
def state_action(g,button,title,icon,active,size=16):
    icon_action(g,button,title,icon+'-active' if active else icon,size)
    context=g.gtk_widget_get_style_context(button)
    (g.gtk_style_context_add_class if active else g.gtk_style_context_remove_class)(context,b'state-enabled')
    return button
