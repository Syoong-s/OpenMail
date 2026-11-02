"""Native idle-reader dashboard: a calendar and an actionable daily mail timeline."""
import ctypes as C
from datetime import date,datetime,timedelta
from .desktop_general import bind,P,I
from .ui_actions import icon_action,state_action


# ==========================================
# Function: Turn the unused reader pane into a calm local mail overview.
# Method: Retain native widgets and query metadata on the existing bounded background loader.
# ==========================================
class MailActivity:
    # ==========================================
    # Function: Build the overview once without taking focus from the message list.
    # Method: Add an independent stack page with compact statistics, calendar and timeline hosts.
    # ==========================================
    def __init__(self,app):
        self.app=app;self.g=g=app.g;self.selected=date.today();self.limit=60;self.data=None;self.rows={};self.visible=False;self.key=None;self.pending=None;self.scope_key=None
        self.root=g.gtk_scrolled_window_new(None,None);g.gtk_scrolled_window_set_policy(self.root,2,1);g.gtk_widget_set_name(self.root,b'mail_activity')
        self.body=g.gtk_box_new(1,22);self.style(self.body,'activity-body');g.gtk_container_add(self.root,self.body)
        header=g.gtk_box_new(1,5);g.gtk_box_pack_start(self.body,header,0,1,0)
        self.label(header,'邮件概览','activity-title');self.subtitle=self.label(header,'正在载入邮箱概览…','activity-muted')
        stats=g.gtk_box_new(0,14);bind(app,'gtk','gtk_box_set_homogeneous',None,P,I)(stats,1);g.gtk_box_pack_start(self.body,stats,0,1,0)
        self.stats={}
        for key,title,role in (('received','今天收到','activity-incoming'),('sent','今天发出','activity-outgoing'),('active_days','近一年活跃天数','activity-neutral')):
            box=g.gtk_box_new(1,6);self.style(box,'activity-stat');g.gtk_box_pack_start(stats,box,1,1,0)
            self.stats[key]=(self.label(box,title,'activity-muted'),self.label(box,'—','activity-number'));self.style(self.stats[key][1],role)
        calendar=g.gtk_box_new(1,13);self.style(calendar,'activity-calendar');g.gtk_box_pack_start(self.body,calendar,0,1,0)
        heading=g.gtk_box_new(0,10);g.gtk_box_pack_start(calendar,heading,0,1,0);self.label(heading,'收发热力图','activity-section',True);self.label(heading,'近一年','activity-chip')
        from .activity_heatmap import ActivityHeatmap
        self.heatmap=ActivityHeatmap(self);g.gtk_box_pack_start(calendar,self.heatmap.widget,0,1,0)
        footer=g.gtk_box_new(0,6);g.gtk_box_pack_start(calendar,footer,0,1,0)
        self.year_total=self.label(footer,'正在整理邮件记录…','activity-muted',True);self.label(footer,'少','activity-muted')
        for index in range(5):
            swatch=g.gtk_box_new(0,0);self.style(swatch,'activity-level-'+str(index));self.style(swatch,'activity-swatch');g.gtk_widget_set_valign(swatch,3);g.gtk_box_pack_start(footer,swatch,0,0,0)
        self.label(footer,'多','activity-muted')
        section=g.gtk_box_new(1,7);g.gtk_box_pack_start(self.body,section,0,1,0)
        line=g.gtk_box_new(0,8);g.gtk_box_pack_start(section,line,0,1,0);self.day_title=self.label(line,'今天','activity-section',True)
        self.previous=self.button(line,'前一天','action-back',lambda:self.select_day(self.selected-timedelta(days=1)))
        self.today_button=g.gtk_button_new_with_label('今天'.encode());self.style(self.today_button,'activity-today');g.gtk_box_pack_start(line,self.today_button,0,0,0)
        g.connect(self.today_button,'clicked',lambda *unused:self.select_day(date.today()),group='activity')
        self.next=self.button(line,'后一天','action-next',lambda:self.select_day(self.selected+timedelta(days=1)))
        self.day_count=self.label(section,'正在载入当天邮件…','activity-muted')
        self.timeline=g.gtk_box_new(1,0);g.gtk_box_pack_start(self.body,self.timeline,0,1,0)
        self.empty=g.gtk_box_new(1,8);self.style(self.empty,'activity-empty');g.gtk_widget_set_no_show_all(self.empty,1);g.gtk_box_pack_start(self.body,self.empty,0,1,0)
        self.label(self.empty,'这一天还没有邮件往来','activity-empty-title');self.empty_note=self.label(self.empty,'选择其他日期，回顾之前的邮件','activity-muted')
        self.more=g.gtk_button_new_with_label('展开更多邮件'.encode());self.style(self.more,'activity-more');g.gtk_box_pack_start(self.body,self.more,0,1,0);g.gtk_widget_set_no_show_all(self.more,1)
        g.connect(self.more,'clicked',lambda *unused:self.load_more(),group='activity')
        coverage=self.label(self.body,'统计已同步邮件 · 不含垃圾邮件、废纸篓与草稿','activity-footnote')
        g.gtk_widget_set_tooltip_text(coverage,'按邮件日期统计；已归档邮件仍保留在概览中，同一账户的重复文件夹副本合并显示。'.encode())
        bind(app,'gtk','gtk_stack_add_named',None,P,P,C.c_char_p)(app.widget('reader_stack'),self.root,b'activity')
        g.gtk_widget_show_all(self.root)

    # ==========================================
    # Function: Attach one semantic CSS role to a native widget.
    # Method: Keep palette choices in the shared theme instead of per-widget providers.
    # ==========================================
    def style(self,widget,role):self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(widget),role.encode())

    # ==========================================
    # Function: Create a single-line label with bounded width and meaningful visual hierarchy.
    # Method: Let expanding labels absorb available space and ellipsize without widening the window.
    # ==========================================
    def label(self,host,text,role,expand=False):
        g=self.g;widget=g.gtk_label_new(text.encode());g.gtk_label_set_xalign(widget,0);g.gtk_label_set_ellipsize(widget,3);g.gtk_label_set_max_width_chars(widget,60)
        self.style(widget,role);g.gtk_box_pack_start(host,widget,expand,1,0);return widget

    # ==========================================
    # Function: Add a compact accessible action without disturbing selected mail or list rows.
    # Method: Keep callbacks in the owning row's lifecycle group and use existing vector assets.
    # ==========================================
    def button(self,host,title,icon,callback,group='activity'):
        g=self.g;button=g.gtk_button_new();icon_action(g,button,title,icon,15);self.style(button,'activity-action');g.gtk_widget_set_valign(button,3)
        g.gtk_box_pack_start(host,button,0,0,0);g.connect(button,'clicked',lambda *unused:self.app.run_action(callback),group=group);return button

    # ==========================================
    # Function: Reveal retained overview widgets whenever no document, mail or chat owns the reader.
    # Method: Restore the stack page immediately and request fresh local metadata independently.
    # ==========================================
    def show(self):
        self.visible=True;self.g.gtk_stack_set_visible_child_name(self.app.widget('reader_stack'),b'activity');self.refresh()

    # ==========================================
    # Function: Stop obsolete overview work when the user begins reading or composing.
    # Method: Invalidate its worker channel without destroying retained dashboard widgets.
    # ==========================================
    def hide(self):
        if self.visible:
            self.visible=False;self.pending=None
            if getattr(self.app,'local_loader',None):self.app.local_loader.cancel('activity')

    # ==========================================
    # Function: Refresh only when account scope, calendar date or committed local data changes.
    # Method: Use latest-only background requests and retain a coherent page while the next result is prepared.
    # ==========================================
    def refresh(self):
        if not self.visible or self.app.closing:return
        app=self.app;g=self.g;store=app.service.store
        account=(g.gtk_combo_box_get_active_id(app.widget('account_filter')) or b'all').decode()
        configured=app.inboxes.active()['accounts'] if app.view=='inbox' else []
        scope=tuple(configured) if account=='all' and configured else None if account=='all' else (account,) if not configured or account in configured else ()
        accounts={key:value.email for key,value in app.service.accounts.items()}
        if app.profile.demo:accounts['demo']='demo@example.com'
        today=date.today()
        if self.data and self.selected.isoformat()==self.data['today'] and today.isoformat()!=self.data['today']:self.selected=today;self.limit=60
        with store.db() as db:revision=db.execute("SELECT value FROM navigation_revision WHERE topic='mail'").fetchone()[0]
        scope_key=(scope,tuple(accounts.items()));key=(revision,scope_key,today,self.selected,self.limit)
        if key==self.pending or key==self.key:return
        if self.scope_key!=scope_key:
            self.scope_key=scope_key;self.data=None;self.heatmap.data=None;self.render_rows([]);g.gtk_widget_queue_draw(self.heatmap.widget)
            for title,value in self.stats.values():g.label(value,'—')
            g.label(self.year_total,'正在整理邮件记录…');g.label(self.day_count,'正在载入当天邮件…')
            g.gtk_widget_hide(self.empty);g.gtk_widget_hide(self.more)
        self.pending=key
        if not getattr(app,'local_loader',None):
            from .desktop_loading import LocalLoader
            app.local_loader=LocalLoader(app)
        from .mail_activity import activity_snapshot

        # ==========================================
        # Function: Apply one current local calendar snapshot on GTK's own thread.
        # Method: Discard superseded scope/date results and update stable timeline controls in place.
        # ==========================================
        def ready(result):
            if not self.visible or self.pending!=key:return
            self.pending=None;self.key=key;self.data=result;self.heatmap.data=result;self.render(result)
        app.local_loader.request('activity',lambda:activity_snapshot(store,accounts,scope,key[3],key[4],today),ready)

    # ==========================================
    # Function: Change the displayed civil day without losing the calendar or account context.
    # Method: Bound selections to the available year and reset only timeline pagination.
    # ==========================================
    def select_day(self,day):
        from .mail_activity import calendar_bounds
        self.selected=max(calendar_bounds(date.today())[0],min(day,date.today()));self.limit=60
        self.g.gtk_widget_queue_draw(self.heatmap.widget);self.refresh()

    # ==========================================
    # Function: Make all of a busy day's messages reachable without eager widget construction.
    # Method: Increase the local page in finite 60-message increments.
    # ==========================================
    def load_more(self):self.limit+=60;self.refresh()

    # ==========================================
    # Function: Update statistics and day navigation from a coherent completed query.
    # Method: Show real zero states, exact coverage and independent incoming/outgoing counts.
    # ==========================================
    def render(self,result):
        g=self.g;day=self.selected;today=date.fromisoformat(result['today']);counts=result['days'].get(day.isoformat(),{})
        date_title='今天' if day==today else day.strftime('%m月%d日');g.label(self.day_title,date_title+'  ·  '+day.strftime('%Y.%m.%d'))
        g.label(self.subtitle,today.strftime('%Y年%m月%d日')+' · '+('全部账户' if self.scope_key[0] is None else '所选账户'))
        for key,title in (('received','收到'),('sent','发出')):
            g.label(self.stats[key][0],('今天' if day==today else day.strftime('%m月%d日'))+title);g.label(self.stats[key][1],str(counts.get(key,0)))
        g.label(self.stats['active_days'][1],str(result['active_days']))
        g.label(self.year_total,f"共 {result['received']+result['sent']} 封 · 收到 {result['received']} / 发出 {result['sent']}")
        g.label(self.day_count,f"{result['total']} 封邮件  ·  收到 {counts.get('received',0)}  /  发出 {counts.get('sent',0)}")
        g.gtk_widget_set_sensitive(self.next,day<today);g.gtk_widget_set_sensitive(self.previous,day.isoformat()>result['start']);g.gtk_widget_set_sensitive(self.today_button,day!=today)
        self.render_rows(result['items']);g.gtk_widget_queue_draw(self.heatmap.widget)
        g.gtk_widget_set_visible(self.empty,not result['items'])
        if not result['items']:
            g.gtk_widget_set_no_show_all(self.empty,0);g.gtk_widget_show_all(self.empty);g.gtk_widget_set_no_show_all(self.empty,1)
        g.gtk_widget_set_visible(self.more,len(result['items'])<result['total'])

    # ==========================================
    # Function: Reconcile timeline membership while keeping unaffected buttons and row positions alive.
    # Method: Key rows by durable source ID and rebuild only changed content, not local read/archive state.
    # ==========================================
    def render_rows(self,items):
        g=self.g;keep={item['id'] for item in items}
        for identity in list(self.rows):
            if identity not in keep:g.disconnect('activity-row-'+identity);g.gtk_widget_destroy(self.rows.pop(identity)['root'])
        for index,item in enumerate(items):
            identity=item['id'];entry=self.rows.get(identity);signature=tuple(item[key] for key in ('sender','sender_name','recipients','subject','preview','direction','timestamp'))
            if entry and entry['signature']!=signature:g.disconnect('activity-row-'+identity);g.gtk_widget_destroy(entry['root']);entry=None
            if entry is None:entry=self.rows[identity]=self.create_row(item);entry['signature']=signature
            entry['item']=item;g.gtk_box_reorder_child(self.timeline,entry['root'],index)
            for key in ('done','seen'):
                state_action(g,entry[key],('移回收件箱' if item[key] else '完成并归档') if key=='done' else ('标为未读' if item[key] else '标为已读'),'spark-layout-'+key,bool(item[key]),14)
            context=g.gtk_widget_get_style_context(entry['subject']);(g.gtk_style_context_remove_class if item['seen'] else g.gtk_style_context_add_class)(context,b'activity-unread')
            g.gtk_widget_show_all(entry['root'])

    # ==========================================
    # Function: Create one linked mail overview with an explicit source and three compact actions.
    # Method: Separate reading from mutation buttons and keep sender/body text bounded in the native row.
    # ==========================================
    def create_row(self,item):
        g=self.g;identity=item['id'];group='activity-row-'+identity;root=g.gtk_box_new(0,12);self.style(root,'activity-row')
        rail=g.gtk_box_new(1,0);g.gtk_box_pack_start(root,rail,0,1,0)
        node=self.label(rail,'↑' if item['direction']=='sent' else '↓','activity-node');self.style(node,'activity-outgoing' if item['direction']=='sent' else 'activity-incoming')
        g.gtk_label_set_xalign(node,.5)
        connector=g.gtk_box_new(1,0);self.style(connector,'activity-connector');g.gtk_widget_set_halign(connector,3);g.gtk_box_pack_start(rail,connector,1,1,3)
        open_button=g.gtk_button_new();self.style(open_button,'activity-open');g.gtk_box_pack_start(root,open_button,1,1,0)
        content=g.gtk_box_new(1,5);g.gtk_container_add(open_button,content)
        sender=('发给 '+(item['recipients'] or '收件人')) if item['direction']=='sent' else item['sender_name'] or item['sender']
        self.label(content,sender,'activity-author');subject=self.label(content,item['subject'] or '无主题','activity-subject');self.label(content,item['preview'] or '无文字正文','activity-preview')
        g.gtk_widget_set_tooltip_text(open_button,(sender+'\n'+item['subject']).encode())
        g.connect(open_button,'clicked',lambda *unused:self.app.run_action(lambda:self.app.read(identity)),group=group)
        trailing=g.gtk_box_new(1,9);g.gtk_widget_set_valign(trailing,1);g.gtk_widget_set_margin_top(trailing,3);g.gtk_box_pack_start(root,trailing,0,0,0)
        stamp=self.label(trailing,datetime.fromtimestamp(item['timestamp']).strftime('%H:%M'),'activity-time');g.gtk_label_set_xalign(stamp,1)
        actions=g.gtk_box_new(0,3);g.gtk_box_pack_start(trailing,actions,0,0,0)
        entry={'root':root,'subject':subject,'open':open_button}
        for code,title in (('done','完成并归档'),('seen','标为已读'),('trash','移到废纸篓')):
            entry[code]=self.button(actions,title,'spark-layout-'+code,lambda code=code:self.act(identity,code),group)
        g.gtk_box_pack_start(self.timeline,root,0,1,0);return entry

    # ==========================================
    # Function: Apply timeline actions locally without changing the reader/list selection.
    # Method: Serialize one captured identity's mutation through the same durable action worker as mail views.
    # ==========================================
    def act(self,identity,action):
        app=self.app
        copies=list(self.rows.get(identity,{}).get('item',{}).get('copy_ids',[identity]))

        # ==========================================
        # Function: Resolve the latest committed state immediately before executing a quick action.
        # Method: Preserve click order and use actual archive/trash mappings rather than display-only flags.
        # ==========================================
        def operation():
            state=app.service.store.state(identity)
            if action=='seen':return app.service.bulk_flags(copies,'seen',not all(app.service.store.state(copy)['seen'] for copy in copies))
            return app.service.move_message(identity,special=('inbox' if state['done'] else 'archive') if action=='done' else 'trash')
        app.local_loader.action(operation,lambda result:app.mail_changed([identity]),app.show_error)
