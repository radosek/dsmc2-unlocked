"""
Atmel maXTouch Multi-Touch Controller Emulation (mXT) for RED DSMC2.
Implements the I2C multi-touch device at address 0x4B (and 0x4A).
Simulates object table, message processor (T5), and touch report generation (T9).
Also provides TWL4030 RTC/Power register fallback for shared physical bus address 0x4B.
"""

from typing import List, Optional
from collections import deque
from emulator.devices.i2c import I2cSlave
from emulator.devices.i2c_pmic import Twl4030Pmic


class MaXTouchDevice(I2cSlave):
    """
    Atmel maXTouch I2C Touch Controller.
    Addresses: 0x4B (primary RED Touch LCD), 0x4A (secondary).
    Shares physical I2C3 bus address 0x4B with the TWL4030 RTC/Power module.
    """

    def __init__(self, address: int = 0x4B, irq_callback: Optional[callable] = None):
        super().__init__(address)
        self.irq_callback = irq_callback
        self.pmic_fallback = Twl4030Pmic(address)

        # Object table layout for DSMC2 touch panels (1024x576)
        # Information block (Address 0x0000, 7 bytes)
        self.family_id = 0xA4
        self.variant_id = 0x01
        self.version = 0x10
        self.build = 0x01
        self.matrix_x_size = 16
        self.matrix_y_size = 10
        self.num_objects = 7

        # Message FIFO (Object T5). Bounded like the controller's on-chip FIFO so a
        # long drag can not grow host memory while the firmware is not draining it.
        self.message_queue = deque(maxlen=64)

        # Touch resolution
        self.max_x = 1024
        self.max_y = 576

        # Build initial register memory map (64KB address space)
        self.reg_map = bytearray(65536)
        self._init_object_table()

    def _init_object_table(self):
        """Construct the maXTouch information block and object table."""
        # Info block at 0x0000
        self.reg_map[0] = self.family_id
        self.reg_map[1] = self.variant_id
        self.reg_map[2] = self.version
        self.reg_map[3] = self.build
        self.reg_map[4] = self.matrix_x_size
        self.reg_map[5] = self.matrix_y_size
        self.reg_map[6] = self.num_objects

        # Object Table Entries (6 bytes each: type, start_pos_lsb, start_pos_msb, size, instances, num_report_ids)
        self.object_table = [
            # Type, StartAddr, Size, Instances, ReportIDs
            (5,  0x0030, 10, 1, 1),   # T5: Message Processor
            (6,  0x0040, 6,  1, 0),   # T6: Command Processor
            (7,  0x0050, 3,  1, 0),   # T7: Power Config
            (8,  0x0060, 10, 1, 0),   # T8: Acquisition Config
            (9,  0x0070, 31, 1, 10),  # T9: Touchscreen (10 fingers)
            (15, 0x00A0, 11, 1, 1),   # T15: Key Array
            (40, 0x00B0, 5,  1, 0),   # T40: High Definition Touch
        ]

        offset = 7
        for obj_type, start_addr, size, instances, report_ids in self.object_table:
            self.reg_map[offset + 0] = obj_type & 0xFF
            self.reg_map[offset + 1] = start_addr & 0xFF
            self.reg_map[offset + 2] = (start_addr >> 8) & 0xFF
            self.reg_map[offset + 3] = (size - 1) & 0xFF
            self.reg_map[offset + 4] = (instances - 1) & 0xFF
            self.reg_map[offset + 5] = report_ids & 0xFF
            offset += 6

    def inject_touch(self, x: int, y: int, pressed: bool, touch_id: int = 0):
        """
        Generate an authentic maXTouch T9 touch message and assert interrupt.
        x: 0..max_x
        y: 0..max_y
        pressed: True if down/move, False if release
        """
        clamped_x = max(0, min(x, self.max_x - 1))
        clamped_y = max(0, min(y, self.max_y - 1))

        # Status byte:
        # Bit 7: Detect, Bit 6: Press, Bit 5: Release, Bit 4: Move
        if pressed:
            status = 0xC0 # Detect | Press
        else:
            status = 0x20 # Release

        report_id = 1 + touch_id # Report ID for finger
        x_high = (clamped_x >> 2) & 0xFF
        y_high = (clamped_y >> 2) & 0xFF
        xy_low = ((clamped_x & 0x03) << 6) | ((clamped_y & 0x03) << 4) | 0x0A

        # T5 message packet: Report ID (1), Status (1), X_hi (1), Y_hi (1), XY_low (1), Area (1), Amp (1)
        msg = bytes([
            report_id,
            status,
            x_high,
            y_high,
            xy_low,
            0x05,       # Area
            0x80        # Amplitude
        ])

        self.message_queue.append(msg)
        if self.irq_callback:
            self.irq_callback()

    def read(self, reg_addr: int, length: int) -> bytes:
        # If reading T5 Message Processor buffer (0x0030)
        if 0x0030 <= reg_addr < 0x0040:
            if self.message_queue:
                msg = self.message_queue.popleft()
                # Pad or slice to requested length
                if len(msg) < length:
                    return msg + b"\xFF" * (length - len(msg))
                return msg[:length]
            return b"\xFF" * length # 0xFF indicates no more messages in queue

        # TWL4030 RTC/Power subsystem register handling
        if reg_addr in (0x44, 0x29, 0x2A, 0x3B, 0x3F, 0x45, 0x80) or (0x1C <= reg_addr <= 0x22):
            return self.pmic_fallback.read(reg_addr, length)

        # Standard register map read
        end = min(reg_addr + length, len(self.reg_map))
        data = bytes(self.reg_map[reg_addr:end])
        if len(data) < length:
            data += b"\x00" * (length - len(data))
        return data

    def write(self, reg_addr: int, data: bytes) -> bool:
        # Pass through to TWL4030 RTC/Power model
        self.pmic_fallback.write(reg_addr, data)

        end = min(reg_addr + len(data), len(self.reg_map))
        self.reg_map[reg_addr:end] = data
        return True
