"""Validated local palette roles and background-only panel transparency."""
import ctypes as C
import re
import time
from .message_style import BUBBLE_KEYS,BUBBLE_DEFAULTS,bubble_colors,bubble_palette
from .ui_typography import DEFAULT_FONT_SIZE,font_size,font_stylesheet,apply_font

ROLES=('canvas','panel','surface','text','accent','border')
LABELS={'canvas':'工作区背景','panel':'侧栏与列表','surface':'卡片与弹层','text':'界面文字','accent':'强调色','border':'边框与分隔线'}
PRESETS={
    'codex':('清晰深色',('#141414','#1b1b1b','#252525','#f1f1f1','#b6c5ff','#454545')),
    'graphite':('石墨',('#18191c','#242528','#2e2f33','#e5e7eb','#a9b9ef','#41434a')),
    'ocean':('深海',('#111a24','#1b2b3b','#263b50','#e2edf6','#80b9e8','#3b536b')),
    'forest':('苔绿',('#151d19','#223129','#304137','#e0ebe4','#8cc9a5','#43584b')),
    'plum':('暮紫',('#1c1823','#2d2538','#3b3049','#eee5f5','#c0a0e3','#564562')),
    'paper':('浅纸',('#e5e7eb','#f0f1f3','#fafafa','#30343a','#526ca4','#cbd0d8'))}

# ==========================================
# Function: Bound a durable percentage even if imported preferences are malformed.
# Method: Accept numeric inputs only and fall back to a safe readable default.
# ==========================================
def percent(value,default=100,low=20):
    try:return min(100,max(low,int(value)))
    except (ValueError,TypeError,OverflowError):return default

# ==========================================
# Function: Validate all palette values before they become native CSS.
# Method: Allow only full RGB hex tokens, never interpolated CSS expressions.
# ==========================================
def palette(values):
    clean={}
    for role in ROLES:
        value=values.get('color_'+role,'')
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError(LABELS[role]+' 请填写 #RRGGBB 颜色')
        clean[role]=value.lower()
    return clean

# ==========================================
# Function: Project a durable scheme onto the named native palette roles.
# Method: Resolve saved themes/presets and validate font, contrast and opacity values.
# ==========================================
def preferences(store):
    scheme=store.preference('appearance_scheme','original')
    if scheme not in (*PRESETS,'custom','original'):scheme='original'
    colors=PRESETS.get(scheme,PRESETS['paper' if store.preference('theme','dark')=='light' else 'codex'])[1]
    result={key:store.preference(key,default) for key,default in [('appearance_scheme',scheme),('ui_font_size',DEFAULT_FONT_SIZE),('panel_opacity',100),('window_opacity',100),('appearance_contrast',110),('attachment_open_width',700),('attachment_auto_expand',True)]}
    from .window_workspace import attachment_width
    result['attachment_open_width']=attachment_width(result['attachment_open_width'])
    result['appearance_contrast']=contrast_level(result['appearance_contrast'])
    result['ui_font_size']=font_size(result['ui_font_size'])
    result['panel_opacity']=percent(result['panel_opacity']);result['window_opacity']=percent(result['window_opacity'],low=50)
    for role,value in zip(ROLES,colors):
        selected=store.preference('color_'+role,value) if scheme=='custom' else value
        result['color_'+role]=selected.lower() if isinstance(selected,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',selected) else value
    defaults=BUBBLE_DEFAULTS['light' if store.preference('theme','dark')=='light' else 'dark']
    for key,default in zip(BUBBLE_KEYS,defaults):
        value=store.preference(key,default)
        result[key]=value.lower() if isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value) else default
    return result

# ==========================================
# Function: Bound readable UI contrast without altering stored RGB colors.
# Method: Accept70–150 percent and keep110 percent as the clearer default.
# ==========================================
def contrast_level(value):
    try:return max(70,min(150,int(value)))
    except (TypeError,ValueError,OverflowError):return 110

# ==========================================
# Function: Blend two validated RGB roles without interpolating CSS.
# Method: Clamp channels after linear per-channel interpolation.
# ==========================================
def blend(a,b,amount):
    return '#'+''.join(f'{max(0,min(255,round(int(a[i:i+2],16)*(1-amount)+int(b[i:i+2],16)*amount))):02x}' for i in (1,3,5))

