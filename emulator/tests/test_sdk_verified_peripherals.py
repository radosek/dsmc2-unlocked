"""
Tests for DM3725 TRM peripherals, HDQ / 1-Wire EEPROM identity & MD5 verification,
TI UCD9090/UCD90160 PMBus power sequencers, DSMC2 I2C chips, and fault modes.

All hardware identities, ROM IDs, and serial numbers verified here are strictly
synthetic placeholders (`SYNTH-*`, `0x52454432...`).
"""

import os
import struct
import pytest

from emulator.camera import Dsmc2Camera
from emulator.core.faults import HardwareFaultInjector
from emulator.devices.hdq_onewire import (
    ONEWIRE_MD5_SALT,
    OmapHdq1Wire,
    compute_onewire_md5_signature,
    crc8_maxim,
    make_rom_id,
)
from emulator.devices.i2c_ucd import (
    UcdPowerSequencer,
    decode_linear11,
    decode_linear16,
    encode_linear11,
    encode_linear16,
)
from emulator.devices.i2c_dsmc2_chips import (
    Si5346ClockSynth,
    Dac7578SensorDac,
    FocalTechTouch,
)
from emulator.devices.l4_interconnect import OmapScmId
from emulator.devices.mcbsp import OmapMcBSP
from emulator.devices.cam_isp import OmapCamIsp


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def camera(workspace_root):
    return Dsmc2Camera(workspace_root)


# ---------------------------------------------------------------------------
# OMAP3 / DM3725 HDQ / 1-Wire Helpers & Tests
# ---------------------------------------------------------------------------


def _hdq_reset(bus) -> bool:
    base = OmapHdq1Wire.BASE_ADDR
    bus.write_u32(
        base + OmapHdq1Wire.REG_CTRL_STATUS,
        OmapHdq1Wire.BIT_INITIALIZATION | OmapHdq1Wire.BIT_GO | OmapHdq1Wire.BIT_CLOCKENABLE,
    )
    ctrl = bus.read_u32(base + OmapHdq1Wire.REG_CTRL_STATUS)
    bus.read_u32(base + OmapHdq1Wire.REG_INT_STATUS)
    return bool(ctrl & OmapHdq1Wire.BIT_PRESENCE_DETECT)


def _hdq_write_bit(bus, bit: int):
    base = OmapHdq1Wire.BASE_ADDR
    bus.write_u32(base + OmapHdq1Wire.REG_TX_DATA, bit & 1)
    bus.write_u32(
        base + OmapHdq1Wire.REG_CTRL_STATUS,
        OmapHdq1Wire.BIT_GO | OmapHdq1Wire.BIT_SINGLE | OmapHdq1Wire.BIT_CLOCKENABLE,
    )


def _hdq_read_bit(bus) -> int:
    base = OmapHdq1Wire.BASE_ADDR
    bus.write_u32(
        base + OmapHdq1Wire.REG_CTRL_STATUS,
        OmapHdq1Wire.BIT_GO
        | OmapHdq1Wire.BIT_DIR_RX
        | OmapHdq1Wire.BIT_SINGLE
        | OmapHdq1Wire.BIT_CLOCKENABLE,
    )
    return bus.read_u32(base + OmapHdq1Wire.REG_RX_DATA) & 1


def _hdq_write_byte(bus, byte_val: int):
    base = OmapHdq1Wire.BASE_ADDR
    bus.write_u32(base + OmapHdq1Wire.REG_TX_DATA, byte_val & 0xFF)
    bus.write_u32(
        base + OmapHdq1Wire.REG_CTRL_STATUS,
        OmapHdq1Wire.BIT_GO | OmapHdq1Wire.BIT_CLOCKENABLE,
    )


def _hdq_read_byte(bus) -> int:
    base = OmapHdq1Wire.BASE_ADDR
    bus.write_u32(
        base + OmapHdq1Wire.REG_CTRL_STATUS,
        OmapHdq1Wire.BIT_GO | OmapHdq1Wire.BIT_DIR_RX | OmapHdq1Wire.BIT_CLOCKENABLE,
    )
    return bus.read_u32(base + OmapHdq1Wire.REG_RX_DATA) & 0xFF


