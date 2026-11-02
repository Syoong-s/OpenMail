"""UI catalog completeness, durable language preference and user-content boundaries."""
import ast
import json
from pathlib import Path
from string import Formatter
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from maildesk import i18n
from maildesk.store import Store

ROOT=Path(__file__).resolve().parents[1]


# ==========================================
# Function: Exercise localization without a display or access to a real mailbox.
# Method: Use the real catalog, source extraction and temporary SQLite preferences.
# ==========================================
class LocalizationTests(TestCase):
    # ==========================================
    # Function: Isolate process-global locale state across unrelated tests.
    # Method: Restore the original language even after assertion failures.
    # ==========================================
    def setUp(self):
        current=i18n.language();self.addCleanup(i18n.set_language,current);i18n.set_language('en')

    # ==========================================
    # Function: Preserve user-authored content and canonical identifiers while localizing marked UI captions.
    # Method: Verify native UTF-8 presentation, concatenation, formatting, equality and JSON persistence separately.
    # ==========================================
    def test_ui_text_does_not_translate_user_content_or_ids(self):
        caption=i18n.text('收件箱');subject='收件箱';name='已完成'
        self.assertEqual(str(caption),'Inbox');self.assertEqual(caption.encode(),b'Inbox')
        self.assertEqual(subject.encode(),'收件箱'.encode());self.assertEqual(str(name),'已完成')
        self.assertEqual(caption,'收件箱');self.assertEqual({caption:1}['收件箱'],1)
        self.assertEqual(json.loads(json.dumps({'name':caption},ensure_ascii=False))['name'],'收件箱')
        self.assertEqual(i18n.join_text(' · ',[caption,subject]),'Inbox · 收件箱')
        self.assertEqual(i18n.text('已处理 {0} 封邮件').format(3),'Processed 3 messages')
        i18n.set_language('zh_CN');self.assertEqual(str(caption),'收件箱')

    # ==========================================
    # Function: Translate authored builder captions without modifying IDs or editable defaults.
    # Method: Pass a deliberately identical caption and user-entry value through the actual XML localization path.
    # ==========================================
    def test_builder_protects_user_fields(self):
        import xml.etree.ElementTree as ET
        source='<interface><object class="GtkEntry" id="收件箱"><property name="text">收件箱</property><property name="placeholder-text">收件箱</property></object><object class="GtkLabel"><property name="label">收件箱</property></object></interface>'
        root=ET.fromstring(i18n.builder_xml(source));entry=root[0]
        self.assertEqual(entry.get('id'),'收件箱');self.assertEqual(entry.find("property[@name='text']").text,'收件箱')
        self.assertEqual(entry.find("property[@name='placeholder-text']").text,'Inbox');self.assertEqual(root[1][0].text,'Inbox')

    # ==========================================
    # Function: Keep custom mailbox and account names intact in generated choice controls.
    # Method: Exercise the production form/composer builders with names that also exist in the UI catalog.
    # ==========================================
    def test_dynamic_choice_names_remain_user_content(self):
        import xml.etree.ElementTree as ET
        from maildesk.desktop_forms import form_xml
        from maildesk.composer_layout import composer_xml
        source=form_xml([('account',i18n.text('发件账户'),'combo',[('mine','收件箱'),('default',i18n.text('默认'))])])
        root=ET.fromstring(i18n.builder_xml(source))
        self.assertEqual(root.find(".//item[@id='mine']").text,'收件箱')
        self.assertEqual(root.find(".//item[@id='default']").text,'Default')
        root=ET.fromstring(i18n.builder_xml(composer_xml([('mine','收件箱')])))
        self.assertEqual(root.find(".//item[@id='mine']").text,'收件箱')

    # ==========================================
    # Function: Keep the English calendar independent of the host's regional language.
    # Method: Check exact English and Chinese dates without setting any system locale.
    # ==========================================
    def test_calendar_uses_interface_language(self):
        from datetime import date
        day=date(2026,11,2)
        self.assertEqual(i18n.date_label(day),'November 2, 2026');self.assertEqual(i18n.month_label(day),'Nov')
        i18n.set_language('zh_CN');self.assertEqual(i18n.date_label(day),'2026年11月02日');self.assertEqual(i18n.month_label(day),'11月')

    # ==========================================
    # Function: Preserve multilingual classifier inputs and old saved explanations across language changes.
    # Method: Recognize a Chinese invoice in English mode and translate only the generated explanation/template.
    # ==========================================
    def test_recognition_and_persisted_system_messages(self):
        from maildesk.filter_smart import recognize
        result=recognize({'category':'personal','sender':'billing@example.invalid','subject':'十一月电子账单','body':'','headers':{}})
        self.assertIn('invoice',result)
        self.assertEqual(i18n.system_message('命中自定义规则：subject 包含 收件箱'),'Custom rule matched: subject contains 收件箱')
        self.assertEqual(i18n.system_message('未发现批量订阅或自动通知特征'),'No bulk mailing or automated notification indicators found')

    # ==========================================
    # Function: Load only saved supported language codes before creating any widgets.
    # Method: Persist to an isolated store, reopen the readonly startup path and check invalid/missing fallbacks.
    # ==========================================
    def test_saved_language_and_fallback(self):
        with TemporaryDirectory() as folder,patch.dict('os.environ',{},clear=True):
            self.assertEqual(i18n.configure(folder),'zh_CN');store=Store(Path(folder)/'mail.sqlite3')
            store.set_preference('interface_language','en');self.assertEqual(i18n.configure(folder),'en')
            store.set_preference('interface_language','unsupported');self.assertEqual(i18n.configure(folder),'zh_CN')

    # ==========================================
    # Function: Prevent incomplete catalogs and broken format placeholders from shipping.
    # Method: Extract every marked Python literal and authored builder caption, then compare formatter contracts.
    # ==========================================
    def test_catalog_covers_source_and_preserves_placeholders(self):
        import re
        import xml.etree.ElementTree as ET
        catalog=json.loads((ROOT/'maildesk/locales/en.json').read_text());required=set()
        for path in (ROOT/'maildesk').glob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_tr' and node.args and isinstance(node.args[0],ast.Constant):required.add(node.args[0].value)
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    required.update(value for key,value in re.findall(r'<property name="(label|title|tooltip-text|placeholder-text)">([^<]*)</property>',node.value) if re.search('[\u4e00-\u9fff]',value))
        for node in ET.parse(ROOT/'maildesk/desktop_assets/main.ui').getroot().iter():
            if node.tag=='property' and node.get('name') in ('label','title','tooltip-text','placeholder-text') or node.tag=='item':
                if node.text and re.search('[\u4e00-\u9fff]',node.text):required.add(node.text)
        self.assertFalse(required-catalog.keys(),sorted(required-catalog.keys()))
        formatter=Formatter()
        for key,value in catalog.items():
            self.assertIsInstance(value,str)
            self.assertFalse(re.search('[\u4e00-\u9fff]',value),key)
            if re.search(r'\{\d+(?:[!:}]|$)',key):
                fields=lambda text:sorted((name,format_spec,conversion) for literal,name,format_spec,conversion in formatter.parse(text) if name is not None)
                self.assertEqual(fields(key),fields(value),key)

    # ==========================================
    # Function: Localize the embedded PDF chrome without touching PDF data or vendor modules.
    # Method: Verify real HTML and JavaScript assets against the English catalog and document language.
    # ==========================================
    def test_pdf_viewer_uses_same_language(self):
        import re
        for name in ('viewer.html','viewer.mjs','bootstrap.mjs'):
            data=(ROOT/'maildesk/desktop_assets/pdfjs'/name).read_bytes();translated=i18n.pdf_resource(name,data).decode()
            self.assertFalse(re.search('[\u4e00-\u9fff]',translated),name)
            if name=='viewer.html':self.assertIn('lang="en"',translated);self.assertIn('requires a password',translated)

    # ==========================================
    # Function: Translate built-in view names across restart without changing a custom view's name.
    # Method: Exercise saved definitions and compare both presentation and raw JSON values.
    # ==========================================
    def test_saved_builtin_titles_and_custom_names(self):
        from maildesk.inbox_views import InboxViews
        with TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.sqlite3');views=InboxViews(store)
            self.assertEqual(str(views.active()['name']),'Focused')
            custom=views.definition('focused','收件箱');views.save(custom)
            self.assertEqual(str(next(row for row in views.all() if row['id']==custom['id'])['name']),'收件箱')
            self.assertEqual(store.preference('inbox_views')[0]['name'],'聚焦列表')
