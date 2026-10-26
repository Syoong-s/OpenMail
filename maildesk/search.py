"""Bound, composable search predicates for cached mail and smart folders."""
from datetime import datetime
import shlex

# ==========================================
# Function: Compile a human-readable mail query into bound SQLite predicates.
# Method: Tokenize quoted phrases and recognized operators, never interpolate values.
# ==========================================
def search_terms(query):
    if len(query)>2000:
        raise ValueError('搜索条件过长')
    try:
        tokens=shlex.split(query)
    except ValueError:
        raise ValueError('搜索引号尚未闭合') from None
    clauses,values=[],[]
    for token in tokens:
        negative=token.startswith('-')
        token=token[1:] if negative else token
        key,sep,value=token.partition(':')
        key=key.lower()
        clause,params='',[]
        if sep and key in ('from','to','subject','body','in','folder','account','category'):
            column={'from':'sender','to':"json_extract(parsed,'$.recipients')",'in':'folder'}.get(key,key)
            clause=f'{column} LIKE ? ESCAPE \'\\\''
            params=['%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%']
        elif sep and key=='is':
            clause={'unread':'seen=0','read':'seen=1','pinned':'pinned=1','starred':'pinned=1','priority':'priority=1','done':'done=1','aside':'aside=1','snoozed':'snoozed_until>strftime(\'%s\',\'now\')'}.get(value.lower(),'')
            if not clause:
                raise ValueError('未知 is: 条件')
        elif sep and key=='has' and value=='attachment':
            clause="json_array_length(parsed,'$.attachments')>0"
        elif sep and key in ('before','after'):
            try:
                moment=datetime.fromisoformat(value).timestamp()
            except ValueError:
                raise ValueError('日期格式应为 YYYY-MM-DD') from None
            clause='timestamp'+('<' if key=='before' else '>=')+'?';params=[moment]
        elif sep and key=='label':
            clause='id IN (SELECT message FROM message_labels WHERE label=?)';params=[value]
        else:
            clause='(subject LIKE ? OR sender LIKE ? OR body LIKE ?)';params=['%'+token+'%']*3
        clauses.append(('NOT ('+clause+')') if negative else '('+clause+')')
        values.extend(params)
    return clauses,values
