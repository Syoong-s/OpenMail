"""Inert document preparation for the embedded reader; no network or scripts."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit,unquote
from .email_styles import adapt_css,mapped_color

# ==========================================
# Function: Preserve document structure while dropping active and remote content.
# Method: Parse HTML tokens, whitelist elements/attributes and constrain URL schemes.
# ==========================================
class InertHTML(HTMLParser):
    allowed=set('html head body title style div span p br hr h1 h2 h3 h4 h5 h6 strong b em i u s del blockquote pre code ul ol li table thead tbody tfoot tr th td a img section article header footer dl dt dd sup sub small center font figure figcaption audio video'.split())
    void={'br','hr','img'}
    blocked={'script','iframe','object','embed','form','svg','math','template','noscript'}

    # ==========================================
    # Function: Initialize isolated sanitizer state.
    # Method: Track active-content suppression separately from inert author CSS and document-root containers.
    # ==========================================
    def __init__(self,images=None,readable_dark=False,remote_images=False,palette=None):
        super().__init__(convert_charrefs=True);self.parts=[];self.suppressed=[]
        self.readable_dark=readable_dark;self.remote_images=remote_images
        self.images={image['cid'].casefold():image for image in (images or []) if image.get('cid')}
        self.used_images=set()
        self.in_head=False;self.in_style=False;self.palette=palette or ('#252525','#f1f1f1','#59616c')

    # ==========================================
    # Function: Accept inert structural tags and safe presentation attributes.
    # Method: Preserve inert CSS, table presentation and author identifiers while enforcing image and active-content limits.
    # ==========================================
    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:self.suppressed.append(tag);return
        if self.suppressed or tag not in self.allowed:return
        if tag=='html':return
        if tag=='head':self.in_head=True;return
        if tag=='style':self.in_style=True;self.parts.append('<style>');return
        if self.in_head:return
        if tag=='body':
            tag='div';body=dict(attrs)
            if body.get('bgcolor') and re.fullmatch(r'#[0-9a-fA-F]{3,8}|[a-zA-Z]+',body['bgcolor']):
                attrs=[(key,value) for key,value in attrs if key not in ('style','bgcolor')]+[('style',(body.get('style') or '')+';background-color:'+body['bgcolor'])]
        if tag=='img':
            image_attrs=dict(attrs);width=image_attrs.get('width') or '';image_style=image_attrs.get('style') or ''
            # Small authored image columns must not collapse to a one-pixel table cell under max-width:100%.
            if re.fullmatch(r'\d{1,3}',width) and 0<int(width)<=160 and not re.search(r'(?:^|;)\s*min-width\s*:',image_style,re.I):
                attrs=[(key,value) for key,value in attrs if key!='style']+[('style',image_style+';min-width:'+str(int(width))+'px')]
        safe=[]
        for name,value in attrs:
            value=value or ''
            if self.readable_dark and name in ('color','bgcolor'):
                value=mapped_color(value,'text' if name=='color' else 'background',*self.palette)
            if self.readable_dark and name=='style':
                value=adapt_css(value,*self.palette)
            if tag=='img' and name=='src' and value.strip().lower().startswith('cid:'):
                image=self.images.get(unquote(value.strip()[4:]).strip('<>').casefold())
                if image:
                    safe.extend([('src',image['uri']),('id','mail-image-'+str(image['index']))]);self.used_images.add(image['index'])
            elif tag=='img' and name=='src' and self.remote_images and urlsplit(value.strip()).scheme.lower() in ('https','http'):
                url=urlsplit(value.strip())
                if url.hostname and not url.username and not url.password and not any(c in value for c in '\r\n\x00'):safe.append((name,value.strip()))
            elif name=='id' and len(value)<=512 and not any(c in value for c in '\x00\r\n'):safe.append((name,value))
            elif tag in ('audio','video') and name=='src' and re.fullmatch(r'data:(?:audio|video)/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+',value):safe.append((name,value))
            elif tag in ('audio','video') and name in ('controls','preload'):safe.append((name,'controls' if name=='controls' else 'metadata'))
            elif name in ('class','style','align','width','height','colspan','rowspan','color','face','size','title','alt','bgcolor','border','cellpadding','cellspacing','valign','role','dir','lang','nowrap'):
                safe.append((name,value))
            elif tag=='a' and name=='href' and urlsplit(value.strip()).scheme.lower() in ('https','http','mailto'):
                safe.extend([('href',value),('rel','noreferrer noopener')])
            elif tag=='img' and name=='src' and re.match(r'^data:image/(png|jpeg|gif|webp|bmp|svg\+xml|avif);base64,[a-zA-Z0-9+/=\s]+$',value):safe.append((name,value))
        self.parts.append('<'+tag+''.join(' '+k+'="'+html.escape(v,quote=True)+'"' for k,v in safe)+'>')

    # ==========================================
    # Function: Close allowed HTML structures without reviving blocked children.
    # Method: Keep CSS/head boundaries intact and convert authored body containers to inert content divs.
    # ==========================================
    def handle_endtag(self, tag):
        if self.suppressed:
            if tag==self.suppressed[-1]:self.suppressed.pop()
            return
        if tag=='style':
            if self.in_style:self.parts.append('</style>');self.in_style=False
            return
        if tag=='head':self.in_head=False;return
        if tag=='html' or self.in_head:return
        if tag=='body':tag='div'
        if tag in self.allowed and tag not in self.void:self.parts.append('</'+tag+'>')

    # ==========================================
    # Function: Preserve readable text as escaped HTML.
    # Method: Escape visible text; preserve raw CSS text so selectors and entities keep their stylesheet meaning.
    # ==========================================
    def handle_data(self, data):
        if self.suppressed:return
        if self.in_style:self.parts.append(adapt_css(data,*self.palette) if self.readable_dark else data)
        elif not self.in_head:self.parts.append(html.escape(data))

# ==========================================
# Function: Format common Markdown inline constructs safely.
# Method: Escape first, then emit a small set of non-executable presentation tags.
# ==========================================
def inline_markdown(text):
    value=html.escape(text)
    value=re.sub(r'`([^`]+)`',r'<code>\1</code>',value)
    value=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',value)
    value=re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)',r'<em>\1</em>',value)
    value=re.sub(r'~~(.+?)~~',r'<del>\1</del>',value)
    value=re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'<a href="\2">\1</a>',value)
    return value

# ==========================================
# Function: Render a documented Markdown subset including tables and fenced code.
# Method: Parse blocks explicitly; raw HTML stays escaped and links are scheme-limited.
# ==========================================
def markdown_html(source):
    lines=source.splitlines();out=[];index=0;list_kind=None
    while index<len(lines):
        line=lines[index];index+=1
        if line.startswith('```') or line.startswith('~~~'):
            if list_kind:out.append('</'+list_kind+'>');list_kind=None
            marker=line[:3];code=[]
            while index<len(lines) and not lines[index].startswith(marker):code.append(lines[index]);index+=1
            index+=index<len(lines);out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');continue
        match=re.match(r'^\s*([-+*]|\d+\.)\s+(.+)',line)
        kind=('ol' if match.group(1)[0].isdigit() else 'ul') if match else None
        if list_kind and list_kind!=kind:out.append('</'+list_kind+'>');list_kind=None
        if kind:
            if not list_kind:out.append('<'+kind+'>');list_kind=kind
            out.append('<li>'+inline_markdown(match.group(2))+'</li>');continue
        if index<len(lines) and '|' in line and re.match(r'^\s*\|?\s*:?-{3,}',lines[index]):
            cells=line.strip().strip('|').split('|');out.append('<table><thead><tr>'+''.join('<th>'+inline_markdown(c.strip())+'</th>' for c in cells)+'</tr></thead><tbody>');index+=1
            while index<len(lines) and '|' in lines[index]:
                out.append('<tr>'+''.join('<td>'+inline_markdown(c.strip())+'</td>' for c in lines[index].strip().strip('|').split('|'))+'</tr>');index+=1
            out.append('</tbody></table>');continue
        heading=re.match(r'^(#{1,6})\s+(.+)',line)
        if heading:
            level=str(len(heading.group(1)));out.append('<h'+level+'>'+inline_markdown(heading.group(2))+'</h'+level+'>')
        elif line.startswith('>'):out.append('<blockquote>'+inline_markdown(line[1:].lstrip())+'</blockquote>')
        elif re.match(r'^\s*([-*_])(?:\s*\1){2,}\s*$',line):out.append('<hr>')
        elif line.strip():out.append('<p>'+inline_markdown(line)+'</p>')
    if list_kind:out.append('</'+list_kind+'>')
    return ''.join(out)

# ==========================================
# Function: Wrap a sanitized document in an offline dark/light reading surface.
# Method: Separate Markdown defaults from authored HTML and adapt neutral palettes without flattening email layout.
# ==========================================
def reader_document(source, markdown=False, dark=True, images=None, adapt_dark=True, font_size=14,remote_images=False,appearance=None):
    background,foreground=('#252525','#f1f1f1') if dark else ('#ffffff','#30363d')
    if appearance:background=appearance['surface'];foreground=appearance['text']
    border=appearance.get('border','#59616c') if appearance else '#59616c' if dark else '#cbd3dd'
    parser=InertHTML(images,adapt_dark and (dark or bool(appearance and appearance.get('force_message'))),remote_images,(background,foreground,border));parser.feed(markdown_html(source) if markdown else source);parser.close()
    for image in images or []:
        if image['index'] not in parser.used_images:
            parser.parts.append('<figure id="mail-image-'+str(image['index'])+'"><img src="'+image['uri']+'" alt="'+html.escape(image['name'],quote=True)+'"><figcaption>'+html.escape(image['name'])+'</figcaption></figure>')
    scrollbar='::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}::-webkit-scrollbar-thumb{background:rgba(150,150,150,.48);border:2px solid transparent;background-clip:padding-box;border-radius:8px}::-webkit-scrollbar-thumb:hover{background:rgba(150,150,150,.8)}'
    font_size=font_size if font_size in (14,16,18,20) else 14
    tables='table{border-collapse:collapse}th,td{padding:8px;border:1px solid '+border+'}' if markdown else ''
    policy="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; media-src data:"
    if remote_images:policy=policy.replace("img-src data:","img-src data: https: http:")
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+policy+'"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width,initial-scale=1"><style>html,body{background:'+background+';color:'+foreground+';font:'+str(font_size)+'px sans-serif;line-height:1.7;margin:0;padding:0;overflow-wrap:anywhere}body{padding:10px;box-sizing:border-box}img{max-width:100%;height:auto}figure{margin:18px 0}figure img{display:block;border-radius:8px}figcaption{color:#9da6b2;font-size:12px;margin-top:6px}table{max-width:100%}'+tables+'pre{padding:16px;background:'+('#1d2024' if dark else '#f0f3f6')+';border-radius:8px;overflow:auto}code{font-family:monospace}a{color:#4eafff}blockquote{border-left:3px solid #4eafff;margin-left:0;padding-left:18px;color:#a9b6c4}'+scrollbar+'</style></head><body>'+''.join(parser.parts)+'</body></html>'
