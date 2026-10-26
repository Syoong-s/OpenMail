"""Native limited rich text: inert HTML import and explicit composer formatting."""
import ctypes as C
from html import escape
from html.parser import HTMLParser

from .gtk_native import P,I,S

# ==========================================
# Function: Convert HTML into inert text and formatting ranges.
# Method: Interpret only text, block breaks and simple emphasis; never load external content.
# ==========================================
class InertRichText(HTMLParser):
    # ==========================================
    # Function: Initialize a bounded formatting accumulator.
    # Method: Track emitted character offsets and only supported nested tags.
    # ==========================================
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.position=0;self.stack=[];self.ranges=[];self.hidden=0

    # ==========================================
    # Function: Emit text and retain its exact character offset.
    # Method: Share one accumulator for both text and line-break events.
    # ==========================================
    def append(self,text):
        self.parts.append(text);self.position+=len(text)

    # ==========================================
    # Function: Parse permitted rich-text starts without processing active HTML.
    # Method: Ignore script/style/embedded subtrees and track simple formatting spans.
    # ==========================================
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','iframe','object','svg','head'):self.hidden+=1;return
        if self.hidden:return
        kind={'b':'bold','strong':'bold','i':'italic','em':'italic','u':'underline','a':'underline'}.get(tag)
        if kind:self.stack.append((tag,kind,self.position))
        if tag=='br':self.append('\n')
        elif tag in ('p','div','li','h1','h2','h3','tr') and self.position and not self.parts[-1].endswith('\n'):self.append('\n')
        if tag=='li':self.append('• ')
        if tag=='img':self.append('[图片: '+dict(attrs).get('alt','内嵌图片')+']')

    # ==========================================
    # Function: Close rich-text spans and block lines.
    # Method: Attach ranges only to already emitted inert text.
    # ==========================================
    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object','svg','head'):
            self.hidden=max(0,self.hidden-1);return
        if self.hidden:return
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                _,kind,start=self.stack.pop(i)
                self.ranges.append((kind,start,self.position));break
        if tag in ('p','div','li','h1','h2','h3','tr') and self.position and not self.parts[-1].endswith('\n'):self.append('\n')

    # ==========================================
    # Function: Retain only visible text content.
    # Method: Drop data from blocked subtrees and preserve source Unicode.
    # ==========================================
    def handle_data(self,data):
        if not self.hidden:self.append(data)

# ==========================================
# Function: Manage native TextBuffer formatting without HTML/browser widgets.
# Method: Use GtkTextTag ranges and serialize only escaped generated markup.
# ==========================================
class NativeRichText:
    # ==========================================
    # Function: Bind a text view to safe bold/italic/underline GTK tags.
    # Method: Declare fixed ABI signatures and let the buffer own added tags.
    # ==========================================
    def __init__(self,g,view):
        self.g,self.view=g,view;self.buffer=g.gtk_text_view_get_buffer(view)
        gtk=g.libs['gtk'];self.gtk=gtk
        functions={'gtk_text_tag_new':(P,S),'gtk_text_buffer_get_tag_table':(P,P),'gtk_text_tag_table_add':(I,P,P),'gtk_text_buffer_get_iter_at_offset':(None,P,P,I),'gtk_text_buffer_get_selection_bounds':(I,P,P,P),'gtk_text_buffer_apply_tag':(None,P,P,P,P),'gtk_text_buffer_remove_tag':(None,P,P,P,P),'gtk_text_iter_get_offset':(I,P),'gtk_text_iter_has_tag':(I,P,P),'gtk_text_iter_forward_to_tag_toggle':(I,P,P),'gtk_text_buffer_delete':(None,P,P,P),'gtk_text_buffer_insert':(None,P,P,S,I)}
        for name,signature in functions.items():
            fn=getattr(gtk,name);fn.restype=signature[0];fn.argtypes=signature[1:]
        self.tags={}
        table=gtk.gtk_text_buffer_get_tag_table(self.buffer)
        for name,property_name,value in [('bold','weight',700),('italic','style',2),('underline','underline',1)]:
            tag=gtk.gtk_text_tag_new(None)
            g.g_object_set(tag,property_name.encode(),value,None)
            gtk.gtk_text_tag_table_add(table,tag);self.tags[name]=tag;g.g_object_unref(tag)

    # ==========================================
    # Function: Obtain an opaque aligned GtkTextIter at a character offset.
    # Method: Reserve a larger aligned buffer than GTK's public iterator struct.
    # ==========================================
    def iterator(self,offset):
        result=(C.c_uint64*16)();self.gtk.gtk_text_buffer_get_iter_at_offset(self.buffer,result,offset);return result

    # ==========================================
    # Function: Apply or remove formatting from the selected text.
    # Method: Toggle based on the selected start iterator's current tag state.
    # ==========================================
    def toggle(self,kind):
        start,end=self.iterator(0),self.iterator(0)
        if self.gtk.gtk_text_buffer_get_selection_bounds(self.buffer,start,end):
            tag=self.tags[kind]
            method=self.gtk.gtk_text_buffer_remove_tag if self.gtk.gtk_text_iter_has_tag(start,tag) else self.gtk.gtk_text_buffer_apply_tag
            method(self.buffer,tag,start,end)

    # ==========================================
    # Function: Update an automatically managed signature without discarding body formatting.
    # Method: Replace only an unchanged terminal text span through native buffer iterators.
    # ==========================================
    def replace_suffix(self, old, new):
        text=self.g.text(self.view,view=True)
        if old and not text.endswith(old):return False
        start,end=self.iterator(len(text)-len(old)),self.iterator(len(text))
        self.gtk.gtk_text_buffer_delete(self.buffer,start,end)
        self.gtk.gtk_text_buffer_insert(self.buffer,start,new.encode(),-1)
        return True

    # ==========================================
    # Function: Import permitted HTML formatting into a native text view.
    # Method: Decode inert text first and apply only the three explicit tag types.
    # ==========================================
    def load_html(self,html):
        parser=InertRichText();parser.feed(html)
        self.g.text(self.view,''.join(parser.parts),view=True)
        for kind,start,end in parser.ranges:
            self.gtk.gtk_text_buffer_apply_tag(self.buffer,self.tags[kind],self.iterator(start),self.iterator(end))

    # ==========================================
    # Function: Produce safe MIME HTML from native formatting ranges.
    # Method: Split text at tag toggles and escape all user-provided text.
    # ==========================================
    def html(self):
        text=self.g.text(self.view,view=True);boundaries={0,len(text)}
        for tag in self.tags.values():
            cursor=self.iterator(0)
            while self.gtk.gtk_text_iter_forward_to_tag_toggle(cursor,tag):
                boundaries.add(self.gtk.gtk_text_iter_get_offset(cursor))
        result=[];points=sorted(boundaries)
        for start,end in zip(points,points[1:]):
            value=escape(text[start:end]).replace('\n','<br>')
            for name,tag in self.tags.items():
                if self.gtk.gtk_text_iter_has_tag(self.iterator(start),tag):
                    element={'bold':'strong','italic':'em','underline':'u'}[name];value=f'<{element}>'+value+f'</{element}>'
            result.append(value)
        return '<span>'+''.join(result)+'</span>'
