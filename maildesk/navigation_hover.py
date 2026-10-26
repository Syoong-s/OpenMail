"""Bounded shared hover ownership for unified folder and mailbox rows."""
import ctypes as C

# ==========================================
# Function: Keep one row's tools discoverable without leaving sticky mouse-focus controls.
# Method: Combine native crossing/focus signals with a single-owner pointer check during existing ticks.
# ==========================================
class NavigationHoverUI:
    # ==========================================
    # Function: Test the current pointer against a row's actual rectangle.
    # Method: Query native coordinates relative to that row, independent of child crossing/grabs.
    # ==========================================
    def navigation_pointer_inside(self,event):
        x,y=C.c_int(),C.c_int();self.g.gtk_widget_get_pointer(event,C.byref(x),C.byref(y))
        return 0<=x.value<self.g.gtk_widget_get_allocated_width(event) and 0<=y.value<self.g.gtk_widget_get_allocated_height(event)

    # ==========================================
    # Function: Remove transient row highlighting and opacity before its widgets can be destroyed.
    # Method: Clear identity before touching native controls to tolerate nested focus notifications.
    # ==========================================
    def clear_navigation_hover(self):
        owner=getattr(self,'navigation_hover_owner',None);self.navigation_hover_owner=None
        if owner:
            self.g.gtk_widget_set_opacity(owner['tools'],0);self.g.gtk_style_context_remove_class(self.g.gtk_widget_get_style_context(owner['line']),b'hover')

    # ==========================================
    # Function: Reveal controls inside the same outer row as their label.
    # Method: Ignore child boundary crossings while distinguishing keyboard focus from pointer entry.
    # ==========================================
    def navigation_hover(self,event,tools,line,leave=False,keyboard=False):
        inside=self.navigation_pointer_inside(event);show=inside or keyboard or not leave
        if not show:
            if getattr(self,'navigation_hover_owner',None) and self.navigation_hover_owner['event']==event:self.clear_navigation_hover()
            else:self.g.gtk_widget_set_opacity(tools,0)
            return False
        owner=getattr(self,'navigation_hover_owner',None)
        if owner and owner['event']!=event:self.clear_navigation_hover()
        self.navigation_hover_owner={'event':event,'tools':tools,'line':line,'keyboard':keyboard and not inside}
        self.g.gtk_widget_set_opacity(tools,1);self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(line),b'hover');return False

    # ==========================================
    # Function: Hide controls reliably even when GTK does not emit a final leave event.
    # Method: Check only the tracked owner, never every folder, and reset keyboard mode after pointer movement.
    # ==========================================
    def navigation_hover_tick(self):
        owner=getattr(self,'navigation_hover_owner',None)
        if not owner:return
        if not getattr(self,'navigation_panel',''):self.clear_navigation_hover();return
        x,y=C.c_int(),C.c_int();self.g.gtk_widget_get_pointer(self.window,C.byref(x),C.byref(y));point=(x.value,y.value);previous=getattr(self,'navigation_hover_pointer',None);self.navigation_hover_pointer=point
        if previous is not None and point!=previous:owner['keyboard']=False
        focus=self.g.gtk_window_get_focus(self.window)
        keyboard=owner['keyboard'] and focus and (focus==owner['event'] or self.g.gtk_widget_is_ancestor(focus,owner['event']))
        if not keyboard and not self.navigation_pointer_inside(owner['event']):self.clear_navigation_hover()
