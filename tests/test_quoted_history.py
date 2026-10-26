"""Conservative render-only quote recognition and preservation regressions."""
from unittest import TestCase
from maildesk.quoted_history import split_history, history_sources, source_cids
from maildesk.document_content import reader_document

# ==========================================
# Function: Exercise ambiguous content and proven client quote boundaries.
# Method: Compare ordered visible segments, nesting, inert output and lossless fallback.
# ==========================================
class QuotedHistoryTests(TestCase):
    # ==========================================
    # Function: Separate localized historical replies without angle-bracket quote prefixes.
    # Method: Follow a dated edit attribution and validated original-message clusters recursively.
    # ==========================================
    def test_localized_unprefixed_plain_chain(self):
        body='CURRENT_ONLY\n在 2026年10月5日 下午5:42:24，联系人甲 编辑:\nLEVEL_ONE\n-----原始邮件-----\n发件人: 联系人乙 <b@example.invalid>\n目标语言: a@example.invalid\n日期: 2026年9月11日 19:09\n主题: 回复测试\nLEVEL_TWO\n在 Sep 8, 2026, 16:31 +0800, 联系人丙，写道:\nLEVEL_THREE\n-----Original Message-----\nFrom: D <d@example.invalid>\nDate: 2026-08-31\nTo: a@example.invalid\nSubject: Earlier\nLEVEL_FOUR'
        model=split_history('',body)
        for marker in ['CURRENT_ONLY','LEVEL_ONE','LEVEL_TWO','LEVEL_THREE']:
            current=''.join(part['source'] for part in model['segments'] if part['kind']=='current')
            self.assertIn(marker,current)
            quotes=[part for part in model['segments'] if part['kind']=='quote'];self.assertEqual(len(quotes),1)
            model=quotes[0]
        self.assertIn('LEVEL_FOUR',''.join(history_sources(model)))

    # ==========================================
    # Function: Preserve rich content while linking unmarked histories inside an existing quote.
    # Method: Combine split attribution tags, localized headers, a table, an image and a dated reply.
    # ==========================================
    def test_unmarked_rich_chain_inside_explicit_history(self):
        source='<div><p>CURRENT_ONLY</p><div class="gmail_quote"><p>在 2026年10月5日，联系人甲 编辑:</p><p>LEVEL_ONE</p><div>-----原始邮件-----<br>发件人: 乙<br>日期: 2026-09-11<br>主题: 回复</div><table><tr><td><b>LEVEL_TWO</b></td></tr></table><p><span>在 Sep 8, 2026, 16:31 +0800, </span><a href="mailto:c@example.invalid">联系人丙</a>，写道:</p><p>LEVEL_THREE<img src="cid:old-image"></p></div><p>CURRENT_AFTER</p></div>'
        model=split_history(source);self.assertEqual([p['kind'] for p in model['segments']],['current','quote','current'])
        first=model['segments'][1];self.assertEqual(len([p for p in first['segments'] if p['kind']=='quote']),1)
        own=''.join(p['source'] for p in first['segments'] if p['kind']=='current');self.assertIn('LEVEL_ONE',own);self.assertNotIn('LEVEL_TWO',own)
        second=next(p for p in first['segments'] if p['kind']=='quote');own=''.join(p['source'] for p in second['segments'] if p['kind']=='current')
        self.assertIn('<table>',own);self.assertIn('<b>LEVEL_TWO</b>',own);self.assertNotIn('LEVEL_THREE',own)
        third=next(p for p in second['segments'] if p['kind']=='quote');self.assertEqual(source_cids(''.join(history_sources(third))),{'old-image'})
        self.assertIn('CURRENT_AFTER',model['segments'][-1]['source'])
        for marker in ['CURRENT_ONLY','LEVEL_ONE','LEVEL_TWO','LEVEL_THREE','CURRENT_AFTER']:
            self.assertEqual(sum(leaf.count(marker) for leaf in history_sources(model)),1)

    # ==========================================
    # Function: Keep pasted examples and ambiguous headers outside history disclosures.
    # Method: Reject undated editing prose, code and header clusters without a sender field.
    # ==========================================
    def test_unmarked_detection_avoids_code_and_weak_boundaries(self):
        for source in ['<p>在文档里编辑:</p><p>Keep</p>','<pre>在 2026年10月5日，A 编辑:\nCODE_KEEP</pre>','<p>-----原始邮件-----</p><p>日期: 2026-09-11<br>发送时间: now<br>主题: Notes</p><p>KEEP</p>']:
            self.assertEqual(split_history(source)['segments'],[{'kind':'current','source':source}])
        body='Current\n-----Original Message-----\n    From:   \nDate: 2026-09-11\nTo: B\nSubject: Notes\nKEEP'
        self.assertFalse(any(part['kind']=='quote' for part in split_history('',body)['segments']))

    # ==========================================
    # Function: Retain inherited styling and native HTML structure at implicit quote boundaries.
    # Method: Require every rich leaf to keep its outer format while displaying each payload exactly once.
    # ==========================================
    def test_implicit_rich_leaf_keeps_ancestor_style(self):
        source='<div style="font-style:italic"><p>NOW</p><p>在2026-09-11，联系人 编辑:</p><p><b>OLDER</b></p></div>'
        leaves=list(history_sources(split_history(source)))
        self.assertEqual(len(leaves),2)
        self.assertTrue(all('font-style:italic' in leaf for leaf in leaves))
        self.assertIn('<b>OLDER</b>',leaves[-1]);self.assertEqual(sum(leaf.count('OLDER') for leaf in leaves),1)

    # ==========================================
    # Function: Keep email-like examples in literal plaintext code fences readable as current text.
    # Method: Supply strong dated markers and complete headers inside a fenced example.
    # ==========================================
    def test_plain_code_fences_do_not_create_history(self):
        body='Example\n```text\n在 2026年10月5日，A 编辑:\nCODE\n-----原始邮件-----\nFrom: A\nDate: 2026-09-11\nTo: B\nSubject: Test\n```\nCurrent answer'
        self.assertFalse(any(part['kind']=='quote' for part in split_history('',body)['segments']))

    # ==========================================
    # Function: Keep long genuine historical chains independently structured beyond the former depth limit.
    # Method: Build twenty dated historical replies and count nested cards without duplicating the oldest text.
    # ==========================================
    def test_twenty_unmarked_history_levels(self):
        source='<p>NOW</p>'+''.join('<p>在 2026年9月11日 12:00，联系人 编辑:</p><p>LEVEL_'+str(index)+'</p>' for index in range(20))
        model=split_history(source);count=0
        while any(part['kind']=='quote' for part in model['segments']):
            quotes=[part for part in model['segments'] if part['kind']=='quote'];self.assertEqual(len(quotes),1)
            model=quotes[0];count+=1
        self.assertEqual(count,20);self.assertIn('LEVEL_19',''.join(history_sources(model)))

    # ==========================================
    # Function: Preserve ordinary blockquotes, code, math and header-like prose.
    # Method: Require supported attribution or a client-specific structural marker.
    # ==========================================
    def test_ambiguous_text_and_html_remain_current(self):
        for source in ['<p>Answer</p><blockquote>A literary quote</blockquote>','<pre>&gt; math</pre>','<div>From: not a mail header</div>']:
            self.assertEqual(split_history(source)['segments'],[{'kind':'current','source':source}])
        for body in ['> x greater than y\n> z','From: our team\nNormal prose','On the road:\n> yes']:
            self.assertFalse(any(x['kind']=='quote' for x in split_history('',body)['segments']))

    # ==========================================
    # Function: Keep inline answers in their original interleaved positions.
    # Method: Recognize attributed runs and recursively detect nested quoted replies.
    # ==========================================
    def test_plain_inline_answers_and_nested_attribution(self):
        body='My first answer\nOn Monday, A wrote:\n> Question one\nInline answer\nOn Tuesday, B wrote:\n> On Sunday, C wrote:\n> > Older question\nFinal answer'
        model=split_history('',body);segments=model['segments']
        self.assertEqual([x['kind'] for x in segments],['current','quote','current','quote','current'])
        self.assertIn('Inline answer',segments[2]['source']);self.assertIn('Final answer',segments[4]['source'])
        self.assertEqual(segments[3]['segments'][0]['kind'],'quote')
        self.assertIn('Older question',''.join(history_sources(model)))

    # ==========================================
    # Function: Preserve rich HTML tables and linked nested client quotes without source text leaks.
    # Method: Extract supported markers into ordered structures without removing unrelated content.
    # ==========================================
    def test_html_nesting_and_interleaved_content(self):
        source='<div><p>Now</p><div class="gmail_quote"><p>On Monday A wrote:</p><table><tr><td>One</td></tr></table><blockquote type="cite"><b>Older</b><img src="cid:old"></blockquote></div><p>After</p></div>'
        model=split_history(source);parts=model['segments']
        self.assertEqual([p['kind'] for p in parts],['current','quote','current'])
        self.assertIn('<p>Now</p>',parts[0]['source']);self.assertIn('<p>After</p>',parts[2]['source'])
        quote=parts[1];self.assertEqual([p['kind'] for p in quote['segments']],['current','quote'])
        self.assertIn('<table>',quote['segments'][0]['source']);self.assertIn('<b>Older</b>',quote['segments'][1]['segments'][0]['source'])
        self.assertIn('cid:old',''.join(history_sources(model)))

    # ==========================================
    # Function: Require a real Outlook header group and retain malformed content safely.
    # Method: Reject isolated delimiters and preserve the entire input on unbalanced quote markup.
    # ==========================================
    def test_outlook_cluster_and_malformed_fallback(self):
        source='<p>Now</p><div id="divRplyFwdMsg">From: A<br>Sent: Monday<br>To: B<br>Subject: Topic</div><p>Earlier</p>'
        model=split_history(source);self.assertEqual([x['kind'] for x in model['segments']],['current','quote'])
        self.assertIn('Earlier',''.join(history_sources({'segments':model['segments'][1]['segments']})))
        fake='<div id="divRplyFwdMsg">From: team</div><p>Important current text</p>'
        self.assertFalse(any(x['kind']=='quote' for x in split_history(fake)['segments']))
        broken='<p>Keep</p><div class="gmail_quote">Unclosed important text'
        self.assertEqual(split_history(broken)['segments'],[{'kind':'current','source':broken}])

    # ==========================================
    # Function: Keep recognized quote content inert under the existing reader policy.
    # Method: Sanitize each leaf and assert scripts, remote resources and active links cannot execute.
    # ==========================================
    def test_quote_leaves_reuse_safe_reader_and_images_stay_local(self):
        source='<p>Now</p><blockquote type="cite"><script>alert(1)</script><img src="https://bad.test/x"><a href="javascript:bad()">old</a><img src="cid:old"></blockquote>'
        model=split_history(source)
        for leaf in history_sources(model):
            safe=reader_document(leaf)
            self.assertNotIn('<script',safe);self.assertNotIn('src="https://bad',safe);self.assertNotIn('href="javascript:',safe)
        self.assertIn('cid:old',''.join(history_sources(model)))

    # ==========================================
    # Function: Reject quote markers on void elements and hidden native title text.
    # Method: Preserve malformed image nodes and derive titles solely from readable content.
    # ==========================================
    def test_void_markers_and_hidden_title_data(self):
        for source in ['<p>now</p><img class="gmail_quote" src="cid:x">','<img id="divRplyFwdMsg" src="cid:x">']:
            self.assertEqual(split_history(source)['segments'],[{'kind':'current','source':source}])
        source='<p>Now</p><blockquote type="cite"><style>body{color:red}</style><script>hidden()</script><p>Person wrote:</p><b>History</b></blockquote>'
        quote=next(part for part in split_history(source)['segments'] if part['kind']=='quote')
        self.assertEqual(quote['title'],'Person wrote:')

    # ==========================================
    # Function: Preserve sanitizer context while finding quote and image ownership.
    # Method: Keep hidden/template/form content suppressed and ignore string-like CID attributes.
    # ==========================================
    def test_hidden_markers_and_real_image_sources_only(self):
        for tag in ['template','form','svg','head','object']:
            source='<p>Now</p><'+tag+'><div class="gmail_quote">HIDDEN</div></'+tag+'>'
            self.assertFalse(any(part['kind']=='quote' for part in split_history(source)['segments']))
            if tag!='head':self.assertNotIn('HIDDEN',reader_document(source).split('<body>')[1])
        self.assertEqual(source_cids('<p title="src=cid:fake">Text</p><script>src="cid:fake"</script><a src="cid:fake">link</a><img src="CID:real%40mail"><template><img src="cid:hidden"></template>'),{'real@mail'})

    # ==========================================
    # Function: Keep quote-only and deeply nested bodies completely readable.
    # Method: Retain a local disclosure without inventing current text and stop recursion without losing payload.
    # ==========================================
    def test_quote_only_and_deep_fallback_preserve_content(self):
        model=split_history('<blockquote type="cite"><b>ONLY_QUOTED</b></blockquote>')
        self.assertEqual([part['kind'] for part in model['segments']],['quote'])
        self.assertIn('<b>ONLY_QUOTED</b>',''.join(history_sources(model)))
        source='<blockquote type="cite">'*18+'DEEPEST_CONTENT'+'</blockquote>'*18
        model=split_history(source);leaves=list(history_sources(model))
        self.assertEqual(sum('DEEPEST_CONTENT' in leaf for leaf in leaves),1)
        self.assertIn('DEEPEST_CONTENT',reader_document(''.join(leaves)))

    # ==========================================
    # Function: Bound synchronous body-history controls without truncating message content.
    # Method: Exceed the shared structural quote budget in rich and plaintext mail and require full-body fallback.
    # ==========================================
    def test_large_quote_fanout_preserves_original_without_native_header_explosion(self):
        source='<p>Now</p>'+''.join('<blockquote type="cite">HISTORY_'+str(index)+'</blockquote>' for index in range(513))
        self.assertEqual(split_history(source)['segments'],[{'kind':'current','source':source}])
        body='Now\n'+''.join('On Monday, A wrote:\n> HISTORY_'+str(index)+'\nANSWER\n' for index in range(513))
        segments=split_history('',body)['segments']
        self.assertEqual(len(segments),1);self.assertEqual(segments[0]['kind'],'current')
        self.assertIn('HISTORY_512',segments[0]['source']);self.assertIn('Now',segments[0]['source'])
