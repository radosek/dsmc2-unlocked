"""
Unit and regression tests for RedUiEngine interactive touchscreen and menu system.
"""

import pytest
from PIL import Image
from emulator.camera import Dsmc2Camera
from emulator.ui.redui import RedUiEngine
from emulator.rcp.protocol import RcpProtocol


@pytest.fixture
def camera(tmp_path):
    cam = Dsmc2Camera(workspace_root=str(tmp_path))
    return cam


@pytest.fixture
def redui(camera):
    return RedUiEngine(camera)


def test_touch_iso_badge_opens_dialog(redui, camera):
    """Verify touching the ISO badge (x=633, y=16) opens the ISO selection dialog."""
    # User's exact reported touch coordinate
    handled = redui.handle_touch(633, 16, pressed=True)
    assert handled is True
    assert redui.active_dialog == "ISO"

    # Verify rendering includes the dialog
    base = Image.new("RGB", (1024, 576), (20, 20, 20))
    rendered = redui.render(base)
    assert rendered.size == (1024, 576)

    # Touch ISO 1280 inside dialog
    # ISO options are at dx1 + 30, dy1 + 60. Index 7 is "1280".
    # dx1 = 512 - 350 = 162. dy1 = 288 - 140 = 148.
    # col = 7 % 5 = 2. row = 7 // 5 = 1.
    # bx = 162 + 30 + 2 * (120 + 12) = 192 + 264 = 456
    # by = 148 + 60 + 1 * (45 + 10) = 208 + 55 = 263
    redui.handle_touch(460, 270, pressed=True)
    assert camera.rcp.state[RcpProtocol.PARAM_ISO] == "1280"
    assert redui.active_dialog is None


def test_touch_fps_badge_opens_dialog(redui, camera):
    """Verify touching FPS badge (x=350, y=20) opens FPS dialog and allows selecting 60.00 fps."""
    redui.handle_touch(350, 20, pressed=True)
    assert redui.active_dialog == "FPS"

    # Select 60.00 FPS (index 7: col=1, row=2)
    # dx1 = 162, dy1 = 148. start_x = 192, start_y = 208.
    # col = 1, row = 2. bx = 192 + 1 * (200 + 12) = 404, by = 208 + 2 * 55 = 318
    redui.handle_touch(410, 325, pressed=True)
    assert camera.rcp.state[RcpProtocol.PARAM_FPS] == "60.00"
    assert redui.active_dialog is None


def test_menu_toggle_and_tabs(redui):
    """Verify toggling DSMC2 System Menu and navigating tabs."""
    assert redui.is_menu_open is False
    redui.toggle_menu()
    assert redui.is_menu_open is True

    # Touch OVERLAYS tab
    # my1 = 50. tab_y for OVERLAYS (index 3) = 50 + 60 + 3 * 46 = 248
    redui.handle_touch(120, 255, pressed=True)
    assert redui.menu_active_tab == "OVERLAYS"

    # Toggle False Color inside OVERLAYS tab
    # rx1 = 80 + 220 = 300, ry = 50 + 70 = 120
    assert redui.is_false_color_on is False
    redui.handle_touch(350, 130, pressed=True)
    assert redui.is_false_color_on is True


def test_physical_buttons_router(redui):
    """Verify physical buttons trigger tools and navigation."""
    redui.handle_button_press("1:1 MAG")
    assert redui.is_magnify_on is True

    redui.handle_button_press("USER 1")
    assert redui.is_false_color_on is True

    redui.handle_button_press("USER 2")
    assert redui.is_zebras_on is True

    redui.handle_button_press("MENU")
    assert redui.is_menu_open is True

    # Test D-pad down
    redui.handle_button_press("NAV DOWN")
    assert redui.menu_active_tab == "MEDIA"


def test_touch_reticle_feedback(redui):
    """Verify touch reticle is drawn when a touch occurs."""
    redui.handle_touch(500, 300, pressed=True)
    assert redui.last_touch_pos == (500, 300)
    assert redui.is_touching is True

    base = Image.new("RGB", (1024, 576), (0, 0, 0))
    rendered = redui.render(base)
    # The pixel at reticle ring (500 + 22, 300) should be colored (red outline)
    pixel = rendered.getpixel((522, 300))
    assert pixel[0] > 100  # Red channel active


