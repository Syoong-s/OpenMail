"""One native settings workspace with flat rows and compact trailing controls."""
from pathlib import Path
import xml.etree.ElementTree as ET
from .desktop_forms import form_xml

ICONS=Path(__file__).parent/'desktop_assets/icons'
DESCRIPTIONS={'filters':'全局和账号独立规则：账号优先、首条匹配停止。新邮件只自动执行一次；已有邮件可按任意缓存文件夹预览并手动运行。','conversations':'选择哪些邮箱文件夹参与联系人的邮件对话汇总。','contacts':'管理保存的联系人与最近来信地址。','general':'按你的工作习惯调整客户端行为。','accounts':'管理本机邮箱、连接与登录状态。','composer':'专注撰写，设置默认的发送和回复方式。','templates':'把常用内容保存为可重复使用的邮件模板。','inbox':'调整优先邮件、发件人筛选与自动归类。','notifications':'只接收你需要关注的邮件提醒。','scheduling':'设置本机稍后发送与跟进提醒的时间。','appearance':'选择主题、密度和邮件列表的呈现方式。','reading':'调整阅读体验，同时保护远程内容隐私。','shortcuts':'用键盘快速导航、搜索和回复。','privacy':'掌控本地数据、凭据和外部内容。','storage':'设置过期邮件自动整理、清理缓存并管理本机储存位置。','about':'本地优先的独立桌面邮件客户端。'}

# ==========================================
# Function: Declare one native property before widget children.
# Method: Preserve an existing property identity or add it to the declaration prefix.
# ==========================================
def property_xml(node,name,value):
    prop=node.find('property[@name="'+name+'"]')
    if prop is None:prop=ET.Element('property',{'name':name});node.insert(0,prop)
    prop.text=str(value)

# ==========================================
# Function: Add a CSS role to a native settings control.
# Method: Keep visual grouping independent of field identifiers.
# ==========================================
def style_xml(node,name):
    style=node.find('style')
    if style is None:style=ET.SubElement(node,'style')
    ET.SubElement(style,'class',{'name':name})

# ==========================================
# Function: Attach a native widget to a container.
# Method: Create an explicit GtkBuilder child wrapper for stable ownership.
# ==========================================
def child_xml(parent,kind,identity=None):
    attrs={'class':kind}
    if identity:attrs['id']=identity
    return ET.SubElement(ET.SubElement(parent,'child'),'object',attrs)

# ==========================================
# Function: Create a packaged original line icon for one settings section.
# Method: Keep image lookup local and use fixed compact size.
# ==========================================
def icon_xml(key):
    node=ET.Element('object',{'class':'GtkImage'});property_xml(node,'file',str(ICONS/('settings-'+key+'.svg')));property_xml(node,'pixel-size',18);return ET.tostring(node,encoding='unicode')

