"""Native HSV palette and always-visible RGB swatches without chooser windows."""
import colorsys
import ctypes as C
from functools import lru_cache
import math

P=C.c_void_p

# ==========================================
# Function: Bind the existing private Cairo runtime for compact native color drawing.
# Method: Cache typed gradient/fill/stroke functions; no additional package or render process is created.
# ==========================================
@lru_cache(maxsize=1)
def cairo_api():
    from .platform_native import load_library
    cairo=load_library('cairo');functions={
        'cairo_set_source_rgb':(None,P,C.c_double,C.c_double,C.c_double),'cairo_set_source_rgba':(None,P,C.c_double,C.c_double,C.c_double,C.c_double),
        'cairo_rectangle':(None,P,C.c_double,C.c_double,C.c_double,C.c_double),'cairo_fill':(None,P),'cairo_set_source':(None,P,P),
        'cairo_pattern_create_linear':(P,C.c_double,C.c_double,C.c_double,C.c_double),'cairo_pattern_add_color_stop_rgba':(None,P,C.c_double,C.c_double,C.c_double,C.c_double,C.c_double),'cairo_pattern_destroy':(None,P),
        'cairo_arc':(None,P,C.c_double,C.c_double,C.c_double,C.c_double,C.c_double),'cairo_stroke':(None,P),'cairo_set_line_width':(None,P,C.c_double)}
    for name,signature in functions.items():
        function=getattr(cairo,name);function.restype,function.argtypes=signature[0],signature[1:]
    return cairo

