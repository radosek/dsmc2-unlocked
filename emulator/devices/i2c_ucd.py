"""
Texas Instruments UCD9090 & UCD90160 PMBus Power Sequencer Models.

Proven against DSMC2 FW 7.4.1 drivers (`clean/ucd9090.c`, `clean/ucd90160.c`) and
`dsmc2-sdk/reference/UCD_REGISTER_MAP.md` + `POWER_RAIL_MAP.md`:
  - IOB  : TI UCD9090  (10 rails, pages 0..10 valid, 0x7C primary / 0x70 single-head alias)
  - ISP  : TI UCD9090  (10 rails, pages 0..10 valid, bus 2 0x70)
  - Sensor: TI UCD90160 (16 rails, pages 0..16 valid, bus 2 0x65)

Includes exact LINEAR16 / LINEAR11 PMBus codecs, offline page-limit discriminator
(`0x10` rejected by UCD9090 with STATUS_CML, accepted by UCD90160), and TI
MFR_GPO_SELECT (0xFA) / MFR_GPO_CONFIG (0xFB) bit-3 state readback.
"""

import math
import struct
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from emulator.devices.i2c import I2cSlave


def _sign_extend(val: int, bits: int) -> int:
    sign_bit = 1 << (bits - 1)
    return (val & (sign_bit - 1)) - (val & sign_bit)


def encode_linear16(volts: float, exp: int = -12) -> int:
    """Encode voltage in Volts into unsigned 16-bit LINEAR16 mantissa."""
    scale = 2.0 ** exp
    raw = int(round(float(volts) / scale))
    return max(0, min(0xFFFF, raw))


def decode_linear16(raw_u16: int, exp: int = -12) -> float:
    """Decode unsigned 16-bit LINEAR16 mantissa using signed 5-bit VOUT_MODE exponent."""
    return float(raw_u16 & 0xFFFF) * (2.0 ** exp)


def encode_linear11(value: float) -> int:
    """Encode floating-point value into TI PMBus LINEAR11 (5-bit E, 11-bit signed Y)."""
    val = float(value)
    if val == 0.0:
        return 0
    best_e = -16
    best_err = float("inf")
    best_word = 0
    for e in range(-16, 16):
        y = int(round(val / (2.0 ** e)))
        if -1024 <= y <= 1023:
            err = abs(y * (2.0 ** e) - val)
            if err < best_err:
                best_err = err
                best_e = e
                best_word = ((e & 0x1F) << 11) | (y & 0x7FF)
    return best_word & 0xFFFF


def decode_linear11(raw_u16: int) -> float:
    """Decode 16-bit TI PMBus LINEAR11 word."""
    w = raw_u16 & 0xFFFF
    y = _sign_extend(w & 0x7FF, 11)
    e = _sign_extend((w >> 11) & 0x1F, 5)
    return float(y) * (2.0 ** e)


@dataclass
class UcdRail:
    """Configuration & live telemetry for a single PMBus power rail (page)."""

    page: int
    name: str
    nominal_v: float
    measured_v: float
    uv_fault_v: float
    uv_warn_v: float
    ov_warn_v: float
    ov_fault_v: float
    ton_delay_ms: float
    ton_rise_ms: float = 2.0
    toff_delay_ms: float = 2.0
    operation: int = 0x80
    on_off_config: int = 0x1A
    vout_mode: int = 0x14  # 5-bit signed -12 -> 1 LSB = 2^-12 V
    status_vout: int = 0x00
    status_iout: int = 0x00
    status_temp: int = 0x00
    current_a: float = 0.5
    temp_c: float = 42.0

    @property
    def vout_exp(self) -> int:
        return _sign_extend(self.vout_mode & 0x1F, 5)