def _hdq_search_all_roms(bus):
    """Standard Maxim AN187 Search ROM loop driven over OmapHdq1Wire MMIO."""
    found = []
    last_discrepancy = 0
    last_device_flag = False
    rom_bytes = bytearray(8)

    while not last_device_flag:
        if not _hdq_reset(bus):
            break

        last_zero = 0
        _hdq_write_byte(bus, 0xF0)  # Search ROM

        search_ok = True
        for id_bit_number in range(1, 65):
            byte_i = (id_bit_number - 1) // 8
            bit_mask = 1 << ((id_bit_number - 1) % 8)

            id_bit = _hdq_read_bit(bus)
            cmp_id_bit = _hdq_read_bit(bus)

            if id_bit == 1 and cmp_id_bit == 1:
                search_ok = False
                break

            if id_bit != cmp_id_bit:
                direction = id_bit
            else:
                if id_bit_number < last_discrepancy:
                    direction = 1 if (rom_bytes[byte_i] & bit_mask) else 0
                else:
                    direction = 1 if (id_bit_number == last_discrepancy) else 0
                if direction == 0:
                    last_zero = id_bit_number

            if direction:
                rom_bytes[byte_i] |= bit_mask
            else:
                rom_bytes[byte_i] &= ~bit_mask

            _hdq_write_bit(bus, direction)

        if not search_ok:
            break

        found.append(bytes(rom_bytes))
        last_discrepancy = last_zero
        if last_discrepancy == 0:
            last_device_flag = True

    return found


def _i2c_write_reg(bus, i2c_base: int, addr: int, reg: int, payload: bytes):
    bus.write_u32(i2c_base + 0x08, 0xFFFF)  # Clear STAT
    bus.write_u32(i2c_base + 0x2C, addr)
    bus.write_u32(i2c_base + 0x18, 1 + len(payload))
    bus.write_u32(i2c_base + 0x24, 0x8601)  # EN | MST | TRX | STT
    bus.write_u32(i2c_base + 0x1C, reg & 0xFF)
    for b in payload:
        bus.write_u32(i2c_base + 0x1C, b & 0xFF)
    stat = bus.read_u32(i2c_base + 0x08)
    bus.write_u32(i2c_base + 0x08, 0xFFFF)
    return stat


def _i2c_read_reg(bus, i2c_base: int, addr: int, reg: int, length: int) -> bytes:
    bus.write_u32(i2c_base + 0x08, 0xFFFF)
    bus.write_u32(i2c_base + 0x2C, addr)
    bus.write_u32(i2c_base + 0x18, 1)
    bus.write_u32(i2c_base + 0x24, 0x8601)
    bus.write_u32(i2c_base + 0x1C, reg & 0xFF)
    bus.write_u32(i2c_base + 0x08, 0xFFFF)

    bus.write_u32(i2c_base + 0x2C, addr)
    bus.write_u32(i2c_base + 0x18, length)
    bus.write_u32(i2c_base + 0x24, 0x8401)  # EN | MST | STT (RX)
    return bytes(bus.read_u32(i2c_base + 0x1C) & 0xFF for _ in range(length))


