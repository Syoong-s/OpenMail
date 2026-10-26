"""Conservative empty-draft policy with explicit generated-content provenance."""
from html.parser import HTMLParser

FIELDS=('to','cc','bcc','subject','body')

# ==========================================
# Function: Distinguish authored message content from untouched generated reply fields.
# Method: Compare only explicitly recorded defaults and retain attachments or rich media.
# ==========================================
def has_draft_content(draft):
    if draft.get('attachments'):return True
    baseline=draft.get('editor_baseline',{})
    if not isinstance(baseline,dict):baseline={}
    for key in FIELDS:
        value=draft.get(key,'')
        if isinstance(value,str) and value.strip() and value.strip()!=str(baseline.get(key,'')).strip():return True
    markup=draft.get('html','')
    if markup:
        parser=DraftHTML();parser.feed(markup)
        if parser.media:return True
        text=''.join(parser.text).strip()
        if text and text!=str(baseline.get('body','')).strip() and not draft.get('body','').strip():return True
    return False

# ==========================================
# Function: Preserve image-only or HTML-only drafts during automatic cleanup.
# Method: Parse visible text and media conservatively without executing or loading HTML.
# ==========================================
class DraftHTML(HTMLParser):
    # ==========================================
    # Function: Initialize a bounded, inert content projection.
    # Method: Record text fragments and a boolean media marker only.
    # ==========================================
    def __init__(self):
        super().__init__(convert_charrefs=True);self.text=[];self.media=False

    # ==========================================
    # Function: Recognize non-text authored material as meaningful content.
    # Method: Retain media elements even when the plain-text editor projection is empty.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        if tag.lower() in ('img','svg','video','audio','object','embed','iframe','table'):self.media=True
        if tag.lower() in ('br','p','div','li'):self.text.append('\n')

    # ==========================================
    # Function: Project HTML-only text without trusting markup or URLs.
    # Method: Accumulate decoded parser text for an emptiness comparison.
    # ==========================================
    def handle_data(self,data):
        self.text.append(data)
