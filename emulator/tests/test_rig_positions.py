"""
Unit tests for the DSMC2 Modular Rig & Physical Position Manager.
Verifies slot detection, GPIO detect pin line assertion, module hot-swapping,
spatial position toggling, and Web Studio REST API integration.
"""

import os
import pytest
from emulator.camera import Dsmc2Camera
from emulator.devices.rig_manager import RigManager, ConnectorPosition


@pytest.fixture
def camera(tmp_path):
    cam = Dsmc2Camera(workspace_root=str(tmp_path))
    return cam


def test_rig_manager_initial_cinema_preset(camera):
    rig = camera.rig
    assert rig is not None
    status = rig.get_status()
    assert status["occupied_slots_count"] >= 3

    top_slot = rig.get_slot(ConnectorPosition.TOP_POGO)
    assert top_slot.is_occupied()
    assert top_slot.attached_module["pin"] == "730-0024"
    assert top_slot.orientation == "normal"

    # Verify virtual GPIO detect pin for Top Pogo (Bank 5 Pin 3) is asserted
    gpio5 = camera.gpio[5]
    assert bool(gpio5.datain & (1 << 3)) is True

    # Rear module attached
    rear_slot = rig.get_slot(ConnectorPosition.REAR_MODULE)
    assert rear_slot.is_occupied()
    assert bool(gpio5.datain & (1 << 5)) is True


def test_rig_slot_detach_and_detect_pin(camera):
    rig = camera.rig
    gpio5 = camera.gpio[5]

    # Detach Top Pogo
    assert rig.detach_slot(ConnectorPosition.TOP_POGO) is True
    top_slot = rig.get_slot(ConnectorPosition.TOP_POGO)
    assert not top_slot.is_occupied()

    # GPIO detect pin must drop to 0 (LOW)
    assert bool(gpio5.datain & (1 << 3)) is False


def test_rig_position_toggle(camera):
    rig = camera.rig
    gpio5 = camera.gpio[5]

    # Initially Top Pogo has RED Touch 7.0, Side Pogo is empty
    assert rig.get_slot(ConnectorPosition.TOP_POGO).is_occupied()
    assert not rig.get_slot(ConnectorPosition.SIDE_POGO).is_occupied()
    assert bool(gpio5.datain & (1 << 3)) is True
    assert bool(gpio5.datain & (1 << 4)) is False

    # Move from Top Pogo -> Side Pogo
    toggled = rig.toggle_slot_position(ConnectorPosition.TOP_POGO, ConnectorPosition.SIDE_POGO)
    assert toggled is True

    # Top Pogo is now empty (GPIO5:3 LOW), Side Pogo is occupied (GPIO5:4 HIGH)
    assert not rig.get_slot(ConnectorPosition.TOP_POGO).is_occupied()
    assert rig.get_slot(ConnectorPosition.SIDE_POGO).is_occupied()
    assert rig.get_slot(ConnectorPosition.SIDE_POGO).attached_module["pin"] == "730-0024"

    assert bool(gpio5.datain & (1 << 3)) is False
    assert bool(gpio5.datain & (1 << 4)) is True


def test_rig_slot_orientation(camera):
    rig = camera.rig
    top_slot = rig.get_slot(ConnectorPosition.TOP_POGO)
    assert top_slot.orientation == "normal"

    assert rig.set_slot_orientation(ConnectorPosition.TOP_POGO, "flipped") is True
    assert top_slot.orientation == "flipped"
    assert top_slot.attached_module["orientation"] == "flipped"


def test_rig_presets(camera):
    rig = camera.rig

    # Bare brain preset
    assert rig.apply_preset("bare_brain") is True
    status = rig.get_status()
    assert status["occupied_slots_count"] == 0
    assert status["total_rig_power_w"] == 0

    # Broadcast studio preset
    assert rig.apply_preset("broadcast_studio") is True
    assert rig.get_slot(ConnectorPosition.LENS_MOUNT).attached_module["pin"] == "725-0022"
    assert camera.lens_mount.mount_type == camera.lens_mount.MOUNT_PL_INTELLIGENT


def test_camera_delegates_to_rig(camera):
    # Testing attach/detach via Dsmc2Camera methods
    res = camera.attach_accessory("730-0026", slot="side_pogo")
    assert res is not None
    assert camera.rig.get_slot("side_pogo").is_occupied()

    res = camera.detach_accessory("", slot="side_pogo")
    assert res is True
    assert not camera.rig.get_slot("side_pogo").is_occupied()
