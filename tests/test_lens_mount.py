"""
Unit and integration tests for RED DSMC2 Smart Lens Mount Subsystem.
Verifies Canon EF, Nikon F, and PL lens mounts, aperture stepping,
focal length tracking, autofocus simulation, and RCP reflection.
"""

import os
import pytest
from emulator.camera import Dsmc2Camera
from emulator.devices.lens_mount import LensMount, LensInfo, APERTURE_STOPS_THIRD, parse_firmware_lens_cfg
from emulator.rcp.protocol import RcpProtocol


@pytest.fixture
def camera(tmp_path):
    slot_dir = tmp_path / "firmware_store" / "unpacked" / "scarlet_w_7_4_1" / "slot"
    slot_dir.mkdir(parents=True)
    (slot_dir / "dsmc_program.mem").write_bytes(b"\x00" * 4096)
    (slot_dir / "system.env").write_text("CAMERA_NAME=SCARLET-W 5K\nPIN=10042\n")

    # Create dummy firmware lens configs to test parsing
    lens_dir = slot_dir / "lens" / "canon_mount"
    lens_dir.mkdir(parents=True)
    (lens_dir / "Canon_EF_24-70mm_f2p8L_II_USM.cfg").write_bytes(b"CFG_CANON_2470")
    (lens_dir / "Canon_EF_50mm_f1p2L_USM.cfg").write_bytes(b"CFG_CANON_50")
    (lens_dir / "canon_mount_lens_list.cfg").write_bytes(b"LIST_BIN")

    cam = Dsmc2Camera(str(tmp_path))
    return cam


def test_firmware_lens_cfg_parser(tmp_path):
    """Verify authentic firmware lens config filename parsing."""
    fpath = str(tmp_path / "canon_mount" / "Canon_EF_70-200mm_f2p8L_IS_II_USM.cfg")
    info = parse_firmware_lens_cfg(fpath)
    assert info is not None
    assert info.brand == "Canon"
    assert info.mount == "Canon EF"
    assert info.focal_min == 70.0
    assert info.focal_max == 200.0
    assert info.is_zoom is True
    assert info.max_aperture == 2.8
    assert info.has_stabilization is True
    assert info.has_ultrasonic_motor is True


def test_lens_mount_initialization_and_attach(camera):
    """Verify lens mount initializes with default workhorse lens and sets RCP parameters."""
    lm = camera.lens_mount
    assert lm is not None
    assert lm.attached_lens is not None
    assert lm.mount_type == LensMount.MOUNT_CANON_EF

    # Verify RCP synchronization
    assert camera.rcp.state["lens_name"] == lm.attached_lens.model
    assert camera.rcp.state["lens_brand"] == lm.attached_lens.brand
    assert camera.rcp.state["aperture"] == f"f/{lm.current_aperture:.1f}"
    assert camera.rcp.state["focal_length"] == f"{int(lm.current_focal_length)}mm"


def test_aperture_stepping_and_limits(camera):
    """Verify 1/3-stop electronic iris control and boundary stops."""
    lm = camera.lens_mount
    # Attach 50mm f/1.2 lens
    fast_fifty = LensInfo("Canon EF 50mm f/1.2L USM", "Canon", "Canon EF", 50.0, 50.0, 1.2, 16.0, False, True, "CN-5012")
    lm.attach_lens(fast_fifty)

    stops = lm.get_available_aperture_stops()
    assert 1.2 in stops
    assert 16.0 in stops

    # Set aperture wide open
    lm.set_aperture(1.2)
    assert lm.current_aperture == 1.2
    assert camera.rcp.state["aperture"] == "f/1.2"

    # Step down (+1/3 stop)
    lm.step_aperture(1)
    assert lm.current_aperture > 1.2
    cur_ap = lm.current_aperture

    # Step up (-1/3 stop)
    lm.step_aperture(-1)
    assert lm.current_aperture == 1.2


def test_focal_length_and_zoom(camera):
    """Verify zoom ring adjustment and clamping within min/max focal lengths."""
    lm = camera.lens_mount
    zoom_lens = LensInfo("Canon EF 24-70mm f/2.8L II USM", "Canon", "Canon EF", 24.0, 70.0, 2.8, 22.0)
    lm.attach_lens(zoom_lens)

    lm.set_focal_length(35.0)
    assert lm.current_focal_length == 35.0
    assert camera.rcp.state["focal_length"] == "35mm"

    # Clamp below min
    lm.set_focal_length(10.0)
    assert lm.current_focal_length == 24.0

    # Clamp above max
    lm.set_focal_length(100.0)
    assert lm.current_focal_length == 70.0


def test_focus_distance_and_autofocus(camera):
    """Verify focus motor drive and simulated autofocus sweep."""
    lm = camera.lens_mount
    lm.set_focus_distance(1.85)
    assert lm.current_focus_distance == 1.85
    assert camera.rcp.state["focus_distance"] == "1.85m"

    # Set infinity
    lm.set_focus_distance(999.0)
    assert camera.rcp.state["focus_distance"] == "INF"

    # Trigger autofocus at spot reticle
    res = lm.trigger_autofocus(target_point=(400, 300))
    assert res is True
    assert lm.autofocus_state == "LOCKED"
    assert camera.rcp.state["af_state"] == "LOCKED"
    assert lm.current_focus_distance > 0.0


def test_mount_swap_and_detach(camera):
    """Verify detaching lens and swapping mount to Nikon F and PL."""
    lm = camera.lens_mount
    lm.detach_lens()
    assert lm.attached_lens is None
    assert camera.rcp.state["lens_name"] == "No Lens"
    assert camera.rcp.state["aperture"] == "f/--"

    # Swap to Nikon F mount
    lm.set_mount_type(LensMount.MOUNT_NIKON_F)
    assert lm.mount_type == LensMount.MOUNT_NIKON_F
    assert lm.attached_lens is not None
    assert lm.attached_lens.mount == "Nikon F"