# ==========================================
# Function: Increase text/surface separation while preserving custom hues and identities.
# Method: Darken dark canvases, lighten text/borders, and reverse the transform for light themes or lower contrast.
# ==========================================
def effective_palette(values):
    c=palette(values);level=contrast_level(values.get('appearance_contrast',110))/100;dark=sum(int(c['canvas'][i:i+2],16) for i in (1,3,5))<384
    if dark:
        c['canvas']=blend(c['canvas'],'#000000',1-1/level);c['panel']=blend(c['panel'],'#000000',1-1/(level**.5))
        c['text']=blend(c['text'],'#ffffff',max(0,level-1)*.8) if level>=1 else blend(c['text'],c['surface'],(1-level)*.7)
        c['border']=blend(c['border'],'#ffffff',max(0,level-1)*.45) if level>=1 else blend(c['border'],c['canvas'],1-level)
    else:
        c['canvas']=blend(c['canvas'],'#ffffff',max(0,level-1)*.4);c['text']=blend(c['text'],'#000000',1-1/level);c['border']=blend(c['border'],'#000000',1-1/(level**.7))
    return c

# ==========================================
# Function: Express a validated RGB token with bounded background alpha.
# Method: Leave foreground/text opacity fully opaque.
# ==========================================
def rgba(color,opacity):return 'rgba('+','.join(str(int(color[i:i+2],16)) for i in (1,3,5))+','+str(opacity/100)+')'