class UcdPowerSequencer(I2cSlave):
    """TI UCD9090 / UCD90160 Paged PMBus Power Sequencer I2C Slave."""

    # PMBus command codes (`ucd_regs.json`)
    CMD_PAGE = 0x00
    CMD_OPERATION = 0x01
    CMD_ON_OFF_CONFIG = 0x02
    CMD_VOUT_MODE = 0x20
    CMD_VOUT_COMMAND = 0x21
    CMD_VOUT_MARGIN_HIGH = 0x25
    CMD_VOUT_MARGIN_LOW = 0x26
    CMD_VOUT_OV_FAULT_LIMIT = 0x40
    CMD_VOUT_OV_WARN_LIMIT = 0x42
    CMD_VOUT_UV_WARN_LIMIT = 0x43
    CMD_VOUT_UV_FAULT_LIMIT = 0x44
    CMD_POWER_GOOD_ON = 0x5E
    CMD_POWER_GOOD_OFF = 0x5F
    CMD_TON_DELAY = 0x60
    CMD_TON_RISE = 0x61
    CMD_TON_MAX_FAULT_LIMIT = 0x62
    CMD_TOFF_DELAY = 0x64
    CMD_STATUS_BYTE = 0x78
    CMD_STATUS_WORD = 0x79
    CMD_STATUS_VOUT = 0x7A
    CMD_STATUS_IOUT = 0x7B
    CMD_STATUS_INPUT = 0x7C
    CMD_STATUS_TEMPERATURE = 0x7D
    CMD_STATUS_CML = 0x7E
    CMD_STATUS_MFR_SPECIFIC = 0x80
    CMD_READ_VIN = 0x88
    CMD_READ_VOUT = 0x8B
    CMD_READ_IOUT = 0x8C
    CMD_READ_TEMPERATURE_1 = 0x8D
    CMD_MFR_ID = 0x99
    CMD_MFR_MODEL = 0x9A
    CMD_MFR_REVISION = 0x9B
    CMD_MFR_GPO_SELECT = 0xFA
    CMD_MFR_GPO_CONFIG = 0xFB
    CMD_IC_DEVICE_ID = 0xFC
    CMD_IC_DEVICE_REV = 0xFD

    def __init__(
        self,
        address: int,
        model: str,
        max_page: int,
        rails: List[UcdRail],
        board_name: str = "",
        vin_v: float = 14.8,
    ):
        super().__init__(address)
        self.model = model
        self.max_page = max_page
        self.board_name = board_name or model
        self.rails: Dict[int, UcdRail] = {r.page: r for r in rails}
        self.current_page: int = 0
        self.vin_v: float = vin_v
        self.status_input: int = 0x00
        self.status_cml: int = 0x00
        self.status_mfr: int = 0x00
        self.gpo_select: int = 0
        self.gpo_configs: Dict[int, int] = {}

    def _active_rail(self) -> UcdRail:
        if self.current_page in self.rails:
            return self.rails[self.current_page]
        first_page = min(self.rails)
        return self.rails[first_page]

    def _rail_status_word(self, rail: UcdRail) -> int:
        word = 0x0000
        if (rail.operation & 0x80) == 0:
            word |= 0x0040  # OFF
        if rail.status_vout & 0x80:
            word |= 0x8020  # VOUT | VOUT_OV
        elif rail.status_vout:
            word |= 0x8000  # VOUT
        if rail.status_iout:
            word |= 0x4010  # IOUT | IOUT_OC
        if self.status_input:
            word |= 0x2000  # INPUT
        if rail.status_temp:
            word |= 0x0004  # TEMP
        if self.status_cml:
            word |= 0x0002  # CML
        if rail.status_vout or rail.status_iout or self.status_input or self.status_cml:
            word |= 0x0800  # POWER_GOOD# negated when fault present
        return word & 0xFFFF

    def read(self, reg_addr: int, length: int) -> bytes:
        cmd = reg_addr & 0xFF
        rail = self._active_rail()
        exp = rail.vout_exp

        # Block / ASCII identity commands
        if cmd == self.CMD_MFR_ID:
            raw = b"TI".ljust(max(length, 8), b"\x00")
            return raw[:length]
        if cmd == self.CMD_MFR_MODEL:
            raw = self.model.encode("ascii").ljust(max(length, 9), b"\x00")
            return raw[:length]
        if cmd == self.CMD_MFR_REVISION:
            raw = b"01".ljust(max(length, 2), b"\x00")
            return raw[:length]
        if cmd == self.CMD_IC_DEVICE_ID:
            raw = f"{self.model}-SYNTH".encode("ascii").ljust(max(length, 32), b"\x00")
            return raw[:length]
        if cmd == self.CMD_IC_DEVICE_REV:
            raw = b"REV-SYNTH".ljust(max(length, 32), b"\x00")
            return raw[:length]

        # Single-byte commands
        if cmd == self.CMD_PAGE:
            return bytes([self.current_page & 0xFF])[:length]
        if cmd == self.CMD_OPERATION:
            return bytes([rail.operation & 0xFF])[:length]
        if cmd == self.CMD_ON_OFF_CONFIG:
            return bytes([rail.on_off_config & 0xFF])[:length]
        if cmd == self.CMD_VOUT_MODE:
            return bytes([rail.vout_mode & 0xFF])[:length]
        if cmd == self.CMD_STATUS_VOUT:
            return bytes([rail.status_vout & 0xFF])[:length]
        if cmd == self.CMD_STATUS_IOUT:
            return bytes([rail.status_iout & 0xFF])[:length]
        if cmd == self.CMD_STATUS_INPUT:
            return bytes([self.status_input & 0xFF])[:length]
        if cmd == self.CMD_STATUS_TEMPERATURE:
            return bytes([rail.status_temp & 0xFF])[:length]
        if cmd == self.CMD_STATUS_CML:
            return bytes([self.status_cml & 0xFF])[:length]
        if cmd == self.CMD_STATUS_MFR_SPECIFIC:
            return bytes([self.status_mfr & 0xFF])[:length]
        if cmd == self.CMD_MFR_GPO_SELECT:
            return bytes([self.gpo_select & 0xFF])[:length]
        if cmd == self.CMD_MFR_GPO_CONFIG:
            val = self.gpo_configs.get(self.gpo_select, 0x03)
            return bytes([val & 0xFF])[:length]

        # Word (2-byte little-endian) commands
        word: Optional[int] = None
        if cmd == self.CMD_VOUT_COMMAND:
            word = encode_linear16(rail.nominal_v, exp)
        elif cmd == self.CMD_VOUT_MARGIN_HIGH:
            word = encode_linear16(rail.nominal_v * 1.03, exp)
        elif cmd == self.CMD_VOUT_MARGIN_LOW:
            word = encode_linear16(rail.nominal_v * 0.97, exp)
        elif cmd == self.CMD_VOUT_OV_FAULT_LIMIT:
            word = encode_linear16(rail.ov_fault_v, exp)
        elif cmd == self.CMD_VOUT_OV_WARN_LIMIT:
            word = encode_linear16(rail.ov_warn_v, exp)
        elif cmd == self.CMD_VOUT_UV_WARN_LIMIT:
            word = encode_linear16(rail.uv_warn_v, exp)
        elif cmd == self.CMD_VOUT_UV_FAULT_LIMIT:
            word = encode_linear16(rail.uv_fault_v, exp)
        elif cmd == self.CMD_POWER_GOOD_ON:
            word = encode_linear16(rail.nominal_v * 0.93, exp)
        elif cmd == self.CMD_POWER_GOOD_OFF:
            word = encode_linear16(rail.nominal_v * 0.90, exp)
        elif cmd == self.CMD_TON_DELAY:
            word = encode_linear11(rail.ton_delay_ms)
        elif cmd == self.CMD_TON_RISE:
            word = encode_linear11(rail.ton_rise_ms)
        elif cmd == self.CMD_TON_MAX_FAULT_LIMIT:
            word = encode_linear11(max(rail.ton_rise_ms * 4.0, 20.0))
        elif cmd == self.CMD_TOFF_DELAY:
            word = encode_linear11(rail.toff_delay_ms)
        elif cmd == self.CMD_STATUS_BYTE:
            sw = self._rail_status_word(rail)
            return bytes([sw & 0xFF])[:length]
        elif cmd == self.CMD_STATUS_WORD:
            word = self._rail_status_word(rail)
        elif cmd == self.CMD_READ_VIN:
            word = encode_linear11(self.vin_v)
        elif cmd == self.CMD_READ_VOUT:
            word = encode_linear16(rail.measured_v, exp)
        elif cmd == self.CMD_READ_IOUT:
            word = encode_linear11(rail.current_a)
        elif cmd == self.CMD_READ_TEMPERATURE_1:
            word = encode_linear11(rail.temp_c)

        if word is not None:
            packed = struct.pack("<H", word & 0xFFFF)
            return packed.ljust(length, b"\x00")[:length]

        return b"\x00" * length

    def write(self, reg_addr: int, data: bytes) -> bool:
        if not data:
            return True
        cmd = reg_addr & 0xFF

        if cmd == self.CMD_PAGE:
            page = data[0] & 0xFF
            if page <= self.max_page or page == 0xFF:
                self.current_page = page
                return True
            # Reject invalid page (UCD9090 vs UCD90160 discriminator) & set CML INVALID DATA
            self.status_cml |= 0x40
            return False

        if cmd == self.CMD_OPERATION:
            self._active_rail().operation = data[0] & 0xFF
            return True

        if cmd == self.CMD_MFR_GPO_SELECT:
            self.gpo_select = data[0] & 0xFF
            return True

        if cmd == self.CMD_MFR_GPO_CONFIG:
            cfg = data[0] & 0xFF
            # Drive (0x07) sets GPO state readback bit 3 (0x08); tri-state (0x03) clears it
            if (cfg & 0x07) == 0x07:
                cfg |= 0x08
            elif (cfg & 0x07) == 0x03:
                cfg &= ~0x08
            self.gpo_configs[self.gpo_select] = cfg
            return True

        if cmd == self.CMD_VOUT_COMMAND and len(data) >= 2:
            raw = struct.unpack("<H", data[:2])[0]
            rail = self._active_rail()
            rail.nominal_v = decode_linear16(raw, rail.vout_exp)
            return True

        if cmd == self.CMD_STATUS_CML:
            # W1C clear
            self.status_cml &= ~(data[0] & 0xFF)
            return True

        return True

    # ---- Diagnostic & Fault Injection Helpers ----

    def inject_uv_fault(self, page: int = 0, drop_volts: float = 0.2):
        """Force an under-voltage fault on the target rail."""
        rail = self.rails.get(page, self._active_rail())
        rail.measured_v = max(0.0, rail.uv_fault_v - abs(drop_volts))
        rail.status_vout |= 0x30  # UV_WARN (b5) | UV_FAULT (b4)

    def inject_ov_fault(self, page: int = 0, spike_volts: Optional[float] = None):
        """Force an over-voltage fault on the target rail."""
        rail = self.rails.get(page, self._active_rail())
        rail.measured_v = spike_volts if spike_volts is not None else rail.ov_fault_v + 0.15
        rail.status_vout |= 0xC0  # OV_FAULT (b7) | OV_WARN (b6)

    def clear_faults(self):
        self.status_input = 0x00
        self.status_cml = 0x00
        self.status_mfr = 0x00
        for r in self.rails.values():
            r.measured_v = r.nominal_v
            r.status_vout = 0x00
            r.status_iout = 0x00
            r.status_temp = 0x00

    def get_status(self) -> Dict[str, Any]:
        return {
            "board": self.board_name,
            "model": self.model,
            "address": f"0x{self.address:02X}",
            "current_page": self.current_page,
            "max_page": self.max_page,
            "vin_v": self.vin_v,
            "status_cml": f"0x{self.status_cml:02X}",
            "rails": [
                {
                    "page": r.page,
                    "name": r.name,
                    "nominal_v": r.nominal_v,
                    "measured_v": r.measured_v,
                    "ton_delay_ms": r.ton_delay_ms,
                    "status_vout": f"0x{r.status_vout:02X}",
                }
                for r in sorted(self.rails.values(), key=lambda x: x.page)
            ],
        }


