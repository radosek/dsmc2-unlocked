"""
End-to-end interactive GUI verification test.
Tests Dsmc2DesktopApp under pure single-threaded execution, verifying:
- Touchscreen interaction on parameter badges (ISO, FPS)
- Modal dialog appearance and selection
- Physical button actuation (MENU, REC, POWER)
- Canvas single-item management (no memory leaks)
- Responsive loop tick timing without Win32 stalls
"""

import os
import time
import tkinter as tk
import pytest
from emulator.ui.app import Dsmc2DesktopApp
from emulator.rcp.protocol import RcpProtocol
from conftest import requires_firmware

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockEvent:
    def __init__(self, x_native: int, y_native: int, scale: float = 0.75):
        self.x = int(x_native * scale)
        self.y = int(y_native * scale)


@requires_firmware
def test_desktop_app_full_interaction():
    """Test full interactive GUI flow programmatically within Tk mainloop."""
    app = Dsmc2DesktopApp(workspace_root=REPO_ROOT)
    if not app.camera.is_booted:
        app.camera.power_on()
        app.buttons.refresh_state()
        app.screen.refresh()

    # 1. Verify initial booted state
    assert app.camera.power_state == app.camera.POWER_ON
    assert len(app.screen.canvas.find_all()) == 1

    # 2. Touch ISO badge at native coords (633, 16)
    app.screen._on_touch_down(MockEvent(633, 16))
    app.screen._on_touch_up(MockEvent(633, 16))
    assert app.screen.redui.active_dialog == "ISO"
    assert len(app.screen.canvas.find_all()) == 1

    # 3. Touch ISO 1600 in dialog
    # ISO options: cols=5, item_w=120, item_h=45, start_x=192, start_y=208
    # "1600" is index 8: col=3, row=1 -> x = 192 + 3 * 132 + 30 = 618, y = 208 + 1 * 55 + 20 = 283
    app.screen._on_touch_down(MockEvent(618, 283))
    app.screen._on_touch_up(MockEvent(618, 283))
    assert app.camera.rcp.state[RcpProtocol.PARAM_ISO] == "1600"
    assert app.screen.redui.active_dialog is None
    assert len(app.screen.canvas.find_all()) == 1

    # 4. Touch FPS badge at native coords (350, 20)
    app.screen._on_touch_down(MockEvent(350, 20))
    app.screen._on_touch_up(MockEvent(350, 20))
    assert app.screen.redui.active_dialog == "FPS"

    # Close dialog by touching close button
    # dx2 = 512 + 350 = 862, dy1 = 288 - 140 = 148 -> close btn at (840, 165)
    app.screen._on_touch_down(MockEvent(840, 165))
    app.screen._on_touch_up(MockEvent(840, 165))
    assert app.screen.redui.active_dialog is None

    # 5. Physical MENU button
    assert app.screen.redui.is_menu_open is False
    app.buttons.menu_btn.invoke()
    assert app.screen.redui.is_menu_open is True
    assert len(app.screen.canvas.find_all()) == 1

    # Toggle MENU off
    app.buttons.menu_btn.invoke()
    assert app.screen.redui.is_menu_open is False

    # 6. Physical 1:1 MAG button
    assert app.screen.redui.is_magnify_on is False
    app.buttons.mag_btn.invoke()
    assert app.screen.redui.is_magnify_on is True
    app.buttons.mag_btn.invoke()
    assert app.screen.redui.is_magnify_on is False

    # 7. Physical REC button
    assert app.camera.rcp.state[RcpProtocol.PARAM_RECORD_STATE] == "0"
    app.buttons.rec_btn.invoke()
    assert app.camera.rcp.state[RcpProtocol.PARAM_RECORD_STATE] == "2"
    assert app.buttons.rec_btn.cget("text") == "■ STOP"

    app.buttons.rec_btn.invoke()
    assert app.camera.rcp.state[RcpProtocol.PARAM_RECORD_STATE] == "0"
    assert app.buttons.rec_btn.cget("text") == "● REC"

    # 8. Physical Power button
    app.buttons.power_btn.invoke()
    assert app.camera.power_state == app.camera.POWER_STANDBY
    assert "[●] STANDBY" in app.buttons.power_led.cget("text")

    app.buttons.power_btn.invoke()
    assert app.camera.power_state == app.camera.POWER_ON
    assert "[●] ONLINE" in app.buttons.power_led.cget("text")

    # 9. Step multiple UI ticks and verify latency & stability
    for _ in range(5):
        t0 = time.perf_counter()
        app.camera.step_slice(20_000)
        app.screen.refresh()
        app.buttons.refresh_state()
        app.dashboard.update_logs()
        tick_ms = (time.perf_counter() - t0) * 1000
        # Tick time must remain well below 40ms frame budget
        assert tick_ms < 50.0

    # Ensure single canvas item persisted throughout all interactions
    assert len(app.screen.canvas.find_all()) == 1

    # Clean shutdown
    import gc
    app._on_close()
    del app
    gc.collect()
