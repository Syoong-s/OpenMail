"""Synthetic mail fixtures, isolated from real account storage and delivery."""
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime

# ==========================================
# Function: Populate a realistic synthetic inbox without network access.
# Method: Create deterministic MIME examples covering categories, threads and attachments.
# ==========================================
def seed(store):
    if not store.list_folders('demo'):
        store.save_folders('demo',[{'name':name,'special':special,'delimiter':'/','flags':[],'selectable':True,'subscribed':True} for name,special in [('INBOX','inbox'),('Sent','sent'),('Drafts','drafts'),('Archive','archive'),('Trash','trash'),('Spam','spam'),('工作',''),('工作/项目资料',''),('个人','')]])
        store.folder_options('demo','工作/项目资料',favorite=True,color='purple')
        store.save_smart_folder('带附件的邮件','has:attachment')
    examples = [
        ('林夏', 'linxia@example.com', '下周研究讨论：时间确认', '你好，\n\n下周三下午三点的讨论会方便吗？我把最新的数据分析结果整理好了，想听听你的建议。\n\n林夏', {}),
        ('设计团队', 'design@example.com', 'TeleMail 界面评审', '这封邮件展示了普通个人邮件。你可以置顶、标记优先，或回复它。', {}),
        ('账号安全', 'no-reply@security.example.com', '登录提醒：新设备', '检测到一次新的设备登录。这是一封合成通知邮件，无需采取操作。', {'Auto-Submitted': 'auto-generated'}),
        ('深空周刊', 'editor@space.example.com', '深空周刊 · 本周宇宙新发现', '本周精选：弱引力透镜、暗物质分布与新的深空观测。\n\n这是一封合成订阅邮件。', {'List-ID': '<space.example.com>', 'List-Unsubscribe': '<mailto:unsubscribe@example.com>'}),
        ('开发者简报', 'weekly@dev.example.com', '开发者简报：把想法写成程序', '本期内容：增量同步、可解释归类与可靠的发件箱设计。', {'Precedence': 'bulk'}),
        ('会议服务', 'alerts@meet.example.com', '提醒：明天下午的项目讨论', '你的讨论会将在明天下午开始。', {'Auto-Submitted': 'auto-generated'}),
        ('林夏', 'linxia@example.com', 'Re: 下周研究讨论：时间确认', '补充一下：我也可以周四上午。期待你的回复！', {'In-Reply-To': '<demo-0@example.com>', 'References': '<demo-0@example.com>'}),
        ('陈舟', 'chenzhou@example.com', '附件：项目笔记', '项目笔记在附件里，方便的时候看看。', {}),
    ]
    now = datetime.now(timezone.utc)
    for index, (name, sender, subject, body, headers) in enumerate(examples):
        msg = EmailMessage()
        msg['From'] = f'{name} <{sender}>'
        msg['To'] = '我 <demo@example.com>'
        msg['Subject'] = subject
        msg['Message-ID'] = f'<demo-{index}@example.com>'
        msg['Date'] = format_datetime(now - timedelta(minutes=index * 32))
        for key, value in headers.items():
            msg[key] = value
        msg.set_content(body)
        if index == 7:
            msg.add_attachment('项目笔记\n这是合成附件，用于验证下载。'.encode(), maintype='text', subtype='plain', filename='项目笔记.txt')
        identity = store.ingest('demo', 'INBOX', '1', str(index + 1), msg.as_bytes(), seen=index in (1, 5))
        if index == 0:
            store.update(identity, {'priority': True})
        elif index == 7:
            store.update(identity, {'pinned': True})
