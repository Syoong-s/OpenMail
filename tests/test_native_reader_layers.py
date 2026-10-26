"""Layer ownership, pending geometry and lifecycle regressions without a native GUI."""
import gc
from types import SimpleNamespace
from unittest import TestCase
from maildesk.native_reader_layers import ReaderLayers,clipped_rectangle

# ==========================================
# Function: Model real root-relative GTK allocations and widget ancestry.
# Method: Provide geometry/visibility only; run production occlusion policy unchanged.
# ==========================================
class Geometry:
    # ==========================================
    # Function: Define independent roots and content/frame relationships.
    # Method: Keep every allocation in root coordinates to make translated coverage unambiguous.
    # ==========================================
    def __init__(self):
        self.boxes={'root':(0,0,1000,800),'overlay':(0,0,1000,800),'body':(300,100,600,600),'frame':(200,150,700,500),'inside':(250,220,300,200),'menu':(400,250,120,80),'other':(0,0,1000,800),'nav':(250,0,300,800)}
        self.parents={'overlay':'root','body':'overlay','frame':'overlay','inside':'frame','menu':'overlay','nav':'overlay'};self.hidden=set()
    # ==========================================
    # Function: Translate a same-root GTK widget allocation into its reader's local coordinates.
    # Method: Fill the caller-owned integer pointers with exact coordinate differences.
    # ==========================================
    def gtk_widget_translate_coordinates(self,source,target,unused_x,unused_y,x,y):
        if self.gtk_widget_get_toplevel(source)!=self.gtk_widget_get_toplevel(target):return False
        a,b=self.boxes[source],self.boxes[target];x._obj.value=a[0]-b[0];y._obj.value=a[1]-b[1];return True
    # ==========================================
    # Function: Return allocated GTK dimensions and mapping state.
    # Method: Read the immutable fixture geometry and explicit hidden set.
    # ==========================================
    def gtk_widget_get_allocated_width(self,widget):return self.boxes[widget][2]
    # ==========================================
    # Function: Return allocated GTK height.
    # Method: Read the fixture's actual widget allocation.
    # ==========================================
    def gtk_widget_get_allocated_height(self,widget):return self.boxes[widget][3]
    # ==========================================
    # Function: Check mapped navigation visibility independently of logical open state.
    # Method: Preserve closing-animation coverage until the widget is really hidden.
    # ==========================================
    def gtk_widget_get_mapped(self,widget):return widget not in self.hidden
    # ==========================================
    # Function: Resolve a widget's own GTK root.
    # Method: Walk real parent relationships instead of application-level selected-window state.
    # ==========================================
    def gtk_widget_get_toplevel(self,widget):
        while widget in self.parents:widget=self.parents[widget]
        return widget
    # ==========================================
    # Function: Test ownership by GTK ancestry.
    # Method: Follow containing widgets rather than popup controller metadata alone.
    # ==========================================
    def gtk_widget_is_ancestor(self,widget,parent):
        while widget in self.parents:
            widget=self.parents[widget]
            if widget==parent:return True
        return False

