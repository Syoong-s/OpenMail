"""Plain numeric entry synchronized with the authoritative native settings scale."""

# ==========================================
# Function: Keep every settings slider and its right-aligned numeric entry synchronized.
# Method: Keep one authoritative scale adjustment, validate plain entry commits and invalidate both native controls after changes.
# ==========================================
class NumericRange:
    # ==========================================
    # Function: Append a bounded keyboard-editable value beside an existing native scale.
    # Method: Use a GtkEntry without stepper buttons and commit through the existing scale adjustment so bounds stay authoritative.
    # ==========================================
    def __init__(self,g,scale,parent,group,title='',step=1):
        self.g,self.scale=g,scale;self.dragging=False
        g.gtk_scale_set_draw_value(scale,0);g.gtk_scale_set_digits(scale,0)
        self.number=g.gtk_entry_new();g.gtk_entry_set_width_chars(self.number,5);g.gtk_entry_set_max_length(self.number,8);g.gtk_entry_set_alignment(self.number,1);g.gtk_entry_set_input_purpose(self.number,2)
        g.gtk_widget_set_hexpand(self.number,0);g.gtk_widget_set_valign(self.number,3);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.number),b'range-number');g.gtk_widget_set_tooltip_text(self.number,(title+' · 输入数值后按 Enter 或点击其他位置').encode());g.gtk_box_pack_start(parent,self.number,0,0,0)
        g.connect(self.number,'activate',lambda *unused:self.commit(),group=group)
        g.connect(self.number,'focus-out-event',lambda *unused:(self.commit(),False)[1],count=3,returns=True,group=group)
        g.connect(scale,'value-changed',lambda *unused:self.redraw(),group=group)
        g.connect(scale,'button-press-event',lambda *unused:self.pointer(True),count=3,returns=True,group=group)
        g.connect(scale,'button-release-event',lambda *unused:self.pointer(False),count=3,returns=True,group=group)
        g.connect(scale,'grab-broken-event',lambda *unused:self.pointer(False),count=3,returns=True,group=group)
        self.redraw()

    # ==========================================
    # Function: Defer expensive appearance preview while the user holds a range thumb.
    # Method: Observe native pointer lifetime without claiming or consuming GTK's drag events.
    # ==========================================
    def pointer(self,active):
        self.dragging=active;return False

    # ==========================================
    # Function: Repaint the actual scale and numeric entry after the shared value changes.
    # Method: Invalidate both widgets without resizing or rebuilding the active settings page.
    # ==========================================
    def redraw(self):
        self.g.text(self.number,str(int(round(self.g.gtk_range_get_value(self.scale)))));self.g.gtk_widget_queue_draw(self.scale);self.g.gtk_widget_queue_draw(self.number)

    # ==========================================
    # Function: Commit in-progress keyboard input before saving the form.
    # Method: Parse bounded integer text, restore invalid partial input and let GtkRange clamp valid values before mirroring the result.
    # ==========================================
    def commit(self):
        try:value=int(self.g.text(self.number).strip())
        except (ValueError,TypeError):value=self.g.gtk_range_get_value(self.scale)
        self.g.gtk_range_set_value(self.scale,value);self.redraw()
