"""Local UI translations, deliberately separate from mailbox and user-authored text."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

LANGUAGES={'zh_CN':'简体中文','en':'English'}
_language='zh_CN'
_catalog=None


# ==========================================
# Function: Select an installed interface language without changing any stored mail or names.
# Method: Keep the language process-local; a saved settings change takes effect on the next launch.
# ==========================================
def set_language(value):
    global _language
    _language=value if isinstance(value,str) and value in LANGUAGES else 'zh_CN'
    return _language


# ==========================================
# Function: Expose the current UI language to native and embedded document controls.
# Method: Return a stable language code independent of translated captions.
# ==========================================
def language():return _language


# ==========================================
# Function: Format calendar captions independently of the operating system's date language.
# Method: Use explicit English month names while preserving numeric Chinese civil dates.
# ==========================================
def date_label(day,short=False):
    if _language=='zh_CN':return day.strftime('%m月%d日' if short else '%Y年%m月%d日')
    month=('January','February','March','April','May','June','July','August','September','October','November','December')[day.month-1]
    return (month[:3]+' '+str(day.day)) if short else month+' '+str(day.day)+', '+str(day.year)


# ==========================================
# Function: Localize month labels without depending on Windows regional settings.
# Method: Use the same explicit month names as the main date heading.
# ==========================================
def month_label(day):return date_label(day,True).split()[0] if _language=='en' else str(day.month)+'月'


# ==========================================
# Function: Match native calendar month and weekday names to the application language.
# Method: Configure only the Windows UI thread locale or Linux LC_TIME after GTK initialization, without changing system settings or timezone.
# ==========================================
def native_calendar_language():
    if os.name=='nt':
        import ctypes as C
        setter=C.WinDLL('kernel32',use_last_error=True).SetThreadLocale
        setter.argtypes=[C.c_uint32];setter.restype=C.c_int
        if not setter(0x0409 if _language=='en' else 0x0804):raise C.WinError(C.get_last_error())
    elif _language=='en':
        import locale
        locale.setlocale(locale.LC_TIME,'C')


# ==========================================
# Function: Load language before any GTK builders or startup dialogs are created.
# Method: Read only the existing local preference, with an explicit environment override for isolated QA.
# ==========================================
def configure(data):
    chosen='zh_CN';path=Path(data)/'mail.sqlite3'
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                row=db.execute("SELECT value FROM preferences WHERE key='interface_language'").fetchone()
                if row:chosen=json.loads(row[0])
        except (sqlite3.Error,ValueError,TypeError):pass
    return set_language(os.environ.get('TELEMAIL_LANGUAGE',chosen))


# ==========================================
# Function: Translate a known application-owned message using a bundled offline catalog.
# Method: Exact-key lookup avoids translating arbitrary mail contents or dynamic user names.
# ==========================================
def translate(source):
    global _catalog
    source=str.__str__(source) if isinstance(source,str) else str(source)
    if _language=='zh_CN':return source
    if _catalog is None:_catalog=json.loads((Path(__file__).parent/'locales/en.json').read_text(encoding='utf-8'))
    return _catalog.get(source,source)


# ==========================================
# Function: Render application-owned explanations retained in older local databases.
# Method: Translate known system messages and the classifier's explicit template, leaving rule values untouched.
# ==========================================
def system_message(source):
    import re
    translated=translate(source)
    if _language=='en' and translated==source:
        match=re.fullmatch(r'命中自定义规则：(.*?) 包含 (.*)',source,re.S)
        if match:return 'Custom rule matched: '+match[1]+' contains '+match[2]
    return translated


# ==========================================
# Function: Mark application text while retaining its original identity in stored settings and lookups.
# Method: Resolve global captions lazily at presentation; ordinary unmarked user strings are never translated.
# ==========================================
class Text(str):
    # ==========================================
    # Function: Render a marked caption in the selected language.
    # Method: Materialize translations only when presentation code requests a string.
    # ==========================================
    def __str__(self):return translate(self)

    # ==========================================
    # Function: Pass localized text to UTF-8 native widget setters.
    # Method: Preserve the normal str.encode signature for existing ctypes callers.
    # ==========================================
    def encode(self,encoding='utf-8',errors='strict'):return str(self).encode(encoding,errors)

    # ==========================================
    # Function: Interpolate localized captions without translating the supplied user data.
    # Method: Apply Python's usual formatting to the translated template.
    # ==========================================
    def format(self,*args,**kwargs):return str(self).format(*args,**kwargs)

    # ==========================================
    # Function: Preserve formatting flags when a caption appears inside another template.
    # Method: Delegate to the materialized language string.
    # ==========================================
    def __format__(self,spec):return format(str(self),spec)

    # ==========================================
    # Function: Combine interface fragments with untouched runtime data.
    # Method: Resolve only explicitly marked fragments during concatenation.
    # ==========================================
    def __add__(self,other):return str(self)+str(other)

    # ==========================================
    # Function: Append a localized suffix to counts or other runtime text.
    # Method: Preserve the left operand and resolve this marked fragment.
    # ==========================================
    def __radd__(self,other):return str(other)+str(self)

    # ==========================================
    # Function: Support legacy percent-format UI strings.
    # Method: Format the translated template with unchanged runtime arguments.
    # ==========================================
    def __mod__(self,other):return str(self)%other

    # ==========================================
    # Function: Escape marked captions correctly when building XML or HTML.
    # Method: Materialize first so standard escape helpers operate on the selected language.
    # ==========================================
    def replace(self,old,new,count=-1):return str(self).replace(old,new,count)


# ==========================================
# Function: Mark one literal as interface text for extraction and runtime rendering.
# Method: Keep source-language value semantics and avoid double wrapping marked strings.
# ==========================================
def text(source):return source if isinstance(source,Text) else Text(source)


# ==========================================
# Function: Join mixed localized captions and user values without losing lazy translations.
# Method: Materialize marked elements explicitly instead of CPython's raw str-subclass join path.
# ==========================================
def join_text(separator,values):return str(separator).join(str(value) for value in values)


# ==========================================
# Function: Translate fixed GtkBuilder captions while preserving IDs and editable field values.
# Method: Limit exact-key lookup to presentation properties and combo captions; never translate entry text or model IDs.
# ==========================================
def builder_xml(source):
    if _language=='zh_CN':return source
    root=ET.fromstring(source)
    for node in root.iter():
        if node.get('translatable')=='no':continue
        if node.tag=='property' and node.get('name') in ('label','title','tooltip-text','placeholder-text') or node.tag=='item':
            if node.text:node.text=translate(node.text)
    return ET.tostring(root,encoding='unicode')


# ==========================================
# Function: Localize only TeleMail-owned PDF viewer chrome, never document bytes or vendor code.
# Method: Replace known HTML text and JavaScript string literals using the same offline catalog.
# ==========================================
def pdf_resource(name,data):
    import html
    source=data.decode('utf-8')
    keys=('PDF 阅读器加载失败，请检查应用文件是否完整','PDF 页面渲染失败','密码不正确，请重试',
          'PDF 无法读取，请确认文件完整且格式有效','PDF 阅读器加载失败','PDF 文档','正在加载 PDF…','此 PDF 需要密码 ','打开')
    for key in keys:
        if name.endswith('.html'):source=source.replace(key,html.escape(translate(key)))
        else:source=source.replace(json.dumps(key,ensure_ascii=False),json.dumps(translate(key),ensure_ascii=False))
    return source.replace('lang="zh-CN"','lang="en"').encode('utf-8')
