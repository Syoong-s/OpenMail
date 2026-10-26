"""One bounded hidden Windows reader tree during asynchronous navigation."""
import os
import time

# ==========================================
# Function: Keep an outgoing native controller alive until its replacement is actually created.
# Method: Hold one hidden original GTK tree for at most 1.5 seconds; never reparent or reuse source HTML.
# ==========================================
class ReaderHandoff:
    # ==========================================
    # Function: Own one optional outgoing reader and its original containing source tree.
    # Method: Keep ownership on the application and native adapter for deterministic clear/quit cleanup.
    # ==========================================
    def __init__(self,app):
        self.app=app;self.reader=None;self.tree=None;self.armed=False;self.deadline=0;self.held=0;self.released=0;self.peak=0

    # ==========================================
    # Function: Mark one deliberate source navigation as eligible for a bounded handoff.
    # Method: Preserve an existing first handoff across rapid superseding requests without extending its deadline.
    # ==========================================
    def begin(self):self.armed=True

    # ==========================================
    # Function: Hold only one already-created outgoing Windows controller before its source is cleared.
    # Method: Hide the original tree and exempt it from show-all/clear until a real replacement exists.
    # ==========================================
    def prepare(self,card,tree=None):
        if not self.armed or self.reader or self.app.closing:return
        readers=card.get('body_readers',[])+[reader for quote in card.get('quote_cards',[]) for reader in quote.get('readers',[])]
        reader=next((reader for reader in readers if not reader.closed and getattr(reader,'handle',None) and reader.lib.md_webview_status(reader.handle)==1),None)
        if not reader:return
        self.reader=reader;self.tree=tree or card.get('timeline_host',card['root']);self.deadline=time.monotonic()+1.5;self.armed=False
        self.held+=1;self.peak=1;g=self.app.g;g.gtk_widget_set_no_show_all(self.tree,1);g.gtk_widget_hide(self.tree)

    # ==========================================
    # Function: Protect only the currently held source tree and its descendants from premature destruction.
    # Method: Use actual GTK ancestry without broad widget references or retained conversation registries.
    # ==========================================
    def protects(self,widget):
        return bool(self.tree and (widget==self.tree or self.app.g.gtk_widget_is_ancestor(widget,self.tree)))

    # ==========================================
    # Function: Release the outgoing controller after a replacement owns the same live browser environment.
    # Method: Require two actual native controllers, or stop on empty selection, timeout or shutdown.
    # ==========================================
    def tick(self):
        if not self.reader:
            if not getattr(self.app,'pending_read_identity','') and not getattr(self.app,'chat_loading',False):self.armed=False
            return
        app=self.app;empty=not (getattr(app,'pending_read_identity','') or getattr(app,'selected_chat','') or getattr(app,'selected',''))
        if app.closing or empty or time.monotonic()>=self.deadline or self.reader.lib.md_webview_metrics(0)>=2:self.close()

    # ==========================================
    # Function: Close the one handoff before its original GTK source tree is destroyed.
    # Method: Clear protection first, close its controller/callbacks, then destroy exactly that hidden tree.
    # ==========================================
    def close(self):
        reader,tree=self.reader,self.tree;self.reader=None;self.tree=None;self.armed=False;self.deadline=0
        if reader:reader.close();self.released+=1
        if tree:self.app.g.gtk_widget_destroy(tree)

# ==========================================
# Function: Lazily enable bounded navigation handoff only on native Windows.
# Method: Leave other platform reader ownership unchanged and share one application-owned holder.
# ==========================================
def navigation_handoff(app):
    if os.name!='nt':return None
    handoff=getattr(app,'reader_handoff',None)
    if handoff is None:
        handoff=app.reader_handoff=ReaderHandoff(app);app.g.reader_handoff=handoff
    return handoff
