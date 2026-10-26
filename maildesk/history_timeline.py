"""Flat presentation of lossless quoted-history provenance trees."""
import re
from .quoted_history import fragment_text,_ORIGINAL,_HEADER,_attribution_at,_header_cluster,_quote_line

# ==========================================
# Function: Distinguish actual historical body from attribution-only client wrapper containers.
# Method: Ignore leading attribution/header metadata for this classification while retaining every source leaf.
# ==========================================
def _has_body(segments):
    sources=[part['source'] for part in segments]
    if any(re.search(r'<img\b',source,re.I) for source in sources):return True
    lines=[_quote_line(line)[1].strip() for line in fragment_text(''.join(sources)).splitlines() if _quote_line(line)[1].strip()]
    while lines:
        attribution,count=_attribution_at(lines)
        if attribution:lines=lines[count:];continue
        if _ORIGINAL.match(lines[0]) and _header_cluster(lines[1:9]):lines.pop(0);continue
        if _header_cluster(lines[:8]) and _HEADER.match(lines[0]):
            while lines and _HEADER.match(lines[0]):lines.pop(0)
            continue
        break
    return bool(lines)

# ==========================================
# Function: Present a genuine sender/date header when a quoted email supplies one.
# Method: Keep original attribution as fallback and never infer a missing timestamp or identity.
# ==========================================
def _caption(segments,fallback):
    sender='';date=''
    for line in fragment_text(''.join(part['source'] for part in segments)).splitlines()[:12]:
        line=_quote_line(line)[1].strip()
        found=re.match(r'^(?:From|发件人|寄件者|發件人|Von|De|差出人)\s*[:：]\s*(.+)$',line.strip(),re.I)
        if found and not sender:sender=found.group(1).strip()
        found=re.match(r'^(?:Date|Sent|日期|发送时间|寄件日期|Gesendet|Envoyé|送信日時)\s*[:：]\s*(.+)$',line.strip(),re.I)
        if found and not date:date=found.group(1).strip()
    return sender or fallback,date

# ==========================================
# Function: Project every historical reply onto independent same-level cards in original reading order.
# Method: Traverse provenance depth-first, coalesce empty client wrappers, and retain aliases for CID lookup.
# ==========================================
def history_timeline(model):
    current=[part for part in model['segments'] if part['kind']=='current'];entries=[]

    # ==========================================
    # Function: Preserve one historical generation without nesting its widgets or losing wrapper text.
    # Method: Carry attribution-only leaves into the next real reply and retain all original source paths.
    # ==========================================
    def visit(segment,path,carry=(),aliases=(),title=''):
        own=[part for part in segment['segments'] if part['kind']=='current']
        children=[(index,part) for index,part in enumerate(segment['segments']) if part['kind']=='quote']
        if children and not _has_body(own):
            for offset,(index,child) in enumerate(children):
                visit(child,path+(index,),tuple(carry)+tuple(own) if not offset else (),aliases+(path,),title or segment['title'])
            return
        sources=list(carry)+own;caption,date=_caption(sources,title or segment['title'])
        entries.append({'path':path,'aliases':aliases+(path,),'segments':sources,'title':caption,'date':date,'evidence':segment.get('evidence','')})
        for index,child in children:visit(child,path+(index,))

    for index,segment in enumerate(model['segments']):
        if segment['kind']=='quote':visit(segment,(index,))
    return {'current':current,'history':entries}
