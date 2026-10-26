"""GTK native print dialog with Pango/Cairo Unicode pagination."""
import ctypes as C
import math

from .gtk_native import P,I,S,GError

# ==========================================
# Function: Print/export a cached message with actual Unicode text and page clipping.
# Method: Render one Pango layout through GtkPrintOperation, preserving system PDF support.
# ==========================================
def print_message(app, message, export=None):
    g=app.g
    from .platform_native import load_library
    pango=load_library('pango');pc=load_library('pangocairo');cairo=load_library('cairo')
    signatures={g.libs['gtk']:{'gtk_print_operation_new':(P,),'gtk_print_operation_set_n_pages':(None,P,I),'gtk_print_operation_set_job_name':(None,P,S),'gtk_print_operation_set_export_filename':(None,P,S),'gtk_print_operation_run':(I,P,I,P,P),'gtk_print_context_create_pango_layout':(P,P),'gtk_print_context_get_width':(C.c_double,P),'gtk_print_context_get_height':(C.c_double,P),'gtk_print_context_get_cairo_context':(P,P)},pango:{'pango_layout_set_text':(None,P,S,I),'pango_layout_set_width':(None,P,I),'pango_layout_get_pixel_size':(None,P,P,P),'pango_font_description_from_string':(P,S),'pango_layout_set_font_description':(None,P,P),'pango_font_description_free':(None,P)},pc:{'pango_cairo_show_layout':(None,P,P)},cairo:{'cairo_save':(None,P),'cairo_restore':(None,P),'cairo_translate':(None,P,C.c_double,C.c_double),'cairo_rectangle':(None,P,C.c_double,C.c_double,C.c_double,C.c_double),'cairo_clip':(None,P)}}
    for lib,functions in signatures.items():
        for name,signature in functions.items():
            fn=getattr(lib,name);fn.restype=signature[0];fn.argtypes=signature[1:]
    gtk=g.libs['gtk'];operation=gtk.gtk_print_operation_new();state={};group='print-'+str(operation)
    text=message['subject']+'\n\n'+message['sender']+'\n'+message['parsed']['recipients']+'\n\n'+message['body']
    # ==========================================
    # Function: Paginate the measured native text layout.
    # Method: Compute required pages using print-context dimensions in device-independent units.
    # ==========================================
    def begin(operation,context,unused):
        layout=gtk.gtk_print_context_create_pango_layout(context)
        state['layout']=layout
        font=pango.pango_font_description_from_string(b'Noto Sans CJK SC 10')
        pango.pango_layout_set_font_description(layout,font);pango.pango_font_description_free(font)
        pango.pango_layout_set_text(layout,text.encode(),-1)
        pango.pango_layout_set_width(layout,int(gtk.gtk_print_context_get_width(context)*1024))
        width,height=I(),I();pango.pango_layout_get_pixel_size(layout,C.byref(width),C.byref(height))
        state['height']=gtk.gtk_print_context_get_height(context)
        gtk.gtk_print_operation_set_n_pages(operation,max(1,math.ceil(height.value/state['height'])))
    # ==========================================
    # Function: Draw one clipped printed page.
    # Method: Offset the same layout by the exact page height and let Pango render CJK glyphs.
    # ==========================================
    def draw(operation,context,page,unused):
        cr=gtk.gtk_print_context_get_cairo_context(context)
        cairo.cairo_save(cr);cairo.cairo_rectangle(cr,0,0,gtk.gtk_print_context_get_width(context),state['height']);cairo.cairo_clip(cr)
        cairo.cairo_translate(cr,0,-int(page)*state['height']);pc.pango_cairo_show_layout(cr,state['layout']);cairo.cairo_restore(cr)
    g.connect(operation,'begin-print',begin,count=3,group=group)
    g.connect(operation,'draw-page',draw,count=4,group=group,types=(P,P,I,P))
    gtk.gtk_print_operation_set_job_name(operation,message['subject'].encode())
    if export:gtk.gtk_print_operation_set_export_filename(operation,str(export).encode())
    error=P()
    try:
        result=gtk.gtk_print_operation_run(operation,3 if export else 0,app.window,C.byref(error))
        if result==0:
            detail=C.cast(error,C.POINTER(GError)).contents.message.decode() if error else '打印失败'
            raise RuntimeError(detail)
    finally:
        g.disconnect(group)
        if error:g.g_error_free(error)
        if state.get('layout'):g.g_object_unref(state['layout'])
        g.g_object_unref(operation)
