"""
Automated unit tests for RED DSMC2 Fault Injection and Resilience (M8).
Tests monitor detachment, I2C bus error, corrupt NAND /env partition, and watchdog reset.
"""

import os
import tempfile
import pytest

from emulator.camera import Dsmc2Camera
from emulator.core.snapshot import SnapshotManager


def test_camera_fault_injection_and_snapshots():
    workspace = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    camera = Dsmc2Camera(workspace)
    camera.load_firmware()

    # 1. Test Monitor Detach and Reconnect
    assert 0x4B in camera.i2c[3].slaves
    assert 0x50 in camera.i2c[3].slaves

    camera.inject_fault("monitor_disconnect")
    assert 0x4B not in camera.i2c[3].slaves
    assert 0x50 not in camera.i2c[3].slaves

    camera.inject_fault("monitor_connect")
    assert 0x4B in camera.i2c[3].slaves
    assert 0x50 in camera.i2c[3].slaves

    # 2. Test I2C Bus Error Injection
    bus = camera.i2c[3]
    assert (bus.i2c_stat & 0x02) == 0
    camera.inject_fault("i2c_nack", bus=3)
    assert (bus.i2c_stat & 0x02) != 0

    # 3. Test Corrupt Environment Handling
    corrupt_data = b"NOT_A_VALID_KEY_VALUE_PAIR_NULLS\x00\xFF\xFE\xFD"
    restored_env = camera.vfs.env.deserialize(corrupt_data)
    assert isinstance(restored_env.config, dict)

    # 4. Boot to 10M instructions and test snapshots
    camera.boot(initial_instructions=10_000_000)
    assert camera.instruction_count == 10_000_000
    orig_pc = camera.cpu.pc

    with tempfile.NamedTemporaryFile(suffix=".dsmc2", delete=False) as tmp:
        snap_path = tmp.name

    try:
        # Save snapshot
        camera.save_snapshot(snap_path, description="Pre-fault test snapshot")
        assert os.path.exists(snap_path)
        assert os.path.getsize(snap_path) > 1000

        # 5. Inject Watchdog Reset
        camera.inject_fault("watchdog_reset")
        assert camera.cpu.pc == 0x80829F2C
        assert camera.cpu.sp == 0x881D2690
        assert camera.instruction_count == 0
        assert camera.is_booted is False

        # 6. Restore Snapshot and verify state restored
        meta = camera.restore_snapshot(snap_path)
        assert camera.cpu.pc == orig_pc
        assert camera.instruction_count == 10_000_000
        assert meta["description"] == "Pre-fault test snapshot"
    finally:
        if os.path.exists(snap_path):
            os.remove(snap_path)