def _make_rail(page: int, name: str, nominal_v: float, ton_ms: float) -> UcdRail:
    return UcdRail(
        page=page,
        name=name,
        nominal_v=nominal_v,
        measured_v=nominal_v,
        uv_fault_v=round(nominal_v * 0.90, 4),
        uv_warn_v=round(nominal_v * 0.93, 4),
        ov_warn_v=round(nominal_v * 1.07, 4),
        ov_fault_v=round(nominal_v * 1.10, 4),
        ton_delay_ms=ton_ms,
    )


def make_iob_ucd9090(address: int = 0x7C) -> UcdPowerSequencer:
    """IOB UCD9090 (10 rails: pages 0..9 + spare page 10 max)."""
    specs = [
        (0, "IOB_3V3", 3.30, 1.0),
        (1, "IOB_2V5", 2.50, 2.0),
        (2, "IOB_1V8", 1.80, 3.0),
        (3, "IOB_DDR_1V5", 1.50, 4.0),
        (4, "IOB_CORE_1V0", 1.00, 5.0),
        (5, "IOB_SATA_1V2", 1.20, 6.0),
        (6, "IOB_HDMI_3V3", 3.30, 7.0),
        (7, "IOB_PHY_1V2", 1.20, 8.0),
        (8, "IOB_VREF_0V75", 0.75, 9.0),
        (9, "IOB_AUX_5V0", 5.00, 10.0),
    ]
    return UcdPowerSequencer(
        address=address,
        model="UCD9090",
        max_page=10,
        rails=[_make_rail(p, n, v, t) for p, n, v, t in specs],
        board_name="IOB",
    )


