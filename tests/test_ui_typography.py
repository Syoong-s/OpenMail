"""Font-only appearance preferences without display or mailbox dependencies."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from maildesk.appearance_settings import AppearanceSettings,FIELDS
from maildesk.appearance_theme import apply,preferences,stylesheet
from maildesk.store import Store
from maildesk.ui_typography import font_stylesheet

# ==========================================
# Function: Protect interface typography from changing layout geometry or saved settings during preview.
# Method: Exercise real preference persistence and the production appearance lifecycle with a native API double.
# ==========================================
class TypographyTests(unittest.TestCase):
    # ==========================================
    # Function: Keep borders, padding and control dimensions independent of UI font choices.
    # Method: Compare trusted style declarations including fractional font sizes and inherited text.
    # ==========================================
    def test_only_font_declarations_change(self):
        source='label { font-size: 12px; padding: 8px 4px; min-width: 72px; border: 1px solid #fff; } .small { font-size: 11.5px; }'
        result=font_stylesheet(source,16)
        self.assertIn('font-size: 12pt;',result)
        self.assertIn('font-size: 11.5pt;',result)
        self.assertEqual(result.replace('font-size: 12pt','font-size: 12px').replace('font-size: 11.5pt','font-size: 11.5px'),source)

    # ==========================================
    # Function: Restore a saved font choice and ignore the abandoned zoom preference.
    # Method: Reopen SQLite preferences and recover malformed or unsupported imported sizes.
    # ==========================================
    def test_persistence_and_old_zoom_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'mail.db';store=Store(path);store.set_preference('ui_scale',200)
            self.assertEqual(preferences(store)['ui_font_size'],14)
            self.assertNotIn('ui_scale',preferences(store))
            store.set_preference('ui_font_size','18')
            self.assertEqual(preferences(Store(path))['ui_font_size'],18)
            for value in ('invalid',None,-5,999,13):
                store.set_preference('ui_font_size',value)
                self.assertEqual(preferences(store)['ui_font_size'],14)

    # ==========================================
    # Function: Preserve palette-derived text sizing under the same font-only policy.
    # Method: Generate real theme CSS and check typography conversion leaves border widths intact.
    # ==========================================
    def test_palette_font_rules_follow_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            css=font_stylesheet(stylesheet(preferences(Store(Path(folder)/'mail.db'))),20)
            self.assertIn('font-size: 11.25pt;',css)
            self.assertIn('border: 1px solid',css)
            self.assertNotIn('font-size: 9px;',css)

    # ==========================================
    # Function: Restore cancelled font previews and reuse providers during repeated changes.
    # Method: Run the actual settings close/save methods around durable baseline preferences.
    # ==========================================
    def test_preview_cancel_save_and_provider_reuse(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.db');g=Mock(surfaces=None)
            g.gtk_css_provider_new.side_effect=[11,12]
            app=SimpleNamespace(g=g,service=SimpleNamespace(store=store),window=1,closing=False)
            editor=AppearanceSettings.__new__(AppearanceSettings)
            editor.app=app;editor.g=g;editor.closed=False;editor.timer=0
            baseline=preferences(store);editor.values=lambda:{**baseline,'ui_font_size':18}
            apply(app,editor.values());provider=app.ui_font_provider
            self.assertEqual(store.preference('ui_font_size',14),14)
            apply(app,{**baseline,'ui_font_size':20});editor.close()
            self.assertEqual(app.ui_font_size,14)
            self.assertEqual(app.ui_font_provider,provider)
            self.assertEqual(g.gtk_style_context_add_provider_for_screen.call_count,2)
            editor.closed=False;editor.save();apply(app)
            self.assertEqual(app.ui_font_size,18)
            self.assertEqual(preferences(Store(store.path))['ui_font_size'],18)

    # ==========================================
    # Function: Restore the readable default through the existing Reset Appearance action.
    # Method: Keep real form values while suppressing only the asynchronous preview scheduling.
    # ==========================================
    def test_reset_restores_font_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'mail.db');values=preferences(store);values['ui_font_size']=20
            editor=AppearanceSettings.__new__(AppearanceSettings)
            editor.app=SimpleNamespace(service=SimpleNamespace(store=store));editor.form=Mock();editor.changed=Mock()
            # ==========================================
            # Function: Read or stage one native-form preference without a display.
            # Method: Mirror only Form.value's public getter/setter contract.
            # ==========================================
            def value(key,chosen=None):
                if chosen is not None:values[key]=chosen
                return values[key]
            editor.form.value.side_effect=value;editor.reset()
            self.assertEqual(values['ui_font_size'],14)
            self.assertIn('ui_font_size',[field[0] for field in FIELDS])
            self.assertNotIn('ui_scale',[field[0] for field in FIELDS])

if __name__=='__main__':unittest.main()
