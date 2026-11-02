"""Service use cases for real folders and personal mail productivity."""
from .i18n import text as _tr
from . import folders
from .local_mail import LOCAL_ACCOUNT,is_local_message

# ==========================================
# Function: Extend the mail service with serialized folder and organization operations.
# Method: Queue message mutations locally while retaining confirmed folder-management operations.
# ==========================================
class OrganizationService:
    # ==========================================
    # Function: Apply a folder-management operation to the selected account.
    # Method: Validate hierarchy/protected folders, mutate remotely, then persist metadata.
    # ==========================================
    def folder_action(self, account_id, operation, path, target=''):
        path=folders.valid_path(path)
        if operation not in ('create','rename','delete','subscribe','unsubscribe'):
            raise ValueError(_tr('无效文件夹操作'))
        if operation=='rename':
            target=folders.valid_path(target)
        with self.lock:
            rows=self.store.list_folders(account_id)
            current=next((r for r in rows if r['folder']==path),None)
            if operation!='create' and not current:
                raise ValueError(_tr('文件夹不存在'))
            if operation=='rename' and current:
                delimiter=current['delimiter']
                if any(r['folder']==target for r in rows) or target==path or (delimiter and target.startswith(path+delimiter)):
                    raise ValueError(_tr('目标已存在或位于原文件夹内部'))
            if operation=='create' and current:
                raise ValueError(_tr('文件夹已存在'))
            if operation in ('rename','delete') and current and current['special']:
                raise ValueError(_tr('系统文件夹不能重命名或删除'))
            if operation=='delete':
                with self.store.db() as db:
                    pending=db.execute('SELECT 1 FROM pending_moves WHERE account=? AND (source_folder=? OR destination=? OR attempted_destination=?) LIMIT 1',(account_id,path,path,path)).fetchone()
                if pending:raise ValueError(_tr('文件夹有尚未同步的邮件移动，请先完成后台同步'))
                delimiter=current['delimiter']
                if any(r['folder']!=path and delimiter and r['folder'].startswith(path+delimiter) for r in rows):
                    raise ValueError(_tr('请先处理子文件夹，再删除父文件夹'))
                if current['total']:
                    raise ValueError(_tr('请先将文件夹中的邮件移出，再删除空文件夹'))
            if self.demo or account_id==LOCAL_ACCOUNT:
                if any(not part for part in path.split('/')) or (operation=='rename' and any(not part for part in target.split('/'))):
                    raise ValueError(_tr('本地文件夹路径不能包含空层级'))
                result=[{'name':r['folder'],**r} for r in rows]
                if operation=='create':
                    result.append({'name':path,'delimiter':'/','flags':[],'special':'','selectable':True,'subscribed':True})
                elif operation=='delete':
                    result=[r for r in result if r['name']!=path]
                elif operation in ('subscribe','unsubscribe'):
                    next(r for r in result if r['name']==path)['subscribed']=operation=='subscribe'
                elif operation=='rename':
                    for row in result:
                        if row['name']==path or row['name'].startswith(path+'/'):
                            row['name']=target+row['name'][len(path):]
            else:
                account=self.accounts.get(account_id)
                if not account:
                    raise ValueError(_tr('请选择有效账户'))
                result=folders.mutate_folder(account,operation,path,target)
            if (self.demo or account_id==LOCAL_ACCOUNT) and operation in ('create','rename'):
                for destination in (path if operation=='create' else target,):
                    parts=destination.split('/')
                    for depth in range(1,len(parts)):
                        parent='/'.join(parts[:depth])
                        if not any(r['name']==parent for r in result):
                            result.append({'name':parent,'delimiter':'/','flags':[],'special':'','selectable':True,'subscribed':True})
            if operation=='rename':
                self.store.rename_folder(account_id,path,target,current['delimiter'])
            elif operation=='delete':
                self.store.remove_folder(account_id,path)
            if not self.demo and account_id!=LOCAL_ACCOUNT:
                previous={row['folder']:row for row in self.store.list_folders(account_id)}
                for row in result:
                    if row['name'] in previous:
                        for key in ('remote_total','remote_unread'):row.setdefault(key,previous[row['name']].get(key))
            self.store.save_folders(account_id,result)
            self.request_sync()
        return self.store.list_folders(account_id)

    # ==========================================
    # Function: Move/copy a selected message or send it to a special-use folder.
    # Method: Persist moves locally; keep explicit copies provider-confirmed and UID-safe.
    # ==========================================
    def move_message(self, identity, destination='', copy=False, special=''):
        message=self.store.get(identity)
        if special:
            destination=self.store.special_folder(message['account'],special)
            if not destination:raise ValueError(_tr('服务器未提供对应文件夹，请在“文件夹管理”中设置 ')+special+_tr(' 映射'))
        if not copy:
            from .mail_mutations import move
            return move(self,identity,destination)
        with self.lock:
            message=self.store.get(identity)
            if message['validity']=='pending':raise ValueError(_tr('此邮件正在移动，请等待后台同步后再复制'))
            row=next((r for r in self.store.list_folders(message['account']) if r['folder']==destination and r['selectable']),None)
            if not row:raise ValueError(_tr('目标文件夹不存在或不可选择'))
            local=self.demo or is_local_message(message)
            if not local:
                account=self.accounts.get(message['account'])
                if not account:raise ValueError(_tr('账户已移除'))
                mapping=folders.transfer(account,message,destination,True)
            else:mapping=None
            return self.store.transfer_local(identity,destination,True,local,mapping)

    # ==========================================
    # Function: Permanently delete selected mail only after explicit UI confirmation.
    # Method: Use targeted UIDPLUS expunge, preserving all unrelated server deletions.
    # ==========================================
    def permanently_delete(self, identity):
        with self.lock:
            message=self.store.get(identity)
            if not self.demo and not is_local_message(message):
                account=self.accounts.get(message['account'])
                if not account:
                    raise ValueError(_tr('账户已移除'))
                folders.delete_message(account,message)
            with self.store.db() as db:
                db.execute('DELETE FROM message_labels WHERE message=?',(identity,))
                db.execute('DELETE FROM messages WHERE id=?',(identity,))
        self.request_sync()

    # ==========================================
    # Function: Execute independent selected-mail actions with clear partial results.
    # Method: Resolve stable IDs one at a time; stop on error without retrying earlier work.
    # ==========================================
    def bulk_action(self, identities, action, value=None):
        if action in ('seen','pinned','priority'):return self.bulk_flags(identities,action,bool(value))
        completed=[]
        for identity in dict.fromkeys(identities):
            try:
                if action in ('archive','trash','spam','inbox','done'):
                    self.move_message(identity,special=('archive' if value is not False else 'inbox') if action=='done' else action)
                elif action in ('move','copy'):
                    self.move_message(identity,destination=value,copy=action=='copy')
                elif action=='delete':
                    self.permanently_delete(identity)
                else:
                    self.store.organize(identity,**{action:value})
                completed.append(identity)
            except Exception as error:
                raise ValueError(_tr('已完成 {0} / {1} 项：{2}').format(len(completed),len(set(identities)),error)) from None
        return completed

    # ==========================================
    # Function: Save bulk flags immediately and defer bounded UID-set operations to background sync.
    # Method: Atomically save compact flags and coalesced provider intents without MIME hydration.
    # ==========================================
    def bulk_flags(self,identities,key,value):
        from .mail_mutations import flags
        return flags(self,identities,key,value)
