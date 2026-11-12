"""
DM3725 / OMAP3630 TRM Memory Map Validation, SPI-Backed Coprocessor Transport,
and Bus Failsafe / Fallback Protection Test Suite.

Cross-checks all registered devices in `Dsmc2Camera` against the authoritative
TI DM37xx Technical Reference Manual (SPRUGN4) memory map table (`trm_memory_map.json`),
verifies that `0x49000000` is the L4-PER AP interconnect firewall, tests the
McSPI-backed coprocessor mailbox (`ts_isp1`, `ts_isp2`, `ts_fpga`, `ts_sensor`),
and validates Strict vs. Permissive bus modes.
"""

import json
import os
import struct
import pytest

from emulator.camera import Dsmc2Camera
from emulator.core.bus import (
    Device,
    SystemBus,
    DM37XX_TRM_MEMORY_MAP,
    UnmappedMemoryAccessError,
)
from emulator.devices.l4_interconnect import OmapL4Ap, OmapScm, OmapPrm, OmapSdrc
from emulator.devices.mcspi import OmapMcspi
from emulator.coprocessors.c2c import C2cTransport, CoprocessorSpiTarget


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def camera(workspace_root):
    return Dsmc2Camera(workspace_root)


def test_all_registered_camera_devices_match_dm37xx_trm_table(camera):
    """Cross-check every device registered on Dsmc2Camera.bus against trm_memory_map.json."""
    json_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "core", "trm_memory_map.json"
    )
    assert os.path.exists(json_path), "Authoritative trm_memory_map.json must exist"

    with open(json_path, "r", encoding="utf-8") as f:
        trm_json = json.load(f)
    assert len(trm_json["regions"]) >= 35

    violations = camera.bus.validate_trm_compliance()
    assert violations == [], f"Non-TRM devices found on bus: {violations}"

    # Verify required DM37xx TRM peripheral base addresses are registered
    expected_bases = {
        # L4-Core / L4-Wakeup / L4-Per Interconnect & Control
        0x48000000: OmapL4Ap,
        0x48002000: OmapScm,
        0x48004000: type(camera.prcm),
        0x48306000: OmapPrm,
        0x49000000: OmapL4Ap,
        # GPMC & SDRC
        0x6D000000: OmapSdrc,
        0x6E000000: type(camera.gpmc),
        # McSPI 1..4
        0x48098000: OmapMcspi,
        0x4809A000: OmapMcspi,
        0x480B8000: OmapMcspi,
        0x480BA000: OmapMcspi,
        # GPTimers 1..11
        0x48318000: type(camera.timers[1]),
        0x49032000: type(camera.timers[2]),
        0x49034000: type(camera.timers[3]),
        0x49036000: type(camera.timers[4]),
        0x49038000: type(camera.timers[5]),
        0x4903A000: type(camera.timers[6]),
        0x4903C000: type(camera.timers[7]),
        0x4903E000: type(camera.timers[8]),
        0x49040000: type(camera.timers[9]),
        0x48086000: type(camera.timers[10]),
        0x48088000: type(camera.timers[11]),
        # INTC
        0x48200000: type(camera.intc),
        # UART 1..4 (including 0x48020000 L4-Core alias and 0x49020000 L4-Per UART3)
        0x4806A000: type(camera.uarts[1]),
        0x4806C000: type(camera.uarts[2]),
        0x48020000: type(camera.uarts[3]),
        0x49020000: type(camera.uarts[3]),
        0x49042000: type(camera.uarts[4]),
        # I2C 1..3
        0x48070000: type(camera.i2c[1]),
        0x48072000: type(camera.i2c[2]),
        0x48060000: type(camera.i2c[3]),
    }

    for base_addr, expected_cls in expected_bases.items():
        assert base_addr in camera.bus.devices, f"Expected TRM peripheral at 0x{base_addr:08X}"
        size, dev = camera.bus.devices[base_addr]
        assert isinstance(dev, expected_cls), (
            f"Address 0x{base_addr:08X} mapped to {type(dev).__name__}, expected {expected_cls.__name__}"
        )


def test_l4_per_ap_at_0x49000000_replaces_synthetic_c2c(camera):
    """Verify 0x49000000 is the authentic L4-PER AP interconnect model, not C2cTransport."""
    _, dev = camera.bus.devices[0x49000000]
    assert isinstance(dev, OmapL4Ap)
    assert not isinstance(dev, C2cTransport)
    assert dev.name == "L4_PER_AP"

    # Component revision register at 0x49000000 returns Sonics S3220 code 0x40000800
    assert camera.bus.read_u32(0x49000000) == 0x40000800
    # Protection group & permission windows return 0xFFFFFFFF (unrestricted R/W)
    assert camera.bus.read_u32(0x49000100) == 0xFFFFFFFF
    assert camera.bus.read_u32(0x49000800) == 0xFFFFFFFF
    # Error log is 0
    assert camera.bus.read_u32(0x49000040) == 0x00000000

    # Verify GPMC CS0 NAND window (0x08000000) and SDRC (0x6D000000) are accessible
    assert camera.bus.is_ram(0x08000000) is True
    assert camera.bus.read_u32(0x6D000080) == 0x03588019  # SDRC_MCFG_0


