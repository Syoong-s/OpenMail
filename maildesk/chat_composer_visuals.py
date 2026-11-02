"""Presentation-only recipient/account captions and a resolution-independent send glyph."""
from .i18n import text as _tr
import ctypes as C
from email.utils import getaddresses


# ==========================================
# Function: Keep recipients legible without merging their identities with the subject line.
# Method: Display the first exact mailbox plus explicit remaining/CC/BCC indicators; preserve originals elsewhere.
# ==========================================
def recipient_caption(to,cc='',bcc=''):
    recipients=[address for name,address in getaddresses([to],strict=False) if address]
    first=recipients[0] if recipients else to.strip() or _tr('选择收件人')
    caption=_tr('收件人  ')+first+(f'  +{len(recipients)-1}' if len(recipients)>1 else '')
    if cc:caption+=_tr(' · 抄送')
    if bcc:caption+=_tr(' · 密送待核对')
    return caption


# ==========================================
# Function: Give the docked sender a short identity without changing its real mail address.
# Method: Prefer configured aliases, otherwise a unique domain or a local-part when domains collide.
# ==========================================
def sender_caption(account,accounts):
    email=account.email;domain=email.rsplit('@',1)[-1]
    alias=(getattr(account,'title','') or getattr(account,'display_name','')).strip()
    if alias and '@' not in alias:return alias
    if sum(other.email.rsplit('@',1)[-1].casefold()==domain.casefold() for other in accounts)==1:return domain
    return email.split('@',1)[0]


# ==========================================
# Function: Render a centered, high-contrast send arrow without scaling a small bitmap.
# Method: Draw native Cairo strokes in a fixed logical square using the button's theme foreground.
# ==========================================
def send_glyph(g,button,group):
    from .platform_native import load_library
    cairo=load_library('cairo');p=C.c_void_p;d=C.c_double
    signatures={'cairo_set_source_rgba':(None,p,d,d,d,d),'cairo_set_line_width':(None,p,d),
                'cairo_set_line_cap':(None,p,C.c_int),'cairo_set_line_join':(None,p,C.c_int),
                'cairo_move_to':(None,p,d,d),'cairo_line_to':(None,p,d,d),'cairo_stroke':(None,p)}
    for name,signature in signatures.items():
        function=getattr(cairo,name);function.restype,function.argtypes=signature[0],signature[1:]
    color=g.libs['gtk'].gtk_style_context_get_color;color.restype=None;color.argtypes=[p,C.c_int,p]
    state=g.libs['gtk'].gtk_style_context_get_state;state.restype=C.c_int;state.argtypes=[p]
    g.gtk_button_set_image(button,None)
    child=g.gtk_bin_get_child(button)
    if child:g.gtk_container_remove(button,child)
    glyph=g.gtk_drawing_area_new();g.gtk_widget_set_size_request(glyph,20,20)
    g.gtk_widget_set_halign(glyph,3);g.gtk_widget_set_valign(glyph,3);g.gtk_widget_set_valign(button,3)
    g.gtk_container_add(button,glyph)

    # ==========================================
    # Function: Paint a symmetric arrow in the allocated glyph's actual center.
    # Method: Use the current GTK style and device transform for dark/light themes and display scaling.
    # ==========================================
    def draw(widget,cr,data):
        context=g.gtk_widget_get_style_context(button);rgba=(d*4)();color(context,state(context),C.byref(rgba))
        cairo.cairo_set_source_rgba(cr,*rgba);cairo.cairo_set_line_width(cr,2.2);cairo.cairo_set_line_cap(cr,1);cairo.cairo_set_line_join(cr,1)
        x=g.gtk_widget_get_allocated_width(widget)/2;y=g.gtk_widget_get_allocated_height(widget)/2
        cairo.cairo_move_to(cr,x-5,y);cairo.cairo_line_to(cr,x,y-5);cairo.cairo_line_to(cr,x+5,y)
        cairo.cairo_move_to(cr,x,y-5);cairo.cairo_line_to(cr,x,y+5);cairo.cairo_stroke(cr)
        return False
    g.connect(glyph,'draw',draw,count=3,returns=True,group=group)
    return glyph
