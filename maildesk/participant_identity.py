"""Mailbox identity and privacy-preserving contact conversation envelopes."""
from collections.abc import Mapping
from email.utils import getaddresses
from email import policy
from html import unescape
import hashlib
import json
import re


# ==========================================
# Function: Normalize a single mailbox without provider-specific alias guessing.
# Method: Parse RFC display syntax, casefold the local part and IDNA the domain.
# ==========================================
def normalize_address(value):
    if not isinstance(value, str) or any(c in value for c in '\r\n\x00'):
        return ''
    try:
        pairs = getaddresses([value])
    except (ValueError, IndexError):
        return ''
    if len(pairs) != 1:
        return ''
    address = pairs[0][1]
    if address.count('@') != 1:
        return ''
    local, domain = address.rsplit('@', 1)
    if not local or not domain or re.search(r'[\s<>;,]', address):
        return ''
    try:
        domain = domain.rstrip('.').encode('idna').decode('ascii').lower()
    except UnicodeError:
        return ''
    if not domain or not re.fullmatch(r'[a-z0-9.-]+', domain):
        return ''
    if any(not label or label.startswith('-') or label.endswith('-') for label in domain.split('.')):
        return ''
    return local.casefold() + '@' + domain


# ==========================================
# Function: Extract distinct valid mailbox identities and their display names.
# Method: Decode address lists with email.utils and retain address-based identity.
# ==========================================
def parse_participants(value):
    values = value if isinstance(value, (list, tuple)) else [value]
    values = [str(item) for item in values if item]
    try:
        pairs = getaddresses(values)
    except (ValueError, IndexError):
        return []
    result, seen = [], set()
    for name, address in pairs:
        identity = normalize_address(address)
        if identity and identity not in seen:
            result.append({'address': identity, 'name': name.strip()})
            seen.add(identity)
    return result


# ==========================================
# Function: Collect every configured sending identity, including paused accounts.
# Method: Accept Account objects, dictionaries or mailbox strings without filtering.
# ==========================================
def own_identities(accounts, extra=()):
    if isinstance(accounts, (str, Mapping)):
        accounts = [accounts]
    if isinstance(extra, str):
        extra = [extra]
    result = set()
    for account in list(accounts or ()) + list(extra or ()):
        value = account.get('email', '') if isinstance(account, Mapping) else getattr(account, 'email', account)
        identity = normalize_address(value)
        if identity:
            result.add(identity)
    return frozenset(result)


# ==========================================
# Function: Attribute standard messages and extracted history entries to self.
# Method: Prefer explicit From headers, then sender/email metadata; never names.
# ==========================================
def is_own_sender(message_or_entry, own):
    if isinstance(message_or_entry, str):
        senders = parse_participants(message_or_entry)
    elif isinstance(message_or_entry, Mapping):
        message = message_or_entry
        headers = {str(k).lower(): v for k, v in (message.get('headers') or {}).items()}
        metadata = message.get('metadata') or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        value = (headers.get('from') or message.get('sender_email') or message.get('email')
                 or metadata.get('sender_email') or metadata.get('email')
                 or message.get('sender') or message.get('from') or metadata.get('sender') or '')
        if isinstance(value, Mapping):
            value = value.get('email') or value.get('address') or ''
        senders = parse_participants(value)
        explicit_sender = any(message.get(key) for key in ('sender_email', 'email', 'sender', 'from')) or bool(headers.get('from')) or any(metadata.get(key) for key in ('email', 'sender_email', 'sender'))
        if not senders and not explicit_sender and message.get('title'):
            # Timeline titles are attribution metadata. Never inspect body/segments.
            title = unescape(str(message['title']))
            title = re.sub(r'</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>', ' ', title)
            addresses = re.findall(r"[\w.!#$%&'*+/=?^_`{|}~-]+@[\w.-]+", title)
            senders = parse_participants(addresses)
    else:
        senders = []
    identities = own_identities(own)
    return bool(senders) and all(item['address'] in identities for item in senders)


# ==========================================
# Function: Detect malformed or display-name-only participants conservatively.
# Method: Validate every parsed address, retaining ambiguous routing as an editor task.
# ==========================================
def _ambiguous(value):
    if not value:
        return False
    try:
        pairs = getaddresses([str(value)])
    except (ValueError, IndexError):
        return True
    return not pairs or any(not normalize_address(address) for _, address in pairs)


