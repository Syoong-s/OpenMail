"""Compact account scope trigger backed by the existing native filter controller."""
from .local_mail import LOCAL_ACCOUNT,LOCAL_LABEL

# ==========================================
# Function: Provide a compact account scope popover with stable selection and account colors.
# Method: Keep the hidden combo as the filter controller while presenting accessible native buttons.
# ==========================================
class AccountScopeUI:
    # ==========================================
    # Function: Create the visible account scope trigger once.
    # Method: Pack an icon, selected label and chevron beside the hidden compatibility controller.
    # ==========================================
    def ensure_account_pill(self):
        if getattr(self,'account_pill',None):return
        g=self.g;combo=self.widget('account_filter');parent=g.gtk_widget_get_parent(combo)
        g.gtk_widget_set_no_show_all(combo,1);g.gtk_widget_set_visible(combo,0)
        pill=g.gtk_menu_button_new();self.account_pill=pill;g.gtk_style_context_add_class(g.gtk_widget_get_style_context(pill),b'account-scope-pill')
        content=g.gtk_box_new(0,6);g.gtk_container_add(pill,content)
        icon=g.gtk_image_new_from_icon_name(b'mail-unread-symbolic',1);g.gtk_box_pack_start(content,icon,0,0,0)
        label=g.gtk_label_new('全部账户'.encode());self.account_pill_label=label;g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,17);g.gtk_box_pack_start(content,label,1,1,0)
        g.gtk_box_pack_start(content,g.gtk_image_new_from_icon_name(b'pan-down-symbolic',1),0,0,0);g.gtk_box_pack_start(parent,pill,0,0,0)
        popup=g.gtk_popover_new(pill);self.account_popover=popup;g.gtk_style_context_add_class(g.gtk_widget_get_style_context(popup),b'account-scope-popover');g.gtk_menu_button_set_popover(pill,popup)
        box=g.gtk_box_new(1,4);self.account_scope_host=box;g.gtk_container_set_border_width(popup,8);g.gtk_container_add(popup,box)
        g.gtk_widget_set_tooltip_text(pill,'切换账户范围'.encode());g.gtk_widget_show_all(pill)

    # ==========================================
    # Function: Rebuild account choices without changing the user's valid selected scope.
    # Method: Update the hidden combo under signal suppression, then create colored popover rows.
    # ==========================================
    def fill_accounts(self):
        g=self.g;combo=self.widget('account_filter');selected=g.gtk_combo_box_get_active_id(combo) or b'all';self.rendering=True
        entries=[('all','全部账户','统一收件箱')]
        if self.profile.demo:entries.append(('demo','演示账户','demo@example.com'))
        else:
            entries.extend((account.id,account.title or account.email,account.email) for account in self.service.accounts.values())
            entries.append((LOCAL_ACCOUNT,LOCAL_LABEL,'此设备上的邮件'))
        self.account_scope_entries={identity:(title,email) for identity,title,email in entries}
        g.gtk_combo_box_text_remove_all(combo)
        for identity,title,email in entries:g.gtk_combo_box_text_append(combo,identity.encode(),title.encode())
        if not g.gtk_combo_box_set_active_id(combo,selected):g.gtk_combo_box_set_active_id(combo,b'all')
        self.rendering=False;self.ensure_account_pill();g.disconnect('account-scope');g.clear(self.account_scope_host);self.account_buttons={};self.account_checks={}
        title=g.gtk_label_new('账户范围'.encode());g.gtk_label_set_xalign(title,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(title),b'account-scope-heading');g.gtk_box_pack_start(self.account_scope_host,title,0,1,0)
        colors=self.identity_colors.snapshot([identity for identity,_,_ in entries if identity!='all'])['colors']
        for identity,title,email in entries:
            button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'account-scope-row');row=g.gtk_box_new(0,9);g.gtk_container_add(button,row)
            dot=g.gtk_label_new(('◎' if identity=='all' else '●').encode());g.gtk_box_pack_start(row,dot,0,0,0)
            if identity!='all':g.style(dot,'label { color: '+colors[identity]+'; }')
            labels=g.gtk_box_new(1,2);g.gtk_box_pack_start(row,labels,1,1,0)
            for text,css in [(title,'account-scope-title'),(email,'account-scope-subtitle')]:
                label=g.gtk_label_new(text.encode());g.gtk_label_set_xalign(label,0);g.gtk_label_set_ellipsize(label,3);g.gtk_label_set_max_width_chars(label,30);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(label),css.encode());g.gtk_box_pack_start(labels,label,0,1,0)
            check=g.gtk_label_new(b'');g.gtk_box_pack_start(row,check,0,0,0);self.account_checks[identity]=check;self.account_buttons[identity]=button
            g.connect(button,'clicked',lambda *unused,identity=identity:self.choose_account_scope(identity),group='account-scope');g.gtk_box_pack_start(self.account_scope_host,button,0,1,0)
        g.gtk_widget_show_all(self.account_scope_host);self.update_account_pill()

    # ==========================================
    # Function: Apply a chosen account using the real existing filter change signal.
    # Method: Close the popover and select the stable account identity on the hidden combo.
    # ==========================================
    def choose_account_scope(self,identity):
        self.g.gtk_popover_popdown(self.account_popover);self.g.gtk_combo_box_set_active_id(self.widget('account_filter'),identity.encode());self.update_account_pill()

    # ==========================================
    # Function: Keep the visible account title and selected checkmark synchronized.
    # Method: Reflect the actual controller after refresh, removal and programmatic scope changes.
    # ==========================================
    def update_account_pill(self):
        if not getattr(self,'account_pill',None):return
        identity=(self.g.gtk_combo_box_get_active_id(self.widget('account_filter')) or b'all').decode();title,email=self.account_scope_entries.get(identity,('全部账户','统一收件箱'))
        self.g.label(self.account_pill_label,title);self.g.gtk_widget_set_tooltip_text(self.account_pill,(title+' · '+email).encode())
        for key,check in self.account_checks.items():self.g.label(check,'✓' if key==identity else '')
