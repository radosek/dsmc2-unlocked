"""
Confirmed RED DSMC2 I2C Peripheral Chip Models (`dsmc2-sdk/reference/I2C_DEVICE_MAP.md`).

Includes:
  - `Si5346ClockSynth` (0x6C): Silicon Labs Si5346 ISP jitter-attenuating clock synthesizer
  - `Dac7578SensorDac` (0x49, 0x4B): TI DAC7578 8-channel 12-bit sensor bias DAC
  - `FocalTechTouch` (0x3E): FocalTech FT5x06 RED Touch 7.0 capacitive touch controller
  - `FixedIdI2cDevice`: scan-verified auxiliary I2C peripherals (LSB Temp 0x55, Video Clk 0xC0,
    IOB Audio Codec 0x0C, RSB Fan/OLPF, LCD7 GPIO Expander)
"""

from typing import Dict, Any, List
from emulator.devices.i2c import I2cSlave


class Si5346ClockSynth(I2cSlave):
    """
    Silicon Labs Si5346 ISP Jitter-Attenuating Clock Synthesizer (addr 0x6C).
    Paged register space (`0x01 PAGE`); Page 0 `0x02..0x03` holds DEVICE_ID (`0x46, 0x53`).
    """

    REG_PAGE = 0x01
    REG_DEVICE_ID_LO = 0x02
    REG_DEVICE_ID_HI = 0x03
    REG_STATUS = 0x0C

    def __init__(self, address: int = 0x6C):
        super().__init__(address)
        self.page: int = 0x00
        self.pages: Dict[int, Dict[int, int]] = {
            0x00: {
                self.REG_DEVICE_ID_LO: 0x46,
                self.REG_DEVICE_ID_HI: 0x53,
                self.REG_STATUS: 0x00,  # PLLs locked, zero LOS/OOF alarms
            }
        }

    def read(self, reg_addr: int, length: int) -> bytes:
        out = bytearray()
        for i in range(length):
            r = (reg_addr + i) & 0xFF
            if r == self.REG_PAGE:
                out.append(self.page & 0xFF)
            else:
                out.append(self.pages.get(self.page, {}).get(r, 0x00))
        return bytes(out)

    def write(self, reg_addr: int, data: bytes) -> bool:
        for i, b in enumerate(data):
            r = (reg_addr + i) & 0xFF
            if r == self.REG_PAGE:
                self.page = b & 0xFF
            else:
                self.pages.setdefault(self.page, {})[r] = b & 0xFF
        return True


class Dac7578SensorDac(I2cSlave):
    """
    TI DAC7578 8-Channel 12-bit Sensor Bias/Reference DAC (addrs 0x49, 0x4B).
    Channel write registers 0x00..0x07 store 12-bit left-justified words `[MSB, LSB]`.
    """

    def __init__(self, address: int = 0x49):
        super().__init__(address)
        self.channels: List[int] = [0x0800] * 8  # Midscale 12-bit default
        self.registers: Dict[int, int] = {}

    def get_channel_code(self, ch: int) -> int:
        if not (0 <= ch < 8):
            raise ValueError(f"DAC7578 channel {ch} out of range 0..7")
        return self.channels[ch] & 0x0FFF

    def read(self, reg_addr: int, length: int) -> bytes:
        cmd = reg_addr & 0xFF
        ch = cmd & 0x07
        if (cmd & 0xF0) in (0x00, 0x10, 0x20, 0x30) and length >= 2:
            raw16 = (self.channels[ch] & 0x0FFF) << 4
            word = bytes([(raw16 >> 8) & 0xFF, raw16 & 0xFF])
            return word.ljust(length, b"\x00")[:length]
        return bytes(self.registers.get((reg_addr + i) & 0xFF, 0x00) for i in range(length))

    def write(self, reg_addr: int, data: bytes) -> bool:
        cmd = reg_addr & 0xFF
        ch = cmd & 0x07
        if (cmd & 0xF0) in (0x00, 0x10, 0x20, 0x30) and len(data) >= 2:
            raw16 = ((data[0] & 0xFF) << 8) | (data[1] & 0xFF)
            self.channels[ch] = (raw16 >> 4) & 0x0FFF
            return True
        for i, b in enumerate(data):
            self.registers[(reg_addr + i) & 0xFF] = b & 0xFF
        return True


class FocalTechTouch(I2cSlave):
    """
    FocalTech FT5x06 RED Touch 7.0 Capacitive Touch Controller (addr 0x3E).
    Confirmed registers: `0x00 DEV_MODE`, `0x02 TD_STATUS`, `0x03..0x06 P1_XY`,
    `0xA3 CHIP_ID = 0x55`, `0xA6 FIRMWARE_ID = 0x01`.
    """

    REG_DEV_MODE = 0x00
    REG_TD_STATUS = 0x02
    REG_P1_XH = 0x03
    REG_P1_XL = 0x04
    REG_P1_YH = 0x05
    REG_P1_YL = 0x06
    REG_CHIP_ID = 0xA3
    REG_FIRMWARE_ID = 0xA6

    def __init__(self, address: int = 0x3E):
        super().__init__(address)
        self.registers: Dict[int, int] = {
            self.REG_DEV_MODE: 0x00,
            self.REG_TD_STATUS: 0x00,
            self.REG_P1_XH: 0x00,
            self.REG_P1_XL: 0x00,
            self.REG_P1_YH: 0x00,
            self.REG_P1_YL: 0x00,
            self.REG_CHIP_ID: 0x55,
            self.REG_FIRMWARE_ID: 0x01,
        }

    def inject_touch(self, x: int, y: int, pressed: bool = True):
        x_clamped = max(0, min(0x0FFF, int(x)))
        y_clamped = max(0, min(0x0FFF, int(y)))
        if pressed:
            self.registers[self.REG_TD_STATUS] = 0x01
            self.registers[self.REG_P1_XH] = (0x00 << 6) | ((x_clamped >> 8) & 0x0F)
            self.registers[self.REG_P1_XL] = x_clamped & 0xFF
            self.registers[self.REG_P1_YH] = (y_clamped >> 8) & 0x0F
            self.registers[self.REG_P1_YL] = y_clamped & 0xFF
        else:
            self.registers[self.REG_TD_STATUS] = 0x00
            self.registers[self.REG_P1_XH] = 0x40  # Lift-up event

    def read(self, reg_addr: int, length: int) -> bytes:
        return bytes(self.registers.get((reg_addr + i) & 0xFF, 0x00) for i in range(length))

    def write(self, reg_addr: int, data: bytes) -> bool:
        for i, b in enumerate(data):
            self.registers[(reg_addr + i) & 0xFF] = b & 0xFF
        return True


class FixedIdI2cDevice(I2cSlave):
    """Generic DSMC2 I2C peripheral with verified presence / scan ID at register 0."""

    def __init__(self, address: int, name: str, device_id: int = 0x00):
        super().__init__(address)
        self.name = name
        self.registers: Dict[int, int] = {0x00: device_id & 0xFF}

    def read(self, reg_addr: int, length: int) -> bytes:
        return bytes(self.registers.get((reg_addr + i) & 0xFF, 0x00) for i in range(length))

    def write(self, reg_addr: int, data: bytes) -> bool:
        for i, b in enumerate(data):
            self.registers[(reg_addr + i) & 0xFF] = b & 0xFF
        return True
