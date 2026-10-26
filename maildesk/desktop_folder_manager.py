"""Modern native folder browser and context actions over existing safe folder services."""
from pathlib import Path
import xml.etree.ElementTree as ET
from .desktop_forms import Form,form_xml
from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL

# ==========================================
# Function: Build a folder browser with icon actions and focused typed details.
# Method: Retain field identifiers while replacing the generic stacked form with two native panes.
# ==========================================
def folder_manager_xml(fields):
    root=ET.fromstring(form_xml(fields));form=root.find('object');rows=list(form.findall('child'))
    for child in rows:form.remove(child)
    form.find("property[@name='orientation']").text='horizontal'
    left=ET.SubElement(ET.SubElement(form,'child'),'object',{'class':'GtkBox','id':'folder_manager_sidebar'})
    ET.SubElement(left,'property',{'name':'orientation'}).text='vertical';ET.SubElement(left,'property',{'name':'spacing'}).text='10'
    ET.SubElement(left,'property',{'name':'width-request'}).text='255'
    heading=ET.SubElement(ET.SubElement(left,'child'),'object',{'class':'GtkLabel'})
    ET.SubElement(heading,'property',{'name':'label'}).text='文件夹';ET.SubElement(heading,'property',{'name':'xalign'}).text='0'
    ET.SubElement(ET.SubElement(heading,'style'),'class',{'name':'settings-heading'})
    scroll=ET.SubElement(ET.SubElement(left,'child'),'object',{'class':'GtkScrolledWindow'})
    ET.SubElement(scroll,'property',{'name':'hscrollbar-policy'}).text='never';ET.SubElement(scroll,'property',{'name':'height-request'}).text='380'
    tree=ET.SubElement(ET.SubElement(scroll,'child'),'object',{'class':'GtkBox','id':'folder_manager_tree'})
    ET.SubElement(tree,'property',{'name':'orientation'}).text='vertical';ET.SubElement(tree,'property',{'name':'spacing'}).text='3'
    right_child=ET.SubElement(form,'child');right=ET.SubElement(right_child,'object',{'class':'GtkBox','id':'folder_manager_details'})
    ET.SubElement(right,'property',{'name':'orientation'}).text='vertical';ET.SubElement(right,'property',{'name':'spacing'}).text='12';ET.SubElement(right,'property',{'name':'hexpand'}).text='True'
    heading=ET.SubElement(ET.SubElement(right,'child'),'object',{'class':'GtkLabel','id':'folder_manager_title'})
    ET.SubElement(heading,'property',{'name':'label'}).text='管理你的文件夹';ET.SubElement(heading,'property',{'name':'xalign'}).text='0'
    ET.SubElement(ET.SubElement(heading,'style'),'class',{'name':'settings-heading'})
    toolbar=ET.SubElement(ET.SubElement(right,'child'),'object',{'class':'GtkBox','id':'folder_manager_actions'});ET.SubElement(toolbar,'property',{'name':'spacing'}).text='5'
    for child in rows:
        object_ids={obj.get('id') for obj in child.iter('object')}
        key=next((key for key,*unused in fields if key in object_ids),None)
        if key:child.find('object').set('id','folder_row_'+key)
        right.append(child)
    ET.SubElement(ET.SubElement(left,'style'),'class',{'name':'folder-manager-sidebar'})
    ET.SubElement(ET.SubElement(right,'style'),'class',{'name':'folder-manager-details'})
    return ET.tostring(root,encoding='unicode')

