"""Bounded cached MIME images for inline mail rendering, without remote fetches."""
import base64
from email import policy
from email.parser import BytesParser
from pathlib import Path
from .mime import MAX_MESSAGE_BYTES, attachment_content

# ==========================================
# Function: Recognize supported raster images from bytes rather than filenames.
# Method: Require known PNG/JPEG/GIF/WebP/BMP signatures and enforce the existing message-size bound.
# ==========================================
def image_type(data):
    if not data or len(data)>MAX_MESSAGE_BYTES:return ''
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp'
    if data.startswith(b'BM'):return 'image/bmp'
    return ''

# ==========================================
# Function: Encode a validated local raster image for the offline HTML renderer.
# Method: Construct a data URI only from recognized bytes, never a remote or local-file URL.
# ==========================================
def image_uri(data):
    kind=image_type(data)
    if not kind:raise ValueError('当前支持 PNG、JPEG、GIF、WebP、BMP 图片，文件最大 30 MiB')
    return 'data:'+kind+';base64,'+base64.b64encode(data).decode('ascii')

# ==========================================
# Function: Recover both CID images and ordinary image attachments from cached mail.
# Method: Traverse the same MIME indices as attachment metadata and bound aggregate decoded bytes.
# ==========================================
def message_images(raw):
    if len(raw)>MAX_MESSAGE_BYTES:raise ValueError('邮件超过 30 MiB 上限')
    message=BytesParser(policy=policy.default).parsebytes(raw);images=[];total=0;excluded=set()
    for index,part in enumerate(message.walk()):
        if id(part) in excluded:continue
        if part.get_content_type()=='message/rfc822':
            excluded.update(id(child) for child in list(part.walk())[1:]);continue
        if part.is_multipart():continue
        if part.get_content_maintype()!='image' and Path(part.get_filename() or '').suffix.lower() not in ('.png','.jpg','.jpeg','.gif','.webp','.bmp'):continue
        data=attachment_content(part)
        if not image_type(data):continue
        total+=len(data)
        if total>MAX_MESSAGE_BYTES:break
        images.append({'index':index,'cid':str(part.get('Content-ID','')).strip().strip('<>'),
                       'name':part.get_filename() or '内嵌图片','uri':image_uri(data)})
    return images
