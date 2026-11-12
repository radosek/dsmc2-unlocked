"""
Optical Low Pass Filter (OLPF) EEPROM Device Model.
Simulates the 256-byte 24C02 I2C identification memory on the RED DSMC2 sensor mount
connected to OMAP3630 I2C2 (slave address 0x54).
"""

import struct
from typing import Dict, Any, List
from emulator.devices.i2c import I2cSlave


class OlpfEeprom(I2cSlave):
    """
    256-byte OLPF Identification & Calibration Memory.
    Identifies installed optical filter (Standard, Skin Tone-Highlight, Low Light Optimized).
    """

    OLPF_PROFILES: Dict[str, Dict[str, Any]] = {
        "Standard": {
            "type_id": 0x01,
            "name": "Standard OLPF",
            "description": "Balanced color reproduction, optimal sharpness and highlight retention.",
            "color_matrix": [1.02, -0.01, -0.01, -0.02, 1.01, 0.01, 0.00, -0.02, 1.02]
        },
        "Skin Tone-Highlight": {
            "type_id": 0x02,
            "name": "Skin Tone-Highlight",
            "description": "Smooth highlight roll-off and authentic skin tone reproduction in high contrast.",
            "color_matrix": [1.05, -0.03, -0.02, -0.01, 1.03, -0.02, 0.01, -0.01, 1.00]
        },
        "Low Light Optimized": {
            "type_id": 0x03,
            "name": "Low Light Optimized",
            "description": "Clean color balance and minimal noise in low-light and shadow scenes.",
            "color_matrix": [0.98, 0.01, 0.01, 0.00, 0.99, 0.01, -0.01, 0.00, 1.01]
        }
    }

    def __init__(self, address: int = 0x54, initial_type: str = "Standard"):
        super().__init__(address)
        self.memory = bytearray(256)
        self.current_olpf_type: str = initial_type
        self.set_olpf_type(initial_type)

    def set_olpf_type(self, olpf_name: str) -> bool:
        """Flash new OLPF profile block into the 256-byte EEPROM memory."""
        # Find matching profile case-insensitively
        match = next((k for k in self.OLPF_PROFILES if k.lower() in olpf_name.lower()), "Standard")
        profile = self.OLPF_PROFILES[match]
        self.current_olpf_type = match

        # Clear EEPROM array
        self.memory = bytearray(256)

        # Header Magic: 'REDOLPF\x01' (8 bytes)
        self.memory[0:8] = b"REDOLPF\x01"

        # Type ID at offset 0x08
        self.memory[8] = profile["type_id"]

        # Null-terminated name at offset 0x10 (max 32 bytes)
        name_bytes = profile["name"].encode("utf-8")[:31] + b"\x00"
        self.memory[0x10:0x10 + len(name_bytes)] = name_bytes

        # Color Matrix at offset 0x30 (9 x 4-byte IEEE 754 floats)
        matrix_bytes = struct.pack("<9f", *profile["color_matrix"])
        self.memory[0x30:0x30 + len(matrix_bytes)] = matrix_bytes

        # Factory checksum at offset 0x80 (simple CRC placeholder)
        self.memory[0x80:0x84] = struct.pack("<I", 0xA5A50000 | profile["type_id"])
        return True

    def get_olpf_type(self) -> str:
        """Return the active OLPF profile name."""
        return self.current_olpf_type

    def get_info(self) -> Dict[str, Any]:
        """Return active OLPF metadata."""
        prof = self.OLPF_PROFILES.get(self.current_olpf_type, self.OLPF_PROFILES["Standard"])
        return {
            "type_name": prof["name"],
            "type_id": prof["type_id"],
            "description": prof["description"],
            "is_standard": (self.current_olpf_type == "Standard")
        }

    def read(self, reg_addr: int, length: int) -> bytes:
        """Handle I2C byte reads from EEPROM memory."""
        out = bytearray()
        for i in range(length):
            idx = (reg_addr + i) % 256
            out.append(self.memory[idx])
        return bytes(out)

    def write(self, reg_addr: int, data: bytes) -> bool:
        """Handle I2C byte writes into EEPROM memory."""
        for i, b in enumerate(data):
            idx = (reg_addr + i) % 256
            self.memory[idx] = b
        return True
