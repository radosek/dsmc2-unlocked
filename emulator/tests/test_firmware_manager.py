"""
Unit and integration tests for RED DSMC2 Firmware Inspection, Staging & Boot Engine.
"""

import os
import struct
import pytest

from emulator.core.firmware import FirmwareManager, FirmwareInspectionResult
from emulator.camera import Dsmc2Camera
from conftest import requires_firmware

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@requires_firmware
def test_firmware_manager_inspect_stock_binary():
    """Verify inspection of genuine stock RED DSMC2 dsmc_program.mem."""
    stock_path = os.path.join(REPO_ROOT, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
    meta = FirmwareManager.inspect(stock_path)

    assert meta.is_valid is True
    assert meta.is_runnable is True
    assert meta.sp == 0x881D2690
    assert meta.reset_pc == 0x80829F2C
    assert "RED DSMC2 DDR Memory Image" in meta.format_name
    assert meta.size_bytes > 10_000_000
    assert len(meta.sha256) == 64
    assert len(meta.md5) == 32


def test_firmware_manager_inspect_invalid():
    """Verify rejection of truncated or invalid non-firmware files."""
    meta = FirmwareManager.inspect(b"NOT_A_FIRMWARE", filename="bad.bin")
    assert meta.is_valid is False
    assert meta.is_runnable is False
    assert "Truncated" in meta.format_name or "Unrecognized" in meta.format_name


def test_firmware_manager_boot_custom_mod():
    """Verify flashing and executing a staged custom DSMC2 binary in DDR RAM."""
    # Build a minimal valid ARM firmware with genuine DSMC2 vector layout
    # Reset vector points to 0x80000040: MOV R0, #42; B . (halt)
    vecs = [0xEA000006] + [0xE59FF024]*7 + [0xE59FD000, 0xE59FF000, 0x881D2690, 0x80000040]
    payload = struct.pack("<12I", *vecs)
    payload += b"\x00" * (0x40 - len(payload))
    payload += struct.pack("<2I", 0xE3A0002A, 0xEAFFFFFE) # MOV R0, #42; B .

    custom_dir = os.path.join(REPO_ROOT, "firmware_store", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    custom_path = os.path.join(custom_dir, "test_custom_mod.bin")
    with open(custom_path, "wb") as f:
        f.write(payload)

    cam = Dsmc2Camera(REPO_ROOT)
    try:
        res = cam.load_and_boot_custom_firmware(custom_path)
        assert res["status"] == "ok"
        assert res["metadata"]["is_valid"] is True
        assert cam.cpu.get_r(0) == 42
        assert cam.is_booted is True
        assert cam.power_state == cam.POWER_ON
    finally:
        if os.path.exists(custom_path):
            os.remove(custom_path)


def test_firmware_manager_crash_reporting():
    """Verify diagnostic crash dump when a custom binary causes an execution fault."""
    # Build an ARM payload that executes an undefined instruction at 0x80000040
    vecs = [0xEA000006] + [0xE59FF024]*7 + [0xE59FD000, 0xE59FF000, 0x881D2690, 0x80000040]
    payload = struct.pack("<12I", *vecs)
    payload += b"\x00" * (0x40 - len(payload))
    payload += struct.pack("<I", 0xE7F001F0) # ARM UDF instruction (guaranteed undefined trap)

    custom_dir = os.path.join(REPO_ROOT, "firmware_store", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    custom_path = os.path.join(custom_dir, "test_crash_mod.bin")
    with open(custom_path, "wb") as f:
        f.write(payload)

    cam = Dsmc2Camera(REPO_ROOT)
    try:
        res = cam.load_and_boot_custom_firmware(custom_path)
        assert res["status"] == "crash"
        assert "registers" in res
        assert "pc" in res["registers"]
        assert cam.is_booted is False
        assert cam.power_state == cam.POWER_STANDBY
    finally:
        if os.path.exists(custom_path):
            os.remove(custom_path)


def test_firmware_manager_custom_mod_uart_output():
    """Verify executing custom firmware code that interacts with OMAP3 UART4 MMIO."""
    # Reset vector points to 0x80000040: writes 'MOD\n' to UART4 (0x4905A000)
    vecs = [0xEA000006] + [0xE59FF024]*7 + [0xE59FD000, 0xE59FF000, 0x881D2690, 0x80000040]
    payload = struct.pack("<12I", *vecs)
    payload += b"\x00" * (0x40 - len(payload))

    insns = [
        0xE3021000, # movw r1, #0x2000
        0xE3441904, # movt r1, #0x4904 (r1 = 0x49042000 UART4)
        0xE3A0004D, # mov r0, #0x4d ('M')
        0xE5C10000, # strb r0, [r1]
        0xE3A0004F, # mov r0, #0x4f ('O')
        0xE5C10000, # strb r0, [r1]
        0xE3A00044, # mov r0, #0x44 ('D')
        0xE5C10000, # strb r0, [r1]
        0xE3A0000A, # mov r0, #0x0a ('\n')
        0xE5C10000, # strb r0, [r1]
        0xEAFFFFFE, # b .
    ]
    payload += struct.pack(f"<{len(insns)}I", *insns)

    custom_dir = os.path.join(REPO_ROOT, "firmware_store", "custom")
    os.makedirs(custom_dir, exist_ok=True)
    custom_path = os.path.join(custom_dir, "test_uart_mod.bin")
    with open(custom_path, "wb") as f:
        f.write(payload)

    cam = Dsmc2Camera(REPO_ROOT)
    try:
        res = cam.load_and_boot_custom_firmware(custom_path)
        assert res["status"] == "ok"
        assert "MOD" in cam.uarts[4].completed_lines
    finally:
        if os.path.exists(custom_path):
            os.remove(custom_path)
