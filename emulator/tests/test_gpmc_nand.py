"""
Unit tests for OMAP3 GPMC NAND controller and TWL4030 RTC subsystem.
Verifies:
- GPMC_STATUS (0x54) reports WAIT0STATUS ready for NAND operations
- ONFI Parameter Page (command 0xEC) returns ONFI geometry
- TWL4030 PMIC returns RTC running status (register 0x2A bit 1 = 1) on slave addresses 0x1B, 0x48, 0x4B
"""

import pytest
from emulator.camera import Dsmc2Camera
from emulator.devices.gpmc import OmapGpmc


def test_gpmc_status_and_onfi_nand_command():
    gpmc = OmapGpmc()

    # GPMC_STATUS at 0x54 should show WAIT0STATUS (bit 8) and EMPTYWRITEBUFFER (bit 0)
    status = gpmc.read(0x54, 4)
    assert (status & 0x100) != 0 # WAIT0STATUS
    assert (status & 0x001) != 0 # EMPTYWRITEBUFFER

    # Send command 0xEC (Read ONFI Parameter Page)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0xEC)

    # Read first word of parameter page -> should be 'ONFI' (0x49464E4F)
    sig = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 4)
    assert sig == 0x49464E4F


def test_twl4030_rtc_status_registers():
    cam = Dsmc2Camera(workspace_root=".")

    # PMIC at 0x1B, 0x48, 0x4B should report RTC running (bit 1 of register 0x2A)
    for addr in (0x1B, 0x48, 0x4B):
        slave = cam.i2c[1].slaves.get(addr)
        assert slave is not None
        rtc_stat = slave.read(0x2A, 1)[0]
        assert (rtc_stat & 0x02) != 0 # RUN bit
