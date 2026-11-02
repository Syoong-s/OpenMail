"""Persistent focused cards, independent of slow mailbox/body projections."""
from collections import OrderedDict
import ctypes as C
from .inbox_views import TITLES

PROJECTION_PREFERENCES=('priority_enabled','priority_limit','group_notification','group_newsletter',
                        'group_verification','labels_list','recognition_enabled','gatekeeper_mode')

# ==========================================
# Function: Identify preferences that affect mailbox query membership or metadata.
# Method: Exclude notification receipts, window geometry and other unrelated saved UI state.
# ==========================================
def projection_policy(store):
    return repr(tuple(store.preference(key) for key in PROJECTION_PREFERENCES))

# ==========================================
# Function: Display either known focused membership or an honest first-load placeholder.
# Method: Keep full grouping snapshots and compact cached descriptors on the same title contract.
# ==========================================
def summary_title(section):
    count=section.get('count',len(section.get('items',())))
    unread=section.get('unread',0)
    return section['title']+('   …' if count is None else '   '+str(count))+(f' · {unread} 未读' if unread else '')+'  ›'

# ==========================================
# Function: Keep focused cards available before expensive mailbox work completes.
# Method: Own a separate native list and eight small account/view-scoped metadata snapshots.
# ==========================================
class FocusPreviewUI:
    # ==========================================
    # Function: Reveal the last focused cards synchronously when returning to their scope.
    # Method: Reuse live widgets; refresh their counts through the normal latest-only query afterward.
    # ==========================================
    def show_focus_preview(self,request):
        view,category,scope,folder,search,limit,definition=request
        active=view=='inbox' and category=='all' and not folder and not search and not self.focus_group and definition['mode']=='focused'
        if not active:
            self.focus_preview_current=None;self.summary_rows={};self.g.gtk_widget_hide(self.widget('focus_summaries'))
            return
        store=self.service.store;key=repr((scope,definition,projection_policy(store)))
        cache=getattr(self,'focus_preview_cache',None)
        if cache is None:cache=self.focus_preview_cache=OrderedDict()
        cached=cache.get(key);sections=cached['sections'] if cached else None
        if sections is None:
            sections=[]
            for base in ('pinned','verification','notification','newsletter'):
                card=definition.get('cards',{}).get(base,{})
                grouping=card.get('grouping',store.preference('group_'+base,definition['grouping']))
                if base in definition['disabled'] or not card.get('enabled',True) or grouping=='none':continue
                sections.append({'key':base,'title':TITLES[base],'count':None,'unread':0,'recent_senders':[]})
        entering=getattr(self,'focus_preview_current',None)!=key
        self.focus_preview_current=key
        self.render_focus_summaries(sections,key,loading=key not in cache)
        if entering:
            self.g.label(self.widget('count'),str(cached['total'])+' 封邮件' if cached else '正在载入邮件…')
            self.g.label(self.widget('view_subtitle'),definition['name'])
            self.g.gtk_widget_hide(self.widget('focus_back'));self.g.gtk_widget_hide(self.widget('more'))
            self.g.gtk_widget_set_no_show_all(self.widget('messages'),1);self.g.gtk_widget_hide(self.widget('messages'))
            scroller=self.g.gtk_widget_get_ancestor(self.widget('focus_summaries'),self.g.gtk_scrolled_window_get_type())
            if scroller:
                setter=self.g.libs['gtk'].gtk_adjustment_set_value;setter.argtypes=[C.c_void_p,C.c_double];setter.restype=None
                setter(self.g.gtk_scrolled_window_get_vadjustment(scroller),0)

    # ==========================================
    # Function: Replace provisional card counts with the current authoritative local projection.
    # Method: Cache only compact descriptors and leave existing native cards attached to their host.
    # ==========================================
    def update_focus_preview(self,projection):
        key=getattr(self,'focus_preview_current',None)
        if key is None:return
        sections=[section for section in projection.get('sections') or [] if section.get('summary')]
        compact=[{'key':s['key'],'title':s['title'],'count':len(s['items']),'unread':s['unread'],
                  'recent_senders':list(s['recent_senders'])} for s in sections]
        self.focus_preview_cache.pop(key,None);self.focus_preview_cache[key]={'sections':compact,'total':projection['total']}
        while len(self.focus_preview_cache)>8:self.focus_preview_cache.popitem(last=False)
        self.render_focus_summaries(compact,key)

    # ==========================================
    # Function: Update four focused cards without waiting for normal row construction.
    # Method: Rebuild only when their scoped identities change; preserve all buttons otherwise.
    # ==========================================
    def render_focus_summaries(self,sections,key,loading=False):
        g=self.g;host=self.widget('focus_summaries');widgets=getattr(self,'focus_summary_widgets',{})
        self.focus_avatar_state=self.identity_colors.snapshot(item['account'] for section in sections for item in section['recent_senders'])
        if getattr(self,'focus_summary_widget_key',None)!=key or list(widgets)!=[s['key'] for s in sections]:
            g.disconnect('focus-summaries');g.clear(host);widgets={};self.focus_summary_widgets=widgets;self.focus_summary_widget_key=key
        self.summary_rows=widgets
        for section in sections:
            entry=widgets.get(section['key'])
            if entry is None:self.summary_row(section);entry=widgets[section['key']]
            else:
                entry['section']=section;g.label(entry['title'],summary_title(section));self.update_summary_senders(entry,section)
            g.gtk_widget_set_sensitive(entry['button'],not loading)
            g.gtk_widget_show_all(entry['row'])
        g.gtk_widget_set_visible(host,bool(sections))
