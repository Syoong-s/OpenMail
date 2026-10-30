"""Window growth, CSD and monitor transitions without a native desktop."""
from contextlib import contextmanager
import ctypes as C
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from maildesk import windows_display as display

# ==========================================
# Function: Model GTK client dimensions separately from its client-side titlebar.
# Method: Retain mutable content, decoration and monitor budgets around production sizing functions.
# ==========================================
class WindowModel:
    # ==========================================
    # Function: Create an isolated parent and one open dialog.
    # Method: Supply only the native geometry contract used by fit_dialog and restore_dialog.
    # ==========================================
    def __init__(self):
        self.size=(900,600);self.decoration=(2,48);self.budget=(2560,1440);self.monitor=(0,0,3840,2160)
        self.native=Mock();self.native.SetThreadDpiAwarenessContext.return_value=-2
        self.g=Mock();self.g.gtk_window_is_maximized.return_value=False
        self.g.gtk_widget_get_allocated_width.side_effect=lambda widget:self.size[0]+(self.decoration[0] if widget=='window' else 0)
        self.g.gtk_widget_get_allocated_height.side_effect=lambda widget:self.size[1]+(self.decoration[1] if widget=='window' else 0)
        self.state={'kind':'dialog','root':'window'}
        self.surfaces=SimpleNamespace(g=self.g,roots={'window':{'overlay':'overlay'}},opened=['dialog'],states={'dialog':self.state})

    # ==========================================
    # Function: Return physical work-area metadata for the selected monitor.
    # Method: Keep Win32 calls mocked while using the actual production bounding and receipt logic.
    # ==========================================
    def geometry(self,*unused):
        left,top,right,bottom=self.monitor
        return SimpleNamespace(hwnd=1,rect=SimpleNamespace(left=0,top=0),work=SimpleNamespace(left=left,top=top,right=right,bottom=bottom),scale=1.5,border=(0,0),budget=self.budget)

    # ==========================================
    # Function: Accept logical GTK size requests without simulating a window manager.
    # Method: Preserve the distinction between content size and total allocated size.
    # ==========================================
    def window_size(self,g,window,requested=None):
        if requested is not None:self.size=requested
        return self.size

    # ==========================================
    # Function: Replace only platform I/O for one production sizing scenario.
    # Method: Run all sizing and restoration calculations unchanged on both test platforms.
    # ==========================================
    @contextmanager
    def bound(self):
        with patch.object(display,'api',return_value=self.native),patch.object(display,'geometry',side_effect=self.geometry),patch.object(display,'window_size',side_effect=self.window_size):yield

# ==========================================
# Function: Protect whole-window scaling and reversible popup expansion.
# Method: Assert monitor bounds, CSD invariants and manual-resize ownership independently of Win32.
# ==========================================
class WindowsDisplayTests(unittest.TestCase):
    # ==========================================
    # Function: Keep one coherent GTK render scale for fractional system DPI.
    # Method: Mock documented API results and inspect process-local environment/context changes.
    # ==========================================
    def test_system_dpi_configures_one_render_scale(self):
        native=Mock();native.SetThreadDpiAwarenessContext.return_value=-4
        with patch.object(display,'api',return_value=native),patch.dict(os.environ,{}):
            for dpi,scale in ((96,1),(144,2),(192,2)):
                native.GetDpiForSystem.return_value=dpi
                result=display.configure()
                self.assertEqual(result['gtk_scale'],scale)
                self.assertEqual(os.environ['GDK_SCALE'],str(scale))
                self.assertEqual(os.environ['GDK_DPI_SCALE'],'1')
                self.assertEqual(C.c_ssize_t(native.SetThreadDpiAwarenessContext.call_args.args[0].value).value,-2)

    # ==========================================
    # Function: Include client-side titlebars when bounding a large settings workspace.
    # Method: Require the total GTK allocation, not just content, to fit the monitor budget.
    # ==========================================
    def test_large_dialog_reserves_titlebar_space(self):
        model=WindowModel();model.budget=(1440,900)
        with model.bound():display.fit_dialog(model.surfaces,model.state,2400,1645)
        self.assertLessEqual(model.size[0]+model.decoration[0],1440)
        self.assertLessEqual(model.size[1]+model.decoration[1],900)
        self.assertGreater(model.size[0],900)

    # ==========================================
    # Function: Keep a changed CSD titlebar from being mistaken for a manual resize.
    # Method: Grow the titlebar while holding total allocation fixed, then refit with the same budget.
    # ==========================================
    def test_titlebar_font_change_is_not_manual_resize(self):
        model=WindowModel();model.budget=(1440,900)
        with model.bound():
            display.fit_dialog(model.surfaces,model.state,2400,1645)
            receipt=model.surfaces.roots['window']['dialog_growth'];receipt['requested_at']=0
            model.decoration=(2,64);model.size=(model.size[0],model.size[1]-16)
            display.fit_dialog(model.surfaces,model.state,2400,1645)
            self.assertFalse(receipt.get('manual',False))
            self.assertLessEqual(model.size[1]+model.decoration[1],900)

    # ==========================================
    # Function: Refit large settings after crossing to a smaller monitor.
    # Method: Change available desktop bounds and require preserved size ownership without a position jump on close.
    # ==========================================
    def test_smaller_monitor_refits_and_close_does_not_jump(self):
        model=WindowModel()
        with model.bound():
            display.fit_dialog(model.surfaces,model.state,2400,1645)
            model.budget=(1440,900);model.monitor=(-2880,0,0,1800)
            display.fit_dialog(model.surfaces,model.state,2400,1645)
            self.assertLessEqual(model.size[0]+model.decoration[0],1440)
            self.assertLessEqual(model.size[1]+model.decoration[1],900)
            self.assertTrue(model.surfaces.roots['window']['dialog_growth']['moved'])
            model.surfaces.opened=[];model.native.reset_mock();display.restore_dialog(model.surfaces,'window')
            self.assertEqual(model.size,(900,600))
            model.native.SetWindowPos.assert_not_called()

    # ==========================================
    # Function: Preserve the user's own dimensions when an editor closes.
    # Method: Change accepted allocation after automatic growth has settled and exercise refit plus close.
    # ==========================================
    def test_manual_resize_survives_close(self):
        model=WindowModel()
        with model.bound():
            display.fit_dialog(model.surfaces,model.state,1600,1100)
            model.size=(model.size[0]-80,model.size[1]-60);manual=model.size
            model.surfaces.roots['window']['dialog_growth']['requested_at']=0
            display.fit_dialog(model.surfaces,model.state,1600,1100)
            model.surfaces.opened=[];display.restore_dialog(model.surfaces,'window')
            self.assertEqual(model.size,manual)

    # ==========================================
    # Function: Avoid restoring a parent while another dialog still needs its space.
    # Method: Close a child without ending the root editor session.
    # ==========================================
    def test_other_open_dialog_delays_restoration(self):
        model=WindowModel()
        with model.bound():
            display.fit_dialog(model.surfaces,model.state,1600,1100);expanded=model.size
            display.restore_dialog(model.surfaces,'window')
            self.assertEqual(model.size,expanded)
            self.assertIn('dialog_growth',model.surfaces.roots['window'])

if __name__=='__main__':unittest.main()