def test_hdq_onewire_presence_search_match_and_md5(camera):
    assert ONEWIRE_MD5_SALT == bytes.fromhex("27a8124fb3ea")

    # 1. Presence detect normal vs ONEWIRE_BUS_FAULT
    assert _hdq_reset(camera.bus) is True

    faults = HardwareFaultInjector(camera)
    faults.inject_fault("ONEWIRE_BUS_FAULT", enable=True)
    assert _hdq_reset(camera.bus) is False
    faults.inject_fault("ONEWIRE_BUS_FAULT", enable=False)
    assert _hdq_reset(camera.bus) is True

    # 2. Full bit-by-bit Search ROM discovers all 5 synthetic boards with valid CRC-8
    roms = _hdq_search_all_roms(camera.bus)
    assert len(roms) == 5
    assert len(set(roms)) == 5
    for rom in roms:
        assert crc8_maxim(rom) == 0

    expected_roms = {b.rom_id: b for b in camera.hdq.devices}
    assert set(roms) == set(expected_roms.keys())

    # 3. Match ROM + Read Memory reads EEPROM part/serial/MD5 over MMIO
    isp_board = camera.hdq.get_board("ISP")
    assert isp_board is not None
    assert _hdq_reset(camera.bus) is True
    _hdq_write_byte(camera.bus, 0x55)  # Match ROM
    for b in isp_board.rom_id:
        _hdq_write_byte(camera.bus, b)
    _hdq_write_byte(camera.bus, 0xF0)  # DS2431 Read Memory
    _hdq_write_byte(camera.bus, 0x00)  # TA1
    _hdq_write_byte(camera.bus, 0x00)  # TA2
    eeprom = bytes(_hdq_read_byte(camera.bus) for _ in range(128))

    part_num = eeprom[0x20:0x30].split(b"\x00", 1)[0].decode("ascii")
    serial_num = eeprom[0x40:0x50].split(b"\x00", 1)[0].decode("ascii")
    stored_md5 = eeprom[0x70:0x80]
    assert part_num == isp_board.part_num
    assert serial_num == isp_board.serial_num

    recomputed = compute_onewire_md5_signature(
        rom_id=isp_board.rom_id,
        class_str=isp_board.name,
        rev_str=isp_board.rev_str,
        field_42=eeprom[0x0C:0x0E],
        sig_type=eeprom[0x0E],
        header_ver=eeprom[0x0F],
        board_info=eeprom[0x10:0x20].split(b"\x00", 1)[0].decode("ascii"),
        part_num=part_num,
        extra_field=eeprom[0x30:0x40].split(b"\x00", 1)[0].decode("ascii"),
        serial_num=serial_num,
    )
    assert stored_md5 == recomputed
    assert camera.hdq.verify_board("ISP") is True

    # 4. ONEWIRE_BOARD_MISMATCH fails verify_board() without updating signature
    faults.inject_fault("ONEWIRE_BOARD_MISMATCH", board="ISP", serial="SYNTH-BAD-9999")
    assert camera.hdq.verify_board("ISP") is False

    # 5. ONEWIRE_BOARD_MISSING drops SENSOR from enumeration
    faults.inject_fault("ONEWIRE_BOARD_MISSING", board="SENSOR")
    names = {b["name"] for b in camera.hdq.list_boards()}
    assert "SENSOR" not in names
    assert len(names) == 4

    camera.hdq.restore_default_boards()
    assert len(camera.hdq.list_boards()) == 5
    assert camera.hdq.verify_board("ISP") is True