# ==========================================
# Function: Build palette rules for application surfaces without recoloring sender identities or PDFs.
# Method: Use scoped widget roles and transparent list rows over one canvas layer.
# ==========================================
def stylesheet(values):
    c=effective_palette(values);alpha=percent(values['panel_opacity']);panel=rgba(c['panel'],alpha);surface=rgba(c['surface'],max(75,alpha));accent=c['accent'];text=c['text'];border=c['border']
    bubbles=''
    for direction,own in [('own',True),('other',False)]:
        colors=bubble_palette(values,own)
        bubbles+=f".message-{direction}, .light .message-{direction} {{ background: {colors['surface']}; border-color: {colors['border']}; }}\n"
        bubbles+=f".message-{direction} .message-text, .message-{direction} button.message-text label, .light .message-{direction} .message-text, .light .message-{direction} button.message-text label {{ color: {colors['text']}; }}\n"
        bubbles+=f".message-{direction} .history-badge {{ background: {rgba(colors['text'],12)}; }}\n"
    return f'''
window, window.light, window.dark {{ background: {c['canvas']}; color: {text}; }}
#workspace_overlay, #workspace, #contact_chat, .light #contact_chat {{ background: {c['canvas']}; }}
#contact_chat .chat-header, .light #contact_chat .chat-header {{ background: {panel}; color: {text}; border-color: {border}; }}
#contact_chat .chat-composer, .light #contact_chat .chat-composer {{ background: transparent; color: {text}; }}
#contact_chat .chat-header label, #contact_chat .chat-composer label {{ color: {text}; }}
#contact_chat .chat-compose-bubble, .light #contact_chat .chat-compose-bubble {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
#contact_chat .chat-compose-scroll, #contact_chat .chat-compose-scroll viewport, #contact_chat .chat-compose-body, #contact_chat .chat-compose-body text {{ background: transparent; border: 0; color: {text}; }}
#contact_chat .chat-compose-field {{ background: {c['surface']}; color: {text}; border-color: {border}; }}
#contact_chat .chat-compose-account button {{ background: {rgba(text,9)}; color: {text}; }}
headerbar, .light headerbar {{ background: {c['panel']}; border-color: {border}; }}
headerbar .title, .light headerbar .title {{ color: {text}; }}
#rail, .light #rail, #listpane, .light #listpane, #sidebar, .light #sidebar, #navigation_surface, .light #navigation_surface {{ background: {panel}; color: {text}; }}
#reader, .light #reader, #mail_card, .light #mail_card, .document-panel {{ background: {c['panel']}; color: {text}; }}
#messages, .light #messages, #messages row, .light #messages row {{ background: transparent; color: {text}; }}
#messages row:hover, #rail button:hover, .light #rail button:hover {{ background: {rgba(accent,12)}; }}
#messages row:selected, .light #messages row:selected, #rail button.rail-active, .light #rail button.rail-active {{ background: {rgba(accent,22)}; color: {text}; }}
.surface-editor, .surface-flyout, .light .surface-editor, .light .surface-flyout, .surface-flyout#views_menu, .light .surface-flyout#views_menu, .conversation-card, .quoted-history-card, .light .conversation-card, .light .quoted-history-card {{ background: {surface}; border-color: {border}; color: {text}; }}
.surface-editor #settings_sidebar, .light .surface-editor #settings_sidebar {{ background: {panel}; }}
.surface-editor .settings-heading, .surface-editor .settings-option label, .surface-editor .editor-field-label, .surface-editor .surface-editor-title, .surface-editor .settings-navigation, .light .surface-editor .settings-heading, .light .surface-editor .settings-navigation {{ color: {text}; }}
.surface-editor .settings-navigation.active, .light .surface-editor .settings-navigation.active, .surface-editor .settings-link:hover, .light .surface-editor .settings-link:hover {{ background: {rgba(accent,16)}; color: {text}; }}
.surface-editor .settings-option, .surface-editor .settings-link, .surface-editor .account-card, .light .surface-editor .settings-option, .light .surface-editor .settings-link, .light .surface-editor .account-card {{ background: transparent; border-color: {border}; }}
.surface-editor entry, .surface-editor .settings-option entry, .surface-editor .editor-field entry, .choice-chip, .light .choice-chip {{ background: {c['surface']}; color: {text}; border-color: {border}; }}
.surface-editor button.suggested-action, button.suggested-action {{ background: {accent}; color: {c['canvas']}; border-color: {accent}; }}
.file-tabs, .file-tab.active, .document-tab, .document-canvas, .document-controls, #list_header, .document-panel, .attachment-card, paned > separator {{ border-color: {border}; }}
.document-controls, .light .document-controls, .attachment-card, .light .attachment-card {{ background: {surface}; color: {text}; }}
.attachment-card:hover, .light .attachment-card:hover {{ background: {rgba(accent,15)}; }}
.document-controls label, .light .document-controls label, .attachment-detail, .light .attachment-detail {{ color: {rgba(text,70)}; }}
.mail-sender, .mail-subject, .subject, .view-title, .light .mail-sender, .light .mail-subject, .light .subject, .light .view-title {{ color: {text}; }}
.file-workspace, .light .file-workspace, .document-canvas, .light .document-canvas {{ background: {c['canvas']}; }}
.muted, .mail-preview, .settings-description, .section-title, .light .muted, .light .mail-preview, .light .settings-description {{ color: {rgba(text,78)}; }}
scrollbar slider {{ background: {rgba(text,32)}; }}
scrollbar slider:hover, scrollbar slider:active {{ background: {rgba(text,55)}; }}
paned > separator {{ background: {border}; }}
.file-tab.active, .file-breadcrumb, .light .file-tab.active, .light .file-breadcrumb {{ background: {surface}; color: {text}; }}
.notification-card {{ background: {c['surface']}; color: {text}; border-color: {border}; border-left-color: {accent}; }}
.notification-title, .notification-body {{ color: {text}; }}
'''+bubbles+borderless_stylesheet(accent,text)+f'''.history-connector {{ background: {border}; min-width: 1px; }}
.attachment-card, .attachment-card:hover, .attachment-card:focus, .attachment-card:active, .light .attachment-card, .light .attachment-card:hover, .light .attachment-card:focus, .light .attachment-card:active {{ border: 1px solid {border}; outline-width: 0; box-shadow: none; }}
#contact_chat button.chat-compose-action, #contact_chat button.chat-compose-action:focus {{ background: transparent; }}
#contact_chat button.chat-compose-action:hover {{ background: {rgba(text,12)}; }}
#contact_chat button.chat-compose-send, #contact_chat button.chat-compose-send:focus {{ background: {accent}; }}
#contact_chat button.chat-compose-send:hover {{ background: {blend(accent,text,.12)}; }}
#contact_chat button.chat-compose-send:disabled {{ background: {rgba(text,12)}; opacity: .5; }}
#contact_chat .chat-compose-bubble {{ background: {blend(c['surface'],c['panel'],.16)}; border-color: {rgba(text,13)}; }}
#contact_chat .chat-compose-bubble.compose-active {{ border-color: {rgba(accent,60)}; }}
.person-header-aliases, .directory-email, .directory-count {{ color: {rgba(text,66)}; }}
#contact_chat label.chat-compose-placeholder {{ color: {rgba(text,50)}; }}
#contact_chat .chat-compose-mode {{ background: {rgba(text,8)}; color: {rgba(text,80)}; }}
.chat-header {{ background: {panel}; color: {text}; border-color: {border}; }}
.picker-avatar, .directory-avatar {{ background: {rgba(accent,15)}; color: {accent}; }}
.directory-person label, .contact-drawer label, .directory-bulk label {{ color: {text}; }}
.directory-person .directory-email {{ color: {rgba(text,64)}; }}
button.directory-person:hover, button.directory-person:focus {{ background: {rgba(accent,10)}; }}
.picker-heading, .picker-empty, .directory-section, .directory-index button {{ color: {rgba(text,66)}; }}
.directory-index button:disabled {{ opacity: .22; }}
.directory-index button:hover {{ background: {rgba(accent,18)}; color: {accent}; }}
.directory-badge {{ background: {rgba(accent,10)}; color: {rgba(text,80)}; }}
.contact-drawer textview, .contact-drawer textview text {{ background: {c['panel']}; color: {text}; }}
#contact_chat .chat-compose-bubble button.sender-choice, #contact_chat .chat-compose-bubble button.recipient-picker-button {{ background: transparent; border: 0; }}
#contact_chat .chat-compose-bubble button.sender-choice:hover, #contact_chat .chat-compose-bubble button.sender-choice:checked, #contact_chat .chat-compose-bubble button.sender-choice:focus,
#contact_chat .chat-compose-bubble button.recipient-picker-button:hover, #contact_chat .chat-compose-bubble button.recipient-picker-button:checked, #contact_chat .chat-compose-bubble button.recipient-picker-button:focus {{ background: {rgba(text,12)}; }}
button.conversation-sender, button.conversation-sender:focus, .light button.conversation-sender:focus {{ background: transparent; }}
button.conversation-sender:hover {{ background: {rgba(text,7)}; }}
.directory-index button, .directory-index button:focus, .directory-index button:hover {{ background: transparent; border: 0; box-shadow: none; }}
.directory-index button.current-letter {{ background: {rgba(text,11)}; color: {text}; font-weight: 700; }}
.picker-section {{ color: {rgba(text,62)}; }}
.reply-history-toggle, .reply-history-remove {{ color: {rgba(text,64)}; }}
.reply-history-toggle, .reply-history-toggle:focus, .reply-history-remove, .reply-history-remove:focus {{ background: transparent; }}
.reply-history-toggle:hover, .reply-history-remove:hover {{ background: {rgba(text,12)}; }}
#messages button.avatar-unread-bubble, #messages button.avatar-unread-bubble:focus {{ color: {c['canvas']}; background: {accent}; font-size: 9px; transition: none; }}
#messages button.avatar-unread-bubble:hover {{ color: {c['canvas']}; background: {blend(accent,text,.2)}; }}
#messages button.avatar-unread-bubble:disabled {{ background: {accent}; }}
#messages .avatar-history-bubble {{ background: {rgba(text,18)}; color: {text}; }}
#messages button.unread-action {{ color: {accent}; }}
.directory-bulk, .light .directory-bulk {{ background: transparent; }}
.directory-bulk button:focus, .directory-bulk button:active {{ background: {rgba(text,10)}; }}
button.state-enabled, button.state-enabled:focus {{ background: {rgba(text,8)}; color: #e9be58; }}
#contact_chat button.chat-bottom-button, #contact_chat button.chat-bottom-button:focus {{ background: {c['panel']}; color: {text}; box-shadow: 0 2px 6px rgba(0,0,0,.18); }}
#contact_chat button.chat-bottom-button:hover {{ background: {rgba(text,18)}; }}
.reply-history-card {{ border: 1px solid {rgba(text,12)}; border-radius: 10px; background: {c['surface']}; }}'''

