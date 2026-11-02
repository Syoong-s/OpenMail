"""A small native calendar with accessible date selection and vector cells."""
import ctypes as C
from datetime import date,timedelta
from functools import lru_cache
from math import pi
from .platform_native import load_library

P=C.c_void_p;D=C.c_double;I=C.c_int


# ==========================================
# Function: Bind the bundled vector/text renderer once for all calendar repaints.
# Method: Draw Unicode month labels with Pango and rounded cells at native device resolution.
# ==========================================
@lru_cache(maxsize=1)
def drawing_api():
    cairo=load_library('cairo');pango=load_library('pango');pc=load_library('pangocairo')
    for library,functions in ((cairo,{'cairo_set_source_rgba':(None,P,D,D,D,D),'cairo_new_sub_path':(None,P),
        'cairo_arc':(None,P,D,D,D,D,D),'cairo_close_path':(None,P),'cairo_fill':(None,P),'cairo_stroke':(None,P),
        'cairo_set_line_width':(None,P,D),'cairo_move_to':(None,P,D,D)}),
        (pango,{'pango_layout_set_text':(None,P,C.c_char_p,I),'pango_layout_set_font_description':(None,P,P),
        'pango_font_description_from_string':(P,C.c_char_p),'pango_font_description_free':(None,P)}),
        (pc,{'pango_cairo_show_layout':(None,P,P)})):
        for name,signature in functions.items():
            function=getattr(library,name);function.restype,function.argtypes=signature[0],signature[1:]
    return cairo,pango,pc