def test_deep_dsmc2_menu_hierarchy_and_breadcrumbs(redui, camera):
    """Verify navigating through authentic DSMC2 menu branches and breadcrumb controls."""
    redui.toggle_menu()
    assert redui.is_menu_open is True
    assert redui.menu_path == ["Menu"]

    # Drill into SETTINGS
    redui._handle_menu_item_selected("SETTINGS")
    assert redui.menu_path == ["Menu", "SETTINGS"]

    # Drill into PROJECT
    redui._handle_menu_item_selected("PROJECT")
    assert redui.menu_path == ["Menu", "SETTINGS", "PROJECT"]

    # Drill into Frame Rate
    redui._handle_menu_item_selected("Frame Rate")
    assert redui.menu_path == ["Menu", "SETTINGS", "PROJECT", "Frame Rate"]

    # Select 60.00 FPS
    redui._handle_menu_item_selected("60.00")
    assert camera.rcp.state[RcpProtocol.PARAM_FPS] == "60.00"

    # Tap Back button (x=870, y=20)
    redui.handle_touch(870, 20, pressed=True)
    assert redui.menu_path == ["Menu", "SETTINGS", "PROJECT"]

    # Tap Home [...] button (x=800, y=20)
    redui.handle_touch(800, 20, pressed=True)
    assert redui.menu_path == ["Menu"]

    # Tap Close button (x=950, y=20)
    redui.handle_touch(950, 20, pressed=True)
    assert redui.is_menu_open is False


def test_format_media_progress_bar_zero_used_no_crash(redui, camera):
    """Verify formatting media with 0% remaining capacity does not cause Pillow ValueError."""
    if hasattr(camera, "recorder"):
        camera.recorder.format_media()

    redui._open_dialog("MEDIA")
    base = Image.new("RGB", (1024, 576), (20, 20, 20))
    # Must render without crashing: ValueError: x1 must be greater than or equal to x0
    rendered = redui.render(base)
    assert rendered.size == (1024, 576)

    # Also test rendering inside the full MEDIA device menu
    redui.active_dialog = None
    redui.is_menu_open = True
    redui.menu_path = ["Menu", "MEDIA", "Device"]
    rendered_menu = redui.render(base)
    assert rendered_menu.size == (1024, 576)


def test_dsmc2_maintenance_and_calibration(redui, camera):
    """Verify executing maintenance actions in DSMC2 menu."""
    redui.is_menu_open = True
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE"]

    # Drill into Calibrate submenu
    redui._handle_menu_item_selected("Calibrate")
    assert redui.menu_path == ["Menu", "SETTINGS", "MAINTENANCE", "Calibrate"]

    # Trigger Sensor Calibration
    redui._handle_menu_item_selected("Black Shading Sensor (T/E)")
    logs = camera.get_serial_logs()
    assert any("Black Shading" in l for l in logs)

    # Return to MAINTENANCE and test Save Log
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE"]
    redui._handle_menu_item_selected("Save Log")
    assert redui.menu_path == ["Menu", "SETTINGS", "MAINTENANCE", "Save Log"]
    redui._handle_menu_item_selected("Save Log to Media")
    logs2 = camera.get_serial_logs()
    assert any("MAINTENANCE" in l for l in logs2)


def test_dsmc2_settings_look_8_tiles_hierarchy(redui, camera):
    """Verify authentic DSMC2 Menu > Settings > Look > hierarchy matching Attachment 3."""
    redui.is_menu_open = True
    redui.menu_path = ["Menu", "SETTINGS", "LOOK"]

    # Verify 8 tiles matching user's screenshot
    items = redui._get_current_items()
    expected_tiles = ["Color", "Gain", "ISO/FLUT®", "Sharpness", "Curves", "Video", "Color Temp", "LGG"]
    assert items == expected_tiles

    # Test drilling into Curves
    redui._handle_menu_item_selected("Curves")
    assert redui.menu_path == ["Menu", "SETTINGS", "LOOK", "Curves"]

    # Select Luma S-Curve
    redui._handle_menu_item_selected("Luma S-Curve")
    logs = camera.get_serial_logs()
    assert any("LOOK" in l and "Curve" in l for l in logs)

    # Verify rendering of Look screen with tiles
    redui.menu_path = ["Menu", "SETTINGS", "LOOK"]
    base = Image.new("RGB", (1024, 576), (15, 15, 15))
    rendered = redui.render(base)
    assert rendered.size == (1024, 576)


