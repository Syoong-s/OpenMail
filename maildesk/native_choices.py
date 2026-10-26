"""Compact native choice chips backed by existing GtkComboBoxText controllers."""
import ctypes as C
from pathlib import Path

ICONS=Path(__file__).parent/'desktop_assets/icons'
DESCRIPTIONS={
    'reply_window_size':{'compact':'在邮件下方继续对话','full':'使用完整编辑空间'},
    'layout_mode':{'fullScreen':'专注查看当前列表或邮件','splitView':'同时显示列表和邮件内容','switchInsideInbox':'在当前收件箱中切换阅读'},
    'theme':{'dark':'深色背景与柔和对比','light':'明亮的阅读和设置界面','system':'与系统的外观保持一致'},
    'gatekeeper_mode':{'explicit':'先审阅新发件人，再接收邮件','inThread':'在来信中决定是否接受','off':'直接接收所有发件人'},
    'inbox_mode_setting':{'focused':'按优先程度和类别整理','smart':'优先处理未读邮件','classic':'按时间顺序查看所有邮件'}}

# ==========================================
# Function: Match the public GtkTreeIter layout used by combo text models.
# Method: Use native integer/pointer alignment without inspecting private model structures.
# ==========================================
class TreeIter(C.Structure):
    _fields_=[('stamp',C.c_int),('data',C.c_void_p),('data2',C.c_void_p),('data3',C.c_void_p)]

