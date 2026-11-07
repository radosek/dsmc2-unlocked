"""
Unit and integration tests for Authentic DSMC2 Display Pipeline & Coprocessor Doorbell.
Tests:
- IOB0 and IOB1 C2C Mailbox Doorbell MMIO (0x3FFE8000 & 0x4FFE8000)
- Monitor Pipeline command 0x26 configuration
- GPIO 130 (MONITOR_HDMI_MUX) toggle handling
- OMAP DSS framebuffer extraction from DDR address 0x87400000
"""

import struct
import pytest
from emulator.camera import Dsmc2Camera
from emulator.coprocessors.c2c import IobDoorbellDevice


def test_iob_mailbox_doorbell_mmio_and_command_dispatch():
    cam = Dsmc2Camera(workspace_root=".")

    # Verify doorbells are registered on the bus
    assert IobDoorbellDevice.BASE_ADDR_IOB0 in cam.bus.devices
    assert IobDoorbellDevice.BASE_ADDR_IOB1 in cam.bus.devices

    # Write a simulated Monitor Pipeline Config command (0x26) to IOB0 mailbox in DDR (0x800B0FFC)
    # Packet: [cmd=0x26, arg0=1, arg1=2 (FRAME_GUIDES), arg2=0]
    packet = struct.pack("<4I", 0x26, 1, 2, 0)
    cam.bus.write_mem(0x800B0FFC, packet)

    # Ring IOB0 doorbell by writing counter to 0x3FFE8004
    cam.iob0_doorbell.write(0x04, 4, 1)

    # IOB0 HDMI mode should now be updated to FRAME_GUIDES
    assert cam.iob0.hdmi_mode == "FRAME_GUIDES"


def test_gpio130_hdmi_monitor_mux_toggle():
    cam = Dsmc2Camera(workspace_root=".")

    # Set bit 2 via SETDATAOUT (0x94) on GPIO module 5 (0x49056094)
    cam.gpio[5].write(0x94, 4, 1 << 2)
    assert cam.iob0.hdmi_connected is True

    # Clear bit 2 via CLEARDATAOUT (0x90) on GPIO module 5
    cam.gpio[5].write(0x90, 4, 1 << 2)
    assert cam.iob0.hdmi_connected is False


def test_dss_framebuffer_extraction_from_ddr():
    cam = Dsmc2Camera(workspace_root=".")

    # Write test pixel pattern into authentic LCD DDR framebuffer address (0x87400000)
    pattern = b"\xAA\xBB\xCC\xFF" * (1024 * 576)
    cam.bus.write_mem(0x87400000, pattern)

    # OmapDss should read directly from DDR 0x87400000
    fb = cam.dss.get_framebuffer_bytes()
    assert len(fb) == 1024 * 576 * 4
    assert fb[:4] == b"\xAA\xBB\xCC\xFF"
    assert fb[-4:] == b"\xAA\xBB\xCC\xFF"