# ==========================================
# Function: Verify all floating surfaces share one root/stack-aware mail occlusion policy.
# Method: Exercise modal, nested, cross-root, stale geometry, navigation and weak reader lifetimes.
# ==========================================
class ReaderLayerTests(TestCase):
    # ==========================================
    # Function: Construct an isolated broker and one fresh production policy object.
    # Method: Use no GUI mocks beyond geometry, with actual ordered open-state records.
    # ==========================================
    def setUp(self):
        self.g=Geometry();self.broker=SimpleNamespace(g=self.g,app=None,states={},opened=[],roots={'root':{'overlay':'overlay'}},stopping=False);self.layers=ReaderLayers(self.broker)
    # ==========================================
    # Function: Add one retained managed surface with explicit root and coverage.
    # Method: Match the broker record schema and chronological layer order.
    # ==========================================
    def surface(self,key,frame='frame',root='root',backdrop=None,bounds=None):
        state={'id':key,'frame':frame,'root':root,'open':True,'backdrop':backdrop}
        if bounds:state['bounds']=bounds
        self.broker.states[key]=state;self.broker.opened.append(key);return state
    # ==========================================
    # Function: Keep a centered modal's body and input entirely above underlying mail.
    # Method: Treat its backdrop as full-root coverage and restore immediately when closed.
    # ==========================================
    def test_modal_backdrop_blocks_underlying_reader(self):
        state=self.surface('settings',backdrop='mask');self.assertEqual(self.layers.rectangles('body','root'),((0,0,600,600),));state['open']=False;self.assertEqual(self.layers.rectangles('body','root'),())
    # ==========================================
    # Function: Preserve a preview owned by a floating dialog while its child menu covers it.
    # Method: Ignore the owner and earlier frames, retaining only higher same-root layers.
    # ==========================================
    def test_own_dialog_preview_and_nested_menu(self):
        self.surface('settings',backdrop='mask');self.assertTrue(self.layers.has_owner('inside','root'));self.assertFalse(self.layers.has_owner('body','root'));self.assertFalse(self.layers.has_owner('inside','other'));self.assertEqual(self.layers.rectangles('inside','root'),());self.surface('child',frame='menu');self.assertEqual(self.layers.rectangles('inside','root'),((142,22,278,118),))
    # ==========================================
    # Function: Prevent one window's menu from affecting another window's renderer.
    # Method: Keep independent roots in the same broker registry.
    # ==========================================
    def test_other_root_and_closed_frames_do_not_occlude(self):
        self.surface('elsewhere',root='other',backdrop='mask');self.assertEqual(self.layers.rectangles('body','root'),());self.surface('retained')['open']=False;self.assertEqual(self.layers.rectangles('body','root'),())
    # ==========================================
    # Function: Cover a new popup before its GTK frame receives its first allocation.
    # Method: Use planned broker bounds and include old allocation during a pending move.
    # ==========================================
    def test_pending_and_moving_popup_geometry(self):
        self.g.boxes['frame']=(200,150,1,1);self.surface('menu',bounds=(500,250,200,100));self.assertEqual(self.layers.rectangles('body','root'),((192,142,408,258),));self.g.boxes['frame']=(600,350,200,100);self.assertEqual(self.layers.rectangles('body','root'),((192,142,508,358),))
    # ==========================================
    # Function: Protect navigation throughout a closing animation without covering dialog-owned previews.
    # Method: Use actual panel mapping, then remove its coverage after the final hide.
    # ==========================================
    def test_navigation_mapping_and_dialog_ownership(self):
        panels={'folders_menu':'nav'};self.broker.app=SimpleNamespace(window='root',widget=panels.__getitem__,navigation_panel='');self.assertEqual(self.layers.rectangles('body','root'),((0,0,258,600),));self.surface('settings',backdrop='mask');self.assertEqual(self.layers.rectangles('inside','root'),());self.broker.states['settings']['open']=False;self.g.hidden.add('nav');self.assertEqual(self.layers.rectangles('body','root'),())
    # ==========================================
    # Function: Bound rectangle projection to the actual reader dimensions.
    # Method: Test shadows, out-of-view geometry and zero-size intersections.
    # ==========================================
    def test_rectangle_bounds(self):
        self.assertEqual(clipped_rectangle((-20,-10,80,50),100,100,8),(0,0,68,48));self.assertIsNone(clipped_rectangle((150,10,20,20),100,100));self.assertIsNone(clipped_rectangle((10,150,20,20),100,100))
    # ==========================================
    # Function: Synchronize only live same-root readers without retaining closed documents.
    # Method: Test real WeakSet behavior, root filtering and reentrant synchronization.
    # ==========================================
    def test_sync_is_root_scoped_weak_and_reentrant(self):
        # ==========================================
        # Function: Supply weak-referenceable owned reader instances.
        # Method: Retain identity without simulating native rendering behavior.
        # ==========================================
        class Reader:pass
        a=Reader();a.widget='body';a.closed=False;a.handle=1;a.calls=0
        # ==========================================
        # Function: Reenter synchronization from a native geometry callback.
        # Method: Require the guard to prevent duplicate recursive commits.
        # ==========================================
        def sync():a.calls+=1;self.layers.sync('root')
        a.sync_native_viewport=sync;b=Reader();b.widget='other';b.closed=False;b.handle=1;b.sync_native_viewport=lambda:self.fail('other-root reader synchronized');self.layers.readers.update((a,b));self.layers.sync('root');self.assertEqual(a.calls,1);a.closed=True;self.layers.sync('root');self.assertEqual(a.calls,1);self.layers.readers.discard(a);del b;gc.collect();self.assertEqual(len(self.layers.readers),0)
