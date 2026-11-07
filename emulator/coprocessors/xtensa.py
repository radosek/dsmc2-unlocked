"""
Tensilica Xtensa 32-bit Coprocessor Architecture & Coprocessor Subsystems.
Models IOB0 (SATA, HDMI, Accelerometer), IOB1 (Sensor Calibration & Defect Tables),
and ISP1/ISP2 (Wavelet REDCODE compression and DDR training).
"""

import os
import math
import zlib
import struct
from typing import Dict, Any, List, Optional, Tuple


class XtensaCore:
    """
    32-bit Tensilica Xtensa LX Coprocessor Core.
    IRAM: 0x40000000, DRAM: 0x3FFE0000.
    """

    IRAM_BASE = 0x40000000
    DRAM_BASE = 0x3FFE0000
    IRAM_SIZE = 64 * 1024
    DRAM_SIZE = 64 * 1024

    STATE_UNINITIALIZED = "UNINITIALIZED"
    STATE_READY = "READY"
    STATE_RUNNING = "RUNNING"
    STATE_IDLE = "IDLE"
    STATE_HALTED = "HALTED"

    def __init__(self, name: str, core_id: int):
        self.name = name
        self.core_id = core_id
        self.state = self.STATE_UNINITIALIZED

        # Register File: a0..a15 (Windowed registers)
        self.regs = [0] * 16
        self.pc = self.IRAM_BASE
        self.ps = 0x00000020  # User/Supervisor mode, IRQ enabled
        self.sar = 0
        self.litbase = 0

        # Memory Buffers
        self.iram = bytearray(self.IRAM_SIZE)
        self.dram = bytearray(self.DRAM_SIZE)

        self.cycles_executed = 0
        self.instructions_executed = 0

    def load_binaries(self, iram_path: str, dram_path: Optional[str] = None) -> bool:
        """Load firmware binaries into IRAM and DRAM."""
        if os.path.exists(iram_path):
            with open(iram_path, "rb") as f:
                data = f.read()
            size = min(len(data), self.IRAM_SIZE)
            self.iram[:size] = data[:size]
            self.state = self.STATE_READY
            self.pc = self.IRAM_BASE

        if dram_path and os.path.exists(dram_path):
            with open(dram_path, "rb") as f:
                data = f.read()
            size = min(len(data), self.DRAM_SIZE)
            self.dram[:size] = data[:size]

        return self.state == self.STATE_READY

    def step(self, count: int = 1):
        """Simulate execution of instruction cycles."""
        if self.state in (self.STATE_READY, self.STATE_IDLE, self.STATE_RUNNING):
            self.state = self.STATE_RUNNING
            self.instructions_executed += count
            self.cycles_executed += count * 2
            self.pc = self.IRAM_BASE + ((self.pc - self.IRAM_BASE + count * 3) % self.IRAM_SIZE)

    def handle_c2c_word(self, word: int) -> Optional[int]:
        """Process incoming 32-bit C2C mailbox word. Default echo with ACK."""
        return (word ^ 0xA5A50000) & 0xFFFFFFFF

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Process structured C2C command packet."""
        return [0x00000000] # Default Success ACK

    def get_status(self) -> Dict[str, Any]:
        """Return core status."""
        return {
            "name": self.name,
            "core_id": self.core_id,
            "state": self.state,
            "pc": f"0x{self.pc:08X}",
            "instructions": self.instructions_executed,
            "cycles": self.cycles_executed,
            "iram_loaded": any(self.iram),
            "dram_loaded": any(self.dram)
        }


class Iob0Coprocessor(XtensaCore):
    """
    IOB0 Coprocessor (Input/Output Bridge 0).
    Controls SATA 3.0 HBA storage link, HDMI transmitter, and STACCELERO SPI accelerometer.
    """

    def __init__(self):
        super().__init__("IOB0", 0)

        # 1. SATA 3.0 HBA Subsystem
        self.sata_link_speed_gbps = 6.0   # SATA 3.0 (6 Gbps)
        self.sata_link_up = True
        self.sata_port_cmd = 0x00010001   # Start & Active
        self.sata_dma_frames_written = 0
        self.sata_bytes_transferred = 0

        # 2. HDMI 1080p Video Transmitter
        self.hdmi_connected = True
        self.hdmi_resolution = (1920, 1080)
        self.hdmi_fps = 60.0
        self.hdmi_hdcp_authenticated = True
        self.hdmi_mode = "CLEAN"  # Options: "CLEAN", "BROADCAST_TALLY", "FRAME_GUIDES"
        self.hdmi_frames_rendered = 0

        # 3. STACCELERO SPI Accelerometer
        self.accel_x = 0.02
        self.accel_y = 0.01
        self.accel_z = 0.98

    def set_accelerometer(self, x: float, y: float, z: float):
        """Set accelerometer force vector in g-force."""
        self.accel_x = float(x)
        self.accel_y = float(y)
        self.accel_z = float(z)

    def get_tilt_angles(self) -> Tuple[float, float, bool]:
        """
        Return (pitch_deg, roll_deg, is_level).
        Feeds the RedUi horizon level assist.
        """
        pitch = math.atan2(self.accel_y, math.sqrt(self.accel_x**2 + self.accel_z**2)) * (180.0 / math.pi)
        roll = math.atan2(-self.accel_x, self.accel_z) * (180.0 / math.pi)
        is_level = abs(pitch) < 1.0 and abs(roll) < 1.0
        return (round(pitch, 1), round(roll, 1), is_level)

    def record_frame_dma(self, frame_size_bytes: int):
        """Simulate high-speed SATA DMA frame write to RED MINI-MAG."""
        self.sata_dma_frames_written += 1
        self.sata_bytes_transferred += frame_size_bytes
        self.step(50)

    def set_hdmi_mode(self, mode: str):
        """Set HDMI output overlay mode: 'CLEAN', 'BROADCAST_TALLY', or 'FRAME_GUIDES'."""
        m = mode.strip().upper()
        if m in ("CLEAN", "BROADCAST_TALLY", "FRAME_GUIDES"):
            self.hdmi_mode = m

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Handle C2C storage or display commands."""
        if cmd == 0x10: # Query SATA Status
            return [0x01 if self.sata_link_up else 0x00, self.sata_dma_frames_written]
        elif cmd == 0x20: # Query Tilt
            pitch, roll, level = self.get_tilt_angles()
            return [int(pitch * 10), int(roll * 10), 1 if level else 0]
        elif cmd == 0x26: # Monitor Pipeline Config
            mode_flag = payload[1] if len(payload) > 1 else 0
            if mode_flag == 1:
                self.hdmi_mode = "BROADCAST_TALLY"
            elif mode_flag == 2:
                self.hdmi_mode = "FRAME_GUIDES"
            else:
                self.hdmi_mode = "CLEAN"
            return [0x00000000]
        return [0x00]

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        pitch, roll, level = self.get_tilt_angles()
        base.update({
            "sata": {
                "link_up": self.sata_link_up,
                "speed_gbps": self.sata_link_speed_gbps,
                "frames_written": self.sata_dma_frames_written,
                "mb_transferred": round(self.sata_bytes_transferred / (1024 * 1024), 2)
            },
            "hdmi": {
                "connected": self.hdmi_connected,
                "resolution": f"{self.hdmi_resolution[0]}x{self.hdmi_resolution[1]} @ {int(self.hdmi_fps)}Hz",
                "hdcp": self.hdmi_hdcp_authenticated,
                "mode": self.hdmi_mode,
                "frames_rendered": self.hdmi_frames_rendered
            },
            "accelerometer": {
                "pitch_deg": pitch,
                "roll_deg": roll,
                "is_level": level,
                "vector": [round(self.accel_x, 2), round(self.accel_y, 2), round(self.accel_z, 2)]
            }
        })
        return base