# ==========================================
# Function: Select saturation/value directly while keeping the shared hex field authoritative.
# Method: Draw two native gradients over the current hue and map a claimed drag to bounded HSV coordinates.
# ==========================================
class ColorPalette:
    # ==========================================
    # Function: Own the native palette and its gesture inside the existing adjacent color menu.
    # Method: Reuse the caller's signal group and send only validated six-digit RGB values.
    # ==========================================
    def __init__(self,g,group,changed):
        self.g,self.changed=g,changed;self.hue=0;self.saturation=0;self.value=1;self.rgb=(1,1,1);self.start=(0,0);self.closed=False
        self.widget=g.gtk_drawing_area_new();g.gtk_widget_set_size_request(self.widget,260,145);g.gtk_widget_set_tooltip_text(self.widget,'拖动选择颜色：左右调整饱和度，上下调整明度'.encode())
        g.connect(self.widget,'draw',self.draw,count=3,returns=True,group=group)
        self.gesture=g.gtk_gesture_drag_new(self.widget);g.gtk_gesture_single_set_button(self.gesture,1)
        g.connect(self.gesture,'drag-begin',self.begin,types=[P,C.c_double,C.c_double,P],group=group)
        g.connect(self.gesture,'drag-update',lambda widget,x,y,data:self.select(self.start[0]+x,self.start[1]+y),types=[P,C.c_double,C.c_double,P],group=group)

    # ==========================================
    # Function: Mirror hex/RGB edits without losing hue when selecting gray or black.
    # Method: Preserve the previous chromatic hue for achromatic values and queue only native redraws.
    # ==========================================
    def sync(self,color):
        self.rgb=tuple(int(color[index:index+2],16)/255 for index in (1,3,5));hue,saturation,value=colorsys.rgb_to_hsv(*self.rgb)
        if saturation>.001:self.hue=hue
        if value>.001:self.saturation=saturation
        self.value=value;self.g.gtk_widget_queue_draw(self.widget)

    # ==========================================
    # Function: Capture a palette drag before the enclosing settings scroller claims it.
    # Method: Store gesture-relative start coordinates and immediately apply the initial selection.
    # ==========================================
    def begin(self,gesture,x,y,unused):
        self.start=(x,y);self.g.gtk_gesture_set_state(gesture,1);self.select(x,y)

    # ==========================================
    # Function: Convert native palette coordinates into a bounded color selection.
    # Method: Clamp saturation/value and emit RGB through the same existing entry/change pipeline.
    # ==========================================
    def select(self,x,y):
        width=max(1,self.g.gtk_widget_get_allocated_width(self.widget)-1);height=max(1,self.g.gtk_widget_get_allocated_height(self.widget)-1)
        self.saturation=min(1,max(0,x/width));self.value=1-min(1,max(0,y/height));self.emit()

    # ==========================================
    # Function: Apply a hue-strip adjustment while preserving the current tone.
    # Method: Keep achromatic selections meaningful by leaving their saturation/value unchanged.
    # ==========================================
    def set_hue(self,degrees):
        self.hue=min(360,max(0,float(degrees)))/360;self.emit()

    # ==========================================
    # Function: Emit one finite RGB color and repaint the crosshair.
    # Method: Encode only numeric HSV conversion output, never interpolate arbitrary CSS.
    # ==========================================
    def emit(self):
        self.rgb=colorsys.hsv_to_rgb(self.hue,self.saturation,self.value);self.changed('#'+''.join(f'{round(channel*255):02x}' for channel in self.rgb));self.g.gtk_widget_queue_draw(self.widget)

    # ==========================================
    # Function: Paint a true two-dimensional color palette with a readable selection marker.
    # Method: Composite horizontal white and vertical black gradients over the chosen hue, releasing both patterns per draw.
    # ==========================================
    def draw(self,widget,cr,unused):
        cairo=cairo_api();width=self.g.gtk_widget_get_allocated_width(widget);height=self.g.gtk_widget_get_allocated_height(widget)
        cairo.cairo_set_source_rgb(cr,*colorsys.hsv_to_rgb(self.hue,1,1));cairo.cairo_rectangle(cr,0,0,width,height);cairo.cairo_fill(cr)
        for coordinates,start,end in [((0,0,width,0),(1,1,1,1),(1,1,1,0)),((0,0,0,height),(0,0,0,0),(0,0,0,1))]:
            pattern=cairo.cairo_pattern_create_linear(*coordinates)
            cairo.cairo_pattern_add_color_stop_rgba(pattern,0,*start);cairo.cairo_pattern_add_color_stop_rgba(pattern,1,*end);cairo.cairo_set_source(cr,pattern);cairo.cairo_rectangle(cr,0,0,width,height);cairo.cairo_fill(cr);cairo.cairo_pattern_destroy(pattern)
        x=self.saturation*max(1,width-1);y=(1-self.value)*max(1,height-1)
        for radius,color in ((6,(0,0,0)),(4,(1,1,1))):
            cairo.cairo_set_source_rgb(cr,*color);cairo.cairo_set_line_width(cr,2);cairo.cairo_arc(cr,x,y,radius,0,math.tau);cairo.cairo_stroke(cr)
        return True

    # ==========================================
    # Function: Paint a solid current-color preview using existing native widgets.
    # Method: Keep preview opacity independent of the surrounding panel's alpha.
    # ==========================================
    def draw_preview(self,widget,cr,unused):
        cairo=cairo_api();width=self.g.gtk_widget_get_allocated_width(widget);height=self.g.gtk_widget_get_allocated_height(widget)
        cairo.cairo_set_source_rgb(cr,*self.rgb);cairo.cairo_rectangle(cr,0,0,width,height);cairo.cairo_fill(cr);cairo.cairo_set_source_rgba(cr,.5,.5,.5,.7);cairo.cairo_set_line_width(cr,1);cairo.cairo_rectangle(cr,.5,.5,width-1,height-1);cairo.cairo_stroke(cr);return True

    # ==========================================
    # Function: Release the palette's single owned gesture exactly once.
    # Method: The caller retires shared native callbacks before dropping this final object reference.
    # ==========================================
    def close(self):
        if self.closed:return
        self.closed=True;self.g.g_object_unref(self.gesture)
