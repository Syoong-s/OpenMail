"""Structured native rule editor with condition rows, source checklists and account-folder targets."""
from .desktop_forms import Form
from .desktop_general import bind,P,I
from .settings_filters import combo,active,account_options,FIELD_LABELS,CATEGORY_LABELS,SMART_LABELS,OP_LABELS
from . import filter_rules
from .ui_actions import icon_action

# ==========================================
# Function: Author a rule without exposing JSON, scripts or ambiguous cross-account folder names.
# Method: Use native dropdown/entry conditions and explicit per-account source/destination controls.
# ==========================================
class FilterEditor:
    # ==========================================
    # Function: Build one scoped rule editor with bounded native scrolling.
    # Method: Keep ordinary typed fields in Form and append dynamic condition rows owned by that same dialog.
    # ==========================================
    def __init__(self,app,rule=None,account=''):
        self.app=app;self.g=g=app.g;self.rule=rule or {};self.account=self.rule.get('account',account);self.sources={key:list(value) for key,value in self.rule.get('sources',{}).items()};self.conditions=[];self.saved=False;self.saving=False
        self.accounts=[(identity,label) for identity,label in account_options(app) if not self.account or identity==self.account];self.folders=app.service.store.list_folders();self.destination_fields={}
        fields=[('name','过滤器名称','text',[]),('enabled','启用','switch',[]),('mode','条件组合','combo',[('all','满足全部条件'),('any','满足任一条件')]),('source_mode','来源范围','combo',[('all','所有文件夹'),('include','只在选定文件夹'),('exclude','排除选定文件夹')]),('subfolders','包含来源子文件夹','switch',[])]
        for index,(identity,label) in enumerate(self.accounts):
            key='destination_'+str(index);options=[('','不应用此账号')]+[(row['folder'],row['folder']) for row in self.folders if row['account']==identity and row['selectable']];fields.append((key,label+' → 目标','combo',options));self.destination_fields[identity]=key
        self.form=Form(app,'编辑过滤器' if rule else '新建过滤器',fields,880);self.form.value('name',self.rule.get('name',''));self.form.value('enabled',self.rule.get('enabled',True));self.form.value('mode',self.rule.get('mode','all'));self.form.value('source_mode',self.rule.get('source_mode','all'));self.form.value('subfolders',self.rule.get('subfolders',False))
        for identity,key in self.destination_fields.items():self.form.value(key,self.rule.get('destinations',{}).get(identity,''))
        root=g.object(self.form.builder,'form');parent=g.gtk_widget_get_parent(root);bind(app,'object','g_object_ref',P,P)(root);bind(app,'gtk','gtk_container_remove',None,P,P)(parent,root)
        scroll=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(scroll,2,1);g.gtk_widget_set_size_request(scroll,-1,max(300,min(520,g.gtk_widget_get_allocated_height(app.window)-240)));g.gtk_container_add(scroll,root);g.gtk_box_pack_start(self.form.content,scroll,1,1,0);bind(app,'object','g_object_unref',None,P)(root)
        sourcebar=g.gtk_box_new(0,8);g.gtk_box_pack_start(root,sourcebar,0,1,5);self.source_button=g.gtk_button_new_with_label('选择来源文件夹…'.encode());g.gtk_box_pack_start(sourcebar,self.source_button,0,0,0);self.source_label=g.gtk_label_new(b'');g.gtk_box_pack_start(sourcebar,self.source_label,1,1,0);g.connect(self.source_button,'clicked',lambda *unused:self.app.run_action(self.choose_sources),group=self.form.group);self.source_summary()
        heading=g.gtk_label_new('匹配条件'.encode());g.gtk_label_set_xalign(heading,0);g.gtk_box_pack_start(root,heading,0,1,5);self.condition_host=g.gtk_box_new(1,6);g.gtk_box_pack_start(root,self.condition_host,0,1,0)
        self.add_condition_button=g.gtk_button_new();icon_action(g,self.add_condition_button,'添加条件','action-add');g.gtk_widget_set_halign(self.add_condition_button,1);g.gtk_box_pack_start(root,self.add_condition_button,0,0,0);g.connect(self.add_condition_button,'clicked',lambda *unused:self.add_condition(),group=self.form.group)
        reorder=bind(app,'gtk','gtk_box_reorder_child',None,P,P,I)
        for widget,position in ((heading,3),(self.condition_host,4),(self.add_condition_button,5),(sourcebar,8)):reorder(root,widget,position)
        bind(app,'gtk','gtk_box_reorder_child',None,P,P,I)(root,self.form.note,-1);g.label(self.form.note,'账号规则优先于全局；同组首条匹配后停止。正文检查前26万字符。通配符支持 * ? []；智能类型可能重叠。学习分数需先在过滤器列表点击“从目标文件夹学习”，是匹配分数估算。')
        for condition in self.rule.get('conditions',[{'field':'subject','op':'contains','value':''}]):self.add_condition(condition)
        self.form.button('取消',-6);self.save_button=self.form.button('保存过滤器',1)

    # ==========================================
    # Function: Show how many explicit account-folder sources are retained in the editor.
    # Method: Preserve selected paths while the user switches include/exclude/all behavior.
    # ==========================================
    def source_summary(self):self.g.label(self.source_label,'已选 '+str(sum(len(paths) for paths in self.sources.values()))+' 个文件夹')

    # ==========================================
    # Function: Choose multiple source folders from actual account-relative cached hierarchy metadata.
    # Method: Use native checkboxes, include namespace parents and never parse a free-text path list.
    # ==========================================
    def choose_sources(self):
        allowed={identity for identity,label in self.accounts};names=dict(self.accounts);rows=[row for row in self.folders if row['account'] in allowed];fields=[('source_'+str(index),names[row['account']]+' · '+row['folder'],'check',[]) for index,row in enumerate(rows)]
        form=Form(self.app,'选择来源文件夹',fields,680);self.source_form=form
        for index,row in enumerate(rows):form.value('source_'+str(index),row['folder'] in self.sources.get(row['account'],[]))
        self.g.label(form.note,'使用“只在选定文件夹”或“排除选定文件夹”时生效。需要包含后代文件夹时，开启“包含来源子文件夹”。');form.button('取消',-6);form.button('确定',1)
        root=self.g.object(form.builder,'form');parent=self.g.gtk_widget_get_parent(root);bind(self.app,'object','g_object_ref',P,P)(root);bind(self.app,'gtk','gtk_container_remove',None,P,P)(parent,root);scroll=self.g.gtk_scrolled_window_new(None,None);self.g.gtk_scrolled_window_set_policy(scroll,2,1);self.g.gtk_widget_set_size_request(scroll,-1,380);self.g.gtk_container_add(scroll,root);self.g.gtk_box_pack_start(form.content,scroll,1,1,0);bind(self.app,'object','g_object_unref',None,P)(root)
        self.g.gtk_widget_show_all(form.window);response=self.g.gtk_dialog_run(form.window)
        if response==1:
            self.sources={}
            for index,row in enumerate(rows):
                if form.value('source_'+str(index)):self.sources.setdefault(row['account'],[]).append(row['folder'])
            self.source_summary()
        form.close()

    # ==========================================
    # Function: Add one bounded condition row with field-specific operator/value controls.
    # Method: Retain stable row objects for editor values, native callbacks and safe removal.
    # ==========================================
    def add_condition(self,value=None):
        if len(self.conditions)>=12:return
        g=self.g;value=value or {'field':'subject','op':'contains','value':''};root=g.gtk_box_new(1,3);line=g.gtk_box_new(0,5);g.gtk_box_pack_start(root,line,0,1,0)
        row={'root':root,'guard':False,'choices':[],'group':self.form.group+'-condition-'+str(root)};row['field']=combo(self.app,self.form,line,'条件字段',FIELD_LABELS,value['field']);row['choices'].append(self.form.choices[-1]);row['op']=combo(self.app,self.form,line,'匹配方式',OP_LABELS,value.get('op','contains'));row['choices'].append(self.form.choices[-1])
        row['text']=g.gtk_entry_new();g.gtk_widget_set_hexpand(row['text'],1);g.gtk_box_pack_start(line,row['text'],1,1,0)
        row['value']=combo(self.app,self.form,line,'条件值',[('true','是'),('false','否')],'true');row['choices'].append(self.form.choices[-1]);row['header']=g.gtk_entry_new();g.gtk_entry_set_placeholder_text(row['header'],b'List-Id / Auto-Submitted');g.gtk_box_pack_start(root,row['header'],0,1,0)
        remove=g.gtk_button_new();icon_action(g,remove,'删除此条件','spark-layout-trash',14);g.gtk_box_pack_start(line,remove,0,0,0)
        row['remove']=remove
        self.conditions.append(row);g.gtk_box_pack_start(self.condition_host,root,0,1,0);g.text(row['text'],value.get('value',''));g.text(row['header'],value.get('header',''))
        g.connect(row['field'],'changed',lambda *unused,item=row:self.update_condition(item),group=row['group']);g.connect(remove,'clicked',lambda *unused,item=row:self.remove_condition(item),group=row['group'])
        self.update_condition(row,value);g.gtk_widget_show_all(root);self.condition_visibility(row)

    # ==========================================
    # Function: Choose compatible operators and translated values when the condition field changes.
    # Method: Preserve existing saved values initially and replace incompatible operators with safe explicit defaults.
    # ==========================================
    def update_condition(self,row,value=None):
        if row['guard']:return
        row['guard']=True;g=self.g;field=active(g,row['field']);old=value or {'op':active(g,row['op']),'value':g.text(row['text'])}
        numeric=field in ('size_kb','learned');select=field in ('has_attachment','seen','starred_contact','category','smart');operators=[('gte','至少'),('gt','大于'),('lte','至多'),('lt','小于')] if numeric else [('is','是'),('is_not','不是')] if select else OP_LABELS
        g.gtk_combo_box_text_remove_all(row['op'])
        for key,label in operators:g.gtk_combo_box_text_append(row['op'],key.encode(),label.encode())
        selected=old.get('op') if old.get('op') in dict(operators) else operators[0][0];g.gtk_combo_box_set_active_id(row['op'],selected.encode())
        choices=CATEGORY_LABELS if field=='category' else SMART_LABELS if field=='smart' else [('true','是'),('false','否')]
        g.gtk_combo_box_text_remove_all(row['value'])
        for key,label in choices:g.gtk_combo_box_text_append(row['value'],key.encode(),label.encode())
        selected=old.get('value') if old.get('value') in dict(choices) else choices[0][0];g.gtk_combo_box_set_active_id(row['value'],selected.encode())
        if field=='learned' and (not old.get('value') or not old['value'].isdigit()):g.text(row['text'],'95')
        elif field=='size_kb' and (not old.get('value') or not old['value'].isdigit()):g.text(row['text'],'1024')
        g.gtk_entry_set_placeholder_text(row['text'],('0–100，建议至少95' if field=='learned' else '大小单位 KiB' if field=='size_kb' else '匹配内容').encode());row['guard']=False;self.condition_visibility(row)

    # ==========================================
    # Function: Hide irrelevant field controls without Gtk show-all bringing them back.
    # Method: Keep text values, translated choices and custom header names mutually explicit.
    # ==========================================
    def condition_visibility(self,row):
        field=active(self.g,row['field']);select=field in ('has_attachment','seen','starred_contact','category','smart')
        for widget,visible in ((row['text'],not select),(row['value'],select),(row['header'],field=='header')):
            self.g.gtk_widget_set_no_show_all(widget,int(not visible));self.g.gtk_widget_set_visible(widget,int(visible))

    # ==========================================
    # Function: Remove a condition while releasing its native dropdown wrappers before widget destruction.
    # Method: Keep the parent Form's ownership list accurate and leave validation to require at least one row.
    # ==========================================
    def remove_condition(self,row):
        if row not in self.conditions:return
        self.g.surfaces.retire(row['group'])
        for choice in row['choices']:
            choice.close();self.form.choices.remove(choice)
        self.conditions.remove(row);self.g.gtk_widget_destroy(row['root'])

    # ==========================================
    # Function: Collect a bounded native form into the production rule schema.
    # Method: Store account IDs and exact paths, not translated display labels or arbitrary executable text.
    # ==========================================
    def values(self):
        conditions=[]
        for row in self.conditions:
            field=active(self.g,row['field']);condition={'field':field,'op':active(self.g,row['op']),'value':active(self.g,row['value']) if field in ('has_attachment','seen','starred_contact','category','smart') else self.g.text(row['text'])}
            if field=='header':condition['header']=self.g.text(row['header'])
            conditions.append(condition)
        result={key:self.form.value(key) for key in ('name','enabled','mode','source_mode','subfolders')};result.update(account=self.account,sources=self.sources,conditions=conditions,destinations={account:self.form.value(key) for account,key in self.destination_fields.items() if self.form.value(key)})
        if self.rule.get('id'):result['id']=self.rule['id']
        return filter_rules.validate(result)

    # ==========================================
    # Function: Acknowledge a durable save from the worker on GTK's own loop.
    # Method: Close only after the service has committed the validated rule.
    # ==========================================
    def save_ready(self,identity):
        self.saved=True;self.saving=False
        if not self.form.closed:self.g.gtk_dialog_response(self.form.window,2)

    # ==========================================
    # Function: Keep authored conditions visible if validation or storage fails.
    # Method: Show the error inside the same editor and restore its save action.
    # ==========================================
    def save_failed(self,error):
        self.saving=False
        if not self.form.closed:self.g.label(self.form.note,str(error));self.g.gtk_widget_set_sensitive(self.save_button,1)

    # ==========================================
    # Function: Run the native editor until a validated save or cancellation.
    # Method: Dispatch local persistence off GTK and retain the complete form while that result is pending.
    # ==========================================
    def run(self):
        self.g.gtk_widget_show_all(self.form.window)
        for row in self.conditions:self.condition_visibility(row)
        try:
            while True:
                response=self.g.gtk_dialog_run(self.form.window)
                if response==2 and self.saved:return True
                if response!=1:return False
                if self.saving:continue
                try:value=self.values()
                except ValueError as error:self.g.label(self.form.note,str(error));continue
                self.saving=True;self.g.gtk_widget_set_sensitive(self.save_button,0);self.app.background(lambda candidate=value:self.app.service.save_filter(candidate),self.save_ready,self.save_failed)
        finally:
            for row in self.conditions:self.g.disconnect(row['group'])
            self.form.close()
