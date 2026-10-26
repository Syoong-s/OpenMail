"""Compact RGB/hex color controls in the common adjacent native flyout."""
import ctypes as C
import re

# ==========================================
# Function: Select a validated color without an operating-system chooser window.
# Method: Keep the original text controller and synchronize a chip, RGB sliders and preset swatches.
# ==========================================
class NativeColor:
    # ==========================================
    # Function: Append a color-circle toggle to its existing native field row.
    # Method: Retain ordinary entry value/change APIs and own callbacks until the chip is destroyed.
    # ==========================================
    def __init__(self,g,entry,title):
        self.g,self.entry=g,entry;self.group='color-'+str(entry);self.syncing=False;self.closed=False;self.sliders=[]
        self.button=g.gtk_menu_button_new();g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.button),b'color-chip');g.gtk_widget_set_tooltip_text(self.button,(title+' · 选择颜色').encode());line=g.gtk_box_new(0,6);self.preview=g.gtk_drawing_area_new();g.gtk_widget_set_size_request(self.preview,44,24);g.gtk_box_pack_start(line,self.preview,0,0,0);g.gtk_container_add(self.button,line);g.gtk_box_pack_start(g.gtk_widget_get_parent(entry),self.button,0,0,4)
        accessible=g.gtk_widget_get_accessible(self.button);setter=C.CFUNCTYPE(None,C.c_void_p,C.c_char_p,C.c_char_p,C.c_void_p)(C.cast(g.libs['object'].g_object_set,C.c_void_p).value);setter(accessible,b'accessible-name',(title+' · 选择颜色').encode(),None)
        self.popup=g.gtk_popover_new(self.button);self.host=g.gtk_box_new(1,8);g.gtk_container_set_border_width(self.host,12);g.gtk_widget_set_size_request(self.host,280,-1);g.gtk_container_add(self.popup,self.host);g.gtk_menu_button_set_popover(self.button,self.popup)
        heading=g.gtk_label_new(title.encode());g.gtk_label_set_xalign(heading,0);g.gtk_box_pack_start(self.host,heading,0,1,0)
        from .color_palette import ColorPalette
        self.palette=ColorPalette(g,self.group,lambda color:g.text(entry,color));g.gtk_box_pack_start(self.host,self.palette.widget,0,1,0)
        from .native_ranges import NumericRange
        hue_line=g.gtk_box_new(0,8);g.gtk_box_pack_start(self.host,hue_line,0,1,0)
        self.hue=g.gtk_scale_new_with_range(0,0,360,1);g.gtk_scale_set_draw_value(self.hue,0);g.gtk_style_context_add_class(g.gtk_widget_get_style_context(self.hue),b'color-hue');g.gtk_box_pack_start(hue_line,self.hue,1,1,0);self.hue_range=NumericRange(g,self.hue,hue_line,self.group,'色相（°）');self.ranges=[]
        g.connect(self.hue,'value-changed',lambda *unused:self.palette.set_hue(g.gtk_range_get_value(self.hue)) if not self.syncing else None,group=self.group)
        g.connect(self.preview,'draw',self.palette.draw_preview,count=3,returns=True,group=self.group)
        self.current_preview=g.gtk_drawing_area_new();g.gtk_widget_set_size_request(self.current_preview,-1,26);g.gtk_box_pack_start(self.host,self.current_preview,0,1,0);g.connect(self.current_preview,'draw',self.palette.draw_preview,count=3,returns=True,group=self.group)
        self.current_hex=g.gtk_label_new(b'');g.gtk_label_set_xalign(self.current_hex,0);g.gtk_box_pack_start(self.host,self.current_hex,0,1,0)
        for channel in ('R','G','B'):
            line=g.gtk_box_new(0,8);g.gtk_box_pack_start(line,g.gtk_label_new(channel.encode()),0,0,0);scale=g.gtk_scale_new_with_range(0,0,255,1);g.gtk_scale_set_digits(scale,0);g.gtk_box_pack_start(line,scale,1,1,0);g.gtk_box_pack_start(self.host,line,0,1,0);self.sliders.append(scale);self.ranges.append(NumericRange(g,scale,line,self.group,channel))
            g.connect(scale,'value-changed',lambda *unused:self.from_sliders(),group=self.group)
        swatches=g.gtk_box_new(1,3);g.gtk_box_pack_start(self.host,swatches,0,1,3)
        for index,value in enumerate(('#141414','#252525','#454545','#b4b4b4','#f1f1f1','#ffffff','#8dacf5','#a792e8','#68bda8','#e1a86e','#eb8295','#65c9d7')):
            if index%6==0:row=g.gtk_box_new(0,4);g.gtk_box_pack_start(swatches,row,0,1,0)
            button=g.gtk_button_new();label=g.gtk_label_new(b'');g.gtk_label_set_markup(label,('<span foreground="'+value+'">●</span>').encode());g.gtk_container_add(button,label);g.gtk_widget_set_tooltip_text(button,value.encode());g.gtk_style_context_add_class(g.gtk_widget_get_style_context(button),b'color-swatch');g.gtk_box_pack_start(row,button,1,1,0);g.connect(button,'clicked',lambda *unused,color=value:g.text(entry,color),group=self.group)
        g.connect(entry,'changed',lambda *unused:self.sync(),group=self.group);g.connect(self.button,'destroy',lambda *unused:self.close(),group=self.group);self.sync()

    # ==========================================
    # Function: Mirror a complete valid color while leaving partial typing intact.
    # Method: Update the swatch and bounded native channels under one recursion guard.
    # ==========================================
    def sync(self):
        if self.closed or self.syncing:return
        value=self.g.text(self.entry)
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',value):return
        self.syncing=True
        try:
            self.palette.sync(value);self.g.gtk_range_set_value(self.hue,self.palette.hue*360);self.g.label(self.current_hex,'当前颜色  '+value.upper());self.g.gtk_widget_queue_draw(self.preview);self.g.gtk_widget_queue_draw(self.current_preview)
            for index,scale in enumerate(self.sliders):self.g.gtk_range_set_value(scale,int(value[index*2+1:index*2+3],16))
        finally:self.syncing=False

    # ==========================================
    # Function: Apply an explicit RGB adjustment to the original field.
    # Method: Produce a finite six-digit hex value and let existing changed handlers preview it.
    # ==========================================
    def from_sliders(self):
        if self.syncing or self.closed:return
        value='#'+''.join(f'{int(round(self.g.gtk_range_get_value(scale))):02x}' for scale in self.sliders);self.g.text(self.entry,value)

    # ==========================================
    # Function: Release color callbacks before the original form fields disappear.
    # Method: Retire native trampolines through the shared surface owner.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True;self.g.surfaces.retire(self.group);self.palette.close()
