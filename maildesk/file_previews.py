"""Local bounded file preview dispatch: text, grids, notebooks and Office XML."""
import base64
import csv
from datetime import datetime,timedelta
from dataclasses import dataclass
import html
import io
import json
from pathlib import Path,PurePosixPath
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from .mail_images import image_type

TEXT_EXT=set('txt text log json jsonl ndjson json5 xml yaml yml toml ini conf cfg properties env c cc cpp cxx h hh hpp cs java js jsx mjs cjs ts tsx py pyw rb rs go sh bash zsh fish ps1 bat cmd sql css scss sass less vue svelte astro php pl pm r rmd swift kt kts scala lua dart ex exs erl hrl hs clj cljs elm jl m mm f f90 f95 for asm s cmake make mk gradle dockerfile gitignore diff patch rst adoc asc bib tex sty cls eml ics vcf srt vtt'.split())
AUDIO={'.mp3':'audio/mpeg','.wav':'audio/wav','.ogg':'audio/ogg','.oga':'audio/ogg','.m4a':'audio/mp4','.flac':'audio/flac','.opus':'audio/ogg'}
VIDEO={'.mp4':'video/mp4','.webm':'video/webm','.ogv':'video/ogg','.mov':'video/mp4','.m4v':'video/mp4'}
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships','a':'http://schemas.openxmlformats.org/drawingml/2006/main','p':'http://schemas.openxmlformats.org/presentationml/2006/main','s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
PAGE_STYLE='''<style>.office-page{background:#fff;color:#20242b;padding:24px;box-sizing:border-box;line-height:1.6;border-radius:3px}.office-page *{color:inherit}.office-page img{max-width:100%;height:auto}.office-page table{width:100%;border-collapse:collapse}.office-page th,.office-page td{border:1px solid #ccd2dc;padding:6px 9px;vertical-align:top}.sheet th{background:#eef1f5;color:#647084;position:sticky;top:0}.sheet td{white-space:pre-wrap;min-width:72px;max-width:340px}.preview-note{font-size:12px;opacity:.7;margin:12px 0}.slide{position:relative;overflow:hidden;background:#fff;color:#20242b;border:1px solid #d0d3da}.slide-shape{position:absolute;box-sizing:border-box;overflow:hidden;padding:4px}.slide-shape p{margin:0;line-height:1.25}.notebook-cell{margin:12px 0;border:1px solid #515660;border-radius:8px;overflow:hidden}.cell-title{font-size:11px;opacity:.65;padding:5px 10px}.notebook-cell pre{margin:0;border-radius:0}.cell-output{padding:10px;overflow:auto;background:#fff;color:#20242b}video,audio{width:100%;max-height:80vh}</style>'''

# ==========================================
# Function: Retain only generated preview fragments and optional source text.
# Method: Keep a lightweight page/sheet model with explicit style ownership and visible limitations.
# ==========================================
@dataclass
class Preview:
    kind:str
    pages:list
    source:str=''
    preserve_style:bool=False

# ==========================================
# Function: Decode bounded local text without invoking a file handler.
# Method: Honor Unicode BOMs and use the existing client encoding fallback.
# ==========================================
def text_bytes(data):
    from .document_reader import document_text
    value=document_text(data[:2_000_000])
    return value+('\n\n[预览显示前 2 MB；保存原始文件可获得完整内容。]' if len(data)>2_000_000 else '')

# ==========================================
# Function: Sanitize standalone SVG images before placing them in an image context.
# Method: Drop executable/embedded/external nodes and references; keep bounded vector geometry and text.
# ==========================================
def svg_uri(data):
    root=xml_root(data);allowed=set('svg g path rect circle ellipse line polyline polygon text tspan defs linearGradient radialGradient stop clipPath mask use title desc'.split())
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.split('}')[-1] not in allowed:parent.remove(child)
        for key,value in list(parent.attrib.items()):
            local=key.split('}')[-1].lower()
            if local.startswith('on') or local=='style' or (local=='href' and not value.startswith('#')) or re.search(r'url\s*\(\s*[\'\"]?(?!#)',value,re.I):del parent.attrib[key]
    if root.tag.split('}')[-1]!='svg':raise ValueError('无效 SVG 文件')
    return 'data:image/svg+xml;base64,'+base64.b64encode(ET.tostring(root,encoding='utf-8')).decode('ascii')