# ==========================================
# Function: Require one raw RFC From mailbox before identity deduplication.
# Method: Count parsed mailbox occurrences even when names share one address.
# ==========================================
def _single_from(value):
    if not isinstance(value,str) or not value or any(c in value for c in '\r\n\x00'):return False
    try:
        header=policy.default.header_factory('From',value)
        pairs=getaddresses([value])
        return not header.defects and len(header.addresses)==1 and len(pairs)==1 and bool(normalize_address(pairs[0][1]))
    except (ValueError,IndexError,TypeError):
        return False



# ==========================================
# Function: Identify conversations by their actual sender across subjects.
# Method: Keep source recipients for routing while excluding them from incoming identity.
# ==========================================
def conversation_envelope(parsed, own, fallback_id=''):
    identities = own_identities(own)
    headers = {str(k).lower(): v for k, v in (parsed.get('headers') or {}).items()}
    raw_from = headers['from'] if 'from' in headers else parsed.get('sender', '')
    raw_to = headers.get('to') or parsed.get('recipients', '')
    raw_cc, raw_bcc = headers.get('cc', ''), headers.get('bcc', '')
    sender = parse_participants(raw_from)
    to, cc, bcc = (parse_participants(value) for value in (raw_to, raw_cc, raw_bcc))
    if sender and 'from' not in headers and not sender[0]['name']:
        sender[0]['name'] = str(parsed.get('sender_name', ''))
    reply_to = parse_participants(headers.get('reply-to', ''))
    # The source recipient map belongs to this mail's route, not its conversation.
    visible = {}
    for item in sender + to + cc:
        if item['address'] not in identities and item['address'] not in visible:
            visible[item['address']] = item
    outgoing = bool(sender) and all(item['address'] in identities for item in sender)
    single_from=_single_from(raw_from)
    ambiguous = (not single_from or any(_ambiguous(value) for value in (raw_to, raw_cc, raw_bcc))
                 or (outgoing and not (to or cc or bcc)))
    if not single_from:
        peers, tokens, kind = [], [], 'unknown'
        tokens.append('unknown:' + str(fallback_id or parsed.get('message_id') or hashlib.sha256(json.dumps(parsed, sort_keys=True, default=str).encode()).hexdigest()))
    elif not outgoing:
        # To/Cc/Bcc variants from the same author share one sender conversation.
        peers, tokens, kind = [sender[0]], [sender[0]['address']], 'direct'
    elif len(visible) == 1 and not bcc and not ambiguous:
        # A one-person sent message remains in the direct dialogue with that peer.
        peers, tokens, kind = list(visible.values()), list(visible), 'direct'
    elif visible or bcc:
        # Sent mass mail is filed by the real own From, never by recipients.
        peers, tokens, kind = [sender[0]], ['sent:' + sender[0]['address']], 'sent'
    else:
        peers, tokens, kind = [], ['own-only'], 'self'
    key = 'contact:' + hashlib.sha256(json.dumps(sorted(tokens), ensure_ascii=False).encode()).hexdigest()[:32]
    route_to = ([item['address'] for item in sender if item['address'] not in identities] if not outgoing else [item['address'] for item in to if item['address'] not in identities])
    route_cc = [address for address in sorted(visible) if address not in route_to]
    if kind == 'self':
        route_to = [item['address'] for item in to] or [item['address'] for item in sender]
    reply_changed = bool(reply_to) and {item['address'] for item in reply_to} != {item['address'] for item in sender}
    reason = 'hidden_recipients' if bcc or (outgoing and not route_to and kind != 'self') else 'ambiguous_participants' if ambiguous else 'reply_to_differs' if reply_changed or _ambiguous(headers.get('reply-to', '')) else ''
    return {'key': key, 'kind': kind, 'peers': peers, 'sender': sender,
            'to': to, 'cc': cc, 'hidden_recipients': bcc, 'reply_to': reply_to,
            'outgoing': outgoing, 'own_only': kind == 'self',
            'route': {'safe': not reason and bool(route_to), 'reason': reason or ('' if route_to else 'no_visible_recipient'),
                      'to': route_to, 'cc': route_cc, 'hidden_count': len(bcc),
                      'reply_to': reply_to, 'requires_full_editor': bool(reason) or not route_to}}
