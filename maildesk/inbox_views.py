"""Local, durable inbox layouts inspired by Spark's public mode contracts."""
from copy import deepcopy
from datetime import datetime
import uuid

MODES = {'focused':'聚焦列表', 'smart':'未读卡片', 'classic':'简洁列表', 'conversations':'对话列表'}
TITLES = {'priority':'优先','personal':'个人','verification':'验证码','notification':'通知','newsletter':'动向','pinned':'已置顶','seen':'已读邮件','today':'今天','earlier':'更早'}

# ==========================================
# Function: Manage independent inbox definitions in the local preference store.
# Method: Validate all settings and preserve stable identifiers across launches.
# ==========================================
class InboxViews:
    # ==========================================
    # Function: Read or initialize the user's inbox layouts.
    # Method: Seed three real modes once and retain the selected view separately.
    # ==========================================
    def __init__(self, store):
        self.store = store
        if not store.preference('inbox_views', None):
            store.set_preference('inbox_views', [self.definition(mode, MODES[mode], mode) for mode in MODES])
        elif not any(row.get('mode')=='conversations' for row in self.all()):
            rows=self.all();rows.append(self.definition('conversations',MODES['conversations'],'conversations'));store.set_preference('inbox_views',rows)

    # ==========================================
    # Function: Build a validated local view definition.
    # Method: Reject unknown modes and use explicit per-card defaults.
    # ==========================================
    def definition(self, mode, name='', identity=None):
        if mode not in MODES: raise ValueError('未知收件箱视图')
        return {'id':identity or uuid.uuid4().hex, 'mode':mode, 'name':name.strip() or MODES[mode], 'accounts':[],
                'grouping':'category', 'limit':5, 'action':'seen', 'disabled':[], 'collapsed':[], 'cards':{}}

    # ==========================================
    # Function: Return isolated copies of saved definitions.
    # Method: Avoid mutating database settings through shared dictionaries.
    # ==========================================
    def all(self):
        return deepcopy(self.store.preference('inbox_views', []))

    # ==========================================
    # Function: Resolve the last selected inbox safely.
    # Method: Fall back to the first existing view after deletion or migration.
    # ==========================================
    def active(self):
        rows=self.all(); selected=self.store.preference('active_inbox_view','focused')
        return next((row for row in rows if row['id']==selected),rows[0])

    # ==========================================
    # Function: Add or replace a bounded, validated inbox configuration.
    # Method: Normalize supported fields before one atomic preference write.
    # ==========================================
    def save(self, value):
        clean=self.definition(value['mode'],value['name'],value['id'])
        if len(clean['name'])>60: raise ValueError('视图名称最多 60 个字符')
        clean['accounts']=list(dict.fromkeys(str(v) for v in value.get('accounts',[])))
        clean['grouping']=value.get('grouping','category')
        if clean['grouping'] not in ('category','sender','domain','account'): raise ValueError('未知分组方式')
        clean['limit']=int(value.get('limit',5))
        if clean['limit'] not in (3,5,10,0): raise ValueError('卡片显示数量无效')
        clean['action']=value.get('action','seen')
        if clean['action'] not in ('none','seen','done','trash'): raise ValueError('未知卡片操作')
        for key in ('disabled','collapsed'): clean[key]=list(dict.fromkeys(str(v) for v in value.get(key,[])))[:500]
        clean['cards']={}
        for key,card in value.get('cards',{}).items():
            if not isinstance(card,dict):raise ValueError('卡片设置无效')
            limit=int(card.get('limit',clean['limit']));action=card.get('action',clean['action']);grouping=card.get('grouping',clean['grouping'])
            if limit not in (3,5,10,0) or action not in ('none','seen','done','trash') or grouping not in ('category','sender','domain','account'):raise ValueError('卡片设置无效')
            clean['cards'][str(key)]={'enabled':bool(card.get('enabled',True)),'limit':limit,'action':action,'grouping':grouping,'accounts':list(dict.fromkeys(str(v) for v in card.get('accounts',[])))}
        rows=self.all(); index=next((i for i,row in enumerate(rows) if row['id']==clean['id']),len(rows))
        if index==len(rows):rows.append(clean)
        else:rows[index]=clean
        self.store.set_preference('inbox_views',rows)
        return clean

    # ==========================================
    # Function: Remove a custom or built-in view without deleting mail.
    # Method: Keep at least one layout available and repair active selection.
    # ==========================================
    def delete(self, identity):
        rows=[r for r in self.all() if r['id']!=identity]
        if not rows: raise ValueError('至少保留一个收件箱视图')
        self.store.set_preference('inbox_views',rows)
        self.store.set_preference('active_inbox_view',self.active()['id'])

    # ==========================================
    # Function: Project cached messages into distinct focused, card or classic sections.
    # Method: Assign each message exactly once, preserving chronological order within groups.
    # ==========================================
    def sections(self, items, definition=None):
        view=definition or self.active()
        rows=[row for row in items if not view['accounts'] or row['account'] in view['accounts']]
        rows.sort(key=lambda row:(-row['timestamp'],row['id']))
        if view['mode']=='classic': return [{'key':'all','title':'所有邮件','items':rows,'shown':rows,'collapsed':False}]
        groups={}
        priority_enabled=self.store.preference('priority_enabled',True)
        grouping_options={key:self.store.preference('group_'+key,view['grouping']) for key in ('notification','newsletter','verification')}
        priority_limit=self.store.preference('priority_limit',5)
        for row in rows:
            priority=row['priority'] and priority_enabled
            if view['mode']=='smart':
                key='seen' if row['seen'] else 'pinned' if row['pinned'] else 'priority' if priority else row['category']
            else:
                key='pinned' if row['pinned'] else 'priority' if priority else row['category'] if row['category']!='personal' else ('today' if datetime.fromtimestamp(row['timestamp']).date()==datetime.now().date() else 'earlier')
            card=view.get('cards',{}).get(key,{})
            if not card.get('enabled',True) or (card.get('accounts') and row['account'] not in card['accounts']):continue
            grouping=card.get('grouping',grouping_options.get(key,view['grouping']))
            if grouping=='none':key='today' if datetime.fromtimestamp(row['timestamp']).date()==datetime.now().date() else 'earlier'
            if key not in ('seen','pinned','priority','today','earlier') and grouping!='category':
                key=key+':'+grouping+':'+(row['account'] if grouping=='account' else row['sender'].rsplit('@',1)[-1] if grouping=='domain' else row['sender'])
            groups.setdefault(key,[]).append(row)
        order=['priority','today','personal','pinned','verification','notification','newsletter','earlier','seen']
        result=[]
        for key,values in sorted(groups.items(),key=lambda pair:(order.index(pair[0]) if pair[0] in order else 7,pair[0])):
            base=key.split(':',1)[0]
            if key in view['disabled'] or base in view['disabled']:continue
            card=view.get('cards',{}).get(base,{})
            limit=card.get('limit',priority_limit) if base=='priority' else card.get('limit',view['limit']) if view['mode']=='smart' else 0
            result.append({'key':key,'base':base,'action':card.get('action',view['action']),'title':TITLES.get(key,TITLES.get(base,base)+' · '+key.split(':',2)[-1]),'items':values,
                'shown':values[:limit] if limit else values,'collapsed':key in view['collapsed'],
                'summary':view['mode']=='focused' and base in ('pinned','verification','notification','newsletter'),
                'recent_senders':recent_senders(values),'unread':sum(not row['seen'] for row in values)})
        return result

    # ==========================================
    # Function: Resolve all cached members of a card beyond the visible list page.
    # Method: Apply account scope before paginated SQLite reads, then use the same grouping projection.
    # ==========================================
    def group_identities(self,key,definition,account=''):
        scope=tuple(definition['accounts']) if definition['accounts'] else account
        if account and definition['accounts']:scope=tuple(value for value in definition['accounts'] if value==account)
        rows=[];offset=0
        while True:
            page=self.store.list_messages(view='inbox',account=scope,offset=offset,limit=200)
            rows.extend(page['items']);offset+=len(page['items'])
            if not page['items'] or offset>=page['total']:break
        return next(([row['id'] for row in section['items']] for section in self.sections(rows,definition) if section['key']==key),[])

# ==========================================
# Function: Describe the latest distinct sender/account identities in a compact summary.
# Method: Keep full membership separately and return at most five newest avatars.
# ==========================================
def recent_senders(values):
    seen=set();result=[]
    for row in values:
        key=(row['account'],row['sender'].casefold())
        if key in seen:continue
        seen.add(key);result.append(row)
        if len(result)==5:break
    return result