# ==========================================
# Function: Build a single sidebar/stack settings workspace with flat option rows.
# Method: Reuse typed field widgets while removing isolated card frames and oversized dropdowns.
# ==========================================
def settings_xml(fields,pages,page_fields):
    root=ET.Element('interface');form=ET.SubElement(root,'object',{'class':'GtkBox','id':'form'});property_xml(form,'orientation','vertical');property_xml(form,'spacing',0)
    workspace=child_xml(form,'GtkBox');property_xml(workspace,'height-request',240);property_xml(workspace,'vexpand','True');style_xml(workspace,'settings-workspace')
    packing=ET.SubElement(form.findall('child')[-1],'packing');ET.SubElement(packing,'property',{'name':'expand'}).text='True';ET.SubElement(packing,'property',{'name':'fill'}).text='True'
    sidebar_scroll=child_xml(workspace,'GtkScrolledWindow','settings_sidebar_scroll');property_xml(sidebar_scroll,'hscrollbar-policy','never');property_xml(sidebar_scroll,'vscrollbar-policy','automatic');property_xml(sidebar_scroll,'vexpand','True')
    sidebar=child_xml(sidebar_scroll,'GtkBox','settings_sidebar');property_xml(sidebar,'name','settings_sidebar');property_xml(sidebar,'orientation','vertical');property_xml(sidebar,'width-request',170);property_xml(sidebar,'spacing',2);property_xml(sidebar,'margin',10)
    packing=ET.SubElement(workspace.findall('child')[-1],'packing');ET.SubElement(packing,'property',{'name':'expand'}).text='False';ET.SubElement(packing,'property',{'name':'fill'}).text='True'
    property_xml(sidebar,'hexpand','False')
    title=child_xml(sidebar,'GtkLabel');property_xml(title,'label','设置');property_xml(title,'xalign',0);style_xml(title,'settings-sidebar-title')
    stack=child_xml(workspace,'GtkStack','settings_stack');property_xml(stack,'homogeneous','False');property_xml(stack,'transition-type','none');property_xml(stack,'transition-duration',0);property_xml(stack,'hexpand','True');property_xml(stack,'vexpand','True')
    mapping={field[0]:field for field in fields}
    for key,title in pages:
        button=child_xml(sidebar,'GtkButton','settings_nav_'+key);property_xml(button,'name','settings_nav_'+key);style_xml(button,'settings-navigation');line=child_xml(button,'GtkBox');property_xml(line,'spacing',10)
        ET.SubElement(line,'child').append(ET.fromstring(icon_xml(key)));label=child_xml(line,'GtkLabel');property_xml(label,'label',title);property_xml(label,'xalign',0);property_xml(label,'hexpand','True')
        wrapper=ET.SubElement(stack,'child');scroll=ET.SubElement(wrapper,'object',{'class':'GtkBox' if key=='contacts' else 'GtkScrolledWindow'});property_xml(scroll,'orientation' if key=='contacts' else 'hscrollbar-policy','vertical' if key=='contacts' else 'never');packing=ET.SubElement(wrapper,'packing');ET.SubElement(packing,'property',{'name':'name'}).text=key;ET.SubElement(packing,'property',{'name':'title'}).text=title
        page=child_xml(scroll,'GtkBox');property_xml(page,'orientation','vertical');property_xml(page,'spacing',8);property_xml(page,'margin',24)
        heading=child_xml(page,'GtkLabel');property_xml(heading,'label',title);property_xml(heading,'xalign',0);style_xml(heading,'settings-heading')
        description=child_xml(page,'GtkLabel');property_xml(description,'label',DESCRIPTIONS.get(key,''));property_xml(description,'xalign',0);property_xml(description,'wrap','True');style_xml(description,'settings-description')
        chosen=[mapping[name] for name in page_fields.get(key,[]) if name in mapping];document=ET.fromstring(form_xml(chosen));body=document.find('object');body.set('id','page_'+key);property_xml(body,'margin',0);property_xml(body,'spacing',0)
        for field,child in zip(chosen,body.findall('child')):
            row=child.find('object');style_xml(row,'settings-option');property_xml(row,'spacing',16);label=row.find("child/object[@class='GtkLabel']");property_xml(label,'width-request',220);property_xml(label,'wrap','True');property_xml(label,'valign','center')
            if key=='storage' and field[0] in ('storage_cache','storage_data','storage_downloads'):
                property_xml(row,'orientation','vertical');property_xml(row,'spacing',7);property_xml(label,'width-request',-1)
                entry_child=row.findall('child')[1];entry=entry_child.find('object');entry_child.remove(entry)
                line=ET.Element('object',{'class':'GtkBox'});entry_child.insert(0,line);property_xml(line,'spacing',8);property_xml(entry,'hexpand','True')
                ET.SubElement(line,'child').append(entry)
                picker=child_xml(line,'GtkButton',field[0]+'_choose');property_xml(picker,'tooltip-text','选择文件夹');property_xml(picker,'valign','center');style_xml(picker,'compact-action')
                image=child_xml(picker,'GtkImage');property_xml(image,'file',str(ICONS/'spark-layout-folder.svg'));property_xml(image,'pixel-size',16)
            if field[0]=='mail_retention_days':
                entry=row.findall('child')[1].find('object')
                property_xml(entry,'input-purpose','digits');property_xml(entry,'width-chars',6);property_xml(entry,'max-width-chars',8);property_xml(entry,'max-length',5);property_xml(entry,'halign','end')
            if field[2]=='body':
                property_xml(row,'orientation','vertical');property_xml(row,'spacing',8);property_xml(label,'width-request',-1);height=row.find("child/object[@class='GtkScrolledWindow']/property[@name='height-request']")
                if height is not None:height.text='120'
        note=body.find('.//object[@id="note"]')
        if note is not None:note.set('id','note_'+key)
        ET.SubElement(page,'child').append(body)
        if key=='contacts':
            # Give only the directory the spare height; headings remain natural size.
            property_xml(page,'margin',16);property_xml(page,'vexpand','True');property_xml(body,'vexpand','True')
            page_packing=ET.SubElement(scroll.find('child'),'packing')
            ET.SubElement(page_packing,'property',{'name':'expand'}).text='True'
            ET.SubElement(page_packing,'property',{'name':'fill'}).text='True'
            for child in page.findall('child'):
                packing=ET.SubElement(child,'packing')
                ET.SubElement(packing,'property',{'name':'expand'}).text='True' if child.find('object') is body else 'False'
                ET.SubElement(packing,'property',{'name':'fill'}).text='True'
            if note is not None:
                property_xml(note,'no-show-all','True');property_xml(note,'visible','False')
    note=child_xml(form,'GtkLabel','note');property_xml(note,'margin',12);property_xml(note,'xalign',0);property_xml(note,'wrap','True');style_xml(note,'muted')
    return ET.tostring(root,encoding='unicode')
