"""Explainable independent classification; no Spark model or code is reused."""
CATEGORIES = ('personal', 'notification', 'newsletter', 'verification')

# ==========================================
# Function: Assign a mail category with a readable explanation.
# Method: Sender corrections and custom rules precede header-based heuristics.
# ==========================================
def classify(message, sender_rules=None, rules=(), enabled=True):
    sender = message['sender'].casefold()
    if sender in (sender_rules or {}):
        return sender_rules[sender], '使用你为此发件人保存的分类'
    domain='@'+sender.rsplit('@',1)[-1]
    if domain in (sender_rules or {}):return sender_rules[domain], '使用你为此域名保存的分类'
    for rule in rules:
        field = rule.get('field')
        if field not in ('sender', 'subject', 'body') or rule.get('category') not in CATEGORIES:
            continue
        value = str(rule.get('contains', '')).casefold()
        if value and value in message.get(field, '').casefold():
            return rule['category'], f'命中自定义规则：{field} 包含 {value}'
    if not enabled:return 'personal','自动邮件识别已关闭；保留手工分类和规则'
    from .verification_mail import verification_reason
    reason=verification_reason(message)
    if reason:return 'verification',reason
    headers = message.get('headers', {})
    if headers.get('list-id') or headers.get('list-unsubscribe'):
        return 'newsletter', '邮件带有订阅列表或退订头'
    if headers.get('precedence', '').lower() in ('bulk', 'list'):
        return 'newsletter', '批量或邮件列表投递标记'
    auto = headers.get('auto-submitted', '').strip().lower()
    if auto and auto != 'no':
        return 'notification', '邮件标记为自动生成'
    local = sender.partition('@')[0]
    if any(token in local for token in ('noreply', 'no-reply', 'no_reply', 'notifications', 'alerts', 'mailer-daemon')):
        return 'notification', '发件地址是自动通知账户'
    subject = message.get('subject', '').casefold()
    if any(token in subject for token in ('验证码', 'verification code', 'security alert', '登录提醒', '订单已', 'payment receipt', '账单提醒')):
        return 'notification', '主题包含事务通知特征'
    return 'personal', '未发现批量订阅或自动通知特征'