# ==========================================
# Function: Expose daily incoming/outgoing activity without a browser or hundreds of widgets.
# Method: Own one Cairo canvas, native tooltip and keyboard/pointer selection handlers.
# ==========================================
class ActivityHeatmap:
    # ==========================================
    # Function: Construct one focusable calendar in the dashboard's native widget tree.
    # Method: Keep geometry and selection local; delegate date changes to the dashboard controller.
    # ==========================================
    def __init__(self,owner):
        self.owner=owner;self.g=g=owner.g;self.data=None;self.cells=[];self.hover=None
        self.widget=g.gtk_drawing_area_new();g.gtk_widget_set_size_request(self.widget,-1,150)
        focus=g.libs['gtk'].gtk_widget_set_can_focus;focus.restype=None;focus.argtypes=[P,I];focus(self.widget,1)
        g.gtk_widget_add_events(self.widget,(1<<2)|(1<<8)|(1<<13))
        g.gtk_widget_set_tooltip_text(self.widget,'每日邮件收发数量 · 点击日期查看 · 方向键切换日期'.encode())
        g.connect(self.widget,'draw',self.draw,count=3,returns=True,group='activity')
        g.connect(self.widget,'motion-notify-event',self.motion,count=3,returns=True,group='activity')
        g.connect(self.widget,'button-press-event',self.pressed,count=3,returns=True,group='activity')
        g.connect(self.widget,'key-press-event',self.key,count=3,returns=True,group='activity')
        g.connect(self.widget,'leave-notify-event',self.leave,count=3,returns=True,group='activity')
        g.connect(self.widget,'size-allocate',self.resize,count=3,group='activity')

    # ==========================================
    # Function: Keep the calendar card compact when a narrower reader shrinks its cells.
    # Method: Match the requested canvas height to seven fitted rows instead of leaving a fixed empty band.
    # ==========================================
    def resize(self,widget,allocation,data):
        from math import ceil
        width=self.g.gtk_widget_get_allocated_width(widget)
        if width<40:return
        height=max(88,ceil(29+7*min(17,max(4,(width-31)/53))))
        if height!=getattr(self,'height',None):
            self.height=height;self.owner.app.queue.put((self.apply_height,height))

    # ==========================================
    # Function: Reflow the calendar after GTK finishes its current allocation pass.
    # Method: Apply only the latest queued height on the native event loop, avoiding ignored recursive resize requests.
    # ==========================================
    def apply_height(self,height):
        if not self.owner.app.closing and self.height==height:self.g.gtk_widget_set_size_request(self.widget,-1,height)

    # ==========================================
    # Function: Resolve a hit from public GDK event coordinates.
    # Method: Compare against the last painted cell geometry, excluding future and gap pixels.
    # ==========================================
    def hit(self,event):
        getter=self.g.libs['gdk'].gdk_event_get_coords;getter.restype=I;getter.argtypes=[P,C.POINTER(D),C.POINTER(D)]
        x,y=D(),D();getter(event,C.byref(x),C.byref(y))
        return next((day for day,left,top,size in self.cells if left<=x.value<=left+size and top<=y.value<=top+size),None)

    # ==========================================
    # Function: Explain the exact local date and separate received/sent counts on hover.
    # Method: Update only when the hovered cell changes, leaving GTK to display the tooltip.
    # ==========================================
    def motion(self,widget,event,data):
        day=self.hit(event)
        if day!=self.hover:
            self.hover=day;counts=(self.data or {}).get('days',{}).get(day,{})
            text=(day+' · 收到 '+str(counts.get('received',0))+' 封 · 发出 '+str(counts.get('sent',0))+' 封') if day else '点击日期查看邮件'
            self.g.gtk_widget_set_tooltip_text(widget,text.encode());self.g.gtk_widget_queue_draw(widget)
        return False

    # ==========================================
    # Function: Clear the temporary cell outline when the pointer leaves the calendar.
    # Method: Retain the selected date while repainting only the single canvas.
    # ==========================================
    def leave(self,*unused):self.hover=None;self.g.gtk_widget_queue_draw(self.widget);return False

    # ==========================================
    # Function: Select a real day from a primary pointer click.
    # Method: Reject future/gap cells and preserve native keyboard focus on the calendar.
    # ==========================================
    def pressed(self,widget,event,data):
        button=C.c_uint();getter=self.g.libs['gdk'].gdk_event_get_button;getter.restype=I;getter.argtypes=[P,C.POINTER(C.c_uint)]
        if not getter(event,C.byref(button)) or button.value!=1:return False
        day=self.hit(event)
        if day:self.g.gtk_widget_grab_focus(widget);self.owner.select_day(date.fromisoformat(day))
        return bool(day)

    # ==========================================
    # Function: Provide keyboard access to the same date selection used by the timeline controls.
    # Method: Move by days or weeks, clamping to available calendar dates in the owner.
    # ==========================================
    def key(self,widget,event,data):
        value=C.c_uint();getter=self.g.libs['gdk'].gdk_event_get_keyval;getter.restype=I;getter.argtypes=[P,C.POINTER(C.c_uint)];getter(event,C.byref(value))
        offset={65361:-7,65363:7,65362:-1,65364:1}.get(value.value)
        if offset is None:return False
        self.owner.select_day(self.owner.selected+timedelta(days=offset));return True

    # ==========================================
    # Function: Paint a full year of activity with quiet month/weekday labels and a selected-day ring.
    # Method: Fit 53 weeks to available width and use a five-step logarithmic intensity scale.
    # ==========================================
    def draw(self,widget,cr,data):
        from math import log2
        from .mail_activity import calendar_bounds
        g=self.g;cairo,pango,pc=drawing_api();today=date.today();start=calendar_bounds(today)[0]
        if self.data:today=date.fromisoformat(self.data['today']);start=date.fromisoformat(self.data['start'])
        width=g.gtk_widget_get_allocated_width(widget);step=min(17,max(4,(width-31)/53));size=max(2,step-3);top=25;left=29
        color=g.libs['gtk'].gtk_style_context_get_color;color.restype=None;color.argtypes=[P,I,P]
        rgba=(D*4)();color(g.gtk_widget_get_style_context(widget),0,C.byref(rgba));dark=sum(rgba[:3])>1.5
        colors=('#2b3039','#304d49','#387264','#469e84','#66d7ac') if dark else ('#e9edf0','#c2e5d6','#89c6ad','#4f9c81','#27715c')
        creator=g.libs['gtk'].gtk_widget_create_pango_layout;creator.restype=P;creator.argtypes=[P,C.c_char_p]
        layout=creator(widget,b'');font=pango.pango_font_description_from_string(b'Sans 9');pango.pango_layout_set_font_description(layout,font)

        # ==========================================
        # Function: Draw one small Unicode annotation using the native text renderer.
        # Method: Reuse one Pango layout and theme foreground throughout the paint callback.
        # ==========================================
        def text(value,x,y):
            cairo.cairo_set_source_rgba(cr,*rgba[:3],.58);cairo.cairo_move_to(cr,x,y);pango.pango_layout_set_text(layout,value.encode(),-1);pc.pango_cairo_show_layout(cr,layout)

        # ==========================================
        # Function: Construct a smooth calendar cell or outline path.
        # Method: Join four circular corners, leaving fill/stroke selection to the caller.
        # ==========================================
        def rounded(x,y,edge):
            radius=min(2.4,edge/3);cairo.cairo_new_sub_path(cr)
            for cx,cy,a,b in ((x+edge-radius,y+radius,-pi/2,0),(x+edge-radius,y+edge-radius,0,pi/2),(x+radius,y+edge-radius,pi/2,pi),(x+radius,y+radius,pi,3*pi/2)):
                cairo.cairo_arc(cr,cx,cy,radius,a,b)
            cairo.cairo_close_path(cr)
        try:
            for index,label in ((0,'一'),(2,'三'),(4,'五')):text(label,0,top+index*step-2)
            self.cells=[];month=None
            for week in range(53):
                first=start+timedelta(days=week*7)
                if first.month!=month:
                    if week<51:text(str(first.month)+'月',left+week*step,0)
                    month=first.month
                for weekday in range(7):
                    day=first+timedelta(days=weekday)
                    if day>today:continue
                    key=day.isoformat();counts=(self.data or {}).get('days',{}).get(key,{})
                    count=counts.get('received',0)+counts.get('sent',0);level=min(4,1+int(log2(count))) if count else 0
                    color=colors[level];cairo.cairo_set_source_rgba(cr,*[int(color[i:i+2],16)/255 for i in (1,3,5)],1)
                    x=left+week*step;y=top+weekday*step;rounded(x,y,size);cairo.cairo_fill(cr)
                    self.cells.append((key,x,y,size))
                    if key==self.owner.selected.isoformat() or key==self.hover:
                        cairo.cairo_set_source_rgba(cr,*rgba[:3],.95 if key==self.owner.selected.isoformat() else .45)
                        cairo.cairo_set_line_width(cr,1.2);rounded(x-1,y-1,size+2);cairo.cairo_stroke(cr)
        finally:pango.pango_font_description_free(font);g.g_object_unref(layout)
        return False
