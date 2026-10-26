"""Compact native filter cards with independent switches, disclosure and visual account routes."""
import ctypes as C
from html import escape

from .desktop_general import bind,P,I
from .ui_actions import ICONS,icon_action

# ==========================================
# Function: Attach a dedicated visual role to a native filter widget.
# Method: Keep card styling scoped to named classes rather than changing shared Settings controls.
# ==========================================
def style(g,widget,name):
    g.gtk_style_context_add_class(g.gtk_widget_get_style_context(widget),name.encode())
    return widget

# ==========================================
# Function: Build one concise, ellipsized text label with its full value available on hover.
# Method: Use native plain text to preserve literal user names and avoid markup injection.
# ==========================================
def label(g,text,role='',width=0):
    widget=g.gtk_label_new(str(text).encode());g.gtk_label_set_xalign(widget,0)
    if role:style(g,widget,role)
    if width:
        g.gtk_label_set_ellipsize(widget,3);g.gtk_label_set_max_width_chars(widget,width)
    g.gtk_widget_set_tooltip_text(widget,str(text).encode())
    return widget

# ==========================================
# Function: Summarize a saved condition using the editor's translated field and value vocabulary.
# Method: Render operators as compact symbols while retaining literal values for readable tooltip details.
# ==========================================
def condition_text(condition):
    from .settings_filters import FIELD_LABELS,SMART_LABELS,CATEGORY_LABELS,OP_LABELS
    field=condition['field'];value=condition.get('value','');operator=condition.get('op','is')
    if field=='smart':value=dict(SMART_LABELS).get(value,value)
    elif field=='category':value=dict(CATEGORY_LABELS).get(value,value)
    elif isinstance(value,bool):value='是' if value else '否'
    suffix=' KiB' if field=='size_kb' else ' 分' if field=='learned' else ''
    op={'is':'＝','is_not':'≠','gt':'>','lt':'<','gte':'≥','lte':'≤'}.get(operator,dict(OP_LABELS).get(operator,operator))
    return dict(FIELD_LABELS).get(field,field)+' '+op+' '+str(value)+suffix

# ==========================================
# Function: Show one folder or scope as a compact icon chip.
# Method: Separate the diagram's visual roles from full folder paths retained in accessible tooltips.
# ==========================================
def chip(g,text,icon,role='filter-chip',width=26):
    box=style(g,g.gtk_box_new(0,6),role)
    if icon:g.gtk_box_pack_start(box,g.image_file(ICONS/(icon+'.svg'),14),0,0,0)
    caption=label(g,text,'',width);g.gtk_box_pack_start(box,caption,1,1,0)
    g.gtk_widget_set_tooltip_text(box,str(text).encode())
    return box

