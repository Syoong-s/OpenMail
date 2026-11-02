"""Theme-scoped typography, calendar colors and compact secondary reader controls."""


# ==========================================
# Function: Match the overview and secondary actions to the app's effective dark/light/custom palette.
# Method: Use generous spacing, restrained surfaces and explicit contrast rather than bitmap decorations.
# ==========================================
def stylesheet(c):
    from .appearance_theme import rgba,blend
    from .semantic_style import tones
    text=c['text'];accent=c['accent'];dark=sum(int(c['canvas'][i:i+2],16) for i in (1,3,5))<384
    t=tones(c);incoming=t['green'];outgoing=t['violet']
    colors=('#2b3039','#304d49','#387264','#469e84','#66d7ac') if dark else ('#e9edf0','#c2e5d6','#89c6ad','#4f9c81','#27715c')
    return f'''
#mail_activity, #mail_activity viewport {{ background: {c['canvas']}; color: {text}; }}
#mail_activity .activity-body {{ padding: 30px 34px 24px; }}
#mail_activity label {{ color: {text}; }}
#mail_activity .activity-title {{ font-size: 23px; font-weight: 600; letter-spacing: .3px; }}
#mail_activity .activity-muted {{ font-size: 11px; color: {rgba(text,52)}; }}
#mail_activity .activity-section {{ font-size: 15px; font-weight: 600; }}
#mail_activity .activity-stat {{ padding: 14px 18px; background: {rgba(text,4)}; border: 1px solid {rgba(text,5)}; border-radius: 12px; }}
#mail_activity .activity-incoming-card {{ background: {rgba(incoming,7)}; border-color: {rgba(incoming,15)}; }}
#mail_activity .activity-outgoing-card {{ background: {rgba(outgoing,7)}; border-color: {rgba(outgoing,15)}; }}
#mail_activity .activity-neutral-card {{ background: {rgba(t['gold'],6)}; border-color: {rgba(t['gold'],14)}; }}
#mail_activity .activity-neutral {{ color: {t['gold']}; }}
#mail_activity .activity-number {{ font-size: 29px; font-weight: 600; }}
#mail_activity .activity-incoming {{ color: {incoming}; }}
#mail_activity .activity-outgoing {{ color: {outgoing}; }}
#mail_activity .activity-calendar {{ padding: 18px 21px 15px; border: 1px solid {rgba(t['blue'],15)}; border-radius: 13px; background: {rgba(t['blue'],3)}; }}
#mail_activity .activity-chip {{ font-size: 10px; color: {rgba(text,60)}; padding: 4px 8px; border-radius: 7px; background: {rgba(text,5)}; }}
#mail_activity .activity-swatch {{ min-width: 10px; min-height: 10px; border-radius: 2px; }}
#mail_activity .activity-row {{ padding: 0; }}
#mail_activity .activity-node {{ min-width: 22px; min-height: 22px; padding: 2px; border-radius: 14px; background: {rgba(text,6)}; font-size: 15px; font-weight: 600; }}
#mail_activity .activity-node.activity-incoming {{ background: {rgba(incoming,11)}; }}
#mail_activity .activity-node.activity-outgoing {{ background: {rgba(outgoing,11)}; }}
#mail_activity .activity-connector {{ min-width: 1px; background: {rgba(text,13)}; }}
#mail_activity button.activity-open, #mail_activity button.activity-open:focus {{ background: transparent; border: 0; padding: 1px 8px 19px; margin: 0; border-radius: 8px; box-shadow: none; }}
#mail_activity button.activity-open:hover {{ background: {rgba(text,4)}; }}
#mail_activity .activity-author {{ font-size: 11px; color: {rgba(text,62)}; }}
#mail_activity .activity-subject {{ font-size: 13px; font-weight: 400; color: {rgba(text,84)}; }}
#mail_activity .activity-subject.activity-unread {{ font-weight: 600; color: {text}; }}
#mail_activity .activity-preview {{ font-size: 11px; color: {rgba(text,55)}; }}
#mail_activity .activity-time {{ font-size: 10px; color: {rgba(text,45)}; }}
#mail_activity button.activity-action {{ min-width: 22px; min-height: 22px; padding: 3px; border-radius: 7px; background: transparent; border: 0; }}
#mail_activity button.activity-action:hover, #mail_activity button.activity-action:focus {{ background: {rgba(text,9)}; }}
#mail_activity button.activity-action.state-enabled {{ background: {rgba(text,6)}; }}
#mail_activity button.activity-today {{ padding: 3px 10px; min-height: 22px; border-radius: 7px; background: {rgba(text,6)}; font-size: 11px; }}
#mail_activity button.activity-today:disabled {{ color: {rgba(text,38)}; }}
#mail_activity .activity-empty {{ padding: 42px 20px 48px; }}
#mail_activity .activity-empty-title {{ font-size: 17px; font-weight: 500; color: {rgba(text,65)}; }}
#mail_activity .activity-footnote {{ font-size: 10px; color: {rgba(text,33)}; padding-top: 5px; }}
#mail_activity button.activity-more {{ padding: 9px; border-radius: 8px; background: {rgba(text,5)}; color: {rgba(text,66)}; }}
.reader-menu-content {{ padding: 3px; }}
.reader-menu-heading {{ font-size: 10px; font-weight: 500; color: {rgba(text,45)}; padding: 7px 8px 4px; }}
button.reader-menu-action {{ min-height: 25px; padding: 8px 9px; border-radius: 8px; background: transparent; border: 0; }}
button.reader-menu-action label {{ font-size: 11px; font-weight: 400; color: {rgba(text,85)}; }}
button.reader-menu-action:hover, button.reader-menu-action:focus {{ background: {rgba(text,8)}; }}
button.reader-menu-action.mail-menu-selected, button.reader-menu-action.mail-menu-selected:focus {{ background: {rgba(accent,14)}; }}
button.reader-menu-action.mail-menu-selected label {{ color: {accent}; font-weight: 600; }}
button.reader-menu-action.reader-menu-danger:hover {{ background: {rgba('#df777e',13)}; }}
button.reader-menu-action.reader-menu-danger label {{ color: {blend(text,'#df777e',.50)}; }}
.reader-menu-classification {{ margin-top: 9px; padding: 9px 8px 3px; border-top: 1px solid {rgba(text,9)}; }}
.reader-menu-classification label {{ font-size: 11px; color: {rgba(text,58)}; }}
'''+''.join(f'#mail_activity .activity-level-{index} {{ background: {color}; }}\n' for index,color in enumerate(colors))