# ==========================================
# Function: Remove pointer focus fills while retaining explicit keyboard navigation cues.
# Method: Match existing id-heavy selectors in the highest-priority theme provider.
# ==========================================
def borderless_stylesheet(accent='#b6c5ff',text='#f1f1f1'):
    selectors=['button','.light button','.surface-editor button','.light .surface-editor button','.surface-flyout button','#rail button','#inbox_view_menu button.inbox-view-choice','.light #inbox_view_menu button.inbox-view-choice','#list_header #focus_back','#list_header #view_toggle','.light #list_header #focus_back','.light #list_header #view_toggle','.floating-navigation .folder-item-row button.folder-row','.surface-editor .settings-option button.color-chip']
    states=('',':hover',':focus',':active',':checked',':disabled','.active')
    all_states=', '.join(selector+state for selector in selectors for state in states)
    focus=', '.join(selector+state for selector in selectors for state in (':focus',':active',':checked','.active'))
    quiet=', '.join(selector+':focus:not(:hover):not(:checked):not(.active):not(.rail-active):not(.current-letter)' for selector in selectors)
    keyboard=', '.join('.keyboard-navigation '+selector+':focus' for selector in selectors)
    return all_states+' { border-style: none; border-width: 0; border-color: transparent; outline-style: none; outline-width: 0; outline-offset: 0; box-shadow: none; background-image: none; }\n'+focus+' { background-color: '+rgba(accent,18)+'; }\n'+quiet+' { background-color: transparent; }\n'+keyboard+' { outline-style: solid; outline-width: 1px; outline-color: '+rgba(text,45)+'; outline-offset: -1px; }\n'

