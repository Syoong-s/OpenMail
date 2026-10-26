"""Native GTK recipient completion from local cached contacts, without remote calls."""
import ctypes as C
from .composer_options import recipient_suggestions,recipient_token_start
from .gtk_native import P,I,S,U

# ==========================================
# Function: Keep native completion model types ABI-aligned on Linux amd64.
# Method: Represent public GtkTreeIter and GValue storage using typed ctypes structures.
# ==========================================
class TreeIter(C.Structure):
    _fields_=[('stamp',I),('data1',P),('data2',P),('data3',P)]

# ==========================================
# Function: Own one address-entry completion until its composer is destroyed.
# Method: Populate an inert GtkListStore and match only the last comma-separated address token.
# ==========================================
class RecipientCompletion:
    # ==========================================
    # Function: Bind completion APIs and build a bounded cached suggestion list.
    # Method: Use GValue string setters rather than unsafe variadic list-store calls.
    # ==========================================
    def __init__(self,composer,entry):
        self.composer,self.g,self.entry=composer,composer.g,entry;gtk=self.g.libs['gtk'];self.gtk=gtk
        signatures={'gtk_list_store_newv':(P,I,P),'gtk_list_store_append':(None,P,P),'gtk_list_store_set_value':(None,P,P,I,P),
            'gtk_entry_completion_new':(P,),'gtk_entry_completion_set_model':(None,P,P),'gtk_entry_completion_set_text_column':(None,P,I),
            'gtk_entry_completion_set_minimum_key_length':(None,P,I),'gtk_entry_set_completion':(None,P,P),
            'gtk_entry_completion_set_match_func':(None,P,P,P,P),'gtk_tree_model_get_value':(None,P,P,I,P),
            'gtk_entry_completion_get_model':(P,P),'gtk_editable_set_position':(None,P,I)}
        for name,spec in signatures.items():
            fn=getattr(gtk,name);fn.restype=spec[0];fn.argtypes=spec[1:]
        objects=self.g.libs['object'];self.objects=objects
        for name,spec in {'g_value_init':(P,P,C.c_size_t),'g_value_set_string':(None,P,S),'g_value_get_string':(S,P),'g_value_unset':(None,P)}.items():
            fn=getattr(objects,name);fn.restype=spec[0];fn.argtypes=spec[1:]
        types=(C.c_size_t*1)(64);model=gtk.gtk_list_store_newv(1,types)
        self.suggestions=recipient_suggestions(composer.app.service.store)
        for address,text in self.suggestions:
            row=TreeIter();value=(C.c_uint64*3)()
            gtk.gtk_list_store_append(model,C.byref(row));objects.g_value_init(value,64)
            objects.g_value_set_string(value,text.encode());gtk.gtk_list_store_set_value(model,C.byref(row),0,value);objects.g_value_unset(value)
        completion=gtk.gtk_entry_completion_new();self.widget=completion
        gtk.gtk_entry_completion_set_model(completion,model);gtk.gtk_entry_completion_set_text_column(completion,0)
        gtk.gtk_entry_completion_set_minimum_key_length(completion,1)
        self.match_callback=C.CFUNCTYPE(I,P,S,P,P)(self.match)
        gtk.gtk_entry_completion_set_match_func(completion,C.cast(self.match_callback,P),None,None)
        self.g.connect(completion,'match-selected',self.selected,count=4,returns=True,group=composer.group)
        gtk.gtk_entry_set_completion(entry,completion);self.g.g_object_unref(model);self.g.g_object_unref(completion)

    # ==========================================
    # Function: Read a completion row string with correct GValue ownership.
    # Method: Copy the borrowed UTF-8 value before unsetting its container.
    # ==========================================
    def text(self,model,row):
        value=(C.c_uint64*3)();self.gtk.gtk_tree_model_get_value(model,row,0,value)
        text=(self.objects.g_value_get_string(value) or b'').decode();self.objects.g_value_unset(value);return text

    # ==========================================
    # Function: Match a typed partial recipient against name or mailbox.
    # Method: Case-fold the last address token and a cached model row only.
    # ==========================================
    def match(self,completion,key,row,unused):
        prefix=self.g.text(self.entry)[recipient_token_start(self.g.text(self.entry)):].strip().casefold()
        model=self.gtk.gtk_entry_completion_get_model(completion)
        return int(bool(prefix) and prefix in self.text(model,row).casefold())

    # ==========================================
    # Function: Replace only the address token selected by the user.
    # Method: Preserve preceding recipients and move the cursor to the accepted suggestion.
    # ==========================================
    def selected(self,completion,model,row,unused):
        current=self.g.text(self.entry);prefix=current[:recipient_token_start(current)]
        if prefix:prefix=prefix.rstrip()+' '
        self.g.text(self.entry,prefix+self.text(model,row));self.gtk.gtk_editable_set_position(self.entry,-1)
        return True