def test_spi_backed_coprocessor_mailbox_and_state_machine(camera):
    """
    Verify coprocessor transport binds to McSPI targets (`ts_isp1`, `ts_isp2`,
    `ts_fpga`, `ts_sensor`) and maintains `system_state_2_if` (`2 -> 6 -> 10`)
    without tripping C2C_ERROR (25) or FAILED_IOB (29).
    """
    c2c = camera.c2c
    status = c2c.get_status()
    assert status["transport"] == "McSPI (SPI-backed mailbox)"
    assert status["c2c_error_event_25"] is False
    assert status["failed_iob_event_29"] is False
    assert status["state_history"] == [
        C2cTransport.STATE_RUN,
        C2cTransport.STATE_PREVIEW_START,
        C2cTransport.STATE_READY_TO_RECORD,
    ]
    assert status["system_state"] == C2cTransport.STATE_READY_TO_RECORD

    # 1. Verify native shell SPI target reads (`read spi ts_isp1/ts_isp2/ts_sensor/ts_fpga`)
    for target_name, expected_magic in (
        ("ts_isp1", b"1PSI"),
        ("ts_isp2", b"2PSI"),
        ("ts_fpga", b"AGPF"),
        ("ts_sensor", b"SNES"),
    ):
        raw_id = c2c.spi_read(target_name, CoprocessorSpiTarget.REG_DEVICE_ID, 4)
        assert raw_id == expected_magic
        raw_state = c2c.spi_read(target_name, CoprocessorSpiTarget.REG_SYSTEM_STATE, 4)
        assert struct.unpack("<I", raw_state)[0] == C2cTransport.STATE_READY_TO_RECORD

    # 2. Verify SPI register write & readback on ts_fpga
    assert c2c.spi_write("ts_fpga", 0x0100, struct.pack("<I", 0xCAFE1234)) is True
    assert struct.unpack("<I", c2c.spi_read("ts_fpga", 0x0100, 4))[0] == 0xCAFE1234

    # 3. Verify McSPI hardware channel transfer with framed C2C command (0xC2 header)
    # McSPI1 Channel 0 is wired to ts_isp1; writing 0xC2010001 sends Heartbeat (cmd 0x01)
    mcspi1_base = 0x48098000
    ch0_tx = mcspi1_base + OmapMcspi.CH_BASE + 0x0C
    ch0_rx = mcspi1_base + OmapMcspi.CH_BASE + 0x10
    camera.bus.write_u32(ch0_tx, 0xC2010001)
    rx_ack = camera.bus.read_u32(ch0_rx)
    assert (rx_ack >> 24) == 0xA5  # Valid C2C SPI mailbox ACK prefix

    # 4. Verify packet CRC32 and sequence increments
    prev_seq = c2c.sequence_number
    hb_resp = c2c.send_packet(C2cTransport.CORE_IOB0, cmd=0x01, payload=[0xAA55])
    assert hb_resp is not None
    assert hb_resp[0] == 0x01
    assert c2c.sequence_number == (prev_seq + 1) & 0xFFFF
    assert c2c.last_crc32 != 0


def test_bus_permissive_vs_strict_mode_failsafe(camera):
    """
    Verify SystemBus Permissive Mode logs warnings with PC and returns 0x00000000
    on unmapped peripheral accesses, while Strict Mode raises UnmappedMemoryAccessError.
    """
    bus = camera.bus
    unmapped_l4_addr = 0x480FF000  # Unassigned slot inside L4-Core (0x48000000..0x490FFFFF)

    # 1. Permissive Mode (default): logs warning with PC and returns 0x00000000 without raising
    assert bus.strict_mode is False
    camera.cpu.pc = 0x80674A10
    val = bus.read_u32(unmapped_l4_addr)
    assert val == 0x00000000
    bus.write_u32(unmapped_l4_addr, 0x12345678)

    assert unmapped_l4_addr in bus.unknown_reads
    assert unmapped_l4_addr in bus.unknown_writes
    assert any(
        w["address"] == unmapped_l4_addr and w["pc"] == 0x80674A10
        for w in bus.fallback_warnings
    )

    # 2. Strict Mode: raises UnmappedMemoryAccessError on unmapped read/write and non-TRM device registration
    bus.set_mode(strict=True)
    try:
        with pytest.raises(UnmappedMemoryAccessError):
            bus.read_u32(0x480FE000)

        with pytest.raises(UnmappedMemoryAccessError):
            bus.write_u32(0x480FE004, 0xDEADBEEF)

        with pytest.raises(UnmappedMemoryAccessError):
            bus.register_device(0x49099000, 0x1000, Device())
    finally:
        bus.set_mode(strict=False)