# ==========================================
# Function: Open the account-scoped folder browser while preserving all existing operations.
# Method: Drive one typed form from icon commands and exact folder identities, then dispatch safely.
# ==========================================
def manage_folders(app,account_id=None):
    g=app.g;rows=app.service.store.list_folders();accounts=sorted({row['account'] for row in rows}|set(app.service.accounts))
    if not accounts:app.message('本地文件夹尚未就绪，请重新打开应用');return
    fields=[('account','账户','combo',[(v,LOCAL_LABEL if v==LOCAL_ACCOUNT else (app.service.accounts[v].title or app.service.accounts[v].email) if v in app.service.accounts else v) for v in accounts]),
        ('folder','已有文件夹','combo',[]),('path','完整路径','text',[]),('target','新路径 / 名称','text',[]),
        ('operation','操作','combo',[(v,t) for v,t in [('create','创建文件夹'),('rename','重命名 / 移动层级'),('delete','删除空文件夹'),('favorite','收藏文件夹'),('unfavorite','取消收藏'),('subscribe','订阅'),('unsubscribe','取消订阅'),('color','设置颜色'),('mapping','设为系统文件夹')]]),
        ('color','颜色','combo',[('', '默认'),('purple','紫色'),('blue','蓝色'),('green','绿色'),('orange','橙色'),('red','红色')]),
        ('special','系统用途','combo',[('archive','归档'),('trash','废纸篓'),('spam','垃圾邮件'),('sent','已发送'),('drafts','草稿')])]
    form=Form(app,'TeleMail · 文件夹',fields,990,layout=folder_manager_xml(fields));app.folder_manager_form=form
    form.folder_buttons={};form.account_headings={};form.operation_buttons={};form.context_buttons={}
    form.detail_rows={key:g.object(form.builder,'folder_row_'+key) for key,*unused in fields}
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(form.window),b'modern-folder-manager')
    # ==========================================
    # Function: Select a precise folder and retain server delimiters for nested operations.
    # Method: Update the existing typed account/folder/path fields instead of parsing display labels.
    # ==========================================
    def selected_folder(account,path):
        form.value('account',account);form.value('folder',path);form.value('path',path)
        g.label(g.object(form.builder,'folder_manager_title'),path)
    # ==========================================
    # Function: Show only details relevant to the chosen folder command.
    # Method: Keep advanced field APIs while preventing hidden rows from reappearing through show_all.
    # ==========================================
    def operation_changed(*unused):
        operation=form.value('operation')
        for key,row in form.detail_rows.items():
            shown=key!='folder' and (key not in ('target','color','special') or operation=={'target':'rename','color':'color','special':'mapping'}[key])
            g.gtk_widget_set_no_show_all(row,not shown);g.gtk_widget_set_visible(row,shown)
            if shown:g.gtk_widget_show_all(row)
        if hasattr(form,'apply_button'):g.gtk_button_set_label(form.apply_button,{'create':'创建文件夹','rename':'重命名','delete':'删除空文件夹'}.get(operation,'保存设置').encode())
    # ==========================================
    # Function: Prepare an icon or context command for the selected folder.
    # Method: Populate exact source/new paths and focus only the input required by that operation.
    # ==========================================
    def prepare(operation,account=None,path=None,popup=None):
        if popup:g.gtk_popover_popdown(popup)
        if account is not None:selected_folder(account,path)
        current=next((r for r in rows if r['account']==form.value('account') and r['folder']==form.value('path')),None)
        if operation=='subfolder':
            if current and not current['delimiter']:g.label(form.note,'此服务器文件夹不支持子文件夹层级，请使用新建文件夹。');return
            form.value('operation','create');form.value('path',(form.value('path')+(current['delimiter'] if current else '/')));g.gtk_widget_grab_focus(form.fields['path'][0])
        elif operation=='create':form.value('operation','create');form.value('path','');g.gtk_widget_grab_focus(form.fields['path'][0])
        else:
            form.value('operation',operation)
            if operation=='rename':form.value('target',form.value('path'));g.gtk_widget_grab_focus(form.fields['target'][0])
            elif operation=='color':g.gtk_widget_grab_focus(form.fields['color'][0])
        g.label(form.note,'输入新的完整路径后应用。' if operation in ('create','subfolder','rename') else '检查所选账户及文件夹后应用。系统文件夹与非空文件夹的删除保护始终生效。')
    # ==========================================
    # Function: Refresh the dependent folder selector after account changes.
    # Method: Keep exact Unicode paths and choose a valid folder within the selected account.
    # ==========================================
    def account_changed(*unused):
        combo=form.fields['folder'][0];g.gtk_combo_box_text_remove_all(combo)
        subset=[r for r in rows if r['account']==form.value('account')]
        for row in subset:g.gtk_combo_box_text_append(combo,row['folder'].encode(),row['folder'].encode())
        if subset:form.value('folder',subset[0]['folder']);form.value('path',subset[0]['folder'])
    g.connect(form.fields['account'][0],'changed',account_changed,group=form.group)
    g.connect(form.fields['folder'][0],'changed',lambda *unused:form.value('path',form.value('folder')),group=form.group)
    g.connect(form.fields['operation'][0],'changed',operation_changed,group=form.group)
    tree=g.object(form.builder,'folder_manager_tree')
    for account in accounts:
        label=LOCAL_LABEL if account==LOCAL_ACCOUNT else ((app.service.accounts[account].title or app.service.accounts[account].email) if account in app.service.accounts else account)
        heading=g.gtk_label_new(label.encode());g.gtk_label_set_xalign(heading,0);g.gtk_label_set_ellipsize(heading,3);g.gtk_label_set_max_width_chars(heading,25)
        color=app.identity_colors.account_color(account);g.style(heading,'label { color: '+color+'; border-left: 3px solid '+color+'; padding: 8px 9px; font-weight: bold; }')
        g.gtk_box_pack_start(tree,heading,0,1,5);form.account_headings[account]=heading
        for row in (item for item in rows if item['account']==account):
            line=g.gtk_box_new(0,2);name=('★ ' if row['favorite'] else '')+row['folder']+(f"  {row['unread']}" if row['unread'] else '')
            button=g.gtk_button_new_with_label(name.encode());g.gtk_button_set_alignment(button,0,.5)
            label_widget=g.gtk_bin_get_child(button);g.gtk_label_set_ellipsize(label_widget,3);g.gtk_label_set_max_width_chars(label_widget,25)
            g.gtk_widget_set_tooltip_text(button,(account+' / '+row['folder']).encode());g.gtk_box_pack_start(line,button,1,1,0)
            g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'folder-manager-row')
            g.connect(button,'clicked',lambda *unused,a=account,p=row['folder']:selected_folder(a,p),group=form.group);form.folder_buttons[(account,row['folder'])]=button
            menu=g.gtk_menu_button_new();g.gtk_button_set_label(menu,'•••'.encode());popup=g.gtk_popover_new(menu);options=g.gtk_box_new(1,3);g.gtk_container_set_border_width(options,6);g.gtk_container_add(popup,options);g.gtk_menu_button_set_popover(menu,popup)
            for operation,title in [('subfolder','新建子文件夹'),('unfavorite' if row['favorite'] else 'favorite','取消收藏' if row['favorite'] else '加入收藏'),('rename','重命名'),('color','文件夹颜色'),('unsubscribe' if row['subscribed'] else 'subscribe','取消订阅' if row['subscribed'] else '订阅'),('delete','删除空文件夹')]:
                action=g.gtk_button_new_with_label(title.encode());g.gtk_box_pack_start(options,action,0,1,0)
                g.connect(action,'clicked',lambda *unused,op=operation,a=account,p=row['folder'],pop=popup:prepare(op,a,p,pop),group=form.group)
                form.context_buttons[(account,row['folder'],operation)]=action
            g.gtk_widget_show_all(options);g.gtk_box_pack_start(line,menu,0,0,0);g.gtk_box_pack_start(tree,line,0,1,0)
    toolbar=g.object(form.builder,'folder_manager_actions')
    for operation,title,icon in [('create','新建文件夹','folder-add'),('subfolder','新建子文件夹','folder-add'),('rename','重命名 / 移动层级','folder-edit'),('favorite','加入收藏','folder-favorite'),('color','设置颜色','folder-color'),('delete','删除空文件夹','spark-layout-trash')]:
        button=g.gtk_button_new();g.gtk_button_set_image(button,g.image_file(Path(__file__).parent/'desktop_assets/icons'/(icon+'.svg'),18));g.gtk_button_set_always_show_image(button,1);g.gtk_widget_set_tooltip_text(button,title.encode())
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'mail-icon-action');g.gtk_box_pack_start(toolbar,button,0,0,0);g.connect(button,'clicked',lambda *unused,op=operation:prepare(op),group=form.group);form.operation_buttons[operation]=button
    form.value('account',account_id if account_id in accounts else app.folder_account or accounts[0]);account_changed()
    if app.folder_path and (not account_id or account_id==app.folder_account):form.value('folder',app.folder_path);form.value('path',app.folder_path)
    form.value('operation','create');form.value('color','purple');form.value('special','archive')
    form.button('关闭',-6);form.apply_button=form.button('应用',1)
    g.label(form.note,'选择左侧文件夹，使用上方图标或 ⋯ 菜单管理。新建可使用完整层级路径；本地文件夹仅存放在此电脑。')
    operation_changed();g.gtk_widget_show_all(form.window);operation_changed();response=g.gtk_dialog_run(form.window)
    values={key:form.value(key) for key,*_ in fields};form.close()
    if response!=1:return
    account,path,operation=values['account'],values['path'].strip(),values['operation']
    if operation in ('favorite','unfavorite','color'):
        app.service.store.folder_options(account,path,**({'color':values['color']} if operation=='color' else {'favorite':operation=='favorite'}));app.refresh_folders();app.message('文件夹设置已保存')
    elif operation=='mapping':
        if not any(row['account']==account and row['folder']==path and row['selectable'] for row in rows):raise ValueError('请选择可用文件夹')
        mapping=app.service.store.preference('folder_mapping',{});mapping.setdefault(account,{})[values['special']]=path;app.service.store.set_preference('folder_mapping',mapping);app.message('系统文件夹映射已保存')
    else:app.background(lambda:app.service.folder_action(account,operation,path,values['target']),lambda result:(app.refresh(),app.message('文件夹操作完成')))