def test_scm_id_mcbsp_and_cam_isp_registers(camera):
    # SCM_ID (0x4830A000)
    idcode = camera.bus.read_u32(OmapScmId.BASE_ADDR + OmapScmId.REG_IDCODE)
    assert idcode == 0x1B89102F
    die = [
        camera.bus.read_u32(OmapScmId.BASE_ADDR + OmapScmId.REG_DIE_ID_0 + 4 * i)
        for i in range(4)
    ]
    assert die == [0x52454432, 0x37323500, 0x00000001, 0x5642524E]

    # McBSP 2..5
    for mcbsp_id, (base, _) in {
        2: (0x49022000, 17),
        3: (0x49024000, 22),
        4: (0x49026000, 23),
        5: (0x48096000, 27),
    }.items():
        # Enable XRST -> XRDY & XEMPTY appear in SPCR2
        camera.bus.write_u32(base + OmapMcBSP.REG_SPCR2, OmapMcBSP.SPCR2_XRST)
        spcr2 = camera.bus.read_u32(base + OmapMcBSP.REG_SPCR2)
        assert spcr2 & (OmapMcBSP.SPCR2_XRST | OmapMcBSP.SPCR2_XRDY | OmapMcBSP.SPCR2_XEMPTY)

        # XCERA write/read
        camera.bus.write_u32(base + OmapMcBSP.REG_XCERA, 0xA55A0001)
        assert camera.bus.read_u32(base + OmapMcBSP.REG_XCERA) == 0xA55A0001

        # Digital Loopback (DLB) DXR -> DRR + SPCR1 RRDY
        camera.bus.write_u32(base + OmapMcBSP.REG_SPCR1, OmapMcBSP.SPCR1_DLB)
        camera.bus.write_u32(base + OmapMcBSP.REG_DXR, 0x12345678)
        assert camera.bus.read_u32(base + OmapMcBSP.REG_SPCR1) & OmapMcBSP.SPCR1_RRDY
        assert camera.bus.read_u32(base + OmapMcBSP.REG_DRR) == 0x12345678

    # CAM_ISP (0x480BC000)
    isp_base = OmapCamIsp.BASE_ADDR
    assert camera.bus.read_u32(isp_base + OmapCamIsp.REG_ISP_REVISION) == 0x20
    camera.bus.write_u32(isp_base + OmapCamIsp.REG_CCDC_PCR, 0x00000001)
    camera.bus.write_u32(isp_base + OmapCamIsp.REG_CCDC_SDR_ADDR, 0x87000000)
    assert camera.bus.read_u32(isp_base + OmapCamIsp.REG_CCDC_PCR) == 0x1
    assert camera.bus.read_u32(isp_base + OmapCamIsp.REG_CCDC_SDR_ADDR) == 0x87000000

    # Soft reset via SYSCONFIG bit 1 clears CCDC_PCR and keeps SYSSTATUS RESETDONE=1
    camera.bus.write_u32(isp_base + OmapCamIsp.REG_ISP_SYSCONFIG, 0x0002)
    assert camera.bus.read_u32(isp_base + OmapCamIsp.REG_ISP_SYSSTATUS) == 0x1
    assert camera.bus.read_u32(isp_base + OmapCamIsp.REG_CCDC_PCR) == 0x0


# ---------------------------------------------------------------------------
# PMBus UCD9090 / UCD90160 & DSMC2 I2C Peripheral Tests
# ---------------------------------------------------------------------------


def test_linear16_and_linear11_roundtrips():
    for v in (0.74, 0.75, 0.91, 1.00, 1.50, 1.80, 2.50, 3.30):
        raw16 = encode_linear16(v, exp=-12)
        dec16 = decode_linear16(raw16, exp=-12)
        assert abs(dec16 - v) < 0.001

    for val in (0.0, 1.0, 2.5, 5.0, 12.0, 42.5, -3.5):
        raw11 = encode_linear11(val)
        dec11 = decode_linear11(raw11)
        assert abs(dec11 - val) < 0.05


