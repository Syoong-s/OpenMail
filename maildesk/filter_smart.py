"""Explainable local email recognition and explicitly trained account-scoped Bayesian similarity."""
from collections import Counter
import json,math,re,time,unicodedata

# ==========================================
# Function: Compare multilingual user text predictably without executing patterns or contacting a model service.
# Method: Normalize compatibility forms and Unicode case once for local deterministic matching.
# ==========================================
def normalize(value):return unicodedata.normalize('NFKC',str(value or '')).casefold()

# ==========================================
# Function: Recognize semantic mail types from standard headers, MIME metadata and bounded text cues.
# Method: Prefer explicit list/calendar/auto-response evidence and retain the application's own corrected category as fallback.
# ==========================================
def recognize(message):
    parsed=message.get('parsed',message);headers=parsed.get('headers',{});subject=normalize(parsed.get('subject',''));body=normalize(parsed.get('body','')[:32768]);result={}
    category=message.get('category')
    if not category:
        from .classifier import classify
        category,reason=classify(parsed)
    else:reason=message.get('reason','使用当前邮件类别')
    result[category]=reason
    if headers.get('list-id') or headers.get('list-unsubscribe') or normalize(headers.get('precedence')) in ('bulk','list'):result['newsletter']='包含邮件列表、退订或批量投递邮件头'
    auto=normalize(headers.get('auto-submitted')).split(';',1)[0].strip()
    if auto=='auto-replied':result['auto_reply']='Auto-Submitted 标记为自动回复'
    if auto and auto!='no':result['notification']='Auto-Submitted 标记为自动生成或自动回复'
    attachment_types={normalize(part.get('type','')) for part in parsed.get('attachments',[])}
    if 'text/calendar' in normalize(headers.get('content-type')) or 'text/calendar' in attachment_types or any(normalize(part.get('name','')).endswith('.ics') for part in parsed.get('attachments',[])) or ('begin:vcalendar' in body and 'begin:vevent' in body):result['calendar']='包含日历 MIME、ICS 附件或标准日历事件'
    terms=('发票','电子账单','账单','收据','invoice','payment receipt','billing statement','tax receipt')
    if any(term in subject for term in terms):result['invoice']='主题包含账单、收据或发票特征'
    elif any(term in normalize(part.get('name','')) for part in parsed.get('attachments',[]) for term in terms):result['invoice']='附件名称包含账单、收据或发票特征'
    if len(result)>1:result.pop('personal',None)
    return result

# ==========================================
# Function: Extract bounded multilingual evidence for a local similarity model.
# Method: Use Bernoulli word/Chinese-bigram presence, separate subject cues and stable sender/domain metadata.
# ==========================================
def features(message):
    parsed=message.get('parsed',message);tokens=set()
    for prefix,text in (('s:',parsed.get('subject','')[:1000]),('t:',parsed.get('body','')[:8192])):
        text=normalize(text)
        words=re.findall(r'[a-z][a-z0-9._+-]{1,39}',text)
        for run in re.findall(r'[\u3400-\u9fff]{2,}',text):words.extend(run[index:index+2] for index in range(min(len(run)-1,1024)))
        tokens.update(prefix+word for word in words[:400])
    sender=normalize(parsed.get('sender',''))
    if sender:tokens.add('from:'+sender);tokens.add('domain:'+sender.rsplit('@',1)[-1])
    for part in parsed.get('attachments',[])[:20]:tokens.add('mime:'+normalize(part.get('type','')))
    return sorted(tokens)[:512]

# ==========================================
# Function: Learn one rule's target-folder style from an explicit local cached-data request.
# Method: Use at least five distinct positive and five negative RFC examples, smoothing and a bounded discriminative vocabulary.
# ==========================================
def train(store,rule,account):
    target=rule['destinations'].get(account)
    if not target:raise ValueError('请先为这个账号设置目标文件夹')
    with store.db() as db:
        positive=db.execute('SELECT message_id,parsed FROM messages WHERE account=? AND folder=? AND remote_gone=0 GROUP BY message_id ORDER BY timestamp DESC LIMIT 200',(account,target)).fetchall()
        negative=db.execute('''SELECT m.message_id,m.parsed FROM messages m WHERE m.account=? AND m.folder<>? AND m.folder NOT LIKE '@%'
            AND m.remote_gone=0 AND NOT EXISTS(SELECT 1 FROM messages p WHERE p.account=m.account AND p.folder=? AND p.remote_gone=0 AND p.message_id=m.message_id)
            GROUP BY m.message_id ORDER BY m.timestamp DESC LIMIT 200''',(account,target,target)).fetchall()
    if len(positive)<5 or len(negative)<5:raise ValueError('学习至少需要目标文件夹5封、其他文件夹5封不同的已缓存邮件')
    counts=[]
    for rows in (positive,negative):
        count=Counter()
        for row in rows:count.update(features(json.loads(row['parsed'])))
        counts.append(count)
    pos,neg=counts;np,nn=len(positive),len(negative);vocabulary=set(pos)|set(neg);weights={};rank=[]
    for token in vocabulary:
        p=(pos[token]+1)/(np+2);n=(neg[token]+1)/(nn+2);absent=math.log((1-p)/(1-n));delta=math.log(p/n)-absent
        if pos[token]+neg[token]>=2:rank.append((abs(delta),token,absent,delta))
    rank.sort(reverse=True);base=0
    for unused,token,absent,delta in rank[:2048]:base+=absent;weights[token]=round(delta,8)
    if not weights:raise ValueError('示例缺少可学习的共同特征，请添加更多邮件')
    model={'version':1,'positive':np,'negative':nn,'base':base,'weights':weights,'target':target}
    with store.db() as db:db.execute('INSERT INTO mail_filter_models VALUES(?,?,?,?) ON CONFLICT(rule,account) DO UPDATE SET payload=excluded.payload,updated=excluded.updated',(rule['id'],account,json.dumps(model,ensure_ascii=False),time.time()))
    return {'positive':np,'negative':nn,'features':len(weights),'target':target}

# ==========================================
# Function: Score similarity to the user's explicitly chosen target-folder examples.
# Method: Apply smoothed Bernoulli evidence with tempered log odds; return a matching score rather than a calibrated probability.
# ==========================================
def score(model,message):
    if not model:return None
    value=(model['base']+sum(model['weights'].get(token,0) for token in features(message)))/3
    return 100/(1+math.exp(-max(-40,min(40,value))))