# ==========================================
# Function: Create an inert local image data URI.
# Method: Validate raster signatures and normalize SVG separately from raw HTML.
# ==========================================
def image_data(name,data):
    mime=image_type(data)
    if mime:return 'data:'+mime+';base64,'+base64.b64encode(data).decode('ascii')
    if Path(name).suffix.lower()=='.svg':return svg_uri(data)
    if data[4:8]==b'ftyp' and data[8:12] in (b'avif',b'avis'):return 'data:image/avif;base64,'+base64.b64encode(data).decode('ascii')
    return ''

# ==========================================
# Function: Parse XML with a finite byte limit and no DTD/entity expansion.
# Method: Reject declarations before ElementTree and never extract document-controlled paths.
# ==========================================
def xml_root(data):
    if len(data)>8_000_000 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)',data,re.I):raise ValueError('文档 XML 过大或包含不支持的实体声明')
    return ET.fromstring(data)

# ==========================================
# Function: Read an Office ZIP as a bounded in-memory package.
# Method: Limit entry count, expanded sizes and XML parts; ignore external relationships and macros.
# ==========================================
class Package:
    # ==========================================
    # Function: Validate the compressed container before parsing any document part.
    # Method: Require unique member names and bound total uncompressed bytes to64MB.
    # ==========================================
    def __init__(self,data):
        self.zip=zipfile.ZipFile(io.BytesIO(data));entries=self.zip.infolist()
        if len(entries)>4000 or sum(e.file_size for e in entries)>64_000_000 or len({e.filename for e in entries})!=len(entries):self.zip.close();raise ValueError('文档解压内容过大或包含重复部件，不能在应用内预览')
        self.names={e.filename for e in entries};self.image_budget=16_000_000

    # ==========================================
    # Function: Read one bounded member without extracting to disk.
    # Method: Enforce declared and actual size limits before returning bytes.
    # ==========================================
    def read(self,name):
        if name not in self.names:return b''
        info=self.zip.getinfo(name)
        if info.file_size>8_000_000:raise ValueError('文档部件超过 8 MB 预览限制')
        with self.zip.open(info) as member:data=member.read(8_000_001)
        if len(data)>8_000_000:raise ValueError('文档部件过大')
        return data

    # ==========================================
    # Function: Resolve only relative relationships inside this ZIP.
    # Method: Ignore TargetMode External and normalized targets outside the package root.
    # ==========================================
    def relationships(self,name):
        path=PurePosixPath(name);rel=str(path.parent/'_rels'/(path.name+'.rels'));data=self.read(rel)
        if not data:return {}
        result={}
        for entry in xml_root(data):
            target=entry.get('Target','')
            if entry.get('TargetMode')=='External' or ':' in target or '\\' in target:continue
            normalized=posixpath.normpath(posixpath.join(str(path.parent),target)) if not target.startswith('/') else target.lstrip('/')
            if not normalized.startswith('../') and normalized in self.names:result[entry.get('Id')]=normalized
        return result

    # ==========================================
    # Function: Inline a bounded raster/vector package image.
    # Method: Share an aggregate image budget and drop unsupported payloads safely.
    # ==========================================
    def image(self,name):
        data=self.read(name)
        if len(data)>self.image_budget:return ''
        self.image_budget-=len(data);uri=image_data(name,data)
        return '<img src="'+uri+'" alt="'+html.escape(PurePosixPath(name).name,quote=True)+'">' if uri else ''

