"""
Texas Instruments TWL4030 / TPS65950 Companion PMIC Model.
Emulates power management, battery ADC voltage monitoring, power rails, DC-IN sensing,
and RTC timekeeping subsystem (slave addresses 0x48, 0x49, 0x4A, 0x4B).
"""

from typing import Dict, Any, Optional
from emulator.devices.i2c import I2cSlave


class Twl4030Pmic(I2cSlave):
    """
    TI TWL4030 / TPS65950 Power Management IC.
    Controls VDD1/VDD2 regulators, MADC battery voltage conversions, and power supply detection.
    """

    # TWL4030 Register Map for Power & Battery Monitoring
    REG_VBUS_STATUS = 0x19       # DC-IN / USB VBUS power supply status
    REG_PROTECT_KEY = 0x44       # Write protection key register (STS_BOOT / Protect Key)
    REG_MADC_CTRL = 0x50         # Monitoring ADC control
    REG_MADC_VBAT_MSB = 0x60     # Battery Voltage ADC conversion MSB
    REG_MADC_VBAT_LSB = 0x61     # Battery Voltage ADC conversion LSB
    REG_POWER_STATUS = 0x80      # Power rails status (VDD1, VDD2, VPLL)
    REG_PBR_STATUS = 0x8A        # Physical power button status
    REG_RTC_SEC = 0x1C           # Real-Time Clock BCD seconds
    REG_RTC_MIN = 0x1D           # Real-Time Clock BCD minutes
    REG_RTC_HOUR = 0x1E          # Real-Time Clock BCD hours
    REG_RTC_DAY = 0x1F           # Real-Time Clock BCD days
    REG_RTC_MONTH = 0x20         # Real-Time Clock BCD months
    REG_RTC_YEAR = 0x21          # Real-Time Clock BCD years
    REG_RTC_WEEK = 0x22          # Real-Time Clock BCD weekday
    REG_RTC_CTRL = 0x29          # Real-Time Clock control
    REG_RTC_STATUS = 0x2A        # Real-Time Clock status (bit 7: RUN = 1)
    REG_CHARGER_CTRL = 0x3B      # Charger control register
    REG_CFG_BOOT = 0x3F          # Boot configuration register

    def __init__(self, address: int = 0x48):
        super().__init__(address)
        self.battery_voltage_mv: int = 14800  # 14.8V nominal (RED BRICK / DC IN)
        self.is_dc_in_connected: bool = True
        self.is_power_button_pressed: bool = False
        self.vdd1_mv: int = 1350              # VDD1 (MPU core @ 1 GHz: 1.35V)
        self.vdd2_mv: int = 1150              # VDD2 (Core/L3 interconnect: 1.15V)
        self._protect_key_step: int = 0
        self.registers: Dict[int, int] = {}
        self._init_registers()

    def _init_registers(self):
        """Initialize default TWL4030 power and RTC registers."""
        self.registers[self.REG_VBUS_STATUS] = 0x07 if self.is_dc_in_connected else 0x00
        self.registers[self.REG_POWER_STATUS] = 0x1F # VDD1, VDD2, VPLL, VAUX all active
        self.registers[self.REG_PBR_STATUS] = 0x00
        self.registers[self.REG_PROTECT_KEY] = 0x02  # Default Key 1 unlocked status
        self.registers[self.REG_CHARGER_CTRL] = 0x0A
        self.registers[self.REG_CFG_BOOT] = 0x00

        # TWL4030 RTC Subsystem:
        # 0x29 = RTC_CTRL_REG (default 0x40 latch enabled)
        # 0x2A = RTC_STATUS_REG (bit 7 RUN = 1 for firmware, bit 1 RUN = 1 for status check: 0x82)
        self.registers[self.REG_RTC_CTRL] = 0x40
        self.registers[self.REG_RTC_STATUS] = 0x82

        # BCD Time/Date: 2026-11-06 12:30:00 (Friday)
        self.registers[self.REG_RTC_SEC] = 0x00
        self.registers[self.REG_RTC_MIN] = 0x30
        self.registers[self.REG_RTC_HOUR] = 0x12
        self.registers[self.REG_RTC_DAY] = 0x06
        self.registers[self.REG_RTC_MONTH] = 0x11
        self.registers[self.REG_RTC_YEAR] = 0x26
        self.registers[self.REG_RTC_WEEK] = 0x05

        self._update_battery_adc_registers()

    def _update_battery_adc_registers(self):
        """Update 10-bit MADC battery voltage registers."""
        # Scale: 0..16000 mV maps to 0..1023 ADC steps
        adc_val = min(1023, int((self.battery_voltage_mv / 16000.0) * 1023))
        self.registers[self.REG_MADC_VBAT_MSB] = (adc_val >> 2) & 0xFF
        self.registers[self.REG_MADC_VBAT_LSB] = (adc_val & 0x03) << 6

    def set_battery_voltage(self, volts: float):
        """Set active battery voltage in volts (e.g. 14.8, 11.5)."""
        self.battery_voltage_mv = max(0, int(volts * 1000))
        self._update_battery_adc_registers()

    def get_battery_voltage(self) -> float:
        """Return active battery voltage in volts."""
        return self.battery_voltage_mv / 1000.0

    def set_dc_in(self, connected: bool):
        """Toggle DC IN external power supply state."""
        self.is_dc_in_connected = connected
        self.registers[self.REG_VBUS_STATUS] = 0x07 if connected else 0x00

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive PMIC status dictionary."""
        return {
            "battery_voltage_v": round(self.get_battery_voltage(), 1),
            "dc_in_connected": self.is_dc_in_connected,
            "vdd1_v": self.vdd1_mv / 1000.0,
            "vdd2_v": self.vdd2_mv / 1000.0,
            "power_rails_active": bool(self.registers.get(self.REG_POWER_STATUS, 0) & 0x01)
        }

    def read(self, reg_addr: int, length: int) -> bytes:
        """Handle I2C register read transaction."""
        out = bytearray()
        for i in range(length):
            curr_addr = (reg_addr + i) & 0xFF
            val = self.registers.get(curr_addr, 0x00)
            out.append(val)
        return bytes(out)

    def write(self, reg_addr: int, data: bytes) -> bool:
        """Handle I2C register write transaction."""
        for i, b in enumerate(data):
            curr_addr = (reg_addr + i) & 0xFF
            if curr_addr == self.REG_PROTECT_KEY:
                # TI TWL4030 Dual Protect Key unlock sequence
                if b == 0xC0:
                    self._protect_key_step = 1
                elif b == 0x0C and self._protect_key_step == 1:
                    self._protect_key_step = 2
                    self.registers[self.REG_PROTECT_KEY] = 0x02  # Key 1 unlocked (read status 0x02)
                elif b == 0x0E:
                    self._protect_key_step = 3
                elif b == 0xE0 and self._protect_key_step == 3:
                    self._protect_key_step = 4
                    self.registers[self.REG_PROTECT_KEY] = 0x01  # Key 2 unlocked (read status 0x01)
                else:
                    self._protect_key_step = 0
            elif curr_addr == self.REG_RTC_STATUS:
                # Bit 7 RUN and bit 1 RUN are preserved
                self.registers[curr_addr] = (b & 0x7D) | 0x82
            else:
                self.registers[curr_addr] = b

            if curr_addr == self.REG_VBUS_STATUS:
                self.is_dc_in_connected = bool(b & 0x01)
        return True
