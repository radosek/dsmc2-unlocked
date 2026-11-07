"""
I2C EDID EEPROM Emulation for RED DSMC2 Monitors.
Implements the 24C02 EEPROM at I2C address 0x50 with authentic RED Touch 7.0 EDID.
"""

from emulator.devices.i2c import I2cSlave


def create_red_touch_edid() -> bytes:
    """Generate a standard 128-byte VESA EDID 1.3 block for RED TOUCH 7.0."""
    edid = bytearray(128)

    # 0x00 - 0x07: Fixed Header
    edid[0:8] = b"\x00\xFF\xFF\xFF\xFF\xFF\xFF\x00"

    # 0x08 - 0x09: Manufacturer ID: "RED"
    # Encoded as 5 bits per character (A=1): R=18, E=5, D=4
    # (18 << 10) | (5 << 5) | 4 = 0x48A4
    edid[8] = 0x48
    edid[9] = 0xA4

    # 0x0A - 0x0B: Product Code
    edid[10] = 0x01
    edid[11] = 0x07 # 7-inch Touch

    # 0x0C - 0x0F: 32-bit Serial Number
    edid[12:16] = b"\x01\x02\x03\x04"

    # 0x10 - 0x11: Week & Year of manufacture (Week 12, 2016 -> 2016-1990 = 26)
    edid[16] = 12
    edid[17] = 26

    # 0x12 - 0x13: EDID Structure Version & Revision (1.3)
    edid[18] = 1
    edid[19] = 3

    # 0x14: Basic Display Parameters (Digital, 8-bit, DVI/HDMI compliant)
    edid[20] = 0x80
    edid[21] = 15 # Horizontal size in cm (15cm)
    edid[22] = 9  # Vertical size in cm (9cm)
    edid[23] = 120 # Gamma = 2.2 ((120+100)/100)
    edid[24] = 0x0A # Features: Preferred timing, RGB 4:4:4

    # 0x19 - 0x22: Color Characteristics
    edid[25:35] = b"\xEE\x91\xA3\x54\x4C\x99\x26\x0F\x50\x54"

    # 0x23 - 0x25: Established Timings (640x480, 800x600, 1024x768 support)
    edid[35:38] = b"\x21\x08\x00"

    # 0x26 - 0x35: Standard Timings (8 2-byte descriptors)
    edid[38:40] = b"\x61\x40" # 1024x768 @ 60Hz
    edid[40:42] = b"\x81\x80" # 1280x1024 @ 60Hz
    edid[42:54] = b"\x01\x01" * 6

    # 0x36 - 0x47: Detailed Timing Descriptor 1 (1024x576 @ 60Hz preferred)
    # Pixel Clock: 44.00 MHz -> 4400 (0x1130)
    edid[54] = 0x30
    edid[55] = 0x11
    edid[56] = 0x00 # H-active lower 8 bits (1024 = 0x400 -> 0x00)
    edid[57] = 0x50 # H-blanking lower 8 bits (208)
    edid[58] = 0x40 # H-active/blanking upper 4 bits
    edid[59] = 0x40 # V-active lower 8 bits (576 = 0x240 -> 0x40)
    edid[60] = 0x20 # V-blanking lower 8 bits (32)
    edid[61] = 0x20 # V-active/blanking upper 4 bits
    edid[62] = 0x18 # H-sync offset
    edid[63] = 0x30 # H-sync pulse width
    edid[64] = 0x33 # V-sync offset & pulse width
    edid[65] = 0x00
    edid[66] = 0x98 # H image size mm
    edid[67] = 0x56 # V image size mm
    edid[68] = 0x00
    edid[69] = 0x00
    edid[70] = 0x00
    edid[71] = 0x1E # Flags

    # 0x48 - 0x59: Descriptor 2: Monitor Name (0xFC)
    edid[72:77] = b"\x00\x00\x00\xFC\x00"
    name = b"RED TOUCH 7.0\n"
    edid[77:77+len(name)] = name
    for k in range(77 + len(name), 90):
        edid[k] = 0x20

    # 0x5A - 0x6B: Descriptor 3: Monitor Range Limits (0xFD)
    edid[90:95] = b"\x00\x00\x00\xFD\x00"
    edid[95] = 23 # Min V-rate (23 Hz)
    edid[96] = 61 # Max V-rate (61 Hz)
    edid[97] = 15 # Min H-rate (15 kHz)
    edid[98] = 80 # Max H-rate (80 kHz)
    edid[99] = 16 # Max pixel clock (160 MHz)
    edid[100:108] = b"\x00\x0A\x20\x20\x20\x20\x20\x20"

    # 0x6C - 0x7D: Descriptor 4: Serial Number string (0xFF)
    edid[108:113] = b"\x00\x00\x00\xFF\x00"
    serial = b"RT7-10042\n"
    edid[113:113+len(serial)] = serial
    for k in range(113 + len(serial), 126):
        edid[k] = 0x20

    # 0x7E: Extension flag (0 = no extension block)
    edid[126] = 0

    # 0x7F: Checksum: Sum of all 128 bytes must be 0 modulo 256
    chk = sum(edid[0:127]) % 256
    edid[127] = (256 - chk) % 256

    return bytes(edid)


class EdidEeprom(I2cSlave):
    """24C02 I2C EEPROM storing monitor EDID data at address 0x50."""

    def __init__(self, address: int = 0x50, edid_data: bytes = None):
        super().__init__(address)
        if edid_data is None:
            edid_data = create_red_touch_edid()
        self.data = bytearray(edid_data)
        self.current_offset = 0

    @property
    def edid_data(self) -> bytes:
        return bytes(self.data)

    def receive_bytes(self, data: bytes):
        if data:
            self.current_offset = data[0] & 0xFF

    def transmit_byte(self) -> int:
        val = self.data[self.current_offset] if self.current_offset < len(self.data) else 0xFF
        self.current_offset = (self.current_offset + 1) & 0xFF
        return val

    def write(self, reg_addr: int, data: bytes) -> bool:
        self.current_offset = reg_addr & 0xFF
        if data:
            for b in data:
                if self.current_offset < len(self.data):
                    self.data[self.current_offset] = b
                    self.current_offset += 1
        return True

    def read(self, reg_addr: int, length: int) -> bytes:
        result = bytearray()
        offset = reg_addr & 0xFF
        for _ in range(length):
            if offset < len(self.data):
                result.append(self.data[offset])
            else:
                result.append(0xFF)
            offset = (offset + 1) & 0xFF
        return bytes(result)