# ==========================================
# Function: Read a namespaced integer attribute without trusting document strings.
# Method: Default malformed values and bound magnitudes before using layout arithmetic.
# ==========================================
def number(value,default=0):
    try:return max(-10**10,min(10**10,int(value)))
    except (TypeError,ValueError):return default

# ==========================================
# Function: Render a Word paragraph with text emphasis and embedded images.
# Method: Escape every run and map a bounded subset of static formatting to HTML.
# ==========================================
def word_paragraph(node,package,rels):
    out=[]
    for run in node.findall('.//w:r',NS):
        props=run.find('w:rPr',NS);style=[]
        if props is not None:
            if props.find('w:b',NS) is not None:style.append('font-weight:700')
            if props.find('w:i',NS) is not None:style.append('font-style:italic')
            if props.find('w:u',NS) is not None:style.append('text-decoration:underline')
            size=props.find('w:sz',NS)
            if size is not None:style.append('font-size:'+str(max(8,min(72,number(size.get('{'+NS['w']+'}val'),22)/2)))+'pt')
            color=props.find('w:color',NS)
            if color is not None and re.fullmatch('[0-9a-fA-F]{6}',color.get('{'+NS['w']+'}val','')):style.append('color:#'+color.get('{'+NS['w']+'}val'))
        text=''.join(html.escape(n.text or '') if n.tag=='{'+NS['w']+'}t' else '<br>' if n.tag in ('{'+NS['w']+'}br','{'+NS['w']+'}cr') else '　' if n.tag=='{'+NS['w']+'}tab' else '' for n in run)
        if text:out.append('<span style="'+';'.join(style)+'">'+text+'</span>')
        for image in run.findall('.//a:blip',NS):
            target=rels.get(image.get('{'+NS['r']+'}embed'))
            if target:out.append(package.image(target))
    props=node.find('w:pPr',NS);tag='p';style=[];bullet=''
    if props is not None:
        pstyle=props.find('w:pStyle',NS);name=pstyle.get('{'+NS['w']+'}val','') if pstyle is not None else ''
        heading=re.search(r'heading\s*([1-6])',name,re.I)
        if heading:tag='h'+heading.group(1)
        elif name.lower()=='title':tag='h1'
        align=props.find('w:jc',NS)
        if align is not None and align.get('{'+NS['w']+'}val') in ('left','right','center','both'):style.append('text-align:'+align.get('{'+NS['w']+'}val').replace('both','justify'))
        if props.find('w:numPr',NS) is not None:bullet='•　'
    return '<'+tag+' style="'+';'.join(style)+'">'+bullet+(''.join(out) or '<br>')+'</'+tag+'>'

# ==========================================
# Function: Render Word body paragraphs/tables/images in document order.
# Method: Read only main document parts; preserve content without claiming Office pagination fidelity.
# ==========================================
def word_preview(package):
    name='word/document.xml';root=xml_root(package.read(name));rels=package.relationships(name);body=root.find('w:body',NS);out=[];count=0
    for node in ([] if body is None else body):
        count+=1
        if count>4000:out.append('<p>预览显示前4000个内容块。</p>');break
        if node.tag=='{'+NS['w']+'}p':out.append(word_paragraph(node,package,rels))
        elif node.tag=='{'+NS['w']+'}tbl':
            rows=[]
            for row in node.findall('w:tr',NS)[:500]:
                cells=[]
                for cell in row.findall('w:tc',NS)[:80]:
                    span=cell.find('w:tcPr/w:gridSpan',NS);colspan=max(1,min(80,number(span.get('{'+NS['w']+'}val'),1))) if span is not None else 1
                    cells.append('<td colspan="'+str(colspan)+'">'+''.join(word_paragraph(p,package,rels) for p in cell.findall('w:p',NS))+'</td>')
                rows.append('<tr>'+''.join(cells)+'</tr>')
            out.append('<table>'+''.join(rows)+'</table>')
    return Preview('document',[('文档',PAGE_STYLE+'<article class="office-page">'+''.join(out)+'</article>')],preserve_style=True)

