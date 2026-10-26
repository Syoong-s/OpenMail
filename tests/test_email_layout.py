"""Inert email layout, authored CSS and neutral-palette regressions without any provider access."""
import unittest
from maildesk.document_content import reader_document
from maildesk.email_styles import adapt_css

FACEBOOK_LAYOUT='''<html><head><style>@media all and (max-width:480px){.row > .cell{display:block!important}}
.hidden{display:none}.rounded{border-radius:8px}#recommendation > table{margin:0}</style></head>
<body bgcolor="#ffffff" style="margin:0;padding:0"><table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
<tr><td valign="top" style="font-family:Arial;color:#050505;background:#ffffff"><table border="0" cellpadding="0" cellspacing="0"><tr>
<td id="recommendation" class="rounded" style="border:solid 1px #E2E5E9;border-radius:8px;padding:16px;display:block">
<table role="presentation" border="0" cellpadding="0" cellspacing="0"><tr><td><img width="96" height="96" style="border-radius:50%" alt="logo"></td>
<td><div style="color:#1c1e21">Page name</div><div style="color:#65676B">Category</div>
<div id="primary" style="border-radius:6px;display:block;background:#0866FF;padding:8px 16px;text-align:center;color:#ffffff">Visit page</div>
</td></tr></table></td></tr></table></td></tr></table></body></html>'''

