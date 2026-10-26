"""Short native row batches so large mailbox changes leave GTK input responsive."""
import ctypes as C
import time

# ==========================================
# Function: Schedule bounded native row construction between normal input/paint events.
# Method: Retain one idle callback and cancel obsolete list generations before replacing widgets.
# ==========================================
class ListRenderUI:
    # ==========================================
    # Function: Begin projecting the newest local query snapshot into native rows.
    # Method: Keep the existing list until the first batch and retain measured render time separately from query time.
    # ==========================================
    def begin_list_render(self,projection,category,search):
        self.cancel_list_render();self.list_renderer=self.render_projection(projection,category,search);self.list_render_started=time.perf_counter();self.list_render_query=projection['prepare_seconds'];self.list_render_active_seconds=0;self.list_render_max_batch=0
        if not getattr(self,'list_render_callback',None):self.list_render_callback=C.CFUNCTYPE(C.c_int,C.c_void_p)(self.render_list_batch)
        self.list_render_source=self.g.g_idle_add(C.cast(self.list_render_callback,C.c_void_p),None)

    # ==========================================
    # Function: Build at most eight normal mail rows in one native idle turn.
    # Method: Scope preferences per batch and yield to GTK events before continuing the same generator.
    # ==========================================
    def render_list_batch(self,unused=None):
        if self.closing:self.cancel_list_render();return 0
        started=time.perf_counter()
        try:
            with self.service.store.preference_snapshot():next(self.list_renderer)
        except StopIteration:
            self.list_render_active_seconds+=time.perf_counter()-started
            self.list_render_max_batch=max(self.list_render_max_batch,time.perf_counter()-started)
            self.last_projection_timing={'max_batch':self.list_render_max_batch,'query':self.list_render_query,'render':self.list_render_active_seconds,'elapsed':time.perf_counter()-self.list_render_started,'rows':len(self.rows)}
            self.list_render_source=0;self.list_renderer=None;self.rendering=False;return 0
        except Exception as error:
            self.list_render_source=0;self.list_renderer=None;self.rendering=False;self.show_error(error);return 0
        self.list_render_active_seconds+=time.perf_counter()-started;self.list_render_max_batch=max(self.list_render_max_batch,time.perf_counter()-started);self.rendering=False;return 1

    # ==========================================
    # Function: Invalidate an unfinished native list without leaking its generator or callback source.
    # Method: Remove only this application's retained idle and restore normal row selection handling.
    # ==========================================
    def cancel_list_render(self):
        if getattr(self,'list_render_source',0):self.g.g_source_remove(self.list_render_source);self.list_render_source=0
        renderer=getattr(self,'list_renderer',None);self.list_renderer=None
        if renderer:renderer.close()
        self.rendering=False