# ==========================================
# Function: Convert a spreadsheet column label to a bounded zero-based index.
# Method: Reject over-wide addresses before allocating row cells.
# ==========================================
def column_index(address):
    match=re.match('[A-Z]+',address.upper());value=0
    for c in match.group(0) if match else 'A':value=value*26+ord(c)-64
    return min(16384,max(0,value-1))

# ==========================================
# Function: Render a row grid with visible coordinate headings.
# Method: Bound every table and escape values instead of treating cell content as markup.
# ==========================================
def grid(rows):
    rows=rows[:1000];columns=min(80,max((len(r) for r in rows),default=0));letters=[]
    for i in range(columns):
        text='';n=i+1
        while n:n,rem=divmod(n-1,26);text=chr(65+rem)+text
        letters.append(text)
    head='<tr><th></th>'+''.join('<th>'+v+'</th>' for v in letters)+'</tr>'
    body=''.join('<tr><th>'+str(index+1)+'</th>'+''.join('<td>'+html.escape(str(value))+'</td>' for value in (list(row)+['']*columns)[:columns])+'</tr>' for index,row in enumerate(rows))
    return PAGE_STYLE+'<div class="office-page"><table class="sheet">'+head+body+'</table><p class="preview-note">显示最多1000行、80列；公式显示文件中保存的结果，不执行宏或重新计算。</p></div>'

# ==========================================
# Function: Render XLSX worksheets including shared strings and saved formula results.
# Method: Resolve workbook order/relationships and bound expanded rows/cells per sheet.
# ==========================================
def workbook_preview(package):
    root=xml_root(package.read('xl/workbook.xml'));rels=package.relationships('xl/workbook.xml');shared=[];data=package.read('xl/sharedStrings.xml')
    if data:shared=[''.join(n.itertext()) for n in xml_root(data).findall('s:si',NS)]
    pages=[];date_styles=set();styles=package.read('xl/styles.xml')
    if styles:
        style_root=xml_root(styles);formats={number(n.get('numFmtId')):n.get('formatCode','') for n in style_root.findall('s:numFmts/s:numFmt',NS)}
        for index,style in enumerate(style_root.findall('s:cellXfs/s:xf',NS)):
            code=number(style.get('numFmtId'));pattern=re.sub(r'"[^"]*"|\\.', '', formats.get(code,''))
            if 14<=code<=22 or (code>=164 and re.search('[yd]',pattern,re.I)):date_styles.add(index)
    for sheet in root.findall('s:sheets/s:sheet',NS)[:40]:
        path=rels.get(sheet.get('{'+NS['r']+'}id'));rows=[]
        if not path:continue
        for row in xml_root(package.read(path)).findall('s:sheetData/s:row',NS)[:1000]:
            index=number(row.get('r'),len(rows)+1)-1
            if index>=1000:break
            while len(rows)<=index:rows.append([])
            values=rows[index]
            for cell in row.findall('s:c',NS)[:80]:
                col=column_index(cell.get('r','A'))
                if col>=80:continue
                while len(values)<=col:values.append('')
                value=cell.findtext('s:v','',NS);kind=cell.get('t')
                if kind=='s':value=shared[number(value)] if 0<=number(value)<len(shared) else ''
                elif kind=='inlineStr':value=''.join(cell.find('s:is',NS).itertext()) if cell.find('s:is',NS) is not None else ''
                elif kind=='b':value='TRUE' if value=='1' else 'FALSE'
                elif not value and cell.find('s:f',NS) is not None:value='='+cell.findtext('s:f','',NS)
                if number(cell.get('s'),-1) in date_styles and kind not in ('s','inlineStr','b'):
                    try:
                        days=float(value);origin=datetime(1904,1,1) if root.find('s:workbookPr',NS) is not None and root.find('s:workbookPr',NS).get('date1904')=='1' else datetime(1899,12,30);date=origin+timedelta(days=days);value=date.strftime('%Y-%m-%d %H:%M' if days%1 else '%Y-%m-%d')
                    except (ValueError,OverflowError):pass
                values[col]=value
        rendered=grid(rows)
        if sum(len(page.encode('utf-8')) for title,page in pages)+len(rendered.encode('utf-8'))>12_000_000:
            pages.append(('预览限制','<p>已达到12 MB表格预览上限。保存原始文件可查看完整工作簿。</p>'));break
        pages.append((sheet.get('name','工作表'),rendered))
    return Preview('sheet',pages or [('工作簿',grid([]))],preserve_style=True)

