"""Shared explicit-sender direction and validated per-message reading palettes."""
import re
from .participant_identity import own_identities,is_own_sender

BUBBLE_KEYS=('bubble_color_own','bubble_color_other')
BUBBLE_LABELS=('我的邮件气泡','他人的邮件气泡')
BUBBLE_DEFAULTS={'dark':('#293c50','#292d34'),'light':('#deebfc','#f5f6f8')}

# ==========================================
# Function: Include every configured mailbox in the user's own identity set.
# Method: Share backend normalization and explicitly include the isolated demo identity.
# ==========================================
def app_own_identities(app):
    return own_identities(app.service.accounts.values(),extra=('demo@example.com',) if getattr(app.profile,'demo',False) else ())

# ==========================================
# Function: Attribute a bubble only from explicit sender metadata.
# Method: Reuse conservative address matching without examining body or recipient text.
# ==========================================
def bubble_direction(message,own):
    return 'own' if is_own_sender(message,own) else 'other'

# ==========================================
# Function: Validate independent message background choices.
# Method: Accept complete RGB hex tokens only, preserving all six global theme roles.
# ==========================================
def bubble_colors(values,theme='dark'):
    result={}
    for key,label,default in zip(BUBBLE_KEYS,BUBBLE_LABELS,BUBBLE_DEFAULTS.get(theme,BUBBLE_DEFAULTS['dark'])):
        value=values.get(key,default)
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError(label+' 请填写 #RRGGBB 颜色')
        result[key]=value.lower()
    return result

# ==========================================
# Function: Choose a readable text color for any selected bubble background.
# Method: Compare relative sRGB luminance against black/white WCAG contrast ratios.
# ==========================================
def bubble_palette(values,own=False,theme='dark'):
    background=bubble_colors(values,theme)[BUBBLE_KEYS[0 if own else 1]]
    channels=[int(background[i:i+2],16)/255 for i in (1,3,5)]
    linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
    light=sum(a*b for a,b in zip(linear,(.2126,.7152,.0722)))
    foreground='#000000' if (light+.05)/.05>=1.05/(light+.05) else '#ffffff'
    border='#'+''.join(f'{round(int(background[i:i+2],16)*.8+int(foreground[i:i+2],16)*.2):02x}' for i in (1,3,5))
    return {'surface':background,'text':foreground,'border':border,'force_message':True}

# ==========================================
# Function: Resolve a reader's live staged message palette without changing document colors.
# Method: Scope overrides to explicitly tagged message readers; file and PDF readers stay global.
# ==========================================
def reader_appearance(reader):
    app=reader.app
    if not hasattr(reader,'message_own'):return getattr(app,'reader_palette',None)
    from .desktop_preferences import resolved_theme
    return bubble_palette(getattr(app,'message_style_values',{}),reader.message_own,resolved_theme(app))

# ==========================================
# Function: Tag native text painted directly on a message bubble's own background.
# Method: Opt in individual labels/actions without recoloring independent child surfaces.
# ==========================================
def message_text(g,widget):
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(widget),b'message-text')
    return widget
