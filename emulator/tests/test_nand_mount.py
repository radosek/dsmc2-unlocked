"""
Tests for OMAP3630 GPMC NAND Flash Controller and DDR Geometry Descriptors.
Verifies ONFI/Micron MT29F8G08 command responses, byte-level FIFO streaming,
and YAFFS /env geometry descriptor mapping.
"""

import os
import struct
import pytest
from emulator.devices.gpmc import OmapGpmc
from emulator.camera import Dsmc2Camera
from conftest import requires_firmware

pytestmark = requires_firmware


def test_gpmc_nand_onfi_and_micron_commands():
    """Verify GPMC responds correctly to 8-bit, 16-bit, and 32-bit accesses for NAND commands."""
    gpmc = OmapGpmc()

    # 1. GPMC_STATUS at 0x54 (WAIT0STATUS=1, EMPTYWRITEBUFFER=1)
    assert gpmc.read(0x54, 4) == 0x00000101

    # 2. Reset (0xFF)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0xFF)
    assert gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) == 0x00 # Default empty/cleared buffer

    # 3. Read ID (0x90) + Address (0x00)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0x90)
    gpmc.write(OmapGpmc.REG_NAND_ADDRESS_0, 1, 0x00)

    # Firmware 0x8067BC04 reads 1 byte at a time using ldrb
    b0 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) # Mfg ID
    b1 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) # Device ID
    b2 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) # 3rd byte
    b3 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) # 4th byte
    b4 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1) # 5th byte

    assert b0 == 0x2C # Micron Manufacturer ID
    assert b1 == 0xBA # 256MB SLC Device ID
    assert b2 == 0x90
    assert b3 == 0xA5
    assert b4 == 0x15

    # 4. Read Status (0x70)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0x70)
    st = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1)
    assert st == 0xE0 # Ready=1, Write-protect inactive=1, Pass=0 (bit 0=0)
    assert (st & 0x01) == 0 # Bit 0 is 0 (PASS)

    # 5. Set Features (0xEF) and Get Features (0xEE)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0xEF)
    gpmc.write(OmapGpmc.REG_NAND_ADDRESS_0, 1, 0x01) # Timing mode
    gpmc.features[0x01] = [0x04, 0x00, 0x00, 0x00] # Timing mode 4

    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0xEE)
    gpmc.write(OmapGpmc.REG_NAND_ADDRESS_0, 1, 0x01)
    f0 = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 1)
    assert f0 == 0x04

    # 6. ONFI Parameter Page (0xEC)
    gpmc.write(OmapGpmc.REG_NAND_CMD_0, 1, 0xEC)
    sig = gpmc.read(OmapGpmc.REG_NAND_DATA_0, 4)
    assert sig == 0x49464E4F # 'ONFI' little-endian


def test_gpmc_ecc_and_prefetch_registers():
    """Verify GPMC hardware BCH ECC engine and prefetch registers."""
    gpmc = OmapGpmc()

    # Prefetch config 1 at 0x1E0
    gpmc.write(0x1E0, 4, 0x08004084)
    assert gpmc.read(0x1E0, 4) == 0x08004084

    # ECC size config at 0x1FC
    gpmc.write(0x1FC, 4, 0x3FCFF000)
    assert gpmc.read(0x1FC, 4) == 0x3FCFF000

    # ECC control at 0x1F8
    gpmc.write(0x1F8, 4, 0x00000101)
    assert gpmc.read(0x1F8, 4) == 0x00000101

    # ECC config at 0x1F4
    gpmc.write(0x1F4, 4, 0x000000B1)
    assert gpmc.read(0x1F4, 4) == 0x000000B1


def test_nand_geometry_descriptor_ddr_mapping():
    """Verify camera initializes DDR NAND geometry descriptor at 0x81EF7824 pointing to 0x80FCEBF6."""
    cam = Dsmc2Camera(workspace_root=".")
    cam.load_firmware()

    # Verify initialized driver flag at 0x81EF7818
    init_flag = cam.bus.read(0x81EF7818, 4)
    assert init_flag == 1

    # Verify ID at 0x81EF7820
    mfg_dev = cam.bus.read(0x81EF7820, 4)
    assert (mfg_dev & 0xFF) == 0x2C # Micron
    assert ((mfg_dev >> 8) & 0xFF) == 0xBA # 256MB SLC

    # Verify geometry pointer at 0x81EF7824
    geom_ptr = cam.bus.read(0x81EF7824, 4)
    assert geom_ptr == 0x80FCEBF6

    # Verify geometry values stored in genuine firmware at 0x80FCEBF6
    page_size = cam.bus.read(geom_ptr, 2)
    pages_per_block = cam.bus.read(geom_ptr + 2, 2)
    total_blocks = cam.bus.read(geom_ptr + 4, 2)
    oob_size = cam.bus.read(geom_ptr + 6, 2)

    assert page_size == 2048 # 2KB per page
    assert pages_per_block == 64 # 64 pages per block (128KB block)
    assert total_blocks == 2048 # 2048 blocks = 256MB
    assert oob_size == 64 # 64 bytes spare area (OOB)
