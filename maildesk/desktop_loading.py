"""Latest-only local read/projection workers, separate from slow network commands."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import time
import threading

# ==========================================
# Function: Keep rapid navigation from accumulating obsolete SQLite/MIME work.
# Method: Run at most one job per channel and retain only its latest requested successor.
# ==========================================
class LocalLoader:
    # ==========================================
    # Function: Own a bounded local executor and small immutable body-model cache.
    # Method: Reserve two foreground lanes for navigation/actions beside two bounded migration/projection workers.
    # ==========================================
    def __init__(self,app):
        self.app=app;self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='maildesk-local');self.foreground=ThreadPoolExecutor(max_workers=2,thread_name_prefix='maildesk-read');self.channels={};self.serial=0;self.closed=False;self.bodies=OrderedDict();self.body_bytes=0;self.body_lock=threading.RLock();self.address_due=time.monotonic()+.1;self.address_running=False;self.classification_policy=None;self.classification_due=0;self.classification_changed=False;self.classification_refresh=0

    # ==========================================
    # Function: Replace a pending request without touching GTK from a worker.
    # Method: Dispatch one current operation and queue its completion through the native loop.
    # ==========================================
    def request(self,channel,operation,success):
        if self.closed:return
        if channel=='list':
            enabled=bool(self.app.service.store.preference('recognition_enabled',True))
            if enabled!=self.classification_policy:self.classification_policy=enabled;self.classification_due=time.monotonic()+.1 if enabled else 0
        self.serial+=1;state=self.channels.setdefault(channel,{'running':False,'wanted':None,'channel':channel});state['wanted']=(self.serial,operation,success)
        if not state['running']:self.start(state)

    # ==========================================
    # Function: Execute one local snapshot while keeping stale errors invisible.
    # Method: Compare request serials on the main thread before applying a result or starting the next one.
    # ==========================================
    def start(self,state):
        serial,operation,success=state['wanted'];state['running']=True
        # ==========================================
        # Function: Commit only the latest snapshot on GTK's own thread.
        # Method: Clear the running flag before dispatch so nested refresh requests can replace it safely.
        # ==========================================
        def finish(pair):
            state['running']=False;wanted=state['wanted']
            if self.closed or self.app.closing:return
            if wanted and wanted[0]==serial:
                state['wanted']=None
                if pair[0]:success(pair[1])
                else:
                    if state['channel']=='read':self.app.pending_read_identity=''
                    if state['channel']=='chat':
                        self.app.chat_loading=False;self.app.chat_load_error=str(pair[1]);self.app.chat_snapshot_failed()
                    self.app.show_error(pair[1])
            if state['wanted'] and not state['running']:self.start(state)
        # ==========================================
        # Function: Produce a bounded snapshot without native widget access.
        # Method: Reuse one preference snapshot and transfer exceptions as values.
        # ==========================================
        def run():
            try:
                with self.app.service.store.preference_snapshot():result=(True,operation())
            except Exception as error:result=(False,error)
            self.app.queue.put((finish,result))
        (self.foreground if state['channel'] in ('chat','read') else self.executor).submit(run)

    # ==========================================
    # Function: Prioritize finite local user actions independently of network and indexing queues.
    # Method: Commit on the foreground pool and deliver success or failure through GTK's normal completion queue.
    # ==========================================
    def action(self,operation,success,failure):
        # ==========================================
        # Function: Execute an explicitly guarded local action without replacing another contact's operation.
        # Method: Transfer only values and exceptions to the application event loop.
        # ==========================================
        def run():
            try:result=operation()
            except Exception as error:self.app.queue.put((failure,error))
            else:self.app.queue.put((success,result))
        if not self.closed:self.foreground.submit(run)

    # ==========================================
    # Function: Invalidate local work when an explicit destination is cleared.
    # Method: Let the current short read finish while suppressing every stale completion.
    # ==========================================
    def cancel(self,channel):
        if channel in self.channels:self.channels[channel]['wanted']=None

    # ==========================================
    # Function: Prepare a selected RFC mail and its history outside GTK.
    # Method: Reuse the bounded common source LRU while querying mutable flags/thread metadata afresh.
    # ==========================================
    def message(self,identity):
        store=self.app.service.store;started=time.monotonic();message=store.get(identity);thread=store.thread(identity,message=message)
        canonical=next((row['id'] for row in thread if row['message_id']==message['message_id']),identity)
        source=message if canonical==identity else store.get(canonical)
        body=self.prepare_body(canonical,source['parsed'])
        from .address_book import sender_detail,message_sender_address
        parsed=message['parsed'];person=sender_detail(store,message_sender_address(store,identity,parsed))
        return {'message':message,'thread':thread,'bodies':{canonical:body},'person':person,'prepare_seconds':time.monotonic()-started}

    # ==========================================
    # Function: Prepare the same immutable rich source for mail and contact surfaces.
    # Method: Reuse admitted parsed rows, read raw MIME only for images and bound the LRU to 16MiB/32 sources.
    # ==========================================
    def prepare_body(self,identity,parsed):
        with self.body_lock:return self._prepare_body(identity,parsed)

    # ==========================================
    # Function: Serialize source LRU mutations across independent latest-only channels.
    # Method: Hold the worker-only cache lock through preparation and accounting.
    # ==========================================
    def _prepare_body(self,identity,parsed):
        from .quoted_history import split_history,history_sources,source_cids
        from .history_timeline import history_timeline
        from .mail_images import message_images
        import hashlib
        key=(identity,hashlib.sha256((parsed.get('html','')+'\0'+parsed.get('body','')+repr(parsed.get('attachments',[]))).encode()).digest())
        body=self.bodies.pop(key,None)
        if body:self.bodies[key]=body;return body
        model=split_history(parsed.get('html',''),parsed.get('body','') or '(无文字正文)')
        cids=set().union(*(source_cids(value) for value in history_sources(model)))
        attachments=parsed.get('attachments',[]);has_images=bool(cids) or 'multipart/related' in parsed.get('headers',{}).get('content-type','').lower() or any(item.get('type','').startswith('image/') or str(item.get('name','')).lower().endswith(('.png','.jpg','.jpeg','.gif','.webp','.bmp')) for item in attachments)
        images=message_images(self.app.service.store.get(identity,raw=True)['raw']) if has_images else []
        body={'history_model':model,'timeline_model':history_timeline(model),'images':images,'orphan_images':[image for image in images if not image.get('cid') or image['cid'].casefold() not in cids],'image_count':len(images),'attachments_info':attachments,'details_parsed':parsed}
        size=len(repr(body).encode('utf-8'))
        body['_bytes']=size
        if size<=16*1024*1024:
            while self.bodies and (len(self.bodies)>=32 or self.body_bytes+size>16*1024*1024):self.body_bytes-=self.bodies.popitem(last=False)[1]['_bytes']
            self.bodies[key]=body;self.body_bytes+=size
        return body

    # ==========================================
    # Function: Advance cached classification independently of visible mailbox queries.
    # Method: Schedule one bounded batch at a time on the existing tick and throttle list refreshes to once per second.
    # ==========================================
    def tick(self):
        if self.closed or self.app.closing:return
        now=time.monotonic()
        if self.address_due and now>=self.address_due and not self.address_running:
            self.address_running=True;self.address_due=0
            # ==========================================
            # Function: Advance two bounded durable local metadata migrations away from GTK.
            # Method: Share a serial loader channel and never scan complete MIME/job bodies on polling.
            # ==========================================
            def migrate():
                from .address_book import backfill
                from .navigation_index import backfill as navigation_backfill
                return backfill(self.app.service.store),navigation_backfill(self.app.service.store)
            # ==========================================
            # Function: Continue finite metadata batches without accumulating pending work.
            # Method: Schedule only after completion; retain a low-frequency check for imported old rows.
            # ==========================================
            def migrated(result):
                self.address_running=False
                self.address_due=time.monotonic()+(.2 if not result[0]['complete'] or not result[1] else 30)
                form=getattr(self.app,'settings_form',None)
                page=getattr(form,'contacts_page',None)
                if page and not form.closed and result[0]['complete'] and result[0]['processed']:page.load()
            self.request('address-index',migrate,migrated)
        if self.classification_changed and now-self.classification_refresh>=1:
            self.classification_changed=False;self.classification_refresh=now;self.app.refresh()
        if not self.classification_due or now<self.classification_due:return
        self.classification_due=0
        # ==========================================
        # Function: Process only one finite cached-mail batch away from GTK.
        # Method: Read current recognition state/revision after guarded updates, without starting a mailbox query first.
        # ==========================================
        def operation():
            from .classification_upgrade import upgrade_verification
            store=self.app.service.store;changed=upgrade_verification(store)
            return changed,store.preference('verification_classifier_revision',0)>=1 or not store.preference('recognition_enabled',True)
        # ==========================================
        # Function: Continue an unfinished upgrade without accumulating worker requests.
        # Method: Keep changed counts local and let one later refresh update the existing native list.
        # ==========================================
        def finished(result):
            changed,complete=result;self.classification_changed=self.classification_changed or bool(changed)
            if not complete:self.classification_due=time.monotonic()+.25
        self.request('classification',operation,finished)

    # ==========================================
    # Function: Release queued snapshots before the service/database closes.
    # Method: Cancel pending jobs, join only finite local work and drop cached body references.
    # ==========================================
    def close(self):
        self.closed=True
        for state in self.channels.values():state['wanted']=None
        self.foreground.shutdown(wait=True,cancel_futures=True);self.executor.shutdown(wait=True,cancel_futures=True);self.bodies.clear();self.body_bytes=0

# ==========================================
# Function: Query one immutable mailbox projection without native controls.
# Method: Batch complete focus groups, folder metadata and visible labels within one worker preference snapshot.
# ==========================================
def mailbox_projection(app,request):
    store=app.service.store;view,category,scope,folder,search,limit,definition=request;started=time.monotonic()
    if view=='inbox' and not folder and definition['mode']=='conversations' and not app.focus_group:
        core=app.contacts;rows=[];offset=0;result=None;indexing=None
        while offset<limit:
            result=core.list_conversations(account=scope,search=search,limit=min(100,limit-offset),offset=offset,backfill_limit=256 if not offset else 0,verification_limit=8 if not offset else 0,verification_bytes=getattr(app,'chat_verify_budget',32*1024*1024))
            if indexing is None:indexing=result['indexing']
            rows.extend(result['items']);offset+=len(result['items'])
            if not result['items'] or offset>=result['total']:break
        return {'contacts':True,'scope':scope,'items':rows,'total':result['total'],'indexing':indexing,'folders':store.list_folders(),'smart':store.smart_folders(),'prepare_seconds':time.monotonic()-started}
    full_groups=view=='inbox' and not search and category=='all' and definition['mode']=='focused';rows=[];offset=0;total=0
    if view=='drafts':
        store.prune_empty_drafts()
        while offset<limit:
            result=store.list_jobs(account=scope,search=search,offset=offset,limit=min(100,limit-offset))
            rows.extend(result['items']);total=result['total'];offset+=len(result['items'])
            if not result['items'] or offset>=total:break
    else:
        while offset<limit or full_groups:
            result=store.list_messages(view='all' if view in ('smart','folder') or search.strip() else view,category='' if category=='all' else category,account=scope,folder=folder,search=search,offset=offset,limit=100,all_items=full_groups)
            rows.extend(result['items']);total=result['total'];offset+=100
            if full_groups or not result['items'] or offset>=total:break
    sections=app.inboxes.sections(rows,definition) if view=='inbox' and not search and category=='all' else None
    if view!='drafts':
        from .mail_list_visuals import history_counts
        admitted=rows
        if sections is not None:
            from .desktop_focus import focused_render_items
            admitted=next((section['items'][:limit] for section in sections if section['key']==app.focus_group),[]) if app.focus_group else [row for row in focused_render_items(sections,limit)[0] if '_summary' not in row]
        counts=history_counts(store,[row['id'] for row in admitted])
        for row in admitted:row['history_count']=counts.get(row['id'],1)
    labels=store.labels_for([row['id'] for row in rows]) if view!='drafts' and store.preference('labels_list',True) else {}
    return {'items':rows,'total':total,'sections':sections,'folders':store.list_folders(),'smart':store.smart_folders(),'labels':labels,'new_count':store.list_messages(view='new_senders')['total'] if view=='inbox' and store.preference('gatekeeper_mode','off')=='explicit' else 0,'prepare_seconds':time.monotonic()-started}
