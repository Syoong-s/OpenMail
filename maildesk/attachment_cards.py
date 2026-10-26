"""Consistent fixed-width adaptive attachment cards without decoding payloads."""
from pathlib import Path

WIDTH=218
TYPES={
    'pdf':('PDF','#dd817e'),'image':('图片','#b9a1e5'),'markdown':('Markdown','#83b4e5'),
    'html':('网页','#dca56d'),'sheet':('表格','#7bb69a'),'document':('文档','#86a5e2'),
    'archive':('压缩包','#d2b16e'),'audio':('音频','#84bfae'),'video':('视频','#d08da6'),'code':('代码','#8abfc9'),'file':('文件','#a5acb8')}

# ==========================================
# Function: Identify an attachment by safe metadata only.
# Method: Favor MIME families, use filename suffixes for common document formats and preserve unknown files.
# ==========================================
def file_kind(name,media_type=''):
    suffix=Path(name).suffix.lower();media_type=(media_type or '').lower()
    if media_type=='application/pdf' or suffix=='.pdf':return 'pdf'
    if media_type.startswith('image/'):return 'image'
    if suffix in ('.png','.jpg','.jpeg','.gif','.webp','.bmp','.tif','.tiff','.heic','.avif','.svg','.ico'):return 'image'
    if suffix in ('.md','.markdown') or media_type=='text/markdown':return 'markdown'
    if suffix in ('.html','.htm') or media_type=='text/html':return 'html'
    if suffix in ('.xls','.xlsx','.xlsm','.ods','.csv','.tsv') or 'spreadsheet' in media_type:return 'sheet'
    if suffix in ('.doc','.docx','.odt','.rtf','.ppt','.pptx','.odp'):return 'document'
    if suffix in ('.zip','.7z','.rar','.tar','.gz','.bz2','.xz','.tgz'):return 'archive'
    if media_type.startswith('audio/') or suffix in ('.mp3','.wav','.flac','.m4a','.ogg'):return 'audio'
    if media_type.startswith('video/') or suffix in ('.mp4','.mkv','.avi','.mov','.webm'):return 'video'
    if suffix in ('.json','.xml','.py','.c','.h','.cpp','.js','.ts','.tsx','.jsx','.rs','.go','.java','.yaml','.yml','.sh','.toml','.ipynb','.tex'):return 'code'
    return 'file'

# ==========================================
# Function: Format bounded metadata sizes without reading an attachment.
# Method: Use compact binary units and tolerate malformed imported size values.
# ==========================================
def size_label(value):
    try:size=max(0,int(value))
    except (ValueError,TypeError,OverflowError):size=0
    if size>=1024*1024:return f'{size/1024/1024:.1f} MB'
    if size>=1024:return f'{size/1024:.0f} KB'
    return str(size)+' B'

# ==========================================
# Function: Configure an attachment host to wrap into as many stable columns as its allocated width permits.
# Method: Align the flow grid and cards left so extra container width never stretches each card.
# ==========================================
def configure(g,host):
    g.gtk_flow_box_set_selection_mode(host,0);g.gtk_flow_box_set_max_children_per_line(host,64);g.gtk_flow_box_set_min_children_per_line(host,1);g.gtk_flow_box_set_column_spacing(host,8);g.gtk_flow_box_set_row_spacing(host,8);g.gtk_widget_set_halign(host,0)

# ==========================================
# Function: Build one accessible attachment card with a type-specific icon and exact file tooltip.
# Method: Ellipsize real labels within a fixed width; keep origin/part callbacks in the caller's group.
# ==========================================
def card(g,attachment,callback,group):
    name=str(attachment.get('name') or '未命名附件');kind=file_kind(name,attachment.get('type',''));title,color=TYPES[kind];button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'attachment-card');g.gtk_widget_set_halign(button,1);g.gtk_widget_set_size_request(button,WIDTH,-1);g.gtk_widget_set_tooltip_text(button,(name+'\n'+title+' · '+size_label(attachment.get('size',0))).encode())
    line=g.gtk_box_new(0,10);g.gtk_container_add(button,line);badge=g.gtk_event_box_new();g.gtk_event_box_set_visible_window(badge,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(badge),('attachment-'+kind).encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(badge),b'attachment-badge');g.gtk_container_add(badge,g.image_file(Path(__file__).parent/'desktop_assets/icons'/('file-'+kind+'.svg'),24));g.gtk_box_pack_start(line,badge,0,0,0)
    labels=g.gtk_box_new(1,4);g.gtk_box_pack_start(line,labels,1,1,0);label=g.gtk_label_new(name.encode());g.gtk_label_set_single_line_mode(label,1);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,17);g.gtk_label_set_xalign(label,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),b'attachment-name');g.gtk_box_pack_start(labels,label,0,1,0)
    detail=g.gtk_label_new((title+' · '+size_label(attachment.get('size',0))).encode());g.gtk_label_set_single_line_mode(detail,1);g.gtk_label_set_ellipsize(detail,3);g.gtk_label_set_max_width_chars(detail,20);g.gtk_label_set_xalign(detail,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(detail),b'attachment-detail');g.gtk_box_pack_start(labels,detail,0,1,0)
    g.connect(button,'clicked',lambda *unused:callback(),group=group);return button
