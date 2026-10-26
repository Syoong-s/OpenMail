"""Same-application rail drag ordering independent of mailbox mutations."""
import ctypes as C
import json

P=C.c_void_p

# ==========================================
# Function: Match GTK3's public drag target record.
# Method: Use a UTF-8 target name and native unsigned flag/info fields.
# ==========================================
class TargetEntry(C.Structure):
    _fields_=[('target',C.c_char_p),('flags',C.c_uint),('info',C.c_uint)]

# ==========================================
# Function: Reorder mandatory and optional rail destinations without moving mail or folders.
# Method: Persist stable descriptors separately from pin membership and use a same-app drag target.
# ==========================================
class NavigationDragUI:
    # ==========================================
    # Function: Convert one optional destination into an unambiguous order key.
    # Method: Encode full account/path pairs as JSON rather than splitting display names.
    # ==========================================
    def rail_key(self,item):
        if item['kind']=='view':return 'view:'+item['view']
        return 'folder:'+json.dumps([item['account'],item['path']],ensure_ascii=False,separators=(',',':'))

    # ==========================================
    # Function: Merge saved ordering with current active destinations and mandatory utilities.
    # Method: Retain user positions, skip unavailable destinations and insert newly pinned entries before More.
    # ==========================================
    def ordered_rail_keys(self,keys):
        default=['core:inbox','core:folders',*keys,'core:more','core:settings'];saved=self.service.store.preference('rail_order',default)
        if not isinstance(saved,list):saved=default
        result=[]
        for key in saved:
            if key in default and key not in result:result.append(key)
        for key in default:
            if key in result:continue
            if key=='core:inbox':result.insert(0,key)
            elif key=='core:folders':result.insert(result.index('core:inbox')+1,key)
            elif key=='core:settings':result.append(key)
            else:
                position=result.index('core:more') if 'core:more' in result else result.index('core:settings') if 'core:settings' in result else len(result);result.insert(position,key)
        return result

    # ==========================================
    # Function: Bind a native source/destination pair to one rail icon.
    # Method: Accept only the application's private drag target and the MOVE visual action.
    # ==========================================
    def bind_rail_drag(self,widget,key):
        g=self.g
        if not hasattr(self,'rail_drag_targets'):self.rail_drag_targets=(TargetEntry*1)(TargetEntry(b'TeleMail-Rail-Order',1,0))
        g.gtk_drag_source_set(widget,1<<8,self.rail_drag_targets,1,4);g.gtk_drag_dest_set(widget,7,self.rail_drag_targets,1,4)
        g.connect(widget,'drag-data-get',lambda w,context,data,info,stamp,user,value=key:g.gtk_selection_data_set_text(data,value.encode(),-1),types=[P,P,P,C.c_uint,C.c_uint,P],group='rail-drag')
        g.connect(widget,'drag-data-received',lambda w,context,x,y,data,info,stamp,user,value=key:self.receive_rail_drop(w,context,y,data,stamp,value),types=[P,P,C.c_int,C.c_int,P,C.c_uint,C.c_uint,P],group='rail-drag')
        g.connect(widget,'drag-begin',lambda *unused:self.close_navigation(),count=3,group='rail-drag')
        g.connect(widget,'drag-motion',lambda w,context,x,y,stamp,user:self.rail_drag_motion(w,y),types=[P,P,C.c_int,C.c_int,C.c_uint,P],returns=True,group='rail-drag')
        g.connect(widget,'drag-leave',lambda w,*unused:self.clear_rail_drop(w),count=4,group='rail-drag')
        g.connect(widget,'drag-end',lambda w,*unused:self.clear_rail_drop(w),count=3,group='rail-drag')

    # ==========================================
    # Function: Highlight the insertion edge while leaving GTK's default drag status handling intact.
    # Method: Distinguish upper/lower icon halves and return false for native MOVE negotiation.
    # ==========================================
    def rail_drag_motion(self,widget,y):
        context=self.g.gtk_widget_get_style_context(widget);after=y>=self.g.gtk_widget_get_allocated_height(widget)/2
        self.g.gtk_style_context_remove_class(context,b'drop-before' if after else b'drop-after');self.g.gtk_style_context_add_class(context,b'drop-after' if after else b'drop-before');return False

    # ==========================================
    # Function: Remove a transient drop-edge indication.
    # Method: Clear both edge states after leaving or completing a drag.
    # ==========================================
    def clear_rail_drop(self,widget):
        context=self.g.gtk_widget_get_style_context(widget);self.g.gtk_style_context_remove_class(context,b'drop-before');self.g.gtk_style_context_remove_class(context,b'drop-after')

    # ==========================================
    # Function: Decode a bounded same-app payload and finish the native drag transaction.
    # Method: Validate against visible rail keys; never interpret data as a filesystem/mailbox operation.
    # ==========================================
    def receive_rail_drop(self,widget,context,y,data,stamp,target):
        success=False;raw=None
        try:
            if 0<self.g.gtk_selection_data_get_length(data)<8192:
                raw=self.g.gtk_selection_data_get_text(data)
                if raw:success=self.reorder_rail(C.string_at(raw).decode(),target,y>=self.g.gtk_widget_get_allocated_height(widget)/2)
        except (UnicodeError,ValueError):success=False
        finally:
            if raw:self.g.g_free(raw)
            self.clear_rail_drop(widget);self.g.gtk_drag_finish(context,success,False,stamp)

    # ==========================================
    # Function: Apply one before/after reorder and refresh through the existing main-thread queue.
    # Method: Move only known tokens, retaining mandatory entries and exact folder identities.
    # ==========================================
    def reorder_rail(self,source,target,after=False):
        order=list(getattr(self,'rail_order_keys',[]))
        if source not in order or target not in order:return False
        if source==target:return True
        order.remove(source);position=order.index(target)+(1 if after else 0);order.insert(position,source);self.service.store.set_preference('rail_order',order);self.queue_folder_refresh();return True

    # ==========================================
    # Function: Preserve a pinned folder's chosen position after confirmed rename/move/delete.
    # Method: Rewrite only matching order tokens using the service's exact-account path mapping.
    # ==========================================
    def migrate_rail_keys(self,mapping):
        order=self.service.store.preference('rail_order',None)
        if not isinstance(order,list):return
        changed=[mapping.get(key,key) for key in order];self.service.store.set_preference('rail_order',[key for key in changed if key is not None])
