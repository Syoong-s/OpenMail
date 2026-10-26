"""Native account, credential and composer dialogs built from GTK widgets."""
import base64
import ctypes as C
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import time
import uuid
import json
from xml.sax.saxutils import escape

from .mime import MAX_MESSAGE_BYTES
from .local_mail import LOCAL_ACCOUNT

# ==========================================
# Function: Build safe native form markup from trusted field definitions.
# Method: Escape labels and choose explicit GtkEntry, ComboBoxText or TextView widgets.
# ==========================================
def form_xml(fields):
    rows = []
    for key, title, kind, options in fields:
        if kind == 'combo':
            items = ''.join(f'<item id="{escape(value)}">{escape(label)}</item>' for value, label in options)
            widget = f'<object class="GtkComboBoxText" id="{key}"><items>{items}</items></object>'
        elif kind == 'check':
            widget=f'<object class="GtkCheckButton" id="{key}"><property name="halign">end</property><property name="valign">center</property></object>'
        elif kind == 'switch':
            widget=f'<object class="GtkSwitch" id="{key}"><property name="halign">end</property><property name="valign">center</property></object>'
        elif kind == 'range':
            low,high,step=options
            widget=f'<object class="GtkScale" id="{key}"><property name="orientation">horizontal</property><property name="digits">0</property><property name="width-request">180</property></object>'
        elif kind == 'color':
            widget=f'<object class="GtkEntry" id="{key}"><property name="width-chars">9</property><property name="max-width-chars">9</property><property name="hexpand">False</property><property name="halign">end</property></object>'
        elif kind == 'body':
            widget = f'<object class="GtkScrolledWindow"><property name="height-request">230</property><property name="vexpand">True</property><child><object class="GtkTextView" id="{key}"><property name="wrap-mode">word-char</property><property name="left-margin">8</property><property name="right-margin">8</property></object></child></object>'
        else:
            extra = '<property name="visibility">False</property><property name="input-purpose">password</property>' if kind == 'secret' else ''
            widget = f'<object class="GtkEntry" id="{key}">{extra}</object>'
        rows.append(f'<child><object class="GtkBox"><property name="spacing">12</property><child><object class="GtkLabel"><property name="label">{escape(title)}</property><property name="width-request">105</property><property name="xalign">0</property></object><packing><property name="expand">False</property></packing></child><child>{widget}<packing><property name="expand">True</property><property name="fill">True</property></packing></child></object></child>')
    return '<interface><object class="GtkBox" id="form"><property name="orientation">vertical</property><property name="spacing">10</property><property name="margin">20</property>' + ''.join(rows) + '<child><object class="GtkLabel" id="note"><property name="wrap">True</property><property name="xalign">0</property><style><class name="muted"/></style></object></child></object></interface>'

# ==========================================
# Function: Arrange generic editors as rounded groups within one same-app card.
# Method: Keep field IDs/value APIs while placing text labels above fields and choice rows side by side.
# ==========================================
def editor_form_xml(fields):
    import xml.etree.ElementTree as ET
    root=ET.fromstring(form_xml(fields));form=root.find('object');form.find("property[@name='spacing']").text='14'
    for field,child in zip(fields,form.findall('child')):
        key,title,kind,unused=field;row=child.find('object');label=row.find("child/object[@class='GtkLabel']")
        width=label.find("property[@name='width-request']")
        if width is not None:label.remove(width)
        style=ET.SubElement(label,'style');ET.SubElement(style,'class',{'name':'editor-field-label'})
        style=ET.SubElement(row,'style');ET.SubElement(style,'class',{'name':'editor-choice-row' if kind in ('combo','switch','check','color','range') else 'editor-field'})
        if kind not in ('combo','switch','check','color','range'):
            prop=ET.Element('property',{'name':'orientation'});prop.text='vertical';row.insert(0,prop);row.find("property[@name='spacing']").text='7'
        if kind=='body':
            scroll=row.find("child/object[@class='GtkScrolledWindow']");scroll.find("property[@name='height-request']").text='170';ET.SubElement(ET.SubElement(scroll,'style'),'class',{'name':'editor-body'})
    return ET.tostring(root,encoding='unicode')