# ==========================================
# Function: Render ordered PowerPoint slides with positioned text boxes and embedded images.
# Method: Use presentation relationships, EMU geometry and escaped text; do not run actions or animation code.
# ==========================================
def slides_preview(package):
    root=xml_root(package.read('ppt/presentation.xml'));rels=package.relationships('ppt/presentation.xml');size=root.find('p:sldSz',NS);width=number(size.get('cx'),9144000) if size is not None else 9144000;height=number(size.get('cy'),5143500) if size is not None else 5143500;pages=[]
    for i,entry in enumerate(root.findall('p:sldIdLst/p:sldId',NS)[:100]):
        path=rels.get(entry.get('{'+NS['r']+'}id'))
        if not path:continue
        slide=xml_root(package.read(path));links=package.relationships(path);shapes=[]
        for shape in slide.findall('p:cSld/p:spTree/*',NS)[:500]:
            transform=shape.find('.//a:xfrm',NS);offset=transform.find('a:off',NS) if transform is not None else None;extent=transform.find('a:ext',NS) if transform is not None else None
            x=number(offset.get('x')) if offset is not None else 0;y=number(offset.get('y')) if offset is not None else 0;cx=number(extent.get('cx'),width) if extent is not None else width;cy=number(extent.get('cy'),height) if extent is not None else height
            style=f'left:{100*x/max(1,width):.3f}%;top:{100*y/max(1,height):.3f}%;width:{100*cx/max(1,width):.3f}%;height:{100*cy/max(1,height):.3f}%;'
            fill=shape.find('p:spPr/a:solidFill/a:srgbClr',NS)
            if fill is not None and re.fullmatch('[0-9a-fA-F]{6}',fill.get('val','')):style+='background:#'+fill.get('val')+';'
            content=[]
            for paragraph in shape.findall('.//a:p',NS):content.append('<p>'+html.escape(''.join(t.text or '' for t in paragraph.findall('.//a:t',NS)))+'</p>')
            for image in shape.findall('.//a:blip',NS):
                target=links.get(image.get('{'+NS['r']+'}embed'))
                if target:content.append(package.image(target))
            if content:shapes.append('<div class="slide-shape" style="'+style+'">'+''.join(content)+'</div>')
        background=slide.find('p:cSld/p:bg/p:bgPr/a:solidFill/a:srgbClr',NS);color=background.get('val','') if background is not None else ''
        color='#'+color if re.fullmatch('[0-9a-fA-F]{6}',color) else '#ffffff'
        pages.append(('幻灯片 '+str(i+1),PAGE_STYLE+f'<div class="slide" style="padding-top:{100*height/max(1,width):.3f}%;background:{color}">'+''.join(shapes)+'</div>'))
    return Preview('presentation',pages or [('幻灯片','<p>没有可预览的幻灯片。</p>')],preserve_style=True)

