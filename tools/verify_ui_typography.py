"""Native font/DPI, popup and pinned-sidebar checks using a disposable profile."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

# ==========================================
# Function: Let GTK settle its pending font, allocation and popup placement changes.
# Method: Iterate only the test's native main context for a bounded interval.
# ==========================================
def settle(g):
    iterate=g.libs['glib'].g_main_context_iteration;iterate.restype=C.c_int;iterate.argtypes=[C.c_void_p,C.c_int]
    deadline=time.monotonic()+.18
    while time.monotonic()<deadline:
        iterate(None,0);time.sleep(.001)

# ==========================================
# Function: Verify real typography and sidebar geometry without opening a mailbox.
# Method: Initialize the private Windows runtime when needed, exercise real widgets and restore process-local resolution.
# ==========================================
def verify(assets):
    if os.name=='nt':
        from maildesk.platform_native import prepare_windows
        prepare_windows()
    from maildesk.gtk_native import GtkNative,P,I
    from maildesk.platform_native import load_library
    from maildesk.ui_typography import apply_font
    g=GtkNative();g.fonts(assets/'fonts')
    if not g.gtk_init_check(None,None):raise RuntimeError('A native desktop or Xvfb is required')
    get_dpi=g.libs['gdk'].gdk_screen_get_resolution;get_dpi.restype=C.c_double;get_dpi.argtypes=[P]
    set_dpi=g.libs['gdk'].gdk_screen_set_resolution;set_dpi.restype=None;set_dpi.argtypes=[P,C.c_double]
    get_layout=g.libs['gtk'].gtk_label_get_layout;get_layout.restype=P;get_layout.argtypes=[P]
    pango=load_library('pango');pixels=pango.pango_layout_get_pixel_size;pixels.restype=None;pixels.argtypes=[P,C.POINTER(I),C.POINTER(I)]
    screen=g.gdk_screen_get_default();original_dpi=get_dpi(screen)
    rail_xml=ET.parse(assets/'main.ui').find('.//object[@id="rail"]')
    builder=g.builder('<interface>'+ET.tostring(rail_xml,encoding='unicode')+'</interface>')
    rail=g.object(builder,'rail');scroll=g.object(builder,'pinned_navigation_scroll');pins=g.object(builder,'pinned_navigation')
    window=g.gtk_window_new(0);g.gtk_window_set_default_size(window,1400,900)
    overlay=g.gtk_overlay_new();g.gtk_container_add(window,overlay)
    row=g.gtk_box_new(0,0);g.gtk_container_add(overlay,row);g.gtk_box_pack_start(row,rail,0,1,0)
    label=g.gtk_label_new('TeleMail 字号与弹窗布局'.encode());g.gtk_box_pack_start(row,label,1,1,0)
    footer=g.gtk_button_new();g.gtk_button_set_image(footer,g.image_file(assets/'icons/spark-layout-preferences.svg',16));g.gtk_button_set_always_show_image(footer,1);g.gtk_box_pack_start(g.object(builder,'rail_settings_slot'),footer,0,1,0)
    for index in range(12):
        button=g.gtk_button_new();g.gtk_button_set_image(button,g.image_file(assets/'icons/spark-layout-folder.svg',16));g.gtk_button_set_always_show_image(button,1);g.gtk_box_pack_start(pins,button,0,1,0)
    g.gtk_widget_set_no_show_all(scroll,0);g.gtk_widget_set_no_show_all(g.object(builder,'rail_settings_slot'),0)
    app=SimpleNamespace(g=g,window=window,closing=False,widget=lambda key:overlay)
    g.surfaces.attach(app);g.css(assets/'style.css');g.gtk_widget_show_all(window)
    metrics={'typography':[],'popups':[]}
    try:
        for dpi in (96,144,192):
            set_dpi(screen,dpi)
            for size in (10,14,20,32):
                apply_font(app,size);settle(g)
                width,height=I(),I();pixels(get_layout(label),C.byref(width),C.byref(height))
                metrics['typography'].append({'dpi':dpi,'font':size,'text_width':width.value,'text_height':height.value})
        samples=metrics['typography']
        for size in (10,14,20,32):
            widths=[item['text_width'] for item in samples if item['font']==size]
            assert widths[0]<widths[1]<widths[2],widths
        apply_font(app,14);dpi_widths=[]
        for dpi in (96,144,192):
            set_dpi(screen,dpi);settle(g)
            width,height=I(),I();pixels(get_layout(label),C.byref(width),C.byref(height));dpi_widths.append(width.value)
        assert dpi_widths[0]<dpi_widths[1]<dpi_widths[2],dpi_widths
        metrics['unchanged_font_dpi_widths']=dpi_widths
        set_dpi(screen,96);apply_font(app,14);settle(g)
        viewport=g.gtk_scrolled_window_get_vadjustment(scroll)
        gtk=g.libs['gtk']
        upper=gtk.gtk_adjustment_get_upper;upper.restype=C.c_double;upper.argtypes=[P]
        page=gtk.gtk_adjustment_get_page_size;page.restype=C.c_double;page.argtypes=[P]
        metrics['sidebar']={'rail_width':g.gtk_widget_get_allocated_width(rail),'pin_area_height':g.gtk_widget_get_allocated_height(scroll),'twelve_fit':upper(viewport)<=page(viewport)+1}
        assert metrics['sidebar']['rail_width']==40,metrics['sidebar']
        assert metrics['sidebar']['pin_area_height']>600
        assert metrics['sidebar']['twelve_fit'],metrics['sidebar']
        old_height=g.gtk_widget_get_allocated_height(window)
        for index in range(12,40):
            button=g.gtk_button_new();g.gtk_button_set_image(button,g.image_file(assets/'icons/spark-layout-folder.svg',16));g.gtk_button_set_always_show_image(button,1);g.gtk_box_pack_start(pins,button,0,1,0)
        g.gtk_widget_show_all(pins);settle(g)
        assert upper(viewport)>page(viewport),'Overflow must remain accessible by scrolling'
        assert g.gtk_widget_get_allocated_height(window)==old_height,'Pins must not force the main window taller'
        for dpi,size in ((96,10),(96,14),(96,20),(96,32),(144,32),(192,32),(96,14)):
            set_dpi(screen,dpi)
            apply_font(app,size);settle(g)
            controller=g.gtk_dialog_new();state=g.surfaces.register_dialog(controller,'字号设置',400)
            body=g.gtk_label_new('Interface font and popup layout'.encode());g.gtk_label_set_line_wrap(body,1)
            g.gtk_box_pack_start(state['content'],body,0,1,0);g.gtk_dialog_add_button(controller,'保存'.encode(),-3)
            g.surfaces.show_dialog(state);settle(g)
            x,y,width,height=state['bounds'];actual_width=g.gtk_widget_get_allocated_width(state['frame'])
            root_width=g.gtk_widget_get_allocated_width(overlay)
            assert width>=400 and x>=0 and x+actual_width<=root_width,(size,state['bounds'],actual_width,root_width)
            assert g.gtk_widget_get_allocated_width(body)<=actual_width
            metrics['popups'].append({'dpi':dpi,'font':size,'planned_width':width,'allocated_width':actual_width})
            g.gtk_widget_destroy(controller);settle(g)
        assert metrics['popups'][3]['planned_width']>metrics['popups'][0]['planned_width'],'Large text must inform popup sizing'
        assert metrics['popups'][3]['planned_width']<=metrics['popups'][4]['planned_width']<=metrics['popups'][5]['planned_width'],'Font-based minimum widths and DPI-driven content must remain bounded and nondecreasing'
        metrics['ok']=True
        return metrics
    finally:
        set_dpi(screen,original_dpi);g.surfaces.stopping=True;g.gtk_widget_destroy(window);g.g_object_unref(builder)

# ==========================================
# Function: Run isolated native font and sidebar acceptance against source or a Windows bundle.
# Method: Redirect profile/cache paths into a temporary directory and retain only JSON measurements.
# ==========================================
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'.runtime/ui-typography')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.bundle:
        sys.path.insert(0,str(args.bundle.resolve()/'app'))
        if os.name=='nt':os.environ['TELEMAIL_WINDOWS_RUNTIME']=str(args.bundle.resolve()/'runtime')
    import maildesk
    assets=Path(maildesk.__file__).parent/'desktop_assets'
    with tempfile.TemporaryDirectory(prefix='telemail-font-qa-') as temporary:
        for key in ('APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_CACHE_HOME'):
            path=Path(temporary)/key;path.mkdir();os.environ[key]=str(path)
        result=verify(assets)
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0

if __name__=='__main__':raise SystemExit(main())
