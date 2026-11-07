"""
Unit and integration tests for RED DSMC2 R3D Clip Recorder and Media Subsystem.
Verifies authentic RED MINI-MAG storage layout, .RDC container generation,
.R3D ISO header structure, .RMD XML sidecar formatting, and clip numbering.
"""

import os
import struct
import xml.etree.ElementTree as ET
import pytest
from emulator.camera import Dsmc2Camera


@pytest.fixture
def camera(tmp_path):
    slot_dir = tmp_path / "firmware_store" / "unpacked" / "scarlet_w_7_4_1" / "slot"
    slot_dir.mkdir(parents=True)
    (slot_dir / "dsmc_program.mem").write_bytes(b"\x00" * 4096)
    (slot_dir / "system.env").write_text("CAMERA_NAME=SCARLET-W 5K\nPIN=10042\n")

    return Dsmc2Camera(str(tmp_path))


def test_r3d_clip_recording_lifecycle(camera):
    """Verify recording start, .RDC directory layout, and clip finalization."""
    rec = camera.recorder
    assert rec.is_recording is False
    assert rec.clip_number == 1

    # 1. Start Recording
    started = camera.start_recording()
    assert started is True
    assert rec.is_recording is True
    assert camera.rcp.state["record_state"] == "2"

    clip_name = rec.current_clip_name
    assert clip_name.startswith("A001_C001_")
    assert clip_name.endswith("_001")

    rdc_dir = rec.current_rdc_path
    assert os.path.isdir(rdc_dir)
    assert rdc_dir.endswith(".RDC")

    r3d_file = rec.current_r3d_path
    assert os.path.isfile(r3d_file)

    # Verify initial .R3D ISO Box Header
    with open(r3d_file, "rb") as f:
        data = f.read(20)
        box_size, box_type, brand = struct.unpack(">I4s4s", data[:12])
        assert box_size == 20
        assert box_type == b"ftyp"
        assert brand == b"RED2"

    # 2. Stop Recording
    stopped = camera.stop_recording()
    assert stopped is True
    assert rec.is_recording is False
    assert camera.rcp.state["record_state"] == "0"
    assert rec.clip_number == 2 # Incremented to C002

    # Verify finalized .R3D file has content
    assert os.path.getsize(r3d_file) > 1024

    # Verify .RMD XML Sidecar exists and is valid XML
    rmd_file = os.path.join(rdc_dir, f"{clip_name}.RMD")
    assert os.path.isfile(rmd_file)

    tree = ET.parse(rmd_file)
    root = tree.getroot()
    assert root.tag == "RED_METADATA"
    assert root.find("CLIP_NAME").text == clip_name
    assert root.find("CAMERA_MODEL").text == "SCARLET-W 5K"
    assert root.find("REEL_ID").text == "A001"
    assert root.find("FRAME_RATE").text == "23.976"
    assert root.find("RECORD_FORMAT").text == "5K 16:9"

    lens_elem = root.find("LENS")
    assert lens_elem is not None
    assert lens_elem.find("NAME") is not None
    assert lens_elem.find("APERTURE") is not None


def test_multiple_clip_progression(camera):
    """Verify sequential clip naming progression (C001 -> C002 -> C003)."""
    rec = camera.recorder

    # Clip 1
    camera.start_recording()
    c1 = rec.current_clip_name
    assert "C001" in c1
    camera.stop_recording()

    # Clip 2
    camera.start_recording()
    c2 = rec.current_clip_name
    assert "C002" in c2
    camera.stop_recording()

    # Clip 3
    camera.start_recording()
    c3 = rec.current_clip_name
    assert "C003" in c3
    camera.stop_recording()

    clips = rec.list_clips()
    assert len(clips) == 3
    names = [c["clip_name"] for c in clips]
    assert c1 in names
    assert c2 in names
    assert c3 in names


def test_media_formatting_and_reel_increment(camera):
    """Verify formatting media wipes current clips and increments reel ID."""
    rec = camera.recorder
    camera.start_recording()
    camera.stop_recording()
    assert len(rec.list_clips()) == 1
    assert rec.current_reel_id == "A001"

    # Format media
    res = rec.format_media()
    assert res is True
    assert rec.current_reel_id == "A002" # Incremented reel
    assert rec.clip_number == 1
    assert len(rec.list_clips()) == 0


def test_media_eject_and_remount(camera):
    """Verify media ejection blocks recording and remounting restores it."""
    rec = camera.recorder
    assert rec.is_media_mounted is True

    # Eject
    rec.eject_media()
    assert rec.is_media_mounted is False
    assert camera.rcp.state["media_remaining_percent"] == "0"

    # Attempt recording should fail
    started = camera.start_recording()
    assert started is False
    assert rec.is_recording is False

    # Remount
    rec.mount_media()
    assert rec.is_media_mounted is True
    started = camera.start_recording()
    assert started is True
    camera.stop_recording()
