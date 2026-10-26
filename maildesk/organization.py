"""Service use cases for real folders and personal mail productivity."""
from . import folders
from .local_mail import LOCAL_ACCOUNT,is_local_message

# ==========================================
# Function: Extend the mail service with serialized folder and organization operations.
# Method: Keep remote confirmation before local state changes and request normal resync.
# ==========================================
class OrganizationService:
    # ==========================================
    # Function: Apply a folder-management operation to the selected account.
    # Method: Validate hierarchy/protected folders, mutate remotely, then persist metadata.
    # ==========================================
    def folder_action(self, account_id, operation, path, target=''):
        path=folders.valid_path(path)
        if operation not in ('create','rename','delete','subscribe','unsubscribe'):
            raise ValueError('无效文件夹操作')
        if operation=='rename':
            target=folders.valid_path(target)
        with self.lock:
            rows=self.store.list_folders(account_id)
            current=next((r for r in rows if r['folder']==path),None)
            if operation!='create' and not current:
                raise ValueError('文件夹不存在')
            if operation=='rename' and current:
                delimiter=current['delimiter']
                if any(r['folder']==target for r in rows) or target==path or (delimiter and target.startswith(path+delimiter)):
                    raise ValueError('目标已存在或位于原文件夹内部')
            if operation=='create' and current:
                raise ValueError('文件夹已存在')
            if operation in ('rename','delete') and current and current['special']:
                raise ValueError('系统文件夹不能重命名或删除')
            if operation=='delete':
                delimiter=current['delimiter']
                if any(r['folder']!=path and delimiter and r['folder'].startswith(path+delimiter) for r in rows):
                    raise ValueError('请先处理子文件夹，再删除父文件夹')
                if current['total']:
                    raise ValueError('请先将文件夹中的邮件移出，再删除空文件夹')
            if self.demo or account_id==LOCAL_ACCOUNT:
                if any(not part for part in path.split('/')) or (operation=='rename' and any(not part for part in target.split('/'))):
                    raise ValueError('本地文件夹路径不能包含空层级')
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
                    raise ValueError('请选择有效账户')
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
    # Method: Resolve account destination before performing a UID-safe server operation.
    # ==========================================
    def move_message(self, identity, destination='', copy=False, special=''):
        with self.lock:
            message=self.store.get(identity)
            if special:
                destination=self.store.special_folder(message['account'],special)
                if not destination:
                    raise ValueError('服务器未提供对应文件夹，请在“文件夹管理”中设置 '+special+' 映射')
            if special=='inbox' and destination==message['folder']:
                self.store.update(identity,{'archived':False})
                return self.store.organize(identity,done=False,aside=False,snoozed_until=0,trashed=False,spam=False)['id']
            row=next((r for r in self.store.list_folders(message['account']) if r['folder']==destination and r['selectable']),None)
            if not row:
                raise ValueError('目标文件夹不存在或不可选择')
            mapping=None
            local=self.demo or is_local_message(message)
            if not local:
                account=self.accounts.get(message['account'])
                if not account:
                    raise ValueError('账户已移除')
                mapping=folders.transfer(account,message,destination,copy)
            elif not self.demo and message['account']!=LOCAL_ACCOUNT:
                raise ValueError('旧版账户本地副本不能直接移动到服务器；可导出 EML 后导入“本地文件夹”')
            result=self.store.transfer_local(identity,destination,copy,local,mapping)
            if not copy:
                with self.store.db() as db:db.execute("UPDATE mail_filter_seen SET state='manual',error='' WHERE account=? AND message_id=? AND state='uncertain'",(message['account'],message['message_id']))
            self.request_sync()
            return result

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
                    raise ValueError('账户已移除')
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
                if action in ('archive','trash','spam','inbox'):
                    self.move_message(identity,special=action)
                elif action in ('move','copy'):
                    self.move_message(identity,destination=value,copy=action=='copy')
                elif action=='delete':
                    self.permanently_delete(identity)
                else:
                    self.store.organize(identity,**{action:value})
                completed.append(identity)
            except Exception as error:
                raise ValueError(f'已完成 {len(completed)} / {len(set(identities))} 项：{error}') from None
        return completed

    # ==========================================
    # Function: Confirm bulk flags using one authenticated UID-set operation per bounded mailbox generation.
    # Method: Read compact identities, preserve partial completion on errors and commit only confirmed groups without MIME hydration.
    # ==========================================
    def bulk_flags(self,identities,key,value):
        from collections import defaultdict
        from contextlib import nullcontext
        from . import transport
        identities=list(dict.fromkeys(identities));completed=[]
        if key not in ('seen','pinned','priority') or not isinstance(value,bool):raise ValueError('无效批量状态')
        with (self.lock if key!='priority' else nullcontext()):
            try:
                for start in range(0,len(identities),100):
                    page=identities[start:start+100];marks=','.join('?' for _ in page)
                    with self.store.db() as db:
                        sources={row['id']:dict(row) for row in db.execute('SELECT id,account,folder,validity,uid,remote_gone FROM messages WHERE id IN ('+marks+')',page)}
                    if len(sources)!=len(page):raise ValueError('所选邮件已变更，请刷新后重试')
                    groups=defaultdict(list)
                    for identity in page:
                        row=sources[identity];local=key=='priority' or self.demo or is_local_message(row)
                        groups[(local,row['account'],row['folder'],row['validity'])].append(row)
                    for (local,account,folder,validity),rows in groups.items():
                        if not local:
                            if account not in self.accounts or any(row['remote_gone'] for row in rows):raise ValueError('邮件无法对应到当前账户，请先同步')
                            transport.set_seen_many(self.accounts[account],rows,value,'\\Seen' if key=='seen' else '\\Flagged')
                        with self.store.db() as db:
                            db.executemany('UPDATE messages SET '+key+'=? WHERE id=?',[(int(value),row['id']) for row in rows])
                            if key=='seen':db.executemany('DELETE FROM pending_read_flags WHERE message=?',[(row['id'],) for row in rows])
                        completed.extend(row['id'] for row in rows)
            except Exception as error:raise ValueError(f'已完成 {len(completed)} / {len(identities)} 项：{error}') from None
        return completed
