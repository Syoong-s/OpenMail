"""MIME parsing, safe text previews, attachment metadata and composition."""
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime, getaddresses, make_msgid, parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
import hashlib
import mimetypes
import re

MAX_MESSAGE_BYTES = 30 * 1024 * 1024

# ==========================================
# Function: Convert HTML mail into inert readable text.
# Method: Drop scripts/styles and collect text without loading remote content.
# ==========================================
class TextExtractor(HTMLParser):
    # ==========================================
    # Function: Initialize the text collector.
    # Method: Track hidden elements and collected output separately.
    # ==========================================
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.hidden = 0

    # ==========================================
    # Function: Handle opening HTML elements.
    # Method: Suppress active elements and preserve paragraph separators.
    # ==========================================
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head'):
            self.hidden += 1
        if tag in ('br', 'p', 'div', 'tr', 'li'):
            self.output.append('\n')

    # ==========================================
    # Function: Handle closing HTML elements.
    # Method: End suppression and separate block text.
    # ==========================================
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li'):
            self.output.append('\n')

    # ==========================================
    # Function: Collect visible text.
    # Method: Ignore data while inside suppressed elements.
    # ==========================================
    def handle_data(self, data):
        if not self.hidden:
            self.output.append(data)

# ==========================================
# Function: Decode a MIME text part robustly.
# Method: Use declared encoding with UTF-8 replacement fallback.
# ==========================================
def part_text(part):
    payload = part.get_payload(decode=True) or b''
    try:
        return payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
    except LookupError:
        return payload.decode('utf-8', errors='replace')

# ==========================================
# Function: Recover attachment bytes, including attached RFC messages.
# Method: Decode transfer encoding or serialize encapsulated message payloads.
# ==========================================
def attachment_content(part):
    decoded = part.get_payload(decode=True)
    if decoded is not None:
        return decoded
    payload = part.get_payload()
    if isinstance(payload, list):
        return b'\r\n'.join(child.as_bytes(policy=policy.SMTP) for child in payload)
    return str(payload or '').encode('utf-8')

# ==========================================
# Function: Parse an RFC message into the local canonical model.
# Method: Decode MIME and references, retain inert text and attachment descriptors.
# ==========================================
def parse_message(raw):
    if len(raw) > MAX_MESSAGE_BYTES:
        raise ValueError('邮件超过 30 MiB 上限')
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sender_name, sender = parseaddr(str(msg.get('From', '')))
    attachments, excluded = [], set()
    for index, part in enumerate(msg.walk()):
        if id(part) in excluded:
            continue
        name = part.get_filename()
        if name or part.get_content_disposition() == 'attachment':
            attachments.append({'index': index, 'name': name or 'attachment', 'type': part.get_content_type(), 'size': len(attachment_content(part))})
            excluded.update(id(child) for child in list(part.walk())[1:])
    html_part=msg.get_body(preferencelist=('html',))
    html_body=part_text(html_part) if html_part is not None else ''
    selected = msg.get_body(preferencelist=('plain', 'html'))
    body = part_text(selected) if selected is not None else ''
    if selected is not None and selected.get_content_type() == 'text/html':
        extractor = TextExtractor()
        extractor.feed(body)
        body = ''.join(extractor.output)
    body = body.strip()
    try:
        date = parsedate_to_datetime(str(msg.get('Date', '')))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        timestamp = date.timestamp()
    except (ValueError, TypeError, OverflowError):
        timestamp = datetime.now(timezone.utc).timestamp()
    message_id = str(msg.get('Message-ID', '')).strip() or '<' + hashlib.sha256(raw).hexdigest() + '@local>'
    references = re.findall(r'<[^<>]+>', str(msg.get('References', '')))
    in_reply_to = re.findall(r'<[^<>]+>', str(msg.get('In-Reply-To', '')))
    headers={k.lower():str(v) for k,v in msg.items()}
    headers['from']=', '.join(str(value) for value in msg.get_all('From',[]))
    from .participant_identity import _single_from
    from_valid=len(msg.get_all('From',[]))==1 and _single_from(headers['from'])
    return {'from_valid':from_valid,'message_id': message_id, 'references': references, 'in_reply_to': in_reply_to,
            'sender': sender.lower(), 'sender_name': sender_name, 'recipients': str(msg.get('To', '')),
            'subject': str(msg.get('Subject', '(无主题)')), 'body': body, 'timestamp': timestamp,
            'html':html_body, 'headers':headers, 'attachments': attachments}

# ==========================================
# Function: Validate recipients and prevent malformed envelope/header input.
# Method: Parse address lists, require basic mailbox syntax, reject line breaks.
# ==========================================
def addresses(value):
    if not isinstance(value, str) or any(c in value for c in '\r\n'):
        raise ValueError('收件人格式无效')
    parsed = getaddresses([value])
    if not parsed or any(not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', address) for _, address in parsed):
        raise ValueError('请输入完整邮箱地址；多个收件人用逗号分隔')
    return [address for _, address in parsed]

# ==========================================
# Function: Compose standards-based outgoing mail.
# Method: Build UTF-8 MIME with stable Message-ID, reply headers and attachments.
# ==========================================
def compose(sender, draft, message_id=None):
    from .reply_history import with_history
    draft=with_history(draft)
    targets = addresses(draft.get('to', ''))
    cc = addresses(draft['cc']) if draft.get('cc') else []
    bcc = addresses(draft['bcc']) if draft.get('bcc') else []
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = sender
    msg['To'] = draft['to']
    if cc:
        msg['Cc'] = draft['cc']
    msg['Subject'] = draft.get('subject', '')
    msg['Date'] = format_datetime(datetime.now(timezone.utc))
    msg['Message-ID'] = message_id or make_msgid()
    if draft.get('request_receipt'):msg['Disposition-Notification-To']=sender
    if draft.get('in_reply_to'):
        msg['In-Reply-To'] = draft['in_reply_to']
        msg['References'] = draft.get('references', draft['in_reply_to'])
    msg.set_content(draft.get('body', ''))
    if draft.get('html'):
        msg.add_alternative(draft['html'],subtype='html')
    for attachment in draft.get('attachments', []):
        data = attachment['data']
        content_type = mimetypes.guess_type(attachment['name'])[0] or 'application/octet-stream'
        maintype, subtype = content_type.split('/', 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=attachment['name'])
    if len(msg.as_bytes()) > MAX_MESSAGE_BYTES:
        raise ValueError('邮件和附件总大小超过 30 MiB')
    return msg, list(dict.fromkeys(targets + cc + bcc))
