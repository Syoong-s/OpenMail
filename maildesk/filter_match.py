"""Bounded data-only rule matching shared by automatic runs, previews and manual filtering."""
import fnmatch
from .filter_smart import normalize,recognize,score
from .participant_identity import parse_participants

# ==========================================
# Function: Match normalized literal or wildcard text with Sieve-style simple operators.
# Method: Keep patterns data-only and avoid arbitrary regular expressions or executable scripts.
# ==========================================
def text_match(values,op,wanted):
    wanted=normalize(wanted);values=[normalize(value) for value in values]
    if op in ('is_not','not_contains'):return not text_match(values,'is' if op=='is_not' else 'contains',wanted)
    return any((wanted in value if op=='contains' else value==wanted if op=='is' else value.startswith(wanted) if op=='starts' else value.endswith(wanted) if op=='ends' else fnmatch.fnmatchcase(value,wanted)) for value in values)

# ==========================================
# Function: Respect exact source folders and real hierarchy boundaries for every account.
# Method: Resolve delimiter metadata instead of treating similarly named folders as descendants.
# ==========================================
def source_matches(rule,message,folder_rows):
    if rule['source_mode']=='all':return True
    paths=rule['sources'].get(message['account'],[]);current=message['folder'];matched=False
    for path in paths:
        delimiter=folder_rows.get((message['account'],path),{}).get('delimiter','/')
        if current==path or (rule['subfolders'] and delimiter and current.startswith(path+delimiter)):matched=True;break
    return matched if rule['source_mode']=='include' else not matched

# ==========================================
# Function: Evaluate one structured condition and provide a human-readable reason.
# Method: Use parsed addresses/attachments and bounded cached text; consult smart and learned evidence only when explicitly selected.
# ==========================================
def condition_matches(condition,message,context,rule):
    parsed=message['parsed'];headers=parsed.get('headers',{});field=condition['field'];op=condition['op'];wanted=condition['value'];value=None
    if field in ('sender','domain','to','cc'):
        raw=headers.get('from',parsed.get('sender','')) if field in ('sender','domain') else headers.get(field,'')
        values=[row['address'] for row in parse_participants(raw)]
        if field=='domain':values=[address.rsplit('@',1)[-1] for address in values]
    elif field in ('subject','body'):values=[parsed.get(field,'')[:(262144 if field=='body' else 4096)]]
    elif field=='header':values=[headers.get(condition['header'],'')[:8192]]
    elif field in ('attachment_name','attachment_type'):values=[row.get('name' if field=='attachment_name' else 'type','') for row in parsed.get('attachments',[])[:100]]
    elif field in ('has_attachment','seen','starred_contact'):
        actual=bool(parsed.get('attachments')) if field=='has_attachment' else bool(message.get('seen')) if field=='seen' else normalize(parsed.get('sender','')) in context['starred']
        value=actual==(wanted=='true');return (not value if op=='is_not' else value),field
    elif field=='category':return ((message['category']==wanted) if op=='is' else (message['category']!=wanted)),'当前邮件类别：'+message['category']
    elif field=='smart':
        matches=recognize(message);value=wanted in matches
        return (value if op=='is' else not value),matches.get(wanted,'未发现所选智能特征')
    elif field in ('size_kb','learned'):
        value=message['raw_size']/1024 if field=='size_kb' else score(context['models'].get((rule['id'],message['account'])),message)
        if value is None:return False,'尚未学习本账号的目标文件夹示例'
        threshold=int(wanted);matched=value>threshold if op=='gt' else value<threshold if op=='lt' else value>=threshold if op=='gte' else value<=threshold
        return matched,('学习匹配分数 '+str(round(value,1)) if field=='learned' else '邮件大小 '+str(round(value,1))+' KiB')
    else:return False,'条件不受支持'
    return text_match(values,op,wanted),field+' '+op+' '+wanted

# ==========================================
# Function: Choose exactly one account-first/global-fallback destination for a source snapshot.
# Method: Stop at the first matching enabled rule and return its explanations even if the destination is already current.
# ==========================================
def first_match(message,items,context):
    account=message['account']
    for scope in (account,''):
        for rule in items:
            if not rule['enabled'] or rule['account']!=scope or account not in rule['destinations'] or not source_matches(rule,message,context['folders']):continue
            results=[]
            for condition in rule['conditions']:
                result=condition_matches(condition,message,context,rule);results.append(result)
                if (rule['mode']=='all' and not result[0]) or (rule['mode']=='any' and result[0]):break
            matched=all(value for value,unused in results) if rule['mode']=='all' else any(value for value,unused in results)
            if matched:
                return {'rule':rule['id'],'name':rule['name'],'destination':rule['destinations'][account],'reason':'；'.join(reason for matched,reason in results if matched)[:800]}
    return None
