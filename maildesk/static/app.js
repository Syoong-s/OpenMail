'use strict';
const $ = selector => document.querySelector(selector);
const labels = {inbox:'统一收件箱',unread:'未读邮件',priority:'优先处理',pinned:'置顶邮件',sent:'已发送',drafts:'草稿与发件箱',archive:'本地归档'};
const categories = {personal:'个人',verification:'验证码',notification:'通知',newsletter:'订阅'};
const jobLabels = {draft:'草稿',queued:'等待发送',sending:'正在发送',sent:'已发送',failed:'发送失败',uncertain:'结果待确认',partial:'部分收件人已接受'};
let session, view='inbox', category='', selected='', items=[], total=0, csrf='', toastTimer, searchTimer, draftId=null, replyHeaders={}, savedAttachments=[], generation=0, requestGeneration=0, lastSync=null, lastJobs='';

// ==========================================
// Function: Call a local application endpoint.
// Method: Same-origin fetch with session cookies and a CSRF header on mutations.
// ==========================================
async function api(path, data) {
  const options = data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-TeleMail-CSRF':csrf},body:JSON.stringify(data)};
  const response = await fetch(path, options);
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求未完成');
  return value;
}

// ==========================================
// Function: Create DOM nodes without interpreting mail as markup.
// Method: Assign untrusted text through textContent, never innerHTML.
// ==========================================
function el(tag, className='', text='') {
  const node=document.createElement(tag); node.className=className; node.textContent=text; return node;
}

// ==========================================
// Function: Present a short action result.
// Method: Replace the current toast and reset its dismissal timer.
// ==========================================
function toast(message) {
  $('#toast').textContent=message; $('#toast').hidden=false; clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>{$('#toast').hidden=true;},6500);
}

// ==========================================
// Function: Surface asynchronous failures from user actions.
// Method: Wrap event handlers and display their public error messages.
// ==========================================
function action(callback) {
  return async event => {try {await callback(event);} catch(error){toast(error.message);}};
}

