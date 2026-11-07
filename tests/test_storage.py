"""
Automated tests for RED DSMC2 Persistent Storage and Virtual Filesystem (M4).
Verifies CameraEnvironment (/env), partition mapping, and file operations.
"""

import os
import tempfile
import pytest

from emulator.storage.env import CameraEnvironment
from emulator.storage.vfs import VirtualFileSystem


def test_camera_environment_defaults():
    env = CameraEnvironment()
    assert env.get("CAMERA_TYPE") == "0x16"
    assert env.get("CAMERA_NAME") == "SCARLET-W 5K"
    assert env.get("SENSOR_TYPE") == "0x04"
    assert env.get("SENSOR_NAME") == "RED DRAGON 5K S35"
    assert env.get("SENSOR_WIDTH") == "5120"
    assert env.get("SENSOR_HEIGHT") == "2700"
    assert env.get("SERIAL_NUMBER") == "016-10042"


def test_camera_environment_serialization_roundtrip():
    env1 = CameraEnvironment({"CUSTOM_PARAM": "TEST_VAL_123", "CAMERA_NAME": "MONSTRO 8K VV"})
    serialized = env1.serialize()
    assert isinstance(serialized, bytes)
    assert b"CUSTOM_PARAM=TEST_VAL_123" in serialized
    assert b"CAMERA_NAME=MONSTRO 8K VV" in serialized

    env2 = CameraEnvironment.deserialize(serialized)
    assert env2.get("CUSTOM_PARAM") == "TEST_VAL_123"
    assert env2.get("CAMERA_NAME") == "MONSTRO 8K VV"
    assert env2.get("CAMERA_TYPE") == "0x16"


def test_vfs_path_resolution_and_mounts():
    with tempfile.TemporaryDirectory() as tmpdir:
        slot_dir = os.path.join(tmpdir, "slot")
        pstore_dir = os.path.join(tmpdir, "pstore")
        os.makedirs(slot_dir)

        # Create dummy slot file
        with open(os.path.join(slot_dir, "cfg"), "wb") as f:
            f.write(b"DUMMY_CONFIG_DATA")

        vfs = VirtualFileSystem(slot_dir, pstore_dir)

        # Verify mount points
        mounts = vfs.mounts
        assert "/env" in mounts
        assert "/image1" in mounts
        assert "/image2" in mounts
        assert "/data" in mounts
        assert "/log" in mounts
        assert "/pdata" in mounts

        # Test resolution
        assert vfs.resolve_path("/image2/cfg") == os.path.join(slot_dir, "cfg")
        assert vfs.resolve_path("/data/settings.bin") == os.path.join(vfs.data_dir, "settings.bin")
        assert vfs.resolve_path("/log/boot.log") == os.path.join(vfs.log_dir, "boot.log")

        # Test file reading
        content = vfs.read_file("/image2/cfg")
        assert content == b"DUMMY_CONFIG_DATA"

        # Test persistent writing
        success = vfs.write_file("/data/settings.bin", b"\xAA\xBB\xCC\xDD")
        assert success is True
        assert vfs.read_file("/data/settings.bin") == b"\xAA\xBB\xCC\xDD"

        # Test appending to log
        assert vfs.append_file("/log/boot.log", b"LINE1\n") is True
        assert vfs.append_file("/log/boot.log", b"LINE2\n") is True
        assert vfs.read_file("/log/boot.log") == b"LINE1\nLINE2\n"