def test_ucd_sequencers_page_discriminator_gpo_and_faults(camera):
    assert camera.ucd_iob is camera.i2c[1].slaves[0x7C]
    assert camera.ucd_isp is camera.i2c[2].slaves[0x70]
    assert camera.ucd_sensor is camera.i2c[2].slaves[0x65]
    assert camera.ucd_sensor is camera.i2c[3].slaves[0x65]
    assert camera.ucd_iob_bus2 is camera.i2c[3].slaves[0x70]

    # Read MFR_MODEL over OmapI2c (I2C2 @ 0x48072000)
    isp_model = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_MODEL, 7)
    assert isp_model == b"UCD9090"

    sns_model = _i2c_read_reg(camera.bus, 0x48072000, 0x65, UcdPowerSequencer.CMD_MFR_MODEL, 8)
    assert sns_model == b"UCD90160"

    # Offline page-limit discriminator: UCD9090 rejects page 0x10 and sets STATUS_CML |= 0x40
    assert camera.ucd_isp.write(UcdPowerSequencer.CMD_PAGE, b"\x10") is False
    cml_isp = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_STATUS_CML, 1)[0]
    assert cml_isp & 0x40

    # UCD90160 accepts page 0x10 over I2C2
    _i2c_write_reg(camera.bus, 0x48072000, 0x65, UcdPowerSequencer.CMD_PAGE, b"\x10")
    page_sns = _i2c_read_reg(camera.bus, 0x48072000, 0x65, UcdPowerSequencer.CMD_PAGE, 1)[0]
    assert page_sns == 0x10
    cml_sns = _i2c_read_reg(camera.bus, 0x48072000, 0x65, UcdPowerSequencer.CMD_STATUS_CML, 1)[0]
    assert (cml_sns & 0x40) == 0

    # TI MFR_GPO_SELECT (0xFA) / MFR_GPO_CONFIG (0xFB) bit-3 state readback
    _i2c_write_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_GPO_SELECT, b"\x02")
    _i2c_write_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_GPO_CONFIG, b"\x07")
    gpo_high = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_GPO_CONFIG, 1)[0]
    assert (gpo_high & 0x08) == 0x08

    _i2c_write_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_GPO_CONFIG, b"\x03")
    gpo_low = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_MFR_GPO_CONFIG, 1)[0]
    assert (gpo_low & 0x08) == 0x00

    # UCD_UV_FAULT sets STATUS_VOUT and STATUS_WORD
    faults = HardwareFaultInjector(camera)
    faults.inject_fault("UCD_UV_FAULT", board="isp", page=0, drop_volts=0.2)
    _i2c_write_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_PAGE, b"\x00")
    svout = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_STATUS_VOUT, 1)[0]
    sword_raw = _i2c_read_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_STATUS_WORD, 2)
    sword = struct.unpack("<H", sword_raw)[0]
    assert svout & 0x30
    assert sword & 0x8000  # VOUT fault bit

    # E49_ISP_POWER_FAULT removes 0x70 & 0x6C together on I2C2; RESTORE brings both back
    faults.inject_fault("E49_ISP_POWER_FAULT")
    assert 0x70 not in camera.i2c[2].slaves
    assert 0x6C not in camera.i2c[2].slaves
    stat = _i2c_write_reg(camera.bus, 0x48072000, 0x70, UcdPowerSequencer.CMD_PAGE, b"\x00")
    assert stat & 0x02  # NACK

    faults.inject_fault("E49_ISP_POWER_RESTORE")
    assert 0x70 in camera.i2c[2].slaves
    assert 0x6C in camera.i2c[2].slaves


def test_si5346_dac7578_and_focaltech_i2c_chips(camera):
    # Si5346 @ I2C2 0x6C -> Page 0 ID = (0x46, 0x53)
    si_id = _i2c_read_reg(camera.bus, 0x48072000, 0x6C, Si5346ClockSynth.REG_DEVICE_ID_LO, 2)
    assert si_id == b"\x46\x53"

    # DAC7578 @ I2C2 0x49 / 0x4B -> 12-bit left-justified channel write
    dac = camera.i2c[2].slaves[0x49]
    assert isinstance(dac, Dac7578SensorDac)
    code12 = 0xABC
    word16 = code12 << 4
    _i2c_write_reg(camera.bus, 0x48072000, 0x49, 0x32, bytes([(word16 >> 8) & 0xFF, word16 & 0xFF]))
    assert dac.get_channel_code(2) == 0xABC

    # FocalTech FT5x06 @ I2C3 0x3E -> CHIP_ID 0x55 & touch injection
    ft_id = _i2c_read_reg(camera.bus, 0x48060000, 0x3E, FocalTechTouch.REG_CHIP_ID, 1)
    assert ft_id == b"\x55"
    ft = camera.i2c[3].slaves[0x3E]
    assert isinstance(ft, FocalTechTouch)
    ft.inject_touch(512, 288, pressed=True)
    td = _i2c_read_reg(camera.bus, 0x48060000, 0x3E, FocalTechTouch.REG_TD_STATUS, 5)
    assert td[0] == 1
    x = ((td[1] & 0x0F) << 8) | td[2]
    y = ((td[3] & 0x0F) << 8) | td[4]
    assert (x, y) == (512, 288)
