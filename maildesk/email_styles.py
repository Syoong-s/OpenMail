"""Conservative neutral-color adaptation that preserves authored email layout and brand colors."""
import re

_STRINGS=r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
_DECLARATION=re.compile(r'(?P<skip>/\*.*?\*/|'+_STRINGS+r')|(?P<key>[-\w]+)\s*:(?P<value>(?:[^;{}"\'()]|'+_STRINGS+r'|\([^)]*\))*)',re.S)
_NAMES={'black':0,'white':255,'gray':128,'grey':128,'silver':192,'gainsboro':220,'whitesmoke':245,'dimgray':105,'dimgrey':105,'darkgray':169,'darkgrey':169,'lightgray':211,'lightgrey':211}
_COLOR=re.compile(r'(?P<skip>/\*.*?\*/|'+_STRINGS+r'|(?:url|var|env|attr)\([^)]*\))|(?P<color>#[0-9a-f]{3,8}\b|rgba?\([^)]*\)|\b(?:'+ '|'.join(_NAMES)+r')\b)',re.I|re.S)

# ==========================================
# Function: Recognize literal RGB colors without evaluating variables, functions or external resources.
# Method: Parse common hex, named and rgb/rgba forms; leave unsupported expressions intact.
# ==========================================
def channels(value):
    text=value.strip().lower();alpha=1
    if text in _NAMES:return (_NAMES[text],)*3+(alpha,)
    if text.startswith('#'):
        raw=text[1:]
        if len(raw) in (3,4):raw=''.join(c*2 for c in raw)
        if len(raw) not in (6,8) or not re.fullmatch(r'[0-9a-f]+',raw):return None
        return tuple(int(raw[i:i+2],16) for i in (0,2,4))+(int(raw[6:8],16)/255 if len(raw)==8 else alpha,)
    if not re.fullmatch(r'rgba?\([^)]*\)',text):return None
    pieces=re.split(r'[,\s/]+',text[text.index('(')+1:-1].strip())
    if len(pieces) not in (3,4):return None
    try:
        rgb=tuple(max(0,min(255,float(p.rstrip('%'))*(2.55 if p.endswith('%') else 1))) for p in pieces[:3])
        if len(pieces)==4:alpha=max(0,min(1,float(pieces[3].rstrip('%'))/(100 if pieces[3].endswith('%') else 1)))
    except ValueError:return None
    return rgb+(alpha,)

# ==========================================
# Function: Distinguish near-neutral tones from intentionally colored buttons, logos and accents.
# Method: Compare RGB channel spread so vivid author colors remain unchanged.
# ==========================================
def neutral(rgb):return max(rgb[:3])-min(rgb[:3])<=32

# ==========================================
# Function: Blend a readable secondary surface or text tone from the validated reader palette.
# Method: Interpolate hexadecimal RGB components without changing source typography or layout.
# ==========================================
def blend(first,second,amount):
    return '#'+''.join(f'{round(int(first[i:i+2],16)*(1-amount)+int(second[i:i+2],16)*amount):02x}' for i in (1,3,5))

# ==========================================
# Function: Adapt one neutral color while retaining vivid backgrounds and transparent image edges.
# Method: Map light backgrounds and dark fonts to the reader palette, preserving alpha and brand surfaces.
# ==========================================
def mapped_color(token,kind,surface,foreground,border,vivid_background=False):
    rgb=channels(token)
    if not rgb or not neutral(rgb) or rgb[3]==0:return token
    brightness=sum(rgb[:3])/765;dark=sum(channels(surface)[:3])<384
    if kind=='text':
        if vivid_background or brightness>=.7:return token
        result=blend(surface,foreground,.72) if .24<brightness<.7 and dark else foreground
    elif kind=='background':
        if brightness<.65 and not dark:return token
        result=blend(surface,foreground,min(.09,max(0,(1-brightness)*.16)))
    else:result=border
    if rgb[3]<1:
        values=channels(result);return 'rgba('+','.join(str(round(v)) for v in values[:3])+','+format(rgb[3],'.3g')+')'
    return result

# ==========================================
# Function: Adapt CSS declarations without discarding style sheets, media queries or structural properties.
# Method: Tokenize strings/comments/functions, remove destructive resets and rewrite only literal neutral colors.
# ==========================================
def adapt_css(source,surface='#252525',foreground='#f1f1f1',border='#59616c'):
    # ==========================================
    # Function: Rewrite a presentation declaration while preserving its original importance and syntax.
    # Method: Keep non-color declarations untouched and inspect the current block for a vivid background.
    # ==========================================
    def declaration(match):
        key=match.group('key')
        if not key:return match.group()
        key=key.lower();value=match.group('value')
        if key in ('all','behavior','-moz-binding'):return ''
        kind='text' if key in ('color','-webkit-text-fill-color') else 'background' if key in ('background','background-color') else 'border' if key.startswith('border') and key not in ('border-radius','border-collapse','border-spacing') else ''
        if not kind:return match.group()
        start=source.rfind('{',0,match.start())+1;end=source.find('}',match.end());block=source[start:end if end>=0 else len(source)]
        backgrounds=re.findall(r'(?:^|[;{])\s*background(?:-color)?\s*:([^;}]+)',block,re.I)
        vivid=any((rgb:=channels(token.group('color'))) and not neutral(rgb) for background in backgrounds for token in _COLOR.finditer(background) if token.group('color'))
        # ==========================================
        # Function: Replace literal neutral color tokens without touching quoted CSS or resource URLs.
        # Method: Preserve all skipped tokens and adapt only recognized palette values.
        # ==========================================
        def color(token):return mapped_color(token.group('color'),kind,surface,foreground,border,vivid) if token.group('color') else token.group()
        return match.group('key')+':'+_COLOR.sub(color,value)
    return _DECLARATION.sub(declaration,source)
