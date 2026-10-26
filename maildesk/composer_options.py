"""Independent local composer policies shared by native UI and delivery service."""
from email.utils import getaddresses
from email.headerregistry import Address
import re

# ==========================================
# Function: Validate address lists without silently dropping malformed fragments.
# Method: Parse complete comma/semicolon separated lists and reject invalid mailbox syntax.
# ==========================================
def validated_addresses(value):
    if not isinstance(value,str) or any(c in value for c in '\r\n'):raise ValueError('邮件地址无效')
    if not value.strip():return []
    parsed=getaddresses([value.replace(';',',')])
    if not parsed or any(not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+',address) for _,address in parsed):
        raise ValueError('请输入有效的邮箱地址，多个地址用逗号分隔')
    return list(dict.fromkeys(address.casefold() for _,address in parsed))

# ==========================================
# Function: Normalize one rule identity to a mailbox or a validated domain key.
# Method: Parse display names once and reject lists, malformed domains and header controls.
# ==========================================
def rule_sender(value):
    if not isinstance(value,str) or any(c in value for c in '\r\n'):raise ValueError('请输入有效的邮箱或 @域名')
    value=value.strip().casefold()
    if value.startswith('@'):
        try:domain=value[1:].encode('idna').decode('ascii')
        except UnicodeError:raise ValueError('请输入有效的 @域名') from None
        label=r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
        if not re.fullmatch(label+r'(?:\.'+label+r')+',domain) or len(domain)>253:raise ValueError('请输入有效的 @域名')
        return value
    addresses=validated_addresses(value)
    if len(addresses)!=1:raise ValueError('请输入一个发件邮箱或 @域名')
    return addresses[0]

# ==========================================
# Function: Find the final recipient token without splitting a quoted display name.
# Method: Scan RFC address quoting, escapes and angle brackets before accepting separators.
# ==========================================
def recipient_token_start(value):
    start=0;quoted=False;escaped=False;angle=0
    for index,char in enumerate(value):
        if escaped:escaped=False;continue
        if quoted and char=='\\':escaped=True;continue
        if char=='"':quoted=not quoted
        elif not quoted:
            if char=='<':angle+=1
            elif char=='>':angle=max(0,angle-1)
            elif char in ',;' and not angle:start=index+1
    return start

# ==========================================
# Function: Add configured CC/BCC and optional client signature to outgoing MIME content.
# Method: Merge per-account copy recipients without duplicates and snapshot receipt preference.
# ==========================================
def outgoing_options(store, account, draft):
    result=dict(draft);copy=store.preference('auto_copy',{}).get(account.id,{})
    if copy.get('enabled'):
        mode=copy.get('mode','bcc')
        if mode not in ('cc','bcc'):raise ValueError('自动抄送设置无效')
        configured=validated_addresses(copy.get('addresses',''))
        existing={address for field in ('to','cc','bcc') for _,address in getaddresses([result.get(field,'')])}
        extra=[address for address in configured if address not in {a.casefold() for a in existing}]
        if extra:result[mode]=', '.join(filter(None,[result.get(mode,''),', '.join(extra)]))
    result['request_receipt']=bool(draft.get('request_receipt',store.preference('request_receipt',False)))
    if store.preference('composer_tagline',False):
        result['body']=result.get('body','')+'\n\nSent with TeleMail'
        if result.get('html'):result['html']+='<p style="color:#7f8790">Sent with TeleMail</p>'
    return result

# ==========================================
# Function: Resolve a reusable template with explicit safe text placeholders.
# Method: Substitute plain text only; missing variables are returned for a native fill-in form.
# ==========================================
def render_template(template, values):
    pattern=r'\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}'
    missing=set()
    # ==========================================
    # Function: Resolve one placeholder without evaluating executable expressions.
    # Method: Keep unresolved placeholders intact and collect their names.
    # ==========================================
    def replace(match):
        key=match.group(1)
        if key not in values:missing.add(key);return match.group()
        return str(values[key])
    result={field:re.sub(pattern,replace,template.get(field,'')) for field in ('subject','body')}
    return result,sorted(missing)

# ==========================================
# Function: Suggest known recipients from local contacts and cached mail only.
# Method: Deduplicate bounded Unicode display names and mailboxes without a remote directory.
# ==========================================
def recipient_suggestions(store):
    from .address_book import suggestions
    names=dict(suggestions(store))
    result=[]
    for address,name in list(names.items())[:300]:
        try:text=str(Address(display_name=' '.join(str(name).split()),addr_spec=address))
        except ValueError:continue
        result.append((address,text))
    return result
