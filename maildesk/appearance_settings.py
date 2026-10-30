"""Staged palette/opacity editing inside the single settings workspace."""
import ctypes as C
from .appearance_theme import PRESETS,ROLES,LABELS,palette,preferences,apply
from .message_style import BUBBLE_KEYS,BUBBLE_LABELS,BUBBLE_DEFAULTS,bubble_colors
from .ui_typography import FONT_SIZES,DEFAULT_FONT_SIZE,font_size

FIELDS=[('appearance_scheme','界面配色','combo',[('original','沿用当前主题')]+[(key,value[0]) for key,value in PRESETS.items()]+[('custom','自定义')]),('appearance_contrast','对比度（%）','range',(70,150,5)),('attachment_auto_expand','打开附件时自动扩宽窗口（关闭附件栏时还原）','switch',[]),('attachment_open_width','打开附件时增加的宽度（逻辑像素）','range',(280,2000,20)),('panel_opacity','面板背景不透明度（%）','range',(20,100,1)),('window_opacity','整个窗口不透明度（含文字，%）','range',(50,100,1))]+[('color_'+role,LABELS[role],'color',[]) for role in ROLES]+[(key,label,'color',[]) for key,label in zip(BUBBLE_KEYS,BUBBLE_LABELS)]
FIELDS.insert(0,('ui_font_size','界面字号','combo',[(str(size),str(size)+' px'+('（默认）' if size==DEFAULT_FONT_SIZE else '')) for size in FONT_SIZES]))
KEYS=[field[0] for field in FIELDS]

# ==========================================
# Function: Preview typography and palette edits without writing durable settings until Save.
# Method: Coalesce native field changes and restore the persisted appearance on cancellation/close.
# ==========================================
class AppearanceSettings:
    # ==========================================
    # Function: Populate all theme controls before binding change observers.
    # Method: Resolve saved scheme roles consistently and retain one callback/timer per form.
    # ==========================================
    def __init__(self,app,form):
        self.app,self.form,self.g=app,form,app.g;self.timer=0;self.updating=False;self.closed=False
        for key,value in preferences(app.service.store).items():form.value(key,value)
        self.callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.preview)
        for key in KEYS:
            widget,kind=form.fields[key];signal='value-changed' if kind=='range' else 'notify::active' if kind=='switch' else 'changed';self.g.connect(widget,signal,lambda *unused,name=key:self.changed(name),group=form.group,count=3 if kind=='switch' else 2)

    # ==========================================
    # Function: Collect actual staged native values for preview and validated Save.
    # Method: Normalize the selected font size and validate RGB values before Save or preview.
    # ==========================================
    def values(self):
        result={key:self.form.value(key) for key in KEYS};result['ui_font_size']=font_size(result['ui_font_size']);palette(result);bubble_colors(result);return result

    # ==========================================
    # Function: Apply preset roles or recognize manual RGB edits as custom.
    # Method: Guard programmatic changes and debounce one preview until color edits or dragging settle.
    # ==========================================
    def changed(self,key):
        if self.updating or self.closed:return
        self.updating=True
        try:
            scheme=self.form.value('appearance_scheme')
            if key=='appearance_scheme' and scheme in PRESETS:
                self.form.value('theme','light' if scheme=='paper' else 'dark')
                for role,value in zip(ROLES,PRESETS[scheme][1]):self.form.value('color_'+role,value)
            elif key.startswith('color_') and scheme!='custom':self.form.value('appearance_scheme','custom')
        finally:self.updating=False
        if self.timer:self.g.g_source_remove(self.timer)
        self.timer=self.g.g_timeout_add(180,C.cast(self.callback,C.c_void_p),None)

    # ==========================================
    # Function: Paint a bounded preview while the form remains alive.
    # Method: Ignore incomplete color tokens without mutating saved preferences.
    # ==========================================
    def preview(self,unused=None):
        self.timer=0
        if self.closed or self.form.closed or self.app.closing:return 0
        controls=list(self.form.ranges.values())+[control for color in self.form.colors for control in [color.hue_range,*color.ranges]]
        if any(control.dragging for control in controls):
            self.timer=self.g.g_timeout_add(100,C.cast(self.callback,C.c_void_p),None);return 0
        try:apply(self.app,self.values());self.g.label(self.form.note,'外观预览中 · 保存后永久生效；取消将恢复。面板透明度只影响背景，窗口透明度同时影响文字。')
        except ValueError as error:self.g.label(self.form.note,str(error))
        return 0

    # ==========================================
    # Function: Restore the baseline native appearance through the same staged controls.
    # Method: Keep account colors and unrelated settings untouched.
    # ==========================================
    def reset(self):
        self.updating=True
        try:
            self.form.value('ui_font_size',DEFAULT_FONT_SIZE)
            self.form.value('appearance_scheme','original');self.form.value('appearance_contrast',110);self.form.value('attachment_open_width',700);self.form.value('attachment_auto_expand',True);self.form.value('panel_opacity',100);self.form.value('window_opacity',100)
            for role,value in zip(ROLES,PRESETS['codex'][1]):self.form.value('color_'+role,value)
            from .desktop_preferences import resolved_theme
            for key,value in zip(BUBBLE_KEYS,BUBBLE_DEFAULTS[resolved_theme(self.app)]):self.form.value(key,value)
        finally:self.updating=False
        self.changed('appearance_scheme')

    # ==========================================
    # Function: Persist only the already validated selected appearance.
    # Method: Reuse local preference storage and avoid any system theme changes.
    # ==========================================
    def save(self):
        for key,value in self.values().items():self.app.service.store.set_preference(key,value)

    # ==========================================
    # Function: End the staged preview regardless of Save or Cancel.
    # Method: Remove its timer before reapplying the latest durable appearance.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True
        if self.timer:self.g.g_source_remove(self.timer);self.timer=0
        if not self.app.closing:apply(self.app)
