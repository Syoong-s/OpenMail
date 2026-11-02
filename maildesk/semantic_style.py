"""Restrained companion colors shared by navigation, editors and action states."""


# ==========================================
# Function: Give familiar actions stable color meanings in both light and dark themes.
# Method: Keep secondary tones softer than the primary selection and preserve saved base palette roles.
# ==========================================
def tones(c):
    dark=sum(int(c['canvas'][i:i+2],16) for i in (1,3,5))<384
    return dict(zip(('blue','green','gold','violet','rose'),
        ('#91b5df','#81c7b0','#d8b777','#b6a6d7','#d9959f') if dark else
        ('#456e9a','#347c66','#916b2e','#79629e','#a75869')))


# ==========================================
# Function: Add calm visual variety to the whole app without competing with mail content.
# Method: Tint shared surfaces lightly and reserve stronger colors for compact functional accents and active states.
# ==========================================
def stylesheet(c,opacity=100):
    from .appearance_theme import rgba,blend
    t=tones(c);text=c['text'];accent=c['accent'];line=rgba(text,12)
    flyout=rgba(blend(c['surface'],t['blue'],.045),max(75,opacity))
    editor=rgba(blend(c['surface'],t['violet'],.025),max(75,opacity))
    css=f'''
#rail, .light #rail {{ background: {rgba(blend(c['panel'],c['canvas'],.40),opacity)}; }}
#list_header {{ background: {rgba(t['blue'],3)}; border-color: {line}; }}
.section-label, .light .section-label {{ background: {rgba(t['blue'],6)}; color: {rgba(text,65)}; }}
#sidebar.floating-navigation, #navigation_surface.floating-navigation,
.light #sidebar.floating-navigation, .light #navigation_surface.floating-navigation,
.surface-flyout, .light .surface-flyout, .surface-flyout#views_menu, .light .surface-flyout#views_menu,
popover, .light popover {{ background: {flyout}; border-color: {rgba(t['blue'],24)}; color: {text}; }}
.surface-editor, .light .surface-editor {{ background: {editor}; color: {text}; border-color: {rgba(t['violet'],23)}; }}
.surface-editor-header {{ background: {rgba(t['violet'],5)}; border-radius: 19px 19px 0 0; }}
.surface-editor-footer {{ background: {rgba(t['blue'],3)}; border-color: {line}; border-radius: 0 0 19px 19px; }}
.surface-editor #settings_sidebar, .light .surface-editor #settings_sidebar {{ background: {rgba(blend(c['panel'],t['blue'],.045),opacity)}; border-color: {line}; }}
.surface-editor .settings-option, .light .surface-editor .settings-option,
.surface-editor .settings-link, .light .surface-editor .settings-link,
.surface-editor .account-card, .light .surface-editor .account-card {{ background: {rgba(t['blue'],4)}; border-color: {line}; }}
.surface-editor entry, .surface-editor .settings-option entry, .surface-editor .editor-field entry,
.choice-chip, .light .choice-chip {{ background: {blend(c['surface'],c['canvas'],.24)}; border-color: {line}; }}
.surface-editor entry:focus {{ border-color: {rgba(accent,65)}; }}
.surface-editor .settings-navigation:hover, .light .surface-editor .settings-navigation:hover,
.choice-option:hover, .choice-option:focus, .light .choice-option:hover, .light .choice-option:focus {{ background: {rgba(t['blue'],10)}; }}
.choice-option label {{ color: {text}; }}
.surface-flyout .choice-description, .surface-editor .settings-description {{ color: {rgba(text,65)}; }}
.surface-editor switch {{ background: {rgba(text,17)}; border-color: {rgba(text,19)}; }}
.surface-editor switch:checked {{ background: {t['green']}; border-color: {t['green']}; }}
.surface-editor switch slider {{ background: #f6f8fa; }}
.floating-navigation .folder-item-row.hover, .floating-navigation .mailbox-item-row.hover,
.floating-navigation .folder-account-row:hover {{ background: {rgba(t['blue'],10)}; }}
.floating-navigation .folder-item-row.active, .floating-navigation .mailbox-item-row.active {{ background: {rgba(accent,19)}; }}
.floating-navigation .folder-account-row button.folder-account-title,
.floating-navigation .folder-account-row button.folder-account-title:hover {{ background: transparent; color: {text}; }}
.floating-navigation .section-title {{ color: {rgba(t['blue'],90)}; }}
.floating-navigation .workspace-title {{ color: {text}; }}
.notification-card {{ border-left-color: {t['green']}; background: {blend(c['surface'],t['green'],.045)}; }}
#toast {{ background: {blend(c['surface'],t['blue'],.10)}; color: {text}; border-color: {rgba(t['blue'],35)}; }}
#toast button {{ color: {t['blue']}; }}
.attachment-card, .light .attachment-card {{ background: {rgba(t['blue'],6)}; border-color: {rgba(t['blue'],19)}; }}
.attachment-card:hover, .light .attachment-card:hover {{ background: {rgba(t['blue'],11)}; }}
#contact_chat .chat-compose-bubble {{ background: {blend(c['surface'],t['violet'],.035)}; }}
#contact_chat .chat-compose-mode {{ background: {rgba(t['violet'],12)}; color: {t['violet']}; }}
#contact_chat .chat-compose-bubble button.sender-choice {{ background: {rgba(t['violet'],9)}; }}
#contact_chat .chat-compose-bubble button.sender-choice label {{ color: {t['violet']}; }}
.surface-flyout .reader-menu-heading {{ color: {rgba(t['blue'],85)}; }}
'''
    for role,color in t.items():
        css+=f'''
button.action-tone-{role}.state-enabled, button.action-tone-{role}.state-enabled:focus,
#mail_activity button.activity-action.action-tone-{role}.state-enabled {{ background: {rgba(color,13)}; color: {color}; }}
button.action-tone-{role}:hover, #mail_activity button.activity-action.action-tone-{role}:hover {{ background: {rgba(color,12)}; }}
button.reader-menu-action.action-tone-{role}.mail-menu-selected,
button.reader-menu-action.action-tone-{role}.mail-menu-selected:focus {{ background: {rgba(color,13)}; }}
button.reader-menu-action.action-tone-{role}.mail-menu-selected label {{ color: {color}; }}
'''
    for category,role in (('pinned','gold'),('verification','green'),('notification','blue'),('newsletter','violet')):
        color=t[role]
        css+=f'''
#focus_summaries row.focus-summary.focus-{category} {{ background: {rgba(color,6)}; border: 1px solid {rgba(color,16)}; border-left: 3px solid {rgba(color,65)}; border-radius: 10px; }}
#focus_summaries row.focus-{category} > button:hover {{ background: {rgba(color,9)}; }}
#focus_summaries row.focus-{category} .focus-title {{ color: {color}; }}
#focus_summaries row.focus-{category} .mail-preview {{ color: {rgba(text,65)}; }}
'''
    return css