# ==========================================
# Function: Render notebook source and saved outputs as inert content.
# Method: Never start a kernel, execute code or trust HTML/JavaScript outputs.
# ==========================================
def notebook_preview(data):
    value=json.loads(data.decode('utf-8-sig'));out=[]
    from .document_content import markdown_html,InertHTML
    for i,cell in enumerate(value.get('cells',[])[:500]):
        source=cell.get('source','');source=''.join(source) if isinstance(source,list) else str(source)
        body=markdown_html(source) if cell.get('cell_type')=='markdown' else '<pre><code>'+html.escape(source)+'</code></pre>'
        outputs=[]
        for output in cell.get('outputs',[])[:30]:
            payload=output.get('data',{});text=output.get('text',payload.get('text/plain',''));text=''.join(text) if isinstance(text,list) else str(text)
            if 'image/png' in payload:
                raw=payload['image/png'];raw=''.join(raw) if isinstance(raw,list) else raw
                if len(raw)<8_000_000:
                    try:decoded=base64.b64decode(raw,validate=True)
                    except ValueError:decoded=b''
                    uri=image_data('output.png',decoded)
                    if uri:outputs.append('<img src="'+uri+'" alt="单元输出">')
            elif 'text/html' in payload:
                raw=payload['text/html'];parser=InertHTML();parser.feed(''.join(raw) if isinstance(raw,list) else str(raw));parser.close();outputs.append(''.join(parser.parts))
            elif text:outputs.append('<pre>'+html.escape(text[:100_000])+'</pre>')
        out.append('<section class="notebook-cell"><div class="cell-title">单元 '+str(i+1)+' · '+html.escape(str(cell.get('cell_type','raw')))+'</div>'+body+('<div class="cell-output">'+''.join(outputs)+'</div>' if outputs else '')+'</section>')
    return Preview('notebook',[('Notebook',PAGE_STYLE+''.join(out))],text_bytes(data),True)

# ==========================================
# Function: Dispatch bounded local file bytes into the shared offline reader.
# Method: Cover installed-app preview families without installing Office, cloud conversion or executing attachments.
# ==========================================
def preview(name,data,media_type=''):
    if len(data)>30*1024*1024:raise ValueError('文件超过30 MiB预览限制')
    suffix=Path(name).suffix.lower();mime=media_type.split(';')[0].lower()
    if suffix=='.pdf' or mime=='application/pdf' or data.lstrip().startswith(b'%PDF-'):return Preview('pdf',[])
    uri=image_data(name,data)
    if uri:return Preview('image',[('图片','<figure><img src="'+uri+'" alt="'+html.escape(name,quote=True)+'"></figure>')])
    if suffix in ('.doc','.rtf') or mime in ('application/msword','application/rtf','text/rtf'):
        from .legacy_documents import legacy_preview
        content,source,kind=legacy_preview(data);return Preview(kind,[('Word文档',content)],source if kind=='html' else '')
    office=suffix in ('.docx','.docm','.dotx','.dotm','.xlsx','.xlsm','.xltx','.xltm','.pptx','.pptm','.ppsx','.ppsm','.potx','.potm') or mime in ('application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.openxmlformats-officedocument.presentationml.presentation','application/vnd.ms-excel.sheet.macroenabled.12')
    if office:
        package=Package(data)
        try:
            if 'word/document.xml' in package.names:return word_preview(package)
            if 'xl/workbook.xml' in package.names:return workbook_preview(package)
            if 'ppt/presentation.xml' in package.names:return slides_preview(package)
            raise ValueError('Office文件中没有有效文档部件')
        finally:package.zip.close()
    if suffix in ('.csv','.tsv') or mime in ('text/csv','text/tab-separated-values'):
        source=text_bytes(data);reader=csv.reader(io.StringIO(source),delimiter='\t' if suffix=='.tsv' or mime=='text/tab-separated-values' else ',');rows=[]
        for row in reader:
            rows.append(row[:80])
            if len(rows)>=1000:break
        return Preview('sheet',[('表格',grid(rows))],source,True)
    if suffix=='.ipynb' or mime=='application/x-ipynb+json':return notebook_preview(data)
    if suffix in AUDIO or mime.startswith('audio/'):
        kind=AUDIO.get(suffix,mime);return Preview('audio',[('音频',PAGE_STYLE+'<audio controls="controls" preload="metadata" src="data:'+kind+';base64,'+base64.b64encode(data).decode()+'"></audio>')],preserve_style=True)
    if suffix in VIDEO or mime.startswith('video/'):
        kind=VIDEO.get(suffix,mime);return Preview('video',[('视频',PAGE_STYLE+'<video controls="controls" preload="metadata" src="data:'+kind+';base64,'+base64.b64encode(data).decode()+'"></video>')],preserve_style=True)
    source=text_bytes(data)
    if suffix in ('.md','.markdown') or mime=='text/markdown':return Preview('markdown',[('预览',source)],source)
    if suffix in ('.html','.htm') or mime=='text/html':return Preview('html',[('预览',source)],source)
    if mime.startswith('text/') or suffix.lstrip('.') in TEXT_EXT or name.lower() in ('makefile','dockerfile','license','readme') or (not suffix and b'\0' not in data[:8192]):return Preview('text',[('源码','<pre><code>'+html.escape(source)+'</code></pre>')],source)
    return Preview('metadata',[('文件','<h3>'+html.escape(name)+'</h3><p>当前格式暂不支持内容预览，可保存原始文件。</p><p>'+html.escape(mime or '未知文件类型')+'</p>')])

