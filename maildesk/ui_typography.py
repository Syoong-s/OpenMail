"""Application font sizes independent of control geometry and system display scaling."""
from pathlib import Path
import re

FONT_SIZES=tuple(range(10,33,2))
DEFAULT_FONT_SIZE=14
BASE_CSS=(Path(__file__).parent/'desktop_assets/style.css').read_text(encoding='utf-8')

# ==========================================
# Function: Recover a supported UI font size from local or imported preferences.
# Method: Accept only the visible choices and use a readable 14-pixel logical default.
# ==========================================
def font_size(value):
    try:value=int(value)
    except (ValueError,TypeError,OverflowError):return DEFAULT_FONT_SIZE
    return value if value in FONT_SIZES else DEFAULT_FONT_SIZE

# ==========================================
# Function: Change typography while preserving every non-font style measurement.
# Method: Convert the original 12-pixel font hierarchy into DPI-aware points at 96 logical DPI.
# ==========================================
def font_stylesheet(source,value):
    factor=font_size(value)/12*72/96
    return re.sub(r'(font-size\s*:\s*)(\d+(?:\.\d+)?)px\b',lambda match:f'{match[1]}{float(match[2])*factor:g}pt',source)

# ==========================================
# Function: Preview or restore one local interface font choice without scaling layout lengths.
# Method: Reuse one base-style provider and refresh font resolution after native DPI changes.
# ==========================================
def apply_font(app,value,force=False):
    size=font_size(value)
    if size==getattr(app,'ui_font_size',None) and not force:return
    g=app.g;old=getattr(app,'ui_font_provider',None);provider=old or g.gtk_css_provider_new()
    source=font_stylesheet(BASE_CSS,size).encode()
    if not g.gtk_css_provider_load_from_data(provider,source,len(source),None):raise ValueError('界面字号样式无法载入')
    if not old:g.gtk_style_context_add_provider_for_screen(g.gdk_screen_get_default(),provider,600)
    app.ui_font_provider=provider;app.ui_font_size=size
    if not getattr(app,'ui_font_dpi_connected',False):
        # ==========================================
        # Function: Re-resolve typography when GTK reports a new screen DPI or monitor scale.
        # Method: Reload the retained provider without writing preferences or changing system DPI.
        # ==========================================
        def dpi_changed(*unused):
            if not getattr(app,'closing',False):apply_font(app,app.ui_font_size,force=True)
        g.connect(g.gdk_screen_get_default(),'notify::resolution',dpi_changed,count=3,group='ui-typography')
        if getattr(app,'window',None):g.connect(app.window,'notify::scale-factor',dpi_changed,count=3,group='ui-typography')
        app.ui_font_dpi_connected=True
    surfaces=getattr(g,'surfaces',None)
    if surfaces:
        for window in surfaces.roots:surfaces.queue_relayout(window)
