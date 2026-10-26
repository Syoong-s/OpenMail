"""Bounded offline Word binary/RTF text extraction; no Office automation or macros."""
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from .platform_native import runtime_root

# ==========================================
# Function: Extract readable RTF text without executing embedded objects or fields.
# Method: Track destinations/codepages/Unicode fallback, ignore binary data and bound output length.
# ==========================================
def rtf_text(data):
    if len(data)>8_000_000:raise ValueError('RTF文件超过8 MB预览限制')
    control=re.compile(r'([a-zA-Z]+)(-?\d+)? ?')
    text=data.decode('latin-1');out=[];stack=[];skip=False;unicode_skip=1;codepage='cp1252';index=0;fallback=0
    destinations={'fonttbl','colortbl','stylesheet','info','pict','object','objdata','filetbl','datastore','themedata','xmlopen','xmlattrname','xmlattrvalue','fldinst','header','footer','generator'}
    while index<len(text) and len(out)<2_000_000:
        char=text[index];index+=1
        if char=='{':stack.append((skip,unicode_skip,codepage));continue
        if char=='}':
            if stack:skip,unicode_skip,codepage=stack.pop()
            continue
        if char!='\\':
            if fallback:fallback-=1
            elif not skip and char not in '\r\n':out.append(char)
            continue
        if index>=len(text):break
        marker=text[index]
        if marker in '{}\\':
            index+=1
            if fallback:fallback-=1
            elif not skip:out.append(marker)
            continue
        if marker=='*':skip=True;index+=1;continue
        if marker=="'" and index+2<len(text):
            escaped=[]
            while index+2<len(text) and text[index]=="'":
                try:escaped.append(int(text[index+1:index+3],16))
                except ValueError:break
                index+=3
                if text[index:index+2]=="\\'":index+=1
                else:break
            if fallback:fallback=max(0,fallback-len(escaped))
            elif not skip:
                try:out.append(bytes(escaped).decode(codepage,errors='replace'))
                except LookupError:out.append(bytes(escaped).decode('cp1252',errors='replace'))
            continue
        match=control.match(text,index)
        if not match:
            index+=1
            if not skip and marker in ('~','_'):out.append(' ' if marker=='~' else '-')
            continue
        word=match.group(1);value=int(match.group(2)) if match.group(2) else 0;index=match.end()
        if word in destinations:skip=True
        elif word=='bin':index=min(len(text),index+max(0,value))
        elif word=='ansicpg':codepage='cp'+str(value)
        elif word=='uc':unicode_skip=max(0,min(8,value))
        elif word=='u' and not skip:out.append(chr(value%65536));fallback=unicode_skip
        elif not skip and word in ('par','line'):out.append('\n')
        elif not skip and word in ('tab','cell'):out.append('\t')
        elif not skip and word=='row':out.append('\n')
    return ''.join(out).encode('utf-16','surrogatepass').decode('utf-16',errors='replace')

# ==========================================
# Function: Read binary Word through the pinned private native converter.
# Method: Use a disposable input/output directory and a finite noninteractive child process; never invoke a shell or Word.
# ==========================================
def binary_word_text(data):
    if len(data)>30*1024*1024:raise ValueError('Word文件超过30 MiB预览限制')
    if os.name=='nt':
        runtime=runtime_root();program=runtime/'bin/antiword.exe';resources=runtime/'share/antiword'
    else:program=Path(shutil.which('antiword') or '/nonexistent/antiword');resources=None
    if not program.is_file():raise ValueError('缺少本机.doc读取组件，请使用完整客户端运行目录')
    env=dict(os.environ)
    if resources:env['ANTIWORDHOME']=str(resources)
    from .storage_paths import active_cache
    temporary_root=active_cache()/'documents';temporary_root.mkdir(parents=True,exist_ok=True,mode=0o700)
    with tempfile.TemporaryDirectory(prefix='maildesk-doc-',dir=temporary_root) as folder:
        folder=Path(folder);input_path=folder/'input.doc';input_path.write_bytes(data)
        with (folder/'output.txt').open('w+b') as output,(folder/'error.txt').open('w+b') as error:
            try:
                result=subprocess.run([str(program),'-m','UTF-8.txt','-w','0',str(input_path)],stdout=output,stderr=error,env=env,cwd=folder,timeout=8,creationflags=0x08000000 if os.name=='nt' else 0)
            except subprocess.TimeoutExpired as exc:raise ValueError('Word文件读取超时，可保存原始文件后查看') from exc
            output.seek(0);raw=output.read(2_000_001);error.seek(0);message=error.read(2000).decode('utf-8',errors='replace').strip()
            if result.returncode!=0:raise ValueError('无法读取该Word文件（可能已加密或损坏）：'+message[:300])
    text=raw[:2_000_000].decode('utf-8',errors='replace')
    if len(raw)>2_000_000:text+='\n\n[预览显示前2 MB文字；保存原始文件可获得完整内容。]'
    return text

# ==========================================
# Function: Distinguish genuine DOC, RTF-backed DOC and HTML-backed DOC by content.
# Method: Return escaped paragraph/table-like text or inert HTML to the existing reader; no filename-only binary decoding.
# ==========================================
def legacy_preview(data):
    head=data.lstrip()[:512]
    if head.startswith(b'{\\rtf'):text=rtf_text(data)
    elif data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1') or (len(data)>2 and data[:2] in (b'\xdb\xa5',b'\xdc\xa5')):text=binary_word_text(data)
    elif re.search(br'<(?:!doctype\s+html|html|body|table|p[ >])',head,re.I):
        from .document_reader import document_text
        source=document_text(data[:2_000_000]);return source,source,'html'
    else:text=binary_word_text(data)
    text=text.replace('\x0c','\n\n').replace('\x07','\t');text=re.sub('[\x00-\x08\x0b\x0e-\x1f]','',text)
    content=''.join('<p style="white-space:pre-wrap">'+html.escape(line)+'</p>' for line in text.splitlines() if line.strip())
    return '<article>'+content+'</article>',text,'document'