# ==========================================
# Function: Convert TIFF/ICO using the existing private GdkPixbuf decoders.
# Method: Scale oversized rasters during size preparation and return a PNG data URI with bounded dimensions.
# ==========================================
def native_raster(g,data):
    import ctypes as C
    P=C.c_void_p;I=C.c_int;U=C.c_uint;S=C.c_char_p;lib=g.libs['pixbuf'];spec={'gdk_pixbuf_loader_new':(P,), 'gdk_pixbuf_loader_set_size':(None,P,I,I),'gdk_pixbuf_loader_write':(I,P,P,C.c_size_t,P),'gdk_pixbuf_loader_close':(I,P,P),'gdk_pixbuf_loader_get_pixbuf':(P,P),'gdk_pixbuf_save_to_bufferv':(I,P,C.POINTER(P),C.POINTER(C.c_size_t),S,P,P,P)}
    for key,signature in spec.items():fn=getattr(lib,key);fn.restype=signature[0];fn.argtypes=signature[1:]
    loader=lib.gdk_pixbuf_loader_new();group='file-raster-'+str(loader);oversized=[False]
    # ==========================================
    # Function: Bound native decoder allocation before full pixel materialization.
    # Method: Reject excessive dimensions and downscale supported large images to4096px.
    # ==========================================
    def prepare(widget,width,height,unused):
        if width<=0 or height<=0 or width*height>100_000_000:oversized[0]=True;lib.gdk_pixbuf_loader_set_size(widget,1,1);return
        scale=min(1,4096/max(width,height));lib.gdk_pixbuf_loader_set_size(widget,max(1,int(width*scale)),max(1,int(height*scale)))
    g.connect(loader,'size-prepared',prepare,types=[P,I,I,P],group=group)
    try:
        source=C.create_string_buffer(data);error=P();ok=lib.gdk_pixbuf_loader_write(loader,source,len(data),C.byref(error))
        if error:g.g_error_free(error);error=P()
        closed=lib.gdk_pixbuf_loader_close(loader,C.byref(error))
        if error:g.g_error_free(error)
        if not ok or not closed or oversized[0]:raise ValueError('图片无法解码或超过原生预览像素限制')
        pixels=lib.gdk_pixbuf_loader_get_pixbuf(loader);buffer=P();length=C.c_size_t();error=P()
        if not pixels or not lib.gdk_pixbuf_save_to_bufferv(pixels,C.byref(buffer),C.byref(length),b'png',None,None,C.byref(error)):
            if error:g.g_error_free(error)
            raise ValueError('无法准备图片预览')
        try:return 'data:image/png;base64,'+base64.b64encode(C.string_at(buffer,length.value)).decode('ascii')
        finally:g.g_free(buffer)
    finally:g.disconnect(group);g.g_object_unref(loader)
