"""Root-scoped occlusion between virtual GTK floating frames and native readers."""
import ctypes as C
from weakref import WeakSet

# ==========================================
# Function: Restrict a floating layer footprint to the current reader's logical bounds.
# Method: Expand for shadows, intersect with the widget and discard empty geometry.
# ==========================================
def clipped_rectangle(box,width,height,padding=0):
    x,y,w,h=box
    left,top=max(0,x-padding),max(0,y-padding);right,bottom=min(width,x+w+padding),min(height,y+h+padding)
    return (left,top,right,bottom) if right>left and bottom>top else None

# ==========================================
# Function: Keep native mail below all higher same-root GTK surfaces without reloading documents.
# Method: Track readers weakly and project the broker's ordered layer ownership into exclusion rectangles.
# ==========================================
class ReaderLayers:
    # ==========================================
    # Function: Retain only weak native-reader references and the existing surface broker.
    # Method: Share geometry/lifecycle knowledge without introducing a second popup registry.
    # ==========================================
    def __init__(self,surfaces):
        self.surfaces=surfaces;self.readers=WeakSet();self.syncing=False

    # ==========================================
    # Function: Synchronize visible native hosts at a floating surface lifecycle boundary.
    # Method: Skip other roots, closed/unrealized readers and reentrant geometry notifications.
    # ==========================================
    def sync(self,root=None):
        if self.syncing or self.surfaces.stopping:return
        self.syncing=True
        try:
            for reader in tuple(self.readers):
                if reader.closed or not reader.handle:continue
                if root is None or self.surfaces.g.gtk_widget_get_toplevel(reader.widget)==root:reader.sync_native_viewport()
        finally:self.syncing=False

    # ==========================================
    # Function: Obtain real allocations without inventing coordinates for an unmapped frame.
    # Method: Translate widgets within their current GTK root and reject stale one-pixel allocations.
    # ==========================================
    def box(self,widget,relative):
        g=self.surfaces.g;x,y=C.c_int(),C.c_int()
        if not widget or not g.gtk_widget_translate_coordinates(widget,relative,0,0,C.byref(x),C.byref(y)):return None
        width,height=g.gtk_widget_get_allocated_width(widget),g.gtk_widget_get_allocated_height(widget)
        return (x.value,y.value,width,height) if width>1 and height>1 else None

    # ==========================================
    # Function: Identify readers that belong inside a dialog or flyout.
    # Method: Use actual GTK ancestry so a frame never occludes its own preview or editor content.
    # ==========================================
    def contains(self,frame,widget):
        return bool(frame and (frame==widget or self.surfaces.g.gtk_widget_is_ancestor(widget,frame)))

    # ==========================================
    # Function: Distinguish floating-preview content from base timeline readers.
    # Method: Only base readers yield to lower-level controls such as the timeline's bottom arrow.
    # ==========================================
    def has_owner(self,widget,root):
        broker=self.surfaces
        return any(state['open'] and state['root']==root and self.contains(state['frame'],widget) for state in (broker.states[key] for key in broker.opened if key in broker.states))

    # ==========================================
    # Function: Cover allocated and pending popup positions during the same layout turn.
    # Method: Union real frame bounds with broker placement until GTK commits the new allocation.
    # ==========================================
    def frame_box(self,state,widget,root):
        broker=self.surfaces;actual=self.box(state['frame'],widget);planned=state.get('bounds');overlay=broker.roots.get(root,{}).get('overlay');origin=self.box(overlay,widget) if overlay else None
        if planned and origin:
            x,y,w,h=planned;planned=(x+origin[0],y+origin[1],w,h)
        else:planned=None
        if not actual:return planned
        if not planned:return actual
        x=min(actual[0],planned[0]);y=min(actual[1],planned[1])
        return x,y,max(actual[0]+actual[2],planned[0]+planned[2])-x,max(actual[1]+actual[3],planned[1]+planned[3])-y

    # ==========================================
    # Function: Project all higher floating layers into one reader's local coordinate system.
    # Method: Respect root and stack ownership; modal backdrops block the root, menus only their bounds.
    # ==========================================
    def rectangles(self,widget,root):
        broker=self.surfaces;g=broker.g;width=g.gtk_widget_get_allocated_width(widget);height=g.gtk_widget_get_allocated_height(widget);result=[]
        states=[broker.states[key] for key in broker.opened if key in broker.states and broker.states[key]['open'] and broker.states[key]['root']==root]
        owner=max((i for i,state in enumerate(states) if self.contains(state['frame'],widget)),default=-1)
        for state in states[owner+1:]:
            box=self.box(root,widget) if state.get('backdrop') else self.frame_box(state,widget,root)
            if box:
                rect=clipped_rectangle(box,width,height,0 if state.get('backdrop') else 8)
                if rect and rect not in result:result.append(rect)
        app=broker.app
        if owner<0 and app and getattr(app,'window',None)==root:
            for name in ('navigation_backdrop','folders_menu','navigation_menu'):
                try:panel=app.widget(name)
                except (AttributeError,KeyError,RuntimeError):continue
                if not panel or not g.gtk_widget_get_mapped(panel) or self.contains(panel,widget):continue
                box=self.box(panel,widget)
                if box:
                    rect=clipped_rectangle(box,width,height,8)
                    if rect and rect not in result:result.append(rect)
        return tuple(result)