# ==========================================
# Function: Present a compact dropdown while retaining the original value/changed API.
# Method: Hide the real combo and mirror its model into a broker-owned rounded choice menu.
# ==========================================
class NativeChoice:
    # ==========================================
    # Function: Replace one visible combo in a native box with a trailing choice chip.
    # Method: Preserve its position, packing and actual controller reference until chip destruction.
    # ==========================================
    def __init__(self,g,combo,title='',key=''):
        self.g=g;self.combo=combo;self.title=title;self.key=key;self.group='choice-'+str(combo);self.closed=False
        parent=g.gtk_widget_get_parent(combo)
        if not parent:raise ValueError('下拉选项缺少所属行')
        children=g.gtk_container_get_children(parent);cursor=children;position=0
        while cursor and cursor.contents.data!=combo:position+=1;cursor=cursor.contents.next
        g.g_list_free(children);expand,fill,padding,pack=C.c_int(),C.c_int(),C.c_uint(),C.c_int();g.gtk_box_query_child_packing(parent,combo,C.byref(expand),C.byref(fill),C.byref(padding),C.byref(pack))
        g.g_object_ref(combo);g.gtk_container_remove(parent,combo);g.gtk_widget_set_no_show_all(combo,1);g.surfaces.orig['gtk_widget_hide'](combo)
        self.button=g.gtk_menu_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'choice-chip');g.gtk_widget_set_halign(self.button,2);g.gtk_widget_set_valign(self.button,3)
        line=g.gtk_box_new(0,7);g.gtk_container_add(self.button,line);self.label=g.gtk_label_new(b'');g.gtk_label_set_ellipsize(self.label,3);g.gtk_label_set_max_width_chars(self.label,28);g.gtk_box_pack_start(line,self.label,1,1,0);g.gtk_box_pack_start(line,g.image_file(ICONS/'action-down.svg',12),0,0,0)
        g.gtk_box_pack_start(parent,self.button,expand.value,fill.value,padding.value);g.gtk_box_reorder_child(parent,self.button,position);g.surfaces.choice_proxies[combo]=self.button
        self.popup=g.gtk_popover_new(self.button);self.menu=g.gtk_box_new(1,2);g.gtk_container_set_border_width(self.menu,5);g.gtk_container_add(self.popup,self.menu);g.gtk_menu_button_set_popover(self.button,self.popup)
        g.connect(combo,'changed',lambda *unused:self.sync(),group=self.group);g.connect(self.button,'toggled',lambda *unused:self.fill() if g.gtk_toggle_button_get_active(self.button) else None,group=self.group);g.connect(self.button,'destroy',lambda *unused:self.close(),group=self.group)
        self.sync()

    # ==========================================
    # Function: Read the actual current GtkComboBoxText model, including dynamically appended options.
    # Method: Traverse public tree iterators and free GTK-allocated text/id projections.
    # ==========================================
    def items(self):
        g=self.g;model=g.gtk_combo_box_get_model(self.combo);iterator=TreeIter();rows=[]
        if not model:return rows
        valid=g.gtk_tree_model_get_iter_first(model,C.byref(iterator));function=g.libs['gtk'].gtk_tree_model_get
        getter=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_int,C.POINTER(C.c_void_p),C.c_int,C.POINTER(C.c_void_p),C.c_int)(C.cast(function,C.c_void_p).value)
        while valid:
            text,identity=C.c_void_p(),C.c_void_p();getter(model,C.byref(iterator),0,C.byref(text),1,C.byref(identity),-1)
            try:rows.append(((C.string_at(identity).decode() if identity.value else str(len(rows))),(C.string_at(text).decode() if text.value else '')))
            finally:
                if text.value:g.g_free(text)
                if identity.value:g.g_free(identity)
            valid=g.gtk_tree_model_iter_next(model,C.byref(iterator))
        return rows

    # ==========================================
    # Function: Keep the chip synchronized with programmatic native value changes.
    # Method: Resolve the active ID from the original controller without maintaining duplicate values.
    # ==========================================
    def sync(self):
        if self.closed:return
        identity=(self.g.gtk_combo_box_get_active_id(self.combo) or b'').decode();caption=next((text for key,text in self.items() if key==identity),'请选择')
        self.g.gtk_label_set_text(self.label,caption.encode());self.g.gtk_widget_set_tooltip_text(self.button,((self.title+' · ') if self.title else '') .encode()+caption.encode())
        self.g.surfaces.orig['gtk_widget_set_sensitive'](self.button,self.g.gtk_widget_get_sensitive(self.combo))

    # ==========================================
    # Function: Render current choices as rounded rows with descriptions and a selected checkmark.
    # Method: Rebuild only the open menu and retain stable native controller IDs.
    # ==========================================
    def fill(self):
        if self.closed:return
        g=self.g;g.surfaces.retire(self.group+'-options');g.clear(self.menu);selected=(g.gtk_combo_box_get_active_id(self.combo) or b'').decode();focus=None
        for identity,title in self.items():
            button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'choice-option');line=g.gtk_box_new(0,18);g.gtk_container_add(button,line);labels=g.gtk_box_new(1,3);g.gtk_box_pack_start(line,labels,1,1,0)
            label=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,36);g.gtk_box_pack_start(labels,label,0,1,0)
            description=DESCRIPTIONS.get(self.key,{}).get(identity)
            if description:
                detail=g.gtk_label_new(description.encode());g.gtk_label_set_xalign(detail,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(detail),b'choice-description');g.gtk_box_pack_start(labels,detail,0,1,0)
            check=g.gtk_label_new(('✓' if selected==identity else '').encode());g.gtk_widget_set_size_request(check,16,-1);g.gtk_box_pack_start(line,check,0,0,0)
            g.connect(button,'clicked',lambda *unused,value=identity:self.select(value),group=self.group+'-options');g.gtk_box_pack_start(self.menu,button,0,1,0)
            if selected==identity:focus=button
        g.gtk_widget_show_all(self.menu)
        if focus:g.gtk_widget_grab_focus(focus)
        state=g.surfaces.states.get(self.popup)
        if state:g.surfaces.position(state)

    # ==========================================
    # Function: Select one real controller option after dismissing its menu branch.
    # Method: Use the original native changed signal so existing validation/render handlers still run.
    # ==========================================
    def select(self,identity):
        self.g.gtk_popover_popdown(self.popup);self.g.gtk_combo_box_set_active_id(self.combo,identity.encode());self.sync()

    # ==========================================
    # Function: Release mirrored control state when its visible chip is destroyed.
    # Method: Remove dispatch mappings first, then retire callbacks and drop the held controller reference.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True;self.g.surfaces.choice_proxies.pop(self.combo,None);self.g.surfaces.retire(self.group+'-options');self.g.surfaces.retire(self.group);self.g.g_object_unref(self.combo)