# ==========================================
# Function: Present one filter with a large disclosure header and per-account routing details.
# Method: Keep switch and icon actions as siblings of the title button so their pointer events never toggle details.
# ==========================================
class FilterCard:
    # ==========================================
    # Function: Construct the header, details revealer and visual routing rows for a saved rule.
    # Method: Reuse parent-owned signal groups and retain view handles for bounded refresh and native acceptance.
    # ==========================================
    def __init__(self,page,rule,names,colors,group):
        self.page=page;self.rule=rule;self.g=g=page.g;identity=rule['id']
        self.box=style(g,g.gtk_box_new(1,0),'filter-card')
        if not rule['enabled']:style(g,self.box,'filter-paused')
        self.header=style(g,g.gtk_box_new(0,6),'filter-card-header');g.gtk_box_pack_start(self.box,self.header,0,1,0)
        self.switch=bind(page.app,'gtk','gtk_switch_new',P)();g.gtk_switch_set_active(self.switch,int(rule['enabled']))
        g.gtk_widget_set_valign(self.switch,3);g.gtk_widget_set_halign(self.switch,1)
        g.gtk_widget_set_tooltip_text(self.switch,('启用 / 暂停过滤器：'+rule['name']).encode());g.gtk_box_pack_start(self.header,self.switch,0,0,0)
        self.expand=style(g,g.gtk_button_new(),'filter-card-disclosure');g.gtk_widget_set_hexpand(self.expand,1)
        titlebox=g.gtk_box_new(0,7);g.gtk_container_add(self.expand,titlebox)
        self.name=label(g,rule['name'],'filter-card-name',42);g.gtk_box_pack_start(titlebox,self.name,1,1,0)
        self.arrow=style(g,g.image_file(ICONS/'filter-chevron-down.svg',14),'filter-card-chevron');g.gtk_widget_set_valign(self.arrow,3);g.gtk_widget_set_size_request(self.arrow,14,14);g.gtk_box_pack_start(titlebox,self.arrow,0,0,0)
        g.gtk_box_pack_start(self.header,self.expand,1,1,0)
        self.actions=style(g,g.gtk_box_new(0,2),'filter-card-actions');g.gtk_box_pack_start(self.header,self.actions,0,0,0)
        for op,title,icon in [('edit','编辑','folder-edit'),('duplicate','复制','action-copy'),('up','上移','action-up'),('down','下移','action-down'),('learn','从目标文件夹学习','action-code'),('delete','删除','spark-layout-trash')]:
            button=g.gtk_button_new();icon_action(g,button,title,icon,12);g.gtk_box_pack_start(self.actions,button,0,0,0);page.buttons[(identity,op)]=button
            if op=='delete':style(g,button,'filter-delete')
            g.connect(button,'clicked',lambda *unused,operation=op:page.app.run_action(lambda:page.operation(identity,operation)),group=group)
        self.revealer=g.gtk_revealer_new();g.gtk_revealer_set_transition_duration(self.revealer,0 if page.store.preference('motion','full')=='off' else 140)
        self.details=style(g,g.gtk_box_new(1,10),'filter-card-details');g.gtk_container_add(self.revealer,self.details);g.gtk_box_pack_start(self.box,self.revealer,0,1,0)
        self.summary(rule)
        self.account_rows={}
        self.routes=bind(page.app,'gtk','gtk_grid_new',P)();bind(page.app,'gtk','gtk_grid_set_column_spacing',None,P,I)(self.routes,9);bind(page.app,'gtk','gtk_grid_set_row_spacing',None,P,I)(self.routes,4)
        g.gtk_box_pack_start(self.details,self.routes,0,1,0)
        for account,target in rule['destinations'].items():self.account_row(account,target,names.get(account,account),colors.get(account,'#98a4b5'))
        self.apply_expansion()
        g.connect(self.expand,'clicked',lambda *unused:self.toggle_details(),group=group)
        g.connect(self.switch,'notify::active',lambda *unused:page.app.run_action(lambda:page.toggle(identity,self.switch)),count=3,group=group)

    # ==========================================
    # Function: Display compact logic, source scope and matching-condition chips.
    # Method: Wrap conditions in a native flow layout so long saved values do not widen the Settings window.
    # ==========================================
    def summary(self,rule):
        g=self.g;line=g.gtk_box_new(0,8);g.gtk_box_pack_start(self.details,line,0,1,0)
        logic=('∩ 全部匹配' if rule['mode']=='all' else '∪ 任一匹配')+' · '+str(len(rule['conditions']))+' 条'
        g.gtk_box_pack_start(line,chip(g,logic,'settings-filters','filter-logic'),0,0,0)
        scope={'all':'所有文件夹','include':'选定文件夹','exclude':'排除选定文件夹'}[rule['source_mode']]
        if rule['subfolders'] and rule['source_mode']!='all':scope+=' · 含子文件夹'
        g.gtk_box_pack_start(line,chip(g,scope,'spark-layout-folder'),0,0,0)
        flow=g.gtk_flow_box_new();g.gtk_flow_box_set_selection_mode(flow,0);g.gtk_flow_box_set_min_children_per_line(flow,1);g.gtk_flow_box_set_max_children_per_line(flow,3)
        g.gtk_flow_box_set_column_spacing(flow,6);g.gtk_flow_box_set_row_spacing(flow,6);style(g,flow,'filter-conditions')
        g.gtk_box_pack_start(self.details,flow,0,1,0)
        for condition in rule['conditions']:g.gtk_container_add(flow,chip(g,condition_text(condition),'','filter-condition',35))

    # ==========================================
    # Function: Draw one account's source-to-target path on its own row.
    # Method: Align account, source, arrow and target in shared grid columns; retain full paths on hover.
    # ==========================================
    def account_row(self,account,target,name,color):
        g=self.g;rule=self.rule;index=len(self.account_rows)
        identity=style(g,g.gtk_box_new(0,7),'filter-account-row');self.account_rows[account]=identity
        dot=label(g,'●','filter-account-dot');g.gtk_label_set_markup(dot,('<span foreground="'+escape(color,quote=True)+'">●</span>').encode())
        g.gtk_box_pack_start(identity,dot,0,0,0);g.gtk_box_pack_start(identity,label(g,name,'filter-account-name',30),1,1,0)
        g.gtk_widget_set_size_request(identity,170,32);g.gtk_widget_set_hexpand(identity,1)
        paths=rule['sources'].get(account,[])
        source='全部文件夹' if rule['source_mode']=='all' or (rule['source_mode']=='exclude' and not paths) else ('排除 ' if rule['source_mode']=='exclude' else '')+('、'.join(paths) or '无匹配来源')
        if rule['subfolders'] and rule['source_mode']!='all':source+=' / …'
        source_widget=chip(g,source,'spark-layout-folder','filter-source',22);target_widget=chip(g,target,'spark-layout-folder','filter-target',28)
        attach=bind(self.page.app,'gtk','gtk_grid_attach',None,P,P,I,I,I,I)
        for column,widget in enumerate((identity,source_widget,label(g,'→','filter-route-arrow'),target_widget)):
            g.gtk_widget_set_valign(widget,3);attach(self.routes,widget,column,index,1,1)

    # ==========================================
    # Function: Apply retained disclosure state without changing rule enablement or running filters.
    # Method: Use equal-size mirrored SVGs in a fixed centered image so glyph baselines cannot shift the arrow.
    # ==========================================
    def apply_expansion(self):
        opened=self.rule['id'] in self.page.expanded;g=self.g
        g.gtk_revealer_set_reveal_child(self.revealer,int(opened))
        bind(self.page.app,'gtk','gtk_image_set_from_file',None,P,C.c_char_p)(self.arrow,str(ICONS/('filter-chevron-up.svg' if opened else 'filter-chevron-down.svg')).encode())
        g.gtk_widget_set_tooltip_text(self.expand,(('收起' if opened else '展开')+'过滤器：'+self.rule['name']).encode())
        context=g.gtk_widget_get_style_context(self.box)
        (g.gtk_style_context_add_class if opened else g.gtk_style_context_remove_class)(context,b'filter-expanded')

    # ==========================================
    # Function: Toggle only this card's details from a native keyboard or pointer click.
    # Method: Store disclosure locally to this Settings session so navigation and asynchronous saves preserve it.
    # ==========================================
    def toggle_details(self):
        identity=self.rule['id']
        if identity in self.page.expanded:self.page.expanded.remove(identity)
        else:self.page.expanded.add(identity)
        self.apply_expansion()