// ==========================================
// Function: Format local mailbox times.
// Method: Use the browser's time zone and locale rather than host server settings.
// ==========================================
function dateText(timestamp, full=false) {
  return new Date(timestamp*1000).toLocaleString('zh-CN', full ? {month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'} : {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}

// ==========================================
// Function: Clear a stale reader when switching mail views.
// Method: Build the empty state from inert DOM elements.
// ==========================================
function emptyReader() {
  selected=''; generation++;
  const empty=el('div','reader-empty'); empty.append(el('div','empty-symbol','✧'),el('h2','','给阅读留一点空间'),el('p','','选择一封邮件，开始处理今天的信息。'));
  $('#reader').replaceChildren(empty);
}

// ==========================================
// Function: Render a page of message cards.
// Method: Preserve server identifiers in closures and show only inert previews.
// ==========================================
function renderList() {
  const list=$('#message-list'); list.replaceChildren();
  for(const message of items) {
    const card=el('button','message-card'+(message.seen?'':' unread')+(selected===message.id?' selected':''));
    card.dataset.category=message.category;
    const top=el('div','card-top');
    top.append(el('span','sender-avatar',(message.sender || '?').slice(0,1).toUpperCase()),el('span','sender-name',message.sender || '(未知发件人)'),el('time','card-time',dateText(message.timestamp)));
    const meta=el('div','card-meta'); meta.append(el('span','category-tag',categories[message.category]));
    if(message.priority)meta.append(el('span','','☆ 优先'));
    if(message.pinned)meta.append(el('span','','⌑ 置顶'));
    card.append(top,el('div','card-subject',message.subject || '(无主题)'),el('div','card-preview',message.preview || '(无正文)'),meta);
    card.addEventListener('click',action(()=>openMessage(message.id))); list.append(card);
  }
  if(!items.length)list.append(el('div','empty-list','这里暂时没有邮件。'));
  $('#result-count').textContent=total+' 封邮件'; $('#footer-count').textContent='已显示 '+items.length+' / '+total+' 封';
  $('#load-more').hidden=items.length>=total;
  if(view==='inbox' && !category && !$('#search').value && !$('#account-filter').value)$('#inbox-count').textContent=total;
}

// ==========================================
// Function: Fetch filtered messages with stale-response protection.
// Method: Use an incrementing request sequence and explicit offset pagination.
// ==========================================
async function loadMessages(more=false) {
  if(view==='drafts'){await loadJobs();return;}
  const sequence=++requestGeneration;
  const query=new URLSearchParams({view,category,account:$('#account-filter').value,search:$('#search').value,offset:more?items.length:0});
  const data=await api('/api/messages?'+query);
  if(sequence!==requestGeneration)return;
  items=more?items.concat(data.items):data.items; total=data.total; renderList();
}

// ==========================================
// Function: Build a reader toolbar action.
// Method: Post explicit state changes, then refresh the message and current filter.
// ==========================================
function tool(text, callback, active=false) {
  const button=el('button',active?'on':'',text); button.type='button';
  button.addEventListener('click',action(callback)); return button;
}

// ==========================================
// Function: Read and present a full message and reference-linked conversation.
// Method: Render only text, and expose attachments exclusively as downloads.
// ==========================================
async function openMessage(id) {
  const sequence=++generation; const data=await api('/api/message?id='+encodeURIComponent(id));
  if(sequence!==generation)return;
  selected=id; renderList();
  const m=data.message, p=m.parsed, reader=$('#reader'); reader.replaceChildren();
  const toolbar=el('div','reader-tools'), group=el('div','reader-tools-group');
  // ==========================================
  // Function: Apply a selected message change from the reader toolbar.
  // Method: Wait for the mutation before refreshing all affected views.
  // ==========================================
  const change=async changes=>{await api('/api/update',{id,changes});await loadMessages();await openMessage(id);};
  group.append(tool(m.seen?'标为未读':'标为已读',()=>change({seen:!m.seen})),tool(m.pinned?'⌑ 已置顶':'⌑ 置顶',()=>change({pinned:!m.pinned}),m.pinned),tool(m.priority?'☆ 已优先':'☆ 优先',()=>change({priority:!m.priority}),m.priority),tool(m.archived?'移回收件箱':'本地归档',async()=>{await change({archived:!m.archived});toast(m.archived?'已移回本地收件箱':'已在本机归档');}));
  const exportLink=el('a','note','导出 ↗'); exportLink.href='/api/export?id='+encodeURIComponent(id); toolbar.append(group,exportLink);
  const sender=el('div','reader-sender'), info=el('div','sender-block');
  info.append(el('strong','',p.sender_name || p.sender),el('small','',p.sender+' → '+p.recipients));
  sender.append(el('span','sender-avatar',(p.sender_name || p.sender || '?').slice(0,1).toUpperCase()),info,el('time','',dateText(p.timestamp,true)));
  const classification=el('div','classification'), select=el('select');select.setAttribute('aria-label','修改邮件分类');
  for(const [key,name] of Object.entries(categories)){const option=el('option','',name);option.value=key;select.append(option);}select.value=m.category;
  select.addEventListener('change',action(async()=>{
    const learn=confirm('是否记住此发件人的分类？\n“确定”：同账户中未来邮件和未单独纠正的旧邮件沿用此分类。\n“取消”：只修改这一封。');
    await change({category:select.value,learn_sender:learn});toast('分类已更新');
  }));
  classification.append(el('span','','邮件分类'),select,el('span','',m.reason));
  const body=el('div','mail-body',p.body || '(这封邮件没有可显示的文字正文)');
  reader.append(toolbar,el('h2','reader-title',m.subject),sender,classification,body);
  if(p.attachments.length){const attachments=el('div','attachment-list');for(const a of p.attachments){const link=el('a','attachment-link','↓ '+a.name+' · '+Math.ceil(a.size/1024)+' KB');link.href='/api/attachment?'+new URLSearchParams({id,index:a.index});attachments.append(link);}reader.append(attachments);}
  const reply=el('div','reply-box');reply.append(el('span','','让对话继续，写下你的回应。'),tool('回复这封邮件 ↗',()=>openComposer({account:m.account,to:p.sender,subject:/^re:/i.test(m.subject)?m.subject:'Re: '+m.subject,in_reply_to:p.message_id,references:[...p.references,p.message_id].join(' ')})));reader.append(reply);
  if(data.thread.length>1){const threads=el('div','thread-list','同一会话 · '+data.thread.length+' 封');for(const item of data.thread){const link=tool(item.sender+' · '+item.subject,()=>openMessage(item.id));link.className='thread-item';threads.append(link);}reader.append(threads);}
}

// ==========================================
// Function: Show durable drafts and delivery results.
// Method: Reflect terminal uncertainty honestly and allow queued delivery cancellation.
// ==========================================
async function loadJobs() {
  const sequence=++requestGeneration; const jobs=await api('/api/jobs'); if(view!=='drafts'||sequence!==requestGeneration)return;
  lastJobs=JSON.stringify(jobs); const account=$('#account-filter').value, search=$('#search').value.toLowerCase();
  const rows=jobs.filter(j=>(!account||j.account===account)&&(!search||((j.draft.subject||'')+' '+(j.draft.to||'')+' '+(j.draft.body||'')).toLowerCase().includes(search)));
  const list=$('#message-list');list.replaceChildren();$('#result-count').textContent=rows.length+' 项';$('#footer-count').textContent='草稿和发件任务保存在本机';$('#load-more').hidden=true;
  for(const job of rows){
    const card=el('button','message-card');card.append(el('div','job-state',jobLabels[job.state]),el('div','card-subject',job.draft.subject || '(无主题)'),el('div','card-preview',job.draft.to || '(尚无收件人)'));
    card.addEventListener('click',action(()=>openJob(job.id)));list.append(card);
  }
  if(!rows.length)list.append(el('div','empty-list','没有草稿或发件任务。'));
}

// ==========================================
// Function: Load one selected draft with its full body and attachments.
// Method: Keep large base64 payloads out of list/status polling responses.
// ==========================================
async function openJob(identity) {
  const job=await api('/api/job?id='+encodeURIComponent(identity));
      generation++; selected='';const reader=$('#reader');reader.replaceChildren(el('h2','reader-title',job.draft.subject || '(无主题)'),el('p','job-state',jobLabels[job.state]));
      if(job.state==='queued')reader.append(el('p','note','计划发送：'+dateText(job.due,true)));
      if(job.error)reader.append(el('p','job-error',job.error));if(job.copy_status)reader.append(el('p','note',job.copy_status));
      reader.append(el('p','note','发往：'+job.draft.to),el('div','job-content',job.draft.body));
      const buttons=el('div','job-actions');
      if(job.state==='draft')buttons.append(tool('编辑草稿',()=>openComposer({...job.draft,account:job.account,id:job.id})));
      if(job.state==='queued')buttons.append(tool('取消排队并恢复草稿',async()=>{await api('/api/cancel',{id:job.id});await loadJobs();emptyReader();toast('已取消排队，邮件恢复为草稿');}));
      if(job.state==='failed')buttons.append(tool('另建草稿并检查后重发',()=>openComposer({...job.draft,account:job.account})));
      reader.append(buttons);

}

// ==========================================
// Function: Open a fresh, reply or saved draft composer.
// Method: Preserve reply metadata and attachment payloads outside rendered fields.
// ==========================================
function openComposer(draft={}) {
  $('#compose-form').reset();draftId=draft.id || crypto.randomUUID().replaceAll('-','');replyHeaders={in_reply_to:draft.in_reply_to||'',references:draft.references||''};savedAttachments=draft.attachments||[];
  $('#compose-account').value=draft.account || $('#account-filter').value || session.accounts[0]?.id || '';
  for(const key of ['to','cc','bcc','subject','body'])$('#compose-'+key).value=draft[key]||'';
  $('#attachment-names').textContent=savedAttachments.map(a=>a.name).join('、');
  $('#send-mail').disabled=session.demo || !session.accounts.length; $('#compose-note').textContent=session.demo?'演示模式 · 可保存草稿，禁用外发':'草稿保存在这台设备上';
  $('#composer').showModal();$('#compose-to').focus();
}

// ==========================================
// Function: Read file bytes as a base64 attachment.
// Method: FileReader data URLs avoid text transcoding and handle binary files.
// ==========================================
function encodedFile(file) {
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve({name:file.name,base64:reader.result.split(',')[1]});reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
}

// ==========================================
// Function: Collect and persist a composed draft or send request.
// Method: Bound attachments, encode them, and submit only after the user action.
// ==========================================
async function submitCompose(send) {
  const files=Array.from($('#compose-files').files);
  if(files.length+savedAttachments.length>20 || files.reduce((n,f)=>n+f.size,0)>30*1024*1024)throw new Error('附件最多 20 个，总大小不超过 30 MiB');
  const payload={account:$('#compose-account').value,...replyHeaders,attachments:[...savedAttachments,...await Promise.all(files.map(encodedFile))]};
  for(const key of ['to','cc','bcc','subject','body'])payload[key]=$('#compose-'+key).value;
  if(draftId)payload.id=draftId;
  if($('#compose-due').value)payload.due=new Date($('#compose-due').value).getTime()/1000;
  if(send && (!payload.to || !payload.subject))throw new Error('发送前请填写收件人和主题');
  $('#save-draft').disabled=true;$('#send-mail').disabled=true;
  try {const result=await api(send?'/api/send':'/api/draft',payload);draftId=result.id;$('#composer').close();toast(send?'邮件已进入发送队列':'草稿已保存');if(view==='drafts')await loadJobs();}
  finally {$('#save-draft').disabled=false;$('#send-mail').disabled=session.demo;}
}

// ==========================================
// Function: Refresh background status without polling full mail bodies.
// Method: Reload lists only when synchronization or delivery state changes.
// ==========================================
async function pollStatus() {
  try {
    const status=await api('/api/status'); const failures=Object.entries(status.accounts).filter(([,v])=>!v.ok);
    $('#sync-status').classList.toggle('error',failures.length>0 || !!status.worker_error);
    $('#sync-status').textContent=status.worker_error?status.worker_error:status.syncing?'正在同步邮件…':failures.length?'同步失败：'+failures.map(([id])=>id).join('、')+' · 检查账户配置':status.last_sync?'最近同步 '+dateText(status.last_sync):'等待首次同步';
    if(lastSync!==status.last_sync){lastSync=status.last_sync;await loadMessages();}
    if(view==='drafts'){const jobs=await api('/api/jobs');if(JSON.stringify(jobs)!==lastJobs)await loadJobs();}
  }catch(error){$('#sync-status').textContent='本地服务已断开，正在等待重连';}
}

// ==========================================
// Function: Initialize accounts, navigation and explicit UI actions.
// Method: Bootstrap the session, bind handlers once and start bounded polling.
// ==========================================
async function init() {
  session=await api('/api/session');csrf=session.csrf;$('#demo-banner').hidden=!session.demo;
  for(const account of session.accounts){
    for(const target of ['#account-filter','#compose-account']){const option=el('option','',account.email);option.value=account.id;$(target).append(option);}
    $('#accounts').append(el('div','account-chip',account.email));
  }
  $('#navigation').addEventListener('click',action(async event=>{const button=event.target.closest('[data-view]');if(!button)return;view=button.dataset.view;requestGeneration++;emptyReader();$('#view-title').textContent=labels[view];$('#breadcrumb').textContent=labels[view];$('#category-tabs').hidden=view==='drafts';$('#navigation .active')?.classList.remove('active');button.classList.add('active');await loadMessages();}));
  $('#category-tabs').addEventListener('click',action(async event=>{const button=event.target.closest('[data-category]');if(!button)return;category=button.dataset.category;for(const tab of document.querySelectorAll('[data-category][role="tab"]')){tab.classList.toggle('selected',tab===button);tab.setAttribute('aria-selected',String(tab===button));}emptyReader();await loadMessages();}));
  $('#search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(action(()=>loadMessages()),220);});
  $('#account-filter').addEventListener('change',action(async()=>{emptyReader();await loadMessages();}));
  $('#load-more').addEventListener('click',action(()=>loadMessages(true)));
  $('#new-mail').addEventListener('click',()=>openComposer());$('#close-composer').addEventListener('click',()=>$('#composer').close());
  $('#save-draft').addEventListener('click',action(()=>submitCompose(false)));
  $('#compose-form').addEventListener('submit',action(async event=>{event.preventDefault();await submitCompose(true);}));
  $('#compose-files').addEventListener('change',()=>{$('#attachment-names').textContent=[...savedAttachments.map(a=>a.name),...Array.from($('#compose-files').files).map(f=>f.name)].join('、');});
  $('#sync').addEventListener('click',action(async()=>{await api('/api/sync',{});toast(session.demo?'演示邮箱已就绪':'已请求同步');await pollStatus();}));
  $('#reclassify').addEventListener('click',action(async()=>{const result=await api('/api/reclassify',{});await loadMessages();if(selected)await openMessage(selected);toast('已重新归类 '+result.updated+' 封邮件');}));
  $('#help').addEventListener('click',()=>$('#help-dialog').showModal());$('#close-help').addEventListener('click',()=>$('#help-dialog').close());
  $('#import').addEventListener('click',()=>$('#eml-file').click());$('#eml-file').addEventListener('change',action(async()=>{const file=$('#eml-file').files[0];if(!file)return;if(file.size>30*1024*1024)throw new Error('邮件超过 30 MiB');const encoded=await encodedFile(file);await api('/api/import',{account:$('#account-filter').value||session.accounts[0]?.id,base64:encoded.base64});await loadMessages();$('#eml-file').value='';toast('邮件已导入本地邮箱');}));
  document.addEventListener('keydown',event=>{if(event.ctrlKey||event.metaKey||event.altKey||/INPUT|TEXTAREA|SELECT/.test(event.target.tagName)||$('dialog[open]'))return;if(event.key.toLowerCase()==='n'){event.preventDefault();openComposer();}if(event.key==='/'){event.preventDefault();$('#search').focus();}});
  await loadMessages();await pollStatus();setInterval(pollStatus,4000);
}
init().catch(error=>toast(error.message));