def test_dsmc2_overlays_tools_ribbon_and_dropdown(redui, camera):
    """Verify authentic Overlays > Tools ribbon toolbar and False Color mode dropdown matching Attachment 4."""
    redui.is_menu_open = True
    redui.menu_path = ["Menu", "OVERLAYS", "TOOLS"]

    # 1. Tap False Color button [ Focus ] in ribbon (x=150, y=70)
    redui.handle_touch(150, 70, pressed=True)
    assert redui.is_false_color_dropdown_open is True

    # 2. Tap "Exposure" option in dropdown (y: 92 + 38 = 130, x: 150)
    redui.handle_touch(150, 140, pressed=True)
    assert redui.active_false_color_mode == "Exposure"
    assert redui.is_false_color_on is True
    assert redui.is_false_color_dropdown_open is False

    # 3. Tap Magnify button in ribbon (x=350, y=70)
    assert redui.is_magnify_on is False
    redui.handle_touch(350, 70, pressed=True)
    assert redui.is_magnify_on is True

    # 4. Tap Zebras button in ribbon (x=780, y=70)
    assert redui.is_zebras_on is False
    redui.handle_touch(780, 70, pressed=True)
    assert redui.is_zebras_on is True


def test_dynamic_brain_specific_menus_and_firmware_switch(redui, camera):
    """Verify switching brain dynamically updates active firmware, menu items, sensor info and format options."""
    # 1. Switch to RED RAVEN 4.5K (0x15)
    success = camera.select_camera_model("0x15")
    assert success is True
    redui.apply_camera_profile(camera.env.CAMERA_PROFILES["0x15"])
    assert redui.camera_model == "RED RAVEN 4.5K"

    # Verify System Status > Project Status dynamically shows RAVEN
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "System Status", "Project Status"]
    items = redui._get_current_items()
    assert any("RED RAVEN 4.5K" in item for item in items)
    assert any("Active Resolution: 4.5K 16:9" in item for item in items)

    # Verify System Status > Camera Info shows RAVEN sensor and firmware
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "System Status", "Camera Info"]
    info_items = redui._get_current_items()
    assert any("RED RAVEN 4.5K" in item for item in info_items)
    assert any("RED DRAGON 4.5K S35 (4608x2160)" in item for item in info_items)

    # Verify Project > Format does NOT offer 5K or 8K, offers 4.5K
    redui.menu_path = ["Menu", "SETTINGS", "PROJECT", "Format"]
    fmt_items = redui._get_current_items()
    assert "4.5K 16:9" in fmt_items
    assert "5K 16:9" not in fmt_items
    assert "8K 16:9" not in fmt_items

    # Verify Project > Frame Rate offers 120 FPS
    redui.menu_path = ["Menu", "SETTINGS", "PROJECT", "Frame Rate"]
    fps_items = redui._get_current_items()
    assert "120.00" in fps_items

    # 2. Switch to WEAPON 6K S35 (0x11)
    success6k = camera.select_camera_model("0x11")
    assert success6k is True
    redui.apply_camera_profile(camera.env.CAMERA_PROFILES["0x11"])
    assert redui.camera_model == "WEAPON 6K S35"

    # Verify System Status > Project Status dynamically shows WEAPON 6K S35
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "System Status", "Project Status"]
    items6k = redui._get_current_items()
    assert any("WEAPON 6K S35" in item for item in items6k)
    assert any("Active Resolution: 6K 16:9" in item for item in items6k)

    # Verify Project > Format offers 6K
    redui.menu_path = ["Menu", "SETTINGS", "PROJECT", "Format"]
    fmt6k_items = redui._get_current_items()
    assert "6K 16:9" in fmt6k_items
    assert "6K 2.4:1" in fmt6k_items

    # 3. Revert back to SCARLET-W 5K (0x16)
    camera.select_camera_model("0x16")
    redui.apply_camera_profile(camera.env.CAMERA_PROFILES["0x16"])
    assert redui.camera_model == "SCARLET-W 5K"


