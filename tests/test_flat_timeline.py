"""Flat quote projection, ambiguity guards and actual viewport fitting regressions."""
import math
from unittest import TestCase
from maildesk.quoted_history import split_history,fragment_text
from maildesk.history_timeline import history_timeline
from maildesk.reader_fit import fitted_height

# ==========================================
# Function: Verify independent generations retain source content and conservative detection.
# Method: Exercise real nested vendor markup, multilingual headers and ambiguous prose.
# ==========================================
class FlatHistoryTests(TestCase):
    # ==========================================
    # Function: Flatten wrappers without repeating nested source or losing inline formatting.
    # Method: Require body-only leaves, three ordered generations and retained CID provenance.
    # ==========================================
    def test_nested_generations_are_flat_and_source_preserving(self):
        source='<p>NOW</p><div class="gmail_quote">On 2026-10-12, A wrote:<blockquote type="cite"><p>BODY_A</p><div class="gmail_quote"><b>BODY_B</b><blockquote type="cite"><p>BODY_C</p><img src="cid:c"></blockquote></div></blockquote></div>'
        model=split_history(source);view=history_timeline(model)
        self.assertEqual(len(view['history']),3)
        leaves=[''.join(part['source'] for part in row['segments']) for row in view['history']]
        self.assertTrue(all(token in source for token in ('BODY_A','BODY_B','BODY_C')))
        for index,token in enumerate(('BODY_A','BODY_B','BODY_C')):
            self.assertIn(token,leaves[index]);self.assertEqual(sum(text.count(token) for text in leaves),1)
        self.assertTrue(all('gmail_quote' not in leaf and '<blockquote' not in leaf for leaf in leaves))
        self.assertIn('<b>BODY_B</b>',leaves[1]);self.assertIn('cid:c',leaves[2])
        self.assertGreaterEqual(len(view['history'][0]['aliases']),2)

    # ==========================================
    # Function: Recognize wrapped attributions and contiguous, genuinely dated sender headers.
    # Method: Test text and HTML with Chinese, English, German and sender-only prose controls.
    # ==========================================
    def test_wrapped_and_header_detection(self):
        bodies=['Now\nOn 2026-10-12, A\nwrote:\nOld', '现在\n发件人：张三\n日期：2026年10月12日\n收件人：我\n主题：你好\n过去正文', 'Now\nVon: A\nGesendet: 2026-10-12\nAn: B\nBetreff: Test\nOlder']
        for body in bodies:
            for source,plain in [('',body),('<div>'+body.replace('\n','<br>')+'</div>','')]:
                view=history_timeline(split_history(source,plain))
                self.assertEqual(len(view['history']),1,body)
        for body in ['From: our team\nOrdinary prose\nDate: 2026-10-12\nTo: everyone\nSubject: Example', 'From: team\nDate: soon\nTo: you\nSubject: example']:
            self.assertEqual(len(history_timeline(split_history('',body))['history']),0)

    # ==========================================
    # Function: Preserve genuine body lines beginning with header words when coalescing wrappers.
    # Method: Keep sender-like prose as a generation instead of swallowing it into descendants.
    # ==========================================
    def test_wrapper_body_not_silently_merged(self):
        model=split_history('<p>Now</p><div class="gmail_quote"><p>From: our team</p><blockquote type="cite">Older</blockquote></div>')
        view=history_timeline(model);self.assertEqual(len(view['history']),2)
        self.assertIn('From: our team',fragment_text(''.join(part['source'] for part in view['history'][0]['segments'])))

# ==========================================
# Function: Verify bounded geometry conversion across real DPI and viewport changes.
# Method: Reject invalid/stale measurements and keep oversized mail scrollable at the cap.
# ==========================================
class ReaderFitTests(TestCase):
    # ==========================================
    # Function: Size content from the browser viewport instead of guessed text/image counts.
    # Method: Compare scaling, minimum, long-document cap and malformed values.
    # ==========================================
    def test_bounds_scaling_and_rejected_values(self):
        self.assertEqual(fitted_height({'height':150,'viewport':300},300),152)
        self.assertEqual(fitted_height({'height':150,'viewport':300},600),302)
        self.assertEqual(fitted_height({'height':0,'viewport':300},300),44)
        self.assertEqual(fitted_height({'height':30000,'viewport':300},300),5000)
        for value in [None,{}, {'height':math.nan,'viewport':300},{'height':-1,'viewport':300},{'height':300,'viewport':0},{'height':'bad','viewport':300},{'height':300,'viewport':1}]:
            self.assertIsNone(fitted_height(value,300))
