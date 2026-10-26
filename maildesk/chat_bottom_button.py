"""A viewport-owned, quiet return-to-latest control for the contact timeline."""
import ctypes as C
import time
from .desktop_general import bind,P
from .ui_actions import icon_action

# ==========================================
# Function: Keep the newest chat mail one click away while browsing older content.
# Method: Overlay a small native circle on the scroller and derive its state from the real scroll adjustment.
# ==========================================
class ChatBottomButton:
    # ==========================================
    # Function: Create one accessible control without reserving timeline or composer space.
    # Method: Own a36px bottom-center overlay and app-lifetime scroll/allocation callbacks.
    # ==========================================
    def __init__(self,app,overlay):
        self.app=app;self.state=None;self.following=False;self.key='';self.adjusting=False;g=app.g;self.adjustment=g.gtk_scrolled_window_get_vadjustment(app.chat_scroll)
        self.button=g.gtk_button_new();icon_action(g,self.button,'回到底部','scroll-bottom',18)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'chat-bottom-button')
        g.gtk_widget_set_size_request(self.button,36,36);g.gtk_widget_set_halign(self.button,3);g.gtk_widget_set_valign(self.button,2);g.gtk_widget_set_margin_bottom(self.button,14)
        g.gtk_overlay_add_overlay(overlay,self.button);g.gtk_widget_set_no_show_all(self.button,1);g.gtk_widget_hide(self.button)
        g.connect(self.button,'clicked',self.activate,group='chat-static')
        g.connect(self.adjustment,'value-changed',self.update,group='chat-static');g.connect(self.adjustment,'changed',self.update,group='chat-static')
        scrollbar=bind(app,'gtk','gtk_scrolled_window_get_vscrollbar',P,P)(app.chat_scroll)
        for widget in (app.chat_scroll,scrollbar):g.connect(widget,'scroll-event' if widget==app.chat_scroll else 'button-press-event',self.user_scroll,count=3,returns=True,group='chat-static')
        g.connect(app.chat_scroll,'key-press-event',self.key_scroll,count=3,returns=True,group='chat-static')

    # ==========================================
    # Function: Read the existing viewport bounds without querying mail or reconstructing cards.
    # Method: Use the current native adjustment for the visible scroller.
    # ==========================================
    def position(self):
        return tuple(bind(self.app,'gtk','gtk_adjustment_get_'+name,C.c_double,P)(self.adjustment) for name in ('value','upper','page_size'))

    # ==========================================
    # Function: Reveal the arrow only when the current contact has newer content below.
    # Method: Observe distance/window state and synchronize native exclusion immediately when the overlay changes.
    # ==========================================
    def update(self,*unused):
        app=self.app;value,upper,page=self.position()
        if app.selected_chat!=self.key:
            self.key=app.selected_chat;self.following=bool(self.key and not app.chat_window_before)
        if app.chat_source_return or app.chat_window_before:self.following=False
        visible=bool(app.selected_chat and not app.closing and not app.chat_source_return and page>1 and (app.chat_window_before or upper-page-value>64))
        state=(visible,not app.chat_loading)
        if state==self.state:return
        self.state=state;app.g.gtk_widget_set_visible(self.button,visible);app.g.gtk_widget_set_sensitive(self.button,state[1])
        surface=getattr(app,'chat_surface',None)
        for leaf in surface.leaves if surface else ():
            reader=leaf['reader'];sync=getattr(reader,'sync_native_viewport',None)
            if sync and reader.handle and not reader.closed:sync()

    # ==========================================
    # Function: Return to the actual newest bottom while retaining the docked draft and live cards.
    # Method: Scroll locally for a current window; reuse guarded latest-window loading when newer mail was paged out.
    # ==========================================
    def activate(self,*unused):
        app=self.app
        if not app.selected_chat or app.closing or app.chat_loading:return
        self.following=True;app.chat_anchor=None
        if app.chat_window_before:app.chat_latest()
        else:
            value,upper,page=self.position()
            app.chat_scroll_pending=(time.monotonic()+.12,'bottom',value,upper)
            bind(app,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(self.adjustment,max(0,upper-page))
        self.update()

    # ==========================================
    # Function: Keep the requested newest bottom visible as asynchronous rich mail changes height.
    # Method: Reapply only while explicit follow intent is active, before viewport-based reader admission/eviction.
    # ==========================================
    def follow(self):
        app=self.app
        if not self.following or not app.selected_chat or app.closing or app.chat_source_return or app.chat_window_before:return
        value,upper,page=self.position()
        if page<=1 or abs(upper-page-value)<.5:return
        self.adjusting=True
        try:bind(app,'gtk','gtk_adjustment_set_value',None,P,C.c_double)(self.adjustment,max(0,upper-page))
        finally:self.adjusting=False

    # ==========================================
    # Function: Respect user wheel or scrollbar navigation instead of pulling it back to new mail.
    # Method: Cancel pending automatic bottom adjustment before GTK or WebView applies the user's gesture.
    # ==========================================
    def user_scroll(self,*unused):
        if self.adjusting:return False
        self.following=False;self.app.chat_force_bottom=False;self.app.chat_scroll_pending=None
        return False

    # ==========================================
    # Function: Let keyboard viewport navigation interrupt automatic bottom following.
    # Method: Observe scroll/navigation keys without consuming the normal native key event.
    # ==========================================
    def key_scroll(self,widget,event,unused):
        key=C.c_uint()
        bind(self.app,'gdk','gdk_event_get_keyval',C.c_int,P,P)(event,C.byref(key))
        if key.value in (65360,65361,65362,65363,65364,65365,65366,65367):self.user_scroll()
        return False
