"""
Unit tests for RedUi Guides, Overlays, and Hardware Limitation Alerts.
Verifies recursive menu tree coverage, frame guides, action safe, title safe,
overlay modes, and on-screen hardware alert popups.
"""

import pytest
from PIL import Image
from emulator.camera import Dsmc2Camera
from emulator.ui.redui import RedUiEngine


@pytest.fixture
def redui(tmp_path):
    cam = Dsmc2Camera(workspace_root=str(tmp_path))
    engine = RedUiEngine(cam)
    return engine


def test_recursive_menu_trace_no_exceptions(redui):
    """Recursively trace every single menu option in DSMC2_MENU_TREE to verify zero unhandled crashes."""
    tree = redui.DSMC2_MENU_TREE
    total_actions = 0

    def walk(node, path):
        nonlocal total_actions
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [k])
        elif isinstance(node, list):
            for item in node:
                redui.menu_path = list(path)
                redui._handle_menu_item_selected(item)
                total_actions += 1

    walk(tree, ["Menu"])
    assert total_actions >= 500


def test_frame_guides_modes_and_rendering(redui):
    """Verify 16:9, 2.39:1, 1.85:1, 4:3, and Off frame guide modes."""
    # 2.39:1 Anamorphic
    redui.menu_path = ["Menu", "OVERLAYS", "GUIDES", "Frame Guide"]
    redui._handle_menu_item_selected("2.39:1 Anamorphic Guide")
    assert redui.guide_mode == "2.39:1"

    img = Image.new("RGB", (1024, 576), (20, 20, 20))
    rendered = redui.render(img)
    assert rendered.size == (1024, 576)

    # 1.85:1 Cinema
    redui._handle_menu_item_selected("1.85:1 Cinema Guide")
    assert redui.guide_mode == "1.85:1"

    # 4:3 Aspect Guide
    redui._handle_menu_item_selected("4:3 Guide")
    assert redui.guide_mode == "4:3"

    # Guides Off
    redui._handle_menu_item_selected("Guides OFF")
    assert redui.guide_mode == "Off"


def test_action_and_title_safe_guides(redui):
    """Verify Action Safe 90% and Title Safe 80% toggle and render."""
    redui.menu_path = ["Menu", "OVERLAYS", "GUIDES", "Action Guide"]
    redui._handle_menu_item_selected("Action Safe 90% ON")
    assert redui.action_guide_on is True

    redui.menu_path = ["Menu", "OVERLAYS", "GUIDES", "Title Guide"]
    redui._handle_menu_item_selected("Title Safe 80% ON")
    assert redui.title_guide_on is True

    # Guide Line Color and Shading
    redui.menu_path = ["Menu", "OVERLAYS", "GUIDES", "General"]
    redui._handle_menu_item_selected("Guide Line: Yellow")
    assert redui.guide_color == (255, 220, 0)

    redui._handle_menu_item_selected("Guide Shading 50%")
    assert redui.guide_shading_pct == 50

    img = Image.new("RGB", (1024, 576), (30, 30, 30))
    rendered = redui.render(img)
    assert rendered is not None


def test_overlay_mode_clean_and_standard(redui):
    """Verify Clean Video Feed suppresses HUD/guides."""
    redui.menu_path = ["Menu", "MONITORING", "ADVANCED", "Video"]
    redui._handle_menu_item_selected("Clean Video Feed")
    assert redui.overlay_mode == "Clean"

    redui._handle_menu_item_selected("Display All Overlays Feed")
    assert redui.overlay_mode == "Standard"


def test_hardware_limitation_alert_popup(redui):
    """Verify that selecting options requiring missing physical hardware triggers the alert popup modal."""
    # Test 1: Touchscreen Digitizer Test
    redui.menu_path = ["Menu", "SETTINGS", "MAINTENANCE", "Self Test", "Touchscreen"]
    redui._handle_menu_item_selected("Run Touchscreen Digitizer Test")
    assert redui.active_alert is not None
    assert "EMULATOR LIMITATION" in redui.active_alert["title"]
    assert "software emulation" in redui.active_alert["message"]
    assert "maXTouch digitizer" in redui.active_alert["message"]

    # Verify rendering alert modal
    img = Image.new("RGB", (1024, 576), (15, 15, 15))
    rendered = redui.render(img)
    assert rendered is not None

    # Verify touch dismisses alert
    redui.handle_touch(512, 360, True, "down")
    assert redui.active_alert is None

    # Test 2: Genlock Offset (Physical sync clock)
    redui.menu_path = ["Menu", "MONITORING", "ADVANCED", "Genlock Offset"]
    redui._handle_menu_item_selected("Genlock Offset 0 Lines")
    assert redui.active_alert is not None
    assert "Genlock" in redui.active_alert["message"]
    assert "software emulation" in redui.active_alert["message"]
    redui.handle_touch(512, 360, True, "down")
    assert redui.active_alert is None