# ==========================================
# Function: Preserve email-authored visual hierarchy while keeping content inert and readable.
# Method: Use realistic nested presentation tables, CSS media queries, buttons and adversarial fragments.
# ==========================================
class EmailLayoutTests(unittest.TestCase):
    # ==========================================
    # Function: Keep presentation tables free of generic spreadsheet cell borders and spacing.
    # Method: Compare HTML and Markdown defaults while requiring every zero-spacing author attribute.
    # ==========================================
    def test_layout_tables_and_markdown_defaults_are_independent(self):
        result=reader_document(FACEBOOK_LAYOUT)
        self.assertNotIn('th,td{padding:8px',result)
        for value in ('role="presentation"','border="0"','cellpadding="0"','cellspacing="0"','valign="top"'):self.assertIn(value,result)
        markdown=reader_document('|A|B|\n|---|---|\n|1|2|',markdown=True)
        self.assertIn('th,td{padding:8px;border:1px solid',markdown)

    # ==========================================
    # Function: Preserve responsive style sheets, combinators, IDs and rounded author cards.
    # Method: Require literal CSS syntax and retain inline structural properties after adaptation.
    # ==========================================
    def test_css_structure_and_identifiers_survive(self):
        result=reader_document(FACEBOOK_LAYOUT)
        for token in ('@media all and (max-width:480px)','.row > .cell','display:block!important','id="recommendation"','border-radius:8px','border-radius:50%','padding:16px'):
            self.assertIn(token,result)
        self.assertNotIn('.row &gt;',result)

    # ==========================================
    # Function: Keep primary action colors under normal dark and custom conversation palettes.
    # Method: Verify a vivid blue button and white text survive without forced transparent backgrounds.
    # ==========================================
    def test_brand_button_survives_dark_and_bubble_palettes(self):
        for appearance in (None,{'surface':'#292d34','text':'#ffffff','border':'#454b57','force_message':True}):
            result=reader_document(FACEBOOK_LAYOUT,appearance=appearance)
            self.assertIn('background:#0866FF',result);self.assertIn('color:#ffffff',result)
            self.assertNotIn('background-color:transparent!important',result)
            self.assertNotIn('body,body *{',result)

    # ==========================================
    # Function: Adapt neutral author backgrounds and black fonts without deleting spacing or shape.
    # Method: Exercise hex, RGB and translucent border declarations in one real style string.
    # ==========================================
    def test_neutral_palette_preserves_layout(self):
        result=adapt_css('color:rgb(0,0,0)!important;background:#FFFFFF;border:1px solid rgba(0,0,0,0.15);border-radius:8px;display:flex;gap:12px')
        for token in ('color:#f1f1f1!important','background:#252525','0.15)','border-radius:8px','display:flex','gap:12px'):self.assertIn(token,result)

    # ==========================================
    # Function: Keep contrast of dark text on a vivid light button.
    # Method: Preserve the paired author foreground when its own block has a colored surface.
    # ==========================================
    def test_vivid_background_keeps_its_author_text(self):
        result=adapt_css('background:#ffe500;color:#000000;padding:8px')
        self.assertIn('color:#000000',result);self.assertIn('background:#ffe500',result)

    # ==========================================
    # Function: Preserve style strings, variables, URL fragments and comments during color adaptation.
    # Method: Treat non-color CSS tokens as opaque rather than replacing substrings that resemble color names.
    # ==========================================
    def test_css_opaque_tokens_survive(self):
        source='color:var(--black);background:url("https://example.invalid/#fff");content:"color:black;white";/* color:black */'
        self.assertEqual(adapt_css(source),source)

    # ==========================================
    # Function: Remove broad destructive resets without erasing normal media rules and selectors.
    # Method: Retain a responsive display rule alongside black-font recoloring.
    # ==========================================
    def test_reset_does_not_erase_stylesheet(self):
        result=adapt_css('*{all:initial}p{color:black!important}@media(max-width:480px){p{display:block}}')
        self.assertNotIn('all:initial',result);self.assertIn('color:#f1f1f1!important',result);self.assertIn('@media(max-width:480px)',result)

    # ==========================================
    # Function: Honor original-style mode and preserve light-mode authored colors.
    # Method: Disable adaptation explicitly and verify original dark fonts and white backgrounds remain.
    # ==========================================
    def test_original_style_mode(self):
        for kwargs in ({'adapt_dark':False},{'dark':False}):
            result=reader_document(FACEBOOK_LAYOUT,**kwargs)
            self.assertIn('color:#050505',result);self.assertIn('background:#ffffff',result)

    # ==========================================
    # Function: Keep CSP ahead of any author CSS and remove active markup and resource consent bypasses.
    # Method: Include a closing-style/script attack, event handler, base, form and tracker URL.
    # ==========================================
    def test_csp_and_active_content_remain_blocked(self):
        source='<head><style>p > a{color:black}</style><script>ATTACK()</script></head><base href="https://example.invalid"><form>SECRET</form><img src="https://tracker.invalid/x" onerror="ATTACK()"><a href="javascript:ATTACK()">safe</a>'
        result=reader_document(source)
        for token in ('<script','ATTACK','SECRET','onerror','src="https:','<base','<form'):self.assertNotIn(token,result)
        self.assertIn("default-src 'none'",result);self.assertIn("style-src 'unsafe-inline'",result)
        self.assertLess(result.index('Content-Security-Policy'),result.index('p > a'))

    # ==========================================
    # Function: Keep remote image consent explicit after layout preservation changes.
    # Method: Compare source attributes and image CSP when opted out and when opted in.
    # ==========================================
    def test_remote_image_consent_unchanged(self):
        source='<img src="https://images.example.invalid/logo.png" width="96" height="96" style="border-radius:50%">'
        self.assertNotIn('src="https:',reader_document(source))
        result=reader_document(source,remote_images=True);self.assertIn('src="https:',result);self.assertIn('img-src data: https: http:',result)

    # ==========================================
    # Function: Preserve small explicit avatar widths without disabling responsive large photographs.
    # Method: Keep a96px authored image column from collapsing while honoring explicit responsive author minima.
    # ==========================================
    def test_small_authored_images_keep_table_columns(self):
        self.assertIn('min-width:96px',reader_document('<img width="96" height="96" style="border-radius:50%">'))
        self.assertNotIn('min-width:1000px',reader_document('<img width="1000">'))
        self.assertNotIn('min-width:96px',reader_document('<img width="96" style="min-width:0">'))

    # ==========================================
    # Function: Keep malformed legacy author colors from preventing an email from loading.
    # Method: Preserve unknown palette values for the browser to ignore instead of raising during adaptation.
    # ==========================================
    def test_invalid_legacy_colors_do_not_break_reading(self):
        self.assertIn('Visible text',reader_document('<table bgcolor="#zzzzzz"><tr><td><font color="#none">Visible text</font></td></tr></table>'))


if __name__=='__main__':unittest.main()
