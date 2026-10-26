"""Local delivery-focused verification-mail recognition without retaining extracted codes."""
import re
import unicodedata

CODE_CUE=re.compile(r'验证码|校验码|验证代码|认证码|动态密码|一次性密码|安全代码|登录代码|登入代碼|驗證碼|(?:verification|security|authentication|login|sign[ -]?in|access|confirmation)\s+(?:code|passcode|pin)|one[ -]time\s+(?:password|passcode|code)|\botp\b',re.I)
AUTH_CUE=re.compile(r'登录|登入|验证|驗證|校验|认证|动态密码|一次性密码|安全|身份|access\s+(?:code|passcode)|email\s+confirmation|sign[ -]?in|log[ -]?in|verif|authenticat|security|one[ -]time|\botp\b',re.I)
DELIVERY_CUE=re.compile(r'有效|过期|失效|分钟|秒内|請|请|输入|使用|用于|valid|expir|minutes?|seconds?|enter|use\s+(?:this|the)|your\s+(?:code|passcode)',re.I)
TOPIC=re.compile(r'教程|原理|算法|如何|实现|功能设计|使用指南|接入文档|讨论|問題|问题|tutorial|implementation|how\s+to|developer\s+guide|sample\s+code',re.I)
QUOTE=re.compile(r'^\s*(?:>|[-_]{3,}\s*(?:original|forwarded|原始|转发)|(?:from|发件人|寄件者)\s*[:：]|on\s+.{4,160}\bwrote\s*[:：]|在\s*.{4,160}(?:写道|寫道)\s*[:：])',re.I|re.M)
CANDIDATE=re.compile(r'(?<![A-Z0-9@])(?:\d{3}[\s-]\d{3}|[A-Z0-9]{4,10})(?![A-Z0-9@])',re.I)

# ==========================================
# Function: Distinguish delivered authentication codes from general notification/tutorial mail.
# Method: Bound current-message text, ignore quoted history and combine a short token with nearby authentication/delivery cues.
# ==========================================
def verification_reason(message):
    subject=unicodedata.normalize('NFKC',str(message.get('subject',''))[:512]);body=unicodedata.normalize('NFKC',str(message.get('body',''))[:16000]);quote=QUOTE.search(body)
    if quote:body=body[:quote.start()]
    if TOPIC.search(subject):return ''
    if re.match(r'\s*(?:re|fw|fwd|回复|转发)\s*[:：]',subject,re.I) and not DELIVERY_CUE.search(body):return ''
    text=subject+'\n'+body;subject_cue=CODE_CUE.search(subject);cues=list(CODE_CUE.finditer(text))
    if not cues:return ''
    dates=list(re.finditer(r'(?:19|20)\d{2}[-/年]\d{1,2}[-/月]\d{1,2}(?:日)?(?!\d)',text))
    for match in CANDIDATE.finditer(text):
        token=re.sub(r'[\s-]','',match.group())
        if not any(character.isdigit() for character in token):continue
        if any(match.start()<date.end() and match.end()>date.start() for date in dates):continue
        if token.isdigit() and len(set(token))==1 and token[0]=='0':continue
        nearby=text[max(0,match.start()-100):match.end()+100]
        close=any(max(cue.start()-match.end(),match.start()-cue.end(),0)<=100 for cue in cues)
        line=text[text.rfind('\n',0,match.start())+1:text.find('\n',match.end()) if '\n' in text[match.end():] else len(text)].strip()
        body_cue=any(cue.start()>len(subject) and max(cue.start()-match.end(),match.start()-cue.end(),0)<=100 for cue in cues)
        if subject_cue and AUTH_CUE.search(subject) and (match.start()<len(subject) or DELIVERY_CUE.search(body) or body_cue or line.strip(' .:：。')==match.group().strip()):
            return '主题包含身份验证特征，当前正文包含短码及投递提示'
        if close and AUTH_CUE.search(nearby) and DELIVERY_CUE.search(nearby):
            return '当前正文中的短码与身份验证、输入或有效期提示相邻'
    if subject_cue and AUTH_CUE.search(subject) and DELIVERY_CUE.search(body) and re.search(r'cid:|<img\b',str(message.get('html',''))[:16000],re.I):
        return '身份验证主题及投递提示，验证码可能位于邮件图片中'
    return ''