# ==========================================
# Function: Reuse one theme provider and apply an explicitly staged or saved appearance.
# Method: Reuse palette and font providers, preserve live drag drawing and keep Cancel rollback possible.
# ==========================================
def apply(app,values=None):
    g=app.g;values=values or preferences(app.service.store);old=getattr(app,'palette_provider',None)
    size=font_size(values.get('ui_font_size',DEFAULT_FONT_SIZE));apply_font(app,size)
    if values['appearance_scheme']=='original':
        from .desktop_preferences import resolved_theme
        colors=PRESETS['paper' if resolved_theme(app)=='light' else 'codex'][1];values={**values,**{'color_'+role:value for role,value in zip(ROLES,colors)}}
    source=font_stylesheet(stylesheet(values),size);provider=old or g.gtk_css_provider_new()
    if not old or source!=getattr(app,'palette_css_source',None):
        encoded=source.encode()
        if not g.gtk_css_provider_load_from_data(provider,encoded,len(encoded),None):raise ValueError('配色样式无法载入')
        if not old:g.gtk_style_context_add_provider_for_screen(g.gdk_screen_get_default(),provider,650)
        app.palette_css_source=source
    app.palette_provider=provider;app.message_style_values=bubble_colors(values);colors=effective_palette(values)
    global_signature=(colors['surface'],colors['text'],colors['border'])
    message_signature=tuple(app.message_style_values.values())
    global_changed=getattr(app,'reader_palette_signature',None)!=global_signature
    message_changed=getattr(app,'message_palette_signature',None)!=message_signature
    app.reader_palette_signature=global_signature;app.reader_palette=colors;app.message_palette_signature=message_signature
    if global_changed or message_changed:
        app.reader_theme_global_pending=bool(getattr(app,'reader_theme_global_pending',False) or global_changed)
        app.reader_theme_message_pending=bool(getattr(app,'reader_theme_message_pending',False) or message_changed)
        app.reader_theme_pending=time.monotonic()+.18
    g.gtk_widget_set_opacity(app.window,percent(values['window_opacity'],low=50)/100)

# ==========================================
# Function: Refresh active HTML colors only after appearance changes settle.
# Method: Use the existing desktop tick; never re-open inactive file engines or recolor native PDF pages.
# ==========================================
def refresh_readers(app):
    pending=getattr(app,'reader_theme_pending',0)
    if not pending or time.monotonic()<pending or app.closing:return
    global_changed=getattr(app,'reader_theme_global_pending',False);message_changed=getattr(app,'reader_theme_message_pending',False)
    app.reader_theme_pending=0;app.reader_theme_global_pending=False;app.reader_theme_message_pending=False;readers=[]
    if not (global_changed or message_changed):return
    for card in list(getattr(app,'conversation_cards',{}).values())+list(getattr(getattr(app,'chat_surface',None),'conversation_cards',{}).values()):
        readers.extend(card.get('body_readers',[]))
        for quote in card.get('quote_cards',[]):readers.extend(quote.get('readers',[]))
    if global_changed and app.document:readers.append(app.document.engine)
    seen=set()
    for reader in readers:
        if reader and id(reader) not in seen and not getattr(reader,'closed',False) and hasattr(reader,'reload'):
            seen.add(id(reader));reader.reload()
