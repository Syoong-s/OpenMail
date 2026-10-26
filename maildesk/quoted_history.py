"""Conservative render-only quote recognition; original MIME is never rewritten."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import unquote

_ATTRIBUTION=re.compile(r'^(?:On\s+.{3,300}\s+wrote\s*:|在.{2,300}(?:写道|写着|编辑|編輯|寫道|寫著)\s*[:：]|.{2,180}[于於].{2,180}(?:写道|寫道)\s*[:：])$',re.I)
_HEADER=re.compile(r'^(From|Sent|Date|To|Subject|发件人|寄件者|發件人|发送时间|寄件日期|日期|收件人|收件者|目标语言|主题|主旨|Von|Gesendet|An|Betreff|De|Envoyé|À|Objet|差出人|送信日時|宛先|件名)\s*[:：]',re.I)
_ORIGINAL=re.compile(r'^[-_]{2,}\s*(?:Original Message|Forwarded message|原始邮件|转发邮件|原始郵件|轉寄郵件)\s*[-_]{2,}$',re.I)
_DATED=re.compile(r'(?<!\d)(?:19|20)\d{2}(?:年|[-/]\d{1,2}|\b)|(?<!\d)\d{1,2}:\d{2}(?!\d)')
_MAX_DEPTH=64
_HIDDEN={'script','style','head','template','iframe','object','embed','form','svg','math','noscript'}
_VOID=set('area base br col embed hr img input link meta param source track wbr'.split())

# ==========================================
# Function: Obtain readable attribution text without interpreting HTML as code.
# Method: Collect data tokens, adding structural breaks around header lines.
# ==========================================
class _Text(HTMLParser):
    # ==========================================
    # Function: Start a bounded inert text collector.
    # Method: Store decoded text and ignore tags as presentation only.
    # ==========================================
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.suppressed=[]
    # ==========================================
    # Function: Preserve readable header boundaries.
    # Method: Turn structural line separators into newline tokens.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        if tag in _HIDDEN:self.suppressed.append(tag)
        if not self.suppressed and tag in ('br','p','div','tr'):self.parts.append('\n')
    # ==========================================
    # Function: Collect original readable text.
    # Method: Append decoded parser data without evaluating source markup.
    # ==========================================
    def handle_data(self,data):
        if not self.suppressed:self.parts.append(data)

    # ==========================================
    # Function: Stop suppressing hidden source text at its own closing boundary.
    # Method: Keep author script and style data out of generated native titles.
    # ==========================================
    def handle_endtag(self,tag):
        if self.suppressed and self.suppressed[-1]==tag:self.suppressed.pop()
        elif not self.suppressed and tag in ('p','div','tr','blockquote'):self.parts.append('\n')

# ==========================================
# Function: Convert a fragment to plain attribution or preview text.
# Method: Parse inertly and retain line boundaries for multi-header validation.
# ==========================================
def fragment_text(source):
    parser=_Text();parser.feed(source);parser.close();return ''.join(parser.parts).strip()

# ==========================================
# Function: Locate complete, explicitly marked client quote nodes.
# Method: Record source offsets and reject unbalanced marked nodes instead of guessing boundaries.
# ==========================================
class _Quotes(HTMLParser):
    # ==========================================
    # Function: Initialize source-preserving structural tracking.
    # Method: Derive absolute offsets from parser line and column positions.
    # ==========================================
    def __init__(self,source):
        super().__init__(convert_charrefs=False);self.source=source;self.lines=[0];self.stack=[];self.nodes=[]
        for match in re.finditer('\n',source):self.lines.append(match.end())
    # ==========================================
    # Function: Resolve the current token's source offset.
    # Method: Add the parser's column to the corresponding original line offset.
    # ==========================================
    def token_offset(self):
        line,column=self.getpos();return self.lines[line-1]+column
    # ==========================================
    # Function: Track client markers and their parent structure without serializing vendor HTML.
    # Method: Recognize only supported explicit classes, IDs and cite blockquote attributes.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        if len(self.nodes)>=20000:raise ValueError('quote token budget exceeded')
        values=dict(attrs);classes=(values.get('class') or '').casefold().split();identity=(values.get('id') or '').casefold()
        evidence=''
        if tag=='blockquote' and (values.get('type') or '').casefold()=='cite':evidence='blockquote-cite'
        elif tag not in _VOID and any(x in classes for x in ('gmail_quote','yahoo_quoted','protonmail_quote')):evidence='client-quote'
        elif tag not in _VOID and identity=='divrplyfwdmsg':evidence='outlook-header'
        node={'tag':tag,'start':self.token_offset(),'inner':self.token_offset()+len(self.get_starttag_text()),'end':None,'parent':self.stack[-1] if self.stack else None,'evidence':evidence}
        if tag in _HIDDEN or any(parent['tag'] in _HIDDEN for parent in self.stack):node['evidence']=''
        self.nodes.append(node)
        if tag in _VOID:node['end']=node['inner']
        else:self.stack.append(node)
    # ==========================================
    # Function: Close self-contained tags accurately.
    # Method: Reuse start handling and pop only the matching nonvoid node.
    # ==========================================
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in _VOID:
            node=self.stack.pop();node['end']=node['inner'];node['inner_end']=node['inner']
    # ==========================================
    # Function: Record complete closing spans and mark implicitly broken ancestors.
    # Method: Match the nearest corresponding opener and leave unmatched inner quote nodes incomplete.
    # ==========================================
    def handle_endtag(self,tag):
        match=next((index for index in range(len(self.stack)-1,-1,-1) if self.stack[index]['tag']==tag),None)
        if match is None:return
        node=self.stack[match];node['inner_end']=self.token_offset();node['end']=self.source.find('>',self.token_offset())+1
        del self.stack[match:]

# ==========================================
# Function: Map visible attribution and header lines back to their untouched HTML boundaries.
# Method: Extend structural tracking with inert text lines, excluding hidden and literal code contexts.
# ==========================================
class _QuoteLines(_Quotes):
    # ==========================================
    # Function: Initialize source-indexed visible lines without rewriting vendor markup.
    # Method: Retain the inherited node stack and one bounded current line.
    # ==========================================
    def __init__(self,source):
        super().__init__(source);self.records=[];self.parts=[];self.anchor=0

    # ==========================================
    # Function: Finish a visible line at a genuine HTML layout boundary.
    # Method: Keep its original opening offset and normalized readable text for detection only.
    # ==========================================
    def flush_line(self,offset):
        text=''.join(self.parts).strip();self.parts=[]
        if text:self.records.append({'text':text,'start':self.anchor})
        self.anchor=offset

    # ==========================================
    # Function: Keep hidden content and code samples outside inferred history boundaries.
    # Method: Check the active original ancestor chain, including explicitly hidden style containers.
    # ==========================================
    def blocked(self):
        return any(node['tag'] in _HIDDEN or node['tag'] in ('pre','code','textarea') or node.get('hidden') for node in self.stack)

    # ==========================================
    # Function: Track visual paragraph starts and explicit line breaks alongside exact source nodes.
    # Method: Flush before block starts, then retain the block's opening tag as its line anchor.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        offset=self.token_offset();block=tag in ('p','div','tr','blockquote','section','article','li','hr')
        if block or tag=='br':self.flush_line(offset)
        super().handle_starttag(tag,attrs)
        self.nodes[-1]['hidden']=bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)',dict(attrs).get('style') or '',re.I))
        if block:self.anchor=offset
        elif tag=='br':self.anchor=self.nodes[-1]['inner']

    # ==========================================
    # Function: End lines at paragraph closers without interpreting hidden source as metadata.
    # Method: Reuse exact node closure and move the next line beyond the closing tag.
    # ==========================================
    def handle_endtag(self,tag):
        block=tag in ('p','div','tr','blockquote','section','article','li')
        if block:self.flush_line(self.token_offset())
        super().handle_endtag(tag)
        if block:self.anchor=self.source.find('>',self.token_offset())+1

    # ==========================================
    # Function: Collect rendered text and preserve newline semantics of pre-wrapped text mail.
    # Method: Treat formatting whitespace as spaces except inside explicit white-space pre-wrap containers.
    # ==========================================
    def handle_data(self,data):
        if self.blocked():return
        prewrap=any(re.search(r'white-space\s*:\s*pre',self.source[node['start']:node['inner']],re.I) for node in self.stack)
        if not prewrap:self.parts.append(data.replace('\r',' ').replace('\n',' '));return
        offset=self.token_offset()
        for match in re.finditer(r'[^\r\n]+|\r\n|[\r\n]',data):
            if match.group().strip('\r\n'):self.parts.append(match.group())
            else:self.flush_line(offset+match.end())

    # ==========================================
    # Function: Recognize attribution text containing escaped punctuation and nonbreaking spaces.
    # Method: Decode inert character references only for the visible line map.
    # ==========================================
    def handle_entityref(self,name):
        if not self.blocked():self.parts.append(html.unescape('&'+name+';'))

    # ==========================================
    # Function: Preserve numeric character references in detected sender and date lines.
    # Method: Share the same inert entity collector without changing original source bytes.
    # ==========================================
    def handle_charref(self,name):
        self.handle_entityref('#'+name)

# ==========================================
# Function: Read a plaintext quote prefix separately from its untouched content.
# Method: Peel at most the requested number of leading greater-than markers with bounded work.
# ==========================================
def _quote_line(line,levels=None):
    limit=_MAX_DEPTH if levels is None else min(_MAX_DEPTH,max(0,levels));offset=0;count=0
    while count<limit:
        found=re.match(r'[ \t]*>[ \t]?',line[offset:])
        if not found:break
        offset+=found.end();count+=1
    return count,line[offset:] if count else line

# ==========================================
# Function: Collect only the historical run owned by a quoted boundary.
# Method: Remove its common prefix while preserving deeper levels, blank lines and later inline answers.
# ==========================================
def _quote_run(lines,start,levels):
    payload=[];cursor=start
    while cursor<len(lines):
        count,text=_quote_line(lines[cursor],levels)
        if count<levels and text.strip():break
        payload.append(text);cursor+=1
    return payload,cursor

# ==========================================
# Function: Validate a genuine original-message header cluster rather than isolated header-like prose.
# Method: Normalize aliases and require a sender plus two independent header roles.
# ==========================================
def _header_cluster(lines):
    roles=set()
    for line in lines:
        line=_quote_line(line)[1].strip();match=_HEADER.match(line)
        if not match or not line[match.end():].strip():continue
        key=match.group(1).casefold()
        if key in ('from','发件人','寄件者','發件人','von','de','差出人'):roles.add('from')
        elif key in ('sent','date','发送时间','寄件日期','日期','gesendet','envoyé','送信日時'):roles.add('date')
        elif key in ('to','收件人','收件者','目标语言','an','à','宛先'):roles.add('to')
        else:roles.add('subject')
    return 'from' in roles and len(roles)>=3

# ==========================================
# Function: Recognize wrapped client attribution without depending on a single visual line.
# Method: Normalize quote markers for detection, join only equally quoted adjacent lines, and retain the consumed span.
# ==========================================
def _attribution_at(lines):
    joined='';prefix=None
    for count,line in enumerate(lines[:3],1):
        level,text=_quote_line(html.unescape(line))
        if len(text)>350 or (prefix is not None and level!=prefix):break
        prefix=level;joined=(joined+' '+text.strip()).strip()
        if _ATTRIBUTION.match(joined):return joined,count
    return '',0

# ==========================================
# Function: Distinguish complete unmarked email headers from isolated header-like prose.
# Method: Require a sender-first cluster, independent header roles and an actual dated field.
# ==========================================
def _bare_headers(lines):
    values=[];prefix=None
    for line in list(lines)[:8]:
        level,text=_quote_line(line);text=text.strip()
        if not text:continue
        if not _HEADER.match(text) or (prefix is not None and prefix!=level):break
        values.append(text);prefix=level
    if not values or not re.match(r'^(?:From|发件人|寄件者|發件人|Von|De|差出人)\s*[:：]',values[0],re.I):return False
    return _header_cluster(values) and any(re.match(r'^(?:Sent|Date|发送时间|寄件日期|日期|Gesendet|Envoyé|送信日時)\s*[:：]',line,re.I) and _DATED.search(line) for line in values)

# ==========================================
# Function: Produce a safe preformatted leaf for original plain text.
# Method: Escape every character before wrapping retained line breaks.
# ==========================================
def _plain(source):
    return '<div style="white-space:pre-wrap">'+html.escape(source)+'</div>'

# ==========================================
# Function: Partition attributed plain-text history without absorbing inline answers.
# Method: Detect boundaries independently of quote depth and peel only their owned run before recursive parsing.
# ==========================================
def _split_plain(body,depth=0,budget=None):
    budget=[512] if budget is None else budget
    if depth>=_MAX_DEPTH:return [{'kind':'current','source':_plain(body)}]
    lines=body.splitlines(keepends=True);segments=[];current=[];index=0;fence='';fence_level=0
    while index<len(lines):
        level,normalized=_quote_line(lines[index]);normalized=normalized.strip();start=index;title='';quote=[];end=index
        marker=re.match(r'^(`{3,}|~{3,})',normalized)
        if marker:
            if not fence:fence=marker.group();fence_level=level
            elif level==fence_level and marker.group()[0]==fence[0] and len(marker.group())>=len(fence) and not normalized[marker.end():].strip():fence=''
            current.append(lines[index]);index+=1;continue
        if fence:current.append(lines[index]);index+=1;continue
        attribution,count=_attribution_at(lines[index:index+3])
        if attribution:
            cursor=index+count
            while cursor<len(lines) and not lines[cursor].strip():cursor+=1
            required=max(1,level)
            quote,end=_quote_run(lines,cursor,required)
            if any(part.strip() for part in quote):title=attribution
            elif not level and _DATED.search(attribution) and any(part.strip() for part in lines[index+count:]):
                quote=lines[index+count:];title=attribution;end=len(lines)
        elif _ORIGINAL.match(normalized):
            if _header_cluster(lines[index+1:index+9]):
                if level:quote,end=_quote_run(lines,index+1,level)
                else:quote=lines[index+1:];end=len(lines)
                if any(part.strip() for part in quote):title=normalized.strip('-_ ')
        elif _bare_headers(lines[index:index+8]) and not (depth and not ''.join(current).strip()):
            if level:quote,end=_quote_run(lines,index,level)
            else:quote=lines[index:];end=len(lines)
            if any(part.strip() for part in quote):title=normalized
        if title:
            budget[0]-=1
            if budget[0]<0:raise ValueError('structured quote budget exceeded')
            if current:segments.append({'kind':'current','source':_plain(''.join(current))});current=[]
            segments.append({'kind':'quote','title':title,'evidence':'attributed-text','segments':_split_plain(''.join(quote),depth+1,budget)})
            index=end
        else:current.append(lines[start]);index+=1
    if current or not segments:segments.append({'kind':'current','source':_plain(''.join(current))})
    return segments

# ==========================================
# Function: Split an HTML source into ordered current and nested quote fragments.
# Method: Combine explicit containers with strong visible header boundaries and preserve rich source spans.
# ==========================================
def _split_html(source):
    parser=_QuoteLines(source);parser.feed(source);parser.close();parser.flush_line(len(source));candidates=[]
    for node in parser.nodes:
        if not node['evidence']:continue
        if node['end'] is None:return [{'kind':'current','source':source}]
        if node['evidence']=='outlook-header':
            text=fragment_text(source[node['inner']:node['inner_end']]);keys={_HEADER.match(line.strip()).group(1).casefold() for line in text.splitlines() if _HEADER.match(line.strip())}
            if len(keys)<3:continue
            parent=node['parent'];node=dict(node)
            node['end']=parent.get('inner_end',parent['end']) if parent else len(source)
            if node['end'] is None:return [{'kind':'current','source':source}]
            node['inner_end']=node['end'];node['inner']=node['start']
        candidates.append(node)
        if len(candidates)>512:return [{'kind':'current','source':source}]
    explicit=list(candidates)
    covered=-1;fence='';fence_level=0
    for index,line in enumerate(parser.records):
        if index<=covered:continue
        level,text=_quote_line(line['text']);text=text.strip();marker=re.match(r'^(`{3,}|~{3,})',text)
        if marker:
            if not fence:fence=marker.group();fence_level=level
            elif level==fence_level and marker.group()[0]==fence[0] and len(marker.group())>=len(fence) and not text[marker.end():].strip():fence=''
            continue
        if fence:continue
        attribution,count=_attribution_at([item['text'] for item in parser.records[index:index+3]])
        attributed=bool(attribution and _DATED.search(attribution))
        original=bool(_ORIGINAL.match(text) and _header_cluster(item['text'] for item in parser.records[index+1:index+9]))
        bare=_bare_headers(item['text'] for item in parser.records[index:index+8])
        if not attributed and not original and not bare:continue
        if attributed:covered=index+count-1
        if original:
            for position,item in enumerate(parser.records[index+1:index+9],index+1):
                if not _HEADER.match(_quote_line(item['text'])[1].strip()):break
                covered=position
        start=line['start']
        enclosing=[node for node in explicit if node['start']<=start<node['inner_end']]
        owner=min(enclosing,key=lambda node:node['inner_end']-node['start']) if enclosing else None
        # An explicit quote already owns its first attribution; avoid an identical extra wrapper.
        if owner and (start<owner['inner'] or not fragment_text(source[owner['inner']:start]).strip()):continue
        end=owner['inner_end'] if owner else len(source)
        candidates.append({'start':start,'inner':start,'inner_end':end,'end':end,
                           'title':attribution if attributed else text,'evidence':'dated-html' if attributed else 'original-headers'})
        if len(candidates)>512:return [{'kind':'current','source':source}]
    if not candidates:return [{'kind':'current','source':source}]
    candidates.sort(key=lambda node:(node['start'],-node['end']))
    inferred=any(node['evidence'] in ('dated-html','original-headers') for node in candidates)

    # ==========================================
    # Function: Retain formatting inherited across a split inside ordinary rich HTML containers.
    # Method: Wrap each exact original span with only its active ancestor tags, never duplicated body data.
    # ==========================================
    def fragment(start,end):
        if not inferred or start==end:return source[start:end]
        before=[];after=[]
        for node in parser.nodes:
            if node['tag'] in _VOID:continue
            if node['evidence']:continue
            limit=node.get('inner_end',len(source))
            if node['start']<start and node['inner']<=start<limit:before.append(source[node['start']:node['inner']])
            if node['start']<end<=limit:after.append('</'+node['tag']+'>')
        return ''.join(before)+source[start:end]+''.join(reversed(after))
    # ==========================================
    # Function: Render one nested source interval without losing current siblings.
    # Method: Emit direct quote children in order and retain exact current spans between them.
    # ==========================================
    def segments(start,end,depth=0):
        if depth>=_MAX_DEPTH:return [{'kind':'current','source':fragment(start,end)}]
        result=[];cursor=start
        direct=[node for node in candidates if node['start']>=start and node['end']<=end]
        for node in direct:
            if node['start']<cursor:continue
            prefix=fragment(cursor,node['start'])
            if fragment_text(prefix).strip() or re.search(r'<(?:img|table)\b',prefix,re.I):result.append({'kind':'current','source':prefix})
            elif prefix.strip() and not result:result.append({'kind':'current','source':prefix})
            content=source[node['inner']:node['inner_end']]
            title=fragment_text(content).splitlines();title=node.get('title') or next((line.strip() for line in title if line.strip()),'引用的历史内容')
            # Exclude this marker from its own child scan (Outlook begins at its marker).
            removed=candidates.index(node);candidates.pop(removed)
            children=segments(node['inner'],node['inner_end'],depth+1)
            candidates.insert(removed,node)
            result.append({'kind':'quote','title':title,'evidence':node['evidence'],'segments':children});cursor=node['end']
        suffix=fragment(cursor,end)
        if suffix and (fragment_text(suffix).strip() or re.search(r'<(?:img|table)\b',suffix,re.I) or not result):result.append({'kind':'current','source':suffix})
        if not result:result=[{'kind':'current','source':fragment(start,end)}]
        return result
    return segments(0,len(source))

# ==========================================
# Function: Derive an ordered render-only history model from an immutable cached message.
# Method: Prefer rich HTML explicit markers and fall back without deleting ambiguous or malformed content.
# ==========================================
def split_history(source='',body=''):
    try:segments=_split_html(source) if source else _split_plain(body)
    except (ValueError,RecursionError,IndexError):segments=[{'kind':'current','source':source or _plain(body)}]
    return {'segments':segments}

# ==========================================
# Function: Enumerate original HTML leaf fragments in display order.
# Method: Traverse nested quote segments without decoding or sanitizing away provenance.
# ==========================================
def history_sources(model):
    for segment in model['segments']:
        if segment['kind']=='current':yield segment['source']
        else:yield from history_sources(segment)

# ==========================================
# Function: Locate genuine visible image CID references in an HTML fragment.
# Method: Parse attributes structurally and ignore suppressed markup rather than matching source strings.
# ==========================================
class _CIDs(HTMLParser):
    # ==========================================
    # Function: Initialize image-origin and suppressed-context tracking.
    # Method: Keep decoded identifiers independent of MIME attachment indexes.
    # ==========================================
    def __init__(self):
        super().__init__(convert_charrefs=True);self.values=set();self.suppressed=[]
    # ==========================================
    # Function: Inspect only visible img source attributes.
    # Method: Follow the reader sanitizer's active-content suppression before canonicalizing local CIDs.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        if tag in _HIDDEN:self.suppressed.append(tag)
        if self.suppressed or tag!='img':return
        value=(dict(attrs).get('src') or '').strip()
        if value[:4].casefold()=='cid:':self.values.add(unquote(value[4:]).strip('<>').casefold())
    # ==========================================
    # Function: Leave a suppressed source container at its own boundary.
    # Method: Mirror hidden-context nesting without trusting source strings.
    # ==========================================
    def handle_endtag(self,tag):
        if self.suppressed and self.suppressed[-1]==tag:self.suppressed.pop()

# ==========================================
# Function: Return normalized visible image references for MIME fragment ownership.
# Method: Preserve the renderer's element and attribute semantics in a small inert parser.
# ==========================================
def source_cids(source):
    parser=_CIDs();parser.feed(source);parser.close();return parser.values
