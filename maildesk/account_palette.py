"""Per-account color circles with a compact same-window palette."""
from .identity_colors import ACCOUNT_PALETTE

# ==========================================
# Function: Put account colors beside their own account heading instead of global settings actions.
# Method: Preserve the existing durable IdentityColors preferences and refresh only after explicit selection.
# ==========================================
class AccountPaletteUI:
    # ==========================================
    # Function: Create a permanent color-circle control for one exact account identity.
    # Method: Use a native toggle and a broker-managed palette with no OS dialog.
    # ==========================================
    def account_color_button(self,account,group='folders',boundary=None):
        g=self.g;button=g.gtk_menu_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'account-color-circle');dot=g.gtk_label_new(b'');g.gtk_container_add(button,dot);self.set_account_dot(dot,account);g.gtk_widget_set_tooltip_text(button,'调整此账户颜色'.encode())
        popup=g.gtk_popover_new(button);host=g.gtk_box_new(1,2);g.gtk_container_set_border_width(host,5);g.gtk_container_add(popup,host);g.gtk_menu_button_set_popover(button,popup)
        if boundary:g.surfaces.beside(popup,boundary)
        options_group='account-palette-'+str(popup);g.surfaces.states[popup].setdefault('cleanup',[]).append(lambda:g.surfaces.retire(options_group))
        g.connect(button,'toggled',lambda *unused:self.fill_account_palette(host,popup,account,dot,options_group) if g.gtk_toggle_button_get_active(button) else None,group=group)
        return button

    # ==========================================
    # Function: Display an account's current color without accumulating CSS providers.
    # Method: Use validated hexadecimal Pango foreground markup on one small circle glyph.
    # ==========================================
    def set_account_dot(self,dot,account):self.g.gtk_label_set_markup(dot,('<span foreground="'+self.identity_colors.account_color(account)+'">●</span>').encode())

    # ==========================================
    # Function: Show supported colors and preserve a previously customized color.
    # Method: Rebuild just this palette's rows and mark the current durable selection.
    # ==========================================
    def fill_account_palette(self,host,popup,account,dot,group):
        g=self.g;g.surfaces.retire(group);g.clear(host);current=self.identity_colors.account_color(account);colors=list(ACCOUNT_PALETTE)
        if current not in colors:colors.append(current)
        titles=['蓝色','橙色','绿色','紫色','粉色','青色','金色','灰蓝色','自定义颜色']
        for index,color in enumerate(colors):
            button=g.gtk_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'choice-option');line=g.gtk_box_new(0,12);g.gtk_container_add(button,line)
            mark=g.gtk_label_new(b'');g.gtk_label_set_markup(mark,('<span foreground="'+color+'">●</span>').encode());g.gtk_box_pack_start(line,mark,0,0,0);label=g.gtk_label_new(titles[min(index,len(titles)-1)].encode());g.gtk_label_set_xalign(label,0);g.gtk_box_pack_start(line,label,1,1,0);g.gtk_box_pack_start(line,g.gtk_label_new(('✓' if current==color else '').encode()),0,0,0)
            g.connect(button,'clicked',lambda *unused,value=color:self.apply_account_palette(popup,account,dot,value),group=group);g.gtk_box_pack_start(host,button,0,1,0)
        g.gtk_widget_show_all(host);g.surfaces.position(g.surfaces.states[popup])

    # ==========================================
    # Function: Apply a color to its own account and defer main content refresh safely.
    # Method: Close the palette before any folder header can be rebuilt and retain unsaved settings fields.
    # ==========================================
    def apply_account_palette(self,popup,account,dot,color):
        self.g.gtk_popover_popdown(popup);self.identity_colors.set_account_color(account,color);self.set_account_dot(dot,account);self.queue.put((lambda unused:self.refresh() if not self.closing else None,None))