def make_isp_ucd9090(address: int = 0x70) -> UcdPowerSequencer:
    """ISP UCD9090 (values aligned to live_isp_power.txt: core 0.91V, Vref 0.75V, Vtt 0.74V)."""
    specs = [
        (0, "ISP_CORE_0V9", 0.91, 1.0),
        (1, "ISP_VREF_0V75", 0.75, 2.0),
        (2, "ISP_VTT_0V74", 0.74, 3.0),
        (3, "ISP_DDR_1V5", 1.50, 4.0),
        (4, "ISP_IO_1V8", 1.80, 5.0),
        (5, "ISP_PLL_2V5", 2.50, 6.0),
        (6, "ISP_SYS_3V3", 3.30, 7.0),
        (7, "ISP_VDDA_2V5", 2.50, 8.0),
        (8, "ISP_X12_1V2", 1.20, 9.0),
        (9, "ISP_XAUI_1V0", 1.00, 10.0),
    ]
    return UcdPowerSequencer(
        address=address,
        model="UCD9090",
        max_page=10,
        rails=[_make_rail(p, n, v, t) for p, n, v, t in specs],
        board_name="ISP",
    )


def make_sensor_ucd90160(address: int = 0x65) -> UcdPowerSequencer:
    """Sensor UCD90160 (16 rails: page 3 = SENSOR_VAA monitored by ucd90160_monitor_sensor_vaa)."""
    specs = [
        (0, "SNS_1V8", 1.80, 1.0),
        (1, "SNS_2V8", 2.80, 2.0),
        (2, "SNS_3V3", 3.30, 3.0),
        (3, "SENSOR_VAA", 3.30, 4.0),
        (4, "SENSOR_VDD", 1.20, 5.0),
        (5, "DRAGON_CORE", 1.00, 6.0),
        (6, "S35_1", 1.50, 7.0),
        (7, "S35_2", 1.50, 8.0),
        (8, "SNS_VTX_3V3", 3.30, 9.0),
        (9, "SNS_VPIX_2V8", 2.80, 10.0),
        (10, "SNS_ADC_1V8", 1.80, 11.0),
        (11, "SNS_PLL_1V2", 1.20, 12.0),
        (12, "SNS_LVDS_2V5", 2.50, 13.0),
        (13, "SNS_BIAS_3V3", 3.30, 14.0),
        (14, "SNS_VREF_1V5", 1.50, 15.0),
        (15, "SNS_AUX_5V0", 5.00, 16.0),
    ]
    return UcdPowerSequencer(
        address=address,
        model="UCD90160",
        max_page=16,
        rails=[_make_rail(p, n, v, t) for p, n, v, t in specs],
        board_name="Sensor",
    )