# ==========================================
# Function: Own the lifecycle of a native form dialog.
# Method: Retain its builder and signal group until explicit destruction.
# ==========================================
class Form:
    # ==========================================
    # Function: Construct a transient native GTK dialog.
    # Method: Add parsed widgets to its content area without a web document.
    # ==========================================
    def __init__(self, app, title, fields, width=680, layout=None, embedded=False):
        self.app, self.g = app, app.g
        self.embedded=embedded
        self.window = self.g.gtk_box_new(1,6) if embedded else self.g.gtk_dialog_new()
        if not embedded:
            self.g.surfaces.attach(app);self.g.surfaces.register_dialog(self.window,title,width)
        self.builder = self.g.builder(layout or (form_xml(fields) if embedded else editor_form_xml(fields)))
        self.fields = {key: (self.g.object(self.builder, key), kind) for key, _, kind, _ in fields}
        for key,unused,kind,options in fields:
            if kind=='range':
                low,high,step=options;self.g.gtk_range_set_range(self.fields[key][0],low,high);self.g.gtk_range_set_increments(self.fields[key][0],step,step*5)
        self.note = self.g.object(self.builder, 'note')
        self.group = f'form-{self.window}'
        self.closed = False
        from .native_ranges import NumericRange
        self.ranges={key:NumericRange(self.g,self.fields[key][0],self.g.gtk_widget_get_parent(self.fields[key][0]),self.group,title,options[2]) for key,title,kind,options in fields if kind=='range'}
        if not hasattr(app,'active_forms'):app.active_forms=[]
        app.active_forms.append(self)
        if getattr(app.options,'self_test',False):app.testing_form=self
        if app.service:
            from .desktop_preferences import resolved_theme
            theme=resolved_theme(app).encode()
            self.g.gtk_style_context_add_class(self.g.gtk_widget_get_style_context(self.window),theme)
        if embedded:
            self.content=self.g.gtk_box_new(1,6);self.action_area=self.g.gtk_flow_box_new()
            self.g.gtk_flow_box_set_selection_mode(self.action_area,0);self.g.gtk_flow_box_set_max_children_per_line(self.action_area,5)
            scroller=self.g.gtk_scrolled_window_new(None,None);self.g.gtk_scrolled_window_set_policy(scroller,2,1)
            self.g.gtk_container_add(scroller,self.content)
            header=self.g.gtk_label_new(title.encode());self.g.gtk_box_pack_start(self.window,header,0,1,8)
            self.g.gtk_box_pack_start(self.window,scroller,1,1,0)
            self.g.gtk_box_pack_start(self.window,self.action_area,0,1,8)
            self.g.gtk_box_pack_start(self.content,self.g.object(self.builder,'form'),1,1,0)
        else:
            self.g.gtk_window_set_title(self.window, title.encode())
            self.g.gtk_window_set_default_size(self.window, width, -1)
            self.g.gtk_window_set_transient_for(self.window, app.window)
            self.g.gtk_window_set_application(self.window, app.application)
            self.content=self.g.gtk_dialog_get_content_area(self.window)
            self.g.gtk_container_add(self.content,self.g.object(self.builder,'form'))
            if self.g.gtk_builder_get_object(self.builder,b'settings_stack'):self.g.surfaces.settings_workspace(self.window)
        from .native_choices import NativeChoice
        self.choices=[NativeChoice(self.g,self.fields[key][0],title,key) for key,title,kind,unused in fields if kind=='combo']
        from .native_colors import NativeColor
        self.colors=[NativeColor(self.g,self.fields[key][0],title) for key,title,kind,unused in fields if kind=='color']

    # ==========================================
    # Function: Read or replace a typed form field.
    # Method: Dispatch to the correct native text or combo API.
    # ==========================================
    def value(self, key, value=None):
        widget, kind = self.fields[key]
        if kind=='range':
            if value is not None:self.g.gtk_range_set_value(widget,float(value))
            else:self.ranges[key].commit()
            return int(round(self.g.gtk_range_get_value(widget)))
        if kind == 'combo':
            if value is not None:
                self.g.gtk_combo_box_set_active_id(widget, str(value).encode())
            return (self.g.gtk_combo_box_get_active_id(widget) or b'').decode()
        if kind=='check':
            if value is not None:self.g.gtk_toggle_button_set_active(widget,int(bool(value)))
            return bool(self.g.gtk_toggle_button_get_active(widget))
        if kind=='switch':
            if value is not None:self.g.gtk_switch_set_active(widget,int(bool(value)))
            return bool(self.g.gtk_switch_get_active(widget))
        return self.g.text(widget, value, view=kind == 'body')

    # ==========================================
    # Function: Add a native response button.
    # Method: Let GtkDialog emit response signals for pointer and keyboard activation.
    # ==========================================
    def button(self, title, response):
        if self.embedded:
            button=self.g.gtk_button_new_with_label(title.encode())
            self.g.connect(button,'clicked',lambda *unused:self.response(self.window,response,None),group=self.group)
            self.g.gtk_container_add(self.action_area,button)
            return button
        return self.g.gtk_dialog_add_button(self.window, title.encode(), response)

    # ==========================================
    # Function: Release form widgets and callback trampolines safely.
    # Method: Disconnect before destroy and then drop the builder reference.
    # ==========================================
    def close(self):
        if self.closed:
            return
        self.closed = True
        if self in getattr(self.app,'active_forms',[]):self.app.active_forms.remove(self)
        self.g.disconnect(self.group)
        self.g.gtk_widget_destroy(self.window)
        self.g.g_object_unref(self.builder)
        if self.embedded:
            self.app.composer=None
            self.g.gtk_stack_set_visible_child_name(self.app.widget('reader_stack'),b'chat' if getattr(self.app,'selected_chat','') else b'mail')

# ==========================================
# Function: Configure mailboxes with an explicit verified native provider workflow.
# Method: Reuse one wizard for new accounts, connection changes and saved logins.
# ==========================================
def account_settings(app, selected_id='new'):
    from .desktop_signin import account_signin
    account=next((item for item in app.profile.accounts() if item.id==selected_id),None)
    return account_signin(app,account,allow_metadata=True)

# ==========================================
# Function: Unlock an account through the same verified confirmation workflow.
# Method: Preserve remembered sessions and prompt only when a usable secret is absent.
# ==========================================
def ask_credential(app, account):
    from .credentials import session_secret
    import os
    if session_secret(account) or os.environ.get(account.secret_env):return
    from .desktop_signin import account_signin
    return account_signin(app,account)

# Preserve the original import path while keeping composer-specific behavior isolated.
from .composer_window import Composer
