"""
Texas Instruments TMP411 Dual-Channel Digital Temperature Sensor Model.
Monitors camera BRAIN ambient temperature (local) and RED DRAGON/HELIUM sensor die temperature (remote).
Connected to OMAP3630 I2C1 (slave address 0x4C).
"""

from typing import Dict, Tuple, Any
from emulator.devices.i2c import I2cSlave


class Tmp411Thermal(I2cSlave):
    """
    TI TMP411 Digital Temperature Monitor.
    Drives the T/E (Temperature/Exposure) status and calibration metrics on the RED monitor.
    """

    # TMP411 Register Map
    REG_LOCAL_TEMP_MSB = 0x00      # BRAIN Core Temperature Integer Part (°C)
    REG_REMOTE_TEMP_MSB = 0x01     # Sensor Die Temperature Integer Part (°C)
    REG_STATUS = 0x02              # Thermal limits & diode fault status
    REG_CONFIG_READ = 0x03         # Configuration read register
    REG_CONV_RATE = 0x04           # Conversion rate register
    REG_REMOTE_TEMP_LSB = 0x10     # Sensor Die Fractional Temperature (0.0625°C resolution)
    REG_LOCAL_TEMP_LSB = 0x15      # BRAIN Core Fractional Temperature
    REG_DEVICE_ID = 0xFD           # TI Manufacturer ID (0x41)
    REG_CHIP_REV = 0xFF            # TMP411 Revision ID (0x11)

    def __init__(self, address: int = 0x4C):
        super().__init__(address)
        # Default operational cinema temperatures
        self.sensor_temp_c: float = 39.0   # Remote sensor die: 39°C
        self.brain_temp_c: float = 63.0    # Local BRAIN core: 63°C
        self.calibrated_target_temp: float = 39.0
        self.registers: Dict[int, int] = {}
        self._init_registers()

    def _init_registers(self):
        """Populate initial TMP411 registers."""
        self.registers[self.REG_STATUS] = 0x00
        self.registers[self.REG_CONFIG_READ] = 0x00
        self.registers[self.REG_CONV_RATE] = 0x07  # 4 conversions / sec
        self.registers[self.REG_DEVICE_ID] = 0x41  # 'A' (TI)
        self.registers[self.REG_CHIP_REV] = 0x11
        self._update_temp_registers()

    def _update_temp_registers(self):
        """Update integer and fractional temperature registers."""
        # Remote (Sensor)
        s_int = int(self.sensor_temp_c)
        s_frac = int((self.sensor_temp_c - s_int) * 16) & 0x0F
        self.registers[self.REG_REMOTE_TEMP_MSB] = s_int & 0xFF
        self.registers[self.REG_REMOTE_TEMP_LSB] = (s_frac << 4) & 0xF0

        # Local (BRAIN Core)
        b_int = int(self.brain_temp_c)
        b_frac = int((self.brain_temp_c - b_int) * 16) & 0x0F
        self.registers[self.REG_LOCAL_TEMP_MSB] = b_int & 0xFF
        self.registers[self.REG_LOCAL_TEMP_LSB] = (b_frac << 4) & 0xF0

    def set_temperatures(self, sensor_c: float, brain_c: float):
        """Set active temperatures for sensor die and BRAIN core."""
        self.sensor_temp_c = float(sensor_c)
        self.brain_temp_c = float(brain_c)
        self._update_temp_registers()

    def get_temperatures(self) -> Tuple[float, float]:
        """Return (sensor_die_temp_c, brain_core_temp_c)."""
        return (self.sensor_temp_c, self.brain_temp_c)

    def is_calibrated_temperature(self) -> bool:
        """Check if sensor temperature is within black shading calibration tolerance (±2°C)."""
        return abs(self.sensor_temp_c - self.calibrated_target_temp) <= 2.5

    def get_status_str(self) -> str:
        """Return formatted string matching RED LCD HUD (e.g. '39°/63°')."""
        return f"{int(self.sensor_temp_c)}°/{int(self.brain_temp_c)}°"

    def read(self, reg_addr: int, length: int) -> bytes:
        """Handle I2C register read."""
        out = bytearray()
        for i in range(length):
            curr_addr = (reg_addr + i) & 0xFF
            out.append(self.registers.get(curr_addr, 0x00))
        return bytes(out)

    def write(self, reg_addr: int, data: bytes) -> bool:
        """Handle I2C register write."""
        for i, b in enumerate(data):
            curr_addr = (reg_addr + i) & 0xFF
            self.registers[curr_addr] = b
        return True
