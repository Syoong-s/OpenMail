"""Compact sender chip and account menu using the shared native surface broker."""
from .native_choices import NativeChoice

# ==========================================
# Function: Present sender selection next to Send with explicit account identity.
# Method: Keep NativeChoice's controller/lifecycle contract and render concise checked menu rows.
# ==========================================
class SenderChoice(NativeChoice):
    # ==========================================
    # Function: Style one sender controller without duplicating its selected account state.
    # Method: Reuse the hidden combo, owned dropdown and programmatic changed signals.
    # ==========================================
    def __init__(self,app,combo,return_focus=None):
        self.app=app;self.return_focus=return_focus
        super().__init__(app.g,combo,'发件邮箱')
        g=self.g;g.gtk_label_set_max_width_chars(self.label,20)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'sender-choice')
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.popup),b'sender-menu')
        g.surfaces.states[self.popup]['width']=310;g.surfaces.states[self.popup]['placement']='above'

    # ==========================================
    # Function: Render account identities and an unambiguous selection checkmark.
    # Method: Use the configured sender's title/email with the same rounded menu rows as other controls.
    # ==========================================
    def fill(self):
        if self.closed:return
        g=self.g;g.surfaces.retire(self.group+'-options');g.clear(self.menu)
        heading=g.gtk_label_new('发件邮箱'.encode());g.gtk_label_set_xalign(heading,0)
        g.gtk_style_context_add_class(g.gtk_widget_get_style_context(heading),b'picker-heading');g.gtk_box_pack_start(self.menu,heading,0,1,0)
        selected=(g.gtk_combo_box_get_active_id(self.combo) or b'').decode()
        for identity,caption in self.items():
            account=self.app.service.accounts.get(identity)
            title=(getattr(account,'title','') or getattr(account,'display_name','')) if account else caption
            email=getattr(account,'email','') if account else ''
            button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'choice-option')
            line=g.gtk_box_new(0,10);g.gtk_container_add(button,line)
            avatar=g.gtk_label_new((title or caption)[:1].upper().encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(avatar),b'picker-avatar');g.gtk_box_pack_start(line,avatar,0,0,0)
            labels=g.gtk_box_new(1,2);g.gtk_box_pack_start(line,labels,1,1,0)
            for text,role in [(title or caption,''),(email if email and email!=title else '','choice-description')]:
                if not text:continue
                label=g.gtk_label_new(text.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,30)
                if role:g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),role.encode())
                g.gtk_box_pack_start(labels,label,0,1,0)
            check=g.gtk_label_new(('✓' if identity==selected else '').encode());g.gtk_widget_set_size_request(check,16,-1);g.gtk_box_pack_start(line,check,0,0,0)
            g.gtk_widget_set_tooltip_text(button,caption.encode());g.gtk_box_pack_start(self.menu,button,0,1,0)
            g.connect(button,'clicked',lambda *unused,value=identity:self.select(value),group=self.group+'-options')
        g.gtk_widget_show_all(self.menu)
        state=g.surfaces.states.get(self.popup)
        if state:g.surfaces.position(state)

    # ==========================================
    # Function: Keep the live reply expanded after a real pointer selection dismisses its menu.
    # Method: Return focus from the hidden option row to the original editor before deferred blur checks.
    # ==========================================
    def select(self,identity):
        if self.closed:return
        super().select(identity)
        self.g.gtk_widget_grab_focus(self.return_focus or self.button)
