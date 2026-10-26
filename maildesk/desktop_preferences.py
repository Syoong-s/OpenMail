"""Local general/appearance policy shared by native views and settings."""
from email import policy
from email.parser import BytesParser
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs,unquote,urlsplit

# ==========================================
# Function: Decode explicit OS mailto requests into an unsent editable draft.
# Method: Whitelist safe fields, bound lengths and reject header/file injection; never enqueue.
# ==========================================
def parse_mailto(uri):
    if not isinstance(uri,str) or len(uri)>65536 or any(character in uri for character in '\r\n\x00\t'):raise ValueError('邮件链接过长')
    parsed=urlsplit(uri)
    if parsed.scheme.lower()!='mailto' or parsed.netloc or parsed.fragment:raise ValueError('无效邮件链接')
    values=parse_qs(parsed.query,keep_blank_values=True)
    if set(values)-{'to','cc','subject','body'}:raise ValueError('邮件链接包含不支持的字段；密送和附件请在编辑器中手动添加')
    result={'to':unquote(parsed.path)}
    for key,items in values.items():
        if len(items)!=1:raise ValueError('邮件链接包含重复字段')
        result[key]=(result[key]+',' if key=='to' and result[key] else '')+items[0]
    for key,value in result.items():
        if '\x00' in value or (key!='body' and any(character in value for character in '\r\n')):raise ValueError('邮件链接包含无效换行')
    from .composer_options import validated_addresses
    for key in ('to','cc'):
        if result.get(key):result[key]=', '.join(validated_addresses(result[key]))
    return result

# ==========================================
# Function: Translate Spark-style list preview options into bounded row presentation.
# Method: Keep the compact default while full-list and split modes apply their own controls.
# ==========================================
def row_presentation(store):
    layout=store.preference('layout_mode','splitView')
    if layout=='fullScreen':lines=2 if store.preference('mail_list_preview','expanded')=='expanded' else 0
    else:
        try:lines=min(3,max(0,int(store.preference('email_preview_lines',1))))
        except (ValueError,TypeError):lines=1
    return {'preview_lines':lines,'row_height':max(48,63+(lines-1)*16),
        'labels_list':bool(store.preference('labels_list',True)),
        'labels_reader':bool(store.preference('labels_reader',True)),
        'labels_system':bool(store.preference('labels_system',False)),
        'layout':layout}

# ==========================================
# Function: Resolve a saved theme using the actual operating-system preference.
# Method: Honor explicit dark/light choice and fall back to dark if the desktop exposes no setting.
# ==========================================
def resolved_theme(app):
    chosen=app.service.store.preference('theme','dark')
    return getattr(app,'system_theme','dark') if chosen=='system' else chosen

# ==========================================
# Function: Expand locally cached MIME attachments into private reusable files.
# Method: Read bounded existing messages, keep safe basenames and atomically save 0600 files without networking.
# ==========================================
def cached_attachments(store,should_yield=None):
    if not store.preference('autodownload_attachments',False):return 0
    from .mime import attachment_content,MAX_MESSAGE_BYTES
    from .storage_paths import active_cache
    root=Path(getattr(store,'cache_dir',active_cache()))/'attachments'
    if root.is_symlink():raise ValueError('附件缓存目录不能是符号链接')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    with store.db() as db:rows=db.execute("SELECT id FROM messages WHERE remote_gone=0 AND json_array_length(parsed,'$.attachments')>0 ORDER BY timestamp DESC").fetchall()
    count=0
    for row in rows:
        if should_yield and should_yield():break
        raw=store.get(row['id'],raw=True)['raw']
        if len(raw)>MAX_MESSAGE_BYTES:continue
        target=root/hashlib.sha256(raw).hexdigest()
        if target.is_symlink():raise ValueError('附件缓存目录无效')
        target.mkdir(mode=0o700,exist_ok=True)
        if (target/'.complete-v2').is_symlink():raise ValueError('附件缓存标记无效')
        if (target/'.complete-v2').is_file():continue
        mail=BytesParser(policy=policy.default).parsebytes(raw)
        parts=list(mail.walk())
        for attachment in store.get(row['id'])['parsed']['attachments']:
            index=attachment['index'];part=parts[index]
            name=re.sub(r'[\x00-\x1f/\\]','_',Path(part.get_filename() or 'attachment').name)
            name=name.encode('utf-8')[:180].decode('utf-8',errors='ignore')
            file=target/(str(index)+'-'+(name or 'attachment'))
            if file.is_symlink():raise ValueError('附件缓存文件无效')
            if file.exists():continue
            data=attachment_content(part)
            if len(data)>MAX_MESSAGE_BYTES:continue
            descriptor,temporary=tempfile.mkstemp(prefix='.attachment-',dir=target)
            try:
                with os.fdopen(descriptor,'wb') as output:output.write(data)
                os.chmod(temporary,0o600);os.replace(temporary,file);count+=1
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        (target/'.complete-v2').touch(mode=0o600,exist_ok=True)
    return count