class Iob1Coprocessor(XtensaCore):
    """
    IOB1 Coprocessor (Sensor Calibration Engine).
    Executes black shading dark-level calibration, defect pixel table lookups, and Bayer green alignment.
    """

    def __init__(self):
        super().__init__("IOB1", 1)

        # Calibration state
        self.is_calibrating = False
        self.cal_progress = 1.0
        self.calibrated_temp_c = 39.0
        self.calibrated_exposure = "1/48"
        self.cal_map_count = 3

        # Defect pixel defect maps (Factory & User)
        self.factory_defects: List[Tuple[int, int]] = [(1024, 768), (2048, 1152), (3072, 1536)]
        self.user_defects: List[Tuple[int, int]] = []
        self.pixels_corrected_total = 0

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Handle C2C calibration and defect table commands."""
        if cmd == 0x30 or cmd == 0x31:
            return [0x00000000]
        return [0x00000000]

    def run_black_shading(self, sensor_temp_c: float = 39.0, exposure: str = "1/48") -> Dict[str, Any]:
        """
        Execute full sensor dark-level calibration.
        Analyzes dark current slope and generates calibration map.
        """
        self.is_calibrating = True
        self.cal_progress = 0.0
        self.step(1500)

        # Discover 2 user hot pixels during thermal analyze_slope
        self.user_defects = [(1536, 920), (2800, 1400)]
        self.calibrated_temp_c = sensor_temp_c
        self.calibrated_exposure = exposure
        self.cal_progress = 1.0
        self.is_calibrating = False

        return {
            "status": "CALIBRATED",
            "target_temp_c": self.calibrated_temp_c,
            "target_exposure": self.calibrated_exposure,
            "defects_masked": len(self.factory_defects) + len(self.user_defects),
            "cal_map": f"cal_{int(sensor_temp_c)}c_exp{exposure.replace('/', '_')}.cal"
        }

    def process_sensor_frame(self, width: int, height: int) -> int:
        """Simulate real-time defective pixel replacement and Bayer green alignment."""
        total_defects = len(self.factory_defects) + len(self.user_defects)
        self.pixels_corrected_total += total_defects
        self.step(100)
        return total_defects

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        if cmd == 0x30: # Trigger Black Shading
            t_c = payload[0] if payload else 39
            res = self.run_black_shading(float(t_c))
            return [0x01, res["defects_masked"]]
        return [0x00]

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "black_shading": {
                "calibrated": not self.is_calibrating,
                "target_temp_c": self.calibrated_temp_c,
                "target_exposure": self.calibrated_exposure,
                "progress": self.cal_progress
            },
            "defect_tables": {
                "factory_defects": len(self.factory_defects),
                "user_defects": len(self.user_defects),
                "pixels_corrected": self.pixels_corrected_total
            }
        })
        return base


class IspCoprocessor(XtensaCore):
    """
    Image Signal Processor (ISP1 & ISP2).
    Dual high-performance coprocessors executing REDCODE Discrete Wavelet Transform (DWT),
    component sub-band slicing (G1/B/R/G2), and DDR self-training.
    """

    def __init__(self, core_id: int = 2):
        name = f"ISP{core_id - 1}"
        super().__init__(name, core_id)

        self.ddr_training_passed = True
        self.wavelet_compression_ratio = "8:1"
        self.frames_compressed = 0
        self.wavelet_dwt_levels = 3

    def compress_frame(self, raw_bytes: bytes, ratio: str = "8:1") -> Dict[str, Any]:
        """
        Simulate REDCODE Discrete Wavelet Transform compression.
        Splits Bayer raw data into 4 sub-bands (G1, B, R, G2) and generates CRC32.
        """
        self.wavelet_compression_ratio = ratio
        ratio_int = int(ratio.split(":")[0]) if ":" in ratio else 8
        compressed_size = max(64, len(raw_bytes) // ratio_int)

        # Component slice sub-bands
        slice_crcs = {
            "G1": zlib.crc32(b"G1" + raw_bytes[:100]) & 0xFFFFFFFF,
            "B": zlib.crc32(b"B" + raw_bytes[100:200]) & 0xFFFFFFFF,
            "R": zlib.crc32(b"R" + raw_bytes[200:300]) & 0xFFFFFFFF,
            "G2": zlib.crc32(b"G2" + raw_bytes[300:400]) & 0xFFFFFFFF,
        }

        self.frames_compressed += 1
        self.step(200)

        return {
            "compressed_size_bytes": compressed_size,
            "ratio": ratio,
            "dwt_levels": self.wavelet_dwt_levels,
            "slice_crcs": slice_crcs,
            "crc32": zlib.crc32(raw_bytes[:compressed_size]) & 0xFFFFFFFF
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "ddr_training": "PASS (Modified SCL V2)",
            "compression_ratio": self.wavelet_compression_ratio,
            "frames_compressed": self.frames_compressed,
            "dwt_levels": self.wavelet_dwt_levels
        })
        return base
