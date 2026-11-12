"""
RED DSMC2 Accessory Bus & Module Enumeration Subsystem.
Implements authentic 1-Wire / UART enumeration handshake:
[Module Attach] -> [WHO] -> [VERSION] -> [REDINFO (TLV)] -> [DEVID Ack] -> [Online].
Decodes base64-encoded ModuleDescriptor binary TLVs.
"""

import base64
import struct
from typing import Dict, Any, List, Optional, Tuple


class ModuleDescriptor:
    """
    Authentic RED DSMC2 Module Descriptor binary TLV.
    TLV Tags:
      0x01: MFG_HW_REV (uint16 mfg_id, uint16 hw_rev)
      0x02: SERIAL_NUM (uint32 serial)
      0x03: NAME_PIN (product_name, part_number)
      0x04: POWER_LIMITS (uint16 max_power_watts, uint16 flags)
    """

    TAG_MFG_HW_REV = 0x01
    TAG_SERIAL_NUM = 0x02
    TAG_NAME_PIN = 0x03
    TAG_POWER_LIMITS = 0x04

    def __init__(self, name: str, pin: str, serial: int, mfg_id: int = 0x1143, hw_rev: int = 1, max_power_w: int = 60):
        self.name = name
        self.pin = pin
        self.serial = serial
        self.mfg_id = mfg_id
        self.hw_rev = hw_rev
        self.max_power_w = max_power_w

    def serialize(self) -> bytes:
        """Encode descriptor into binary TLV format."""
        out = bytearray(b"REDMOD\x01") # Magic header

        # TLV 1: MFG & HW Rev
        mfg_bytes = struct.pack("<HH", self.mfg_id, self.hw_rev)
        out += struct.pack("<BB", self.TAG_MFG_HW_REV, len(mfg_bytes)) + mfg_bytes

        # TLV 2: Serial Number
        serial_bytes = struct.pack("<I", self.serial)
        out += struct.pack("<BB", self.TAG_SERIAL_NUM, len(serial_bytes)) + serial_bytes

        # TLV 3: Product Name & PIN (Null-separated)
        np_bytes = self.name.encode("utf-8") + b"\x00" + self.pin.encode("utf-8")
        out += struct.pack("<BB", self.TAG_NAME_PIN, len(np_bytes)) + np_bytes

        # TLV 4: Power Limits
        pwr_bytes = struct.pack("<HH", self.max_power_w, 0x0001)
        out += struct.pack("<BB", self.TAG_POWER_LIMITS, len(pwr_bytes)) + pwr_bytes

        return bytes(out)

    def to_base64(self) -> str:
        """Return base64 string matching REDINFO UART output."""
        return base64.b64encode(self.serialize()).decode("ascii")

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["ModuleDescriptor"]:
        """Decode binary TLV descriptor."""
        if len(data) < 7 or data[:7] != b"REDMOD\x01":
            return None

        idx = 7
        name, pin, serial, mfg, rev, pwr = "Unknown", "000-0000", 0, 0, 1, 45

        while idx + 2 <= len(data):
            tag, length = struct.unpack("<BB", data[idx:idx + 2])
            val_bytes = data[idx + 2:idx + 2 + length]
            idx += 2 + length

            if tag == cls.TAG_MFG_HW_REV and len(val_bytes) >= 4:
                mfg, rev = struct.unpack("<HH", val_bytes[:4])
            elif tag == cls.TAG_SERIAL_NUM and len(val_bytes) >= 4:
                serial = struct.unpack("<I", val_bytes[:4])[0]
            elif tag == cls.TAG_NAME_PIN:
                parts = val_bytes.split(b"\x00")
                name = parts[0].decode("utf-8", errors="ignore")
                pin = parts[1].decode("utf-8", errors="ignore") if len(parts) > 1 else "000-0000"
            elif tag == cls.TAG_POWER_LIMITS and len(val_bytes) >= 4:
                pwr = struct.unpack("<HH", val_bytes[:4])[0]

        return cls(name, pin, serial, mfg, rev, pwr)

    @classmethod
    def from_base64(cls, b64_str: str) -> Optional["ModuleDescriptor"]:
        try:
            raw = base64.b64decode(b64_str)
            return cls.from_bytes(raw)
        except Exception:
            return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "pin": self.pin,
            "serial": f"SN-{self.serial:06d}",
            "mfg_id": f"0x{self.mfg_id:04X}",
            "hw_rev": self.hw_rev,
            "max_power_w": self.max_power_w
        }


class AccessoryBus:
    """
    DSMC2 Accessory Bus Manager.
    Handles module discovery, enumeration handshake, and hot-plug attach/detach events.
    """

    # Authentic Catalog of DSMC2 Modules
    KNOWN_MODULES: Dict[str, Dict[str, Any]] = {
        "720-0033": {
            "name": "DSMC2 Base Expander",
            "pin": "720-0033",
            "ports": ["HDMI", "3G-SDI", "DC IN", "SYNC", "CTRL", "Headphone 3.5mm"],
            "power_draw_w": 12,
            "category": "REAR_EXPANDER"
        },
        "720-0034": {
            "name": "DSMC2 REDVOLT Expander",
            "pin": "720-0034",
            "ports": ["REDVOLT Battery", "2x XLR Audio", "Gigabit Ethernet", "AUX Power", "HDMI", "3G-SDI"],
            "power_draw_w": 28,
            "category": "REAR_EXPANDER"
        },
        "720-0035": {
            "name": "DSMC2 Jetpack-SDI Expander",
            "pin": "720-0035",
            "ports": ["2x 3G-SDI", "DC IN (Lemo)", "AUX Power", "Giga Ethernet"],
            "power_draw_w": 10,
            "category": "REAR_EXPANDER"
        },
        "730-0024": {
            "name": "RED Touch 7.0 LCD",
            "pin": "730-0024",
            "ports": ["LCD1", "Integrated maXTouch"],
            "power_draw_w": 8,
            "category": "DISPLAY"
        },
        "750-0075": {
            "name": "RED MINI-MAG 512GB",
            "pin": "750-0075",
            "ports": ["SATA0 Turbo"],
            "power_draw_w": 5,
            "category": "MEDIA"
        }
    }

    def __init__(self, camera=None):
        self.camera = camera
        self.attached_modules: Dict[str, Dict[str, Any]] = {}
        self.enumeration_state = "IDLE"

        # Default standard production rig attached
        self._init_default_accessories()

    def _init_default_accessories(self):
        """Mount standard out-of-the-box DSMC2 camera configuration."""
        self.attach_module("720-0033", serial=104921) # Base Expander
        self.attach_module("730-0024", serial=203814) # RED Touch 7.0
        self.attach_module("750-0075", serial=309482) # MINI-MAG 512GB

    def attach_module(self, pin_or_name: str, serial: int = 100001) -> Optional[Dict[str, Any]]:
        """
        Execute enumeration handshake and register attached module.
        [Attach] -> [WHO] -> [VERSION] -> [REDINFO] -> [Online].
        """
        mod_info = None
        for pin, info in self.KNOWN_MODULES.items():
            if pin == pin_or_name or info["name"].lower() == pin_or_name.lower():
                mod_info = info
                break

        if not mod_info:
            return None

        # Build TLV descriptor
        desc = ModuleDescriptor(
            name=mod_info["name"],
            pin=mod_info["pin"],
            serial=serial,
            max_power_w=mod_info["power_draw_w"]
        )

        entry = {
            "id": mod_info["pin"],
            "name": mod_info["name"],
            "category": mod_info["category"],
            "ports": mod_info["ports"],
            "power_w": mod_info["power_draw_w"],
            "descriptor": desc.to_dict(),
            "descriptor_base64": desc.to_base64(),
            "descriptor_obj": desc,
            "serial": f"SN-{serial:06d}",
            "status": "ONLINE"
        }

        self.attached_modules[mod_info["pin"]] = entry
        if self.camera:
            self.camera.log_system(f"[ACCESSORY] Discovered {entry['name']} ({entry['id']}, {entry['serial']}) on bus -> ONLINE")

        return entry

    def detach_module(self, pin_or_name: str) -> bool:
        """Disconnect an attached accessory module."""
        target_pin = None
        for pin, entry in self.attached_modules.items():
            if pin == pin_or_name or entry["name"].lower() == pin_or_name.lower():
                target_pin = pin
                break

        if target_pin and target_pin in self.attached_modules:
            name = self.attached_modules[target_pin]["name"]
            del self.attached_modules[target_pin]
            if self.camera:
                self.camera.log_system(f"[ACCESSORY] Detached module {name} ({target_pin}) -> Powered Down")
            return True
        return False

    def handle_uart_handshake(self, query: str) -> str:
        """Service UART accessory protocol queries (WHO, VERSION, REDINFO)."""
        q = query.strip().upper()
        if q == "WHO":
            return "BASE_EXPANDER" if "720-0033" in self.attached_modules else "NONE"
        elif q == "VERSION":
            return "hw:1 sw:7.4.1"
        elif q == "REDINFO":
            exp = self.attached_modules.get("720-0033")
            if exp:
                return exp.get("descriptor_base64", exp["descriptor_obj"].to_base64())
            return "NONE"
        return "ERROR"

    def get_status(self) -> Dict[str, Any]:
        """Return status list of all attached modules."""
        return {
            "count": len(self.attached_modules),
            "modules": [
                {
                    "pin": entry["id"],
                    "name": entry["name"],
                    "category": entry["category"],
                    "serial": entry["serial"],
                    "power_w": entry["power_w"],
                    "ports": entry["ports"],
                    "status": entry["status"]
                }
                for entry in self.attached_modules.values()
            ],
            "total_accessory_power_w": sum(e["power_w"] for e in self.attached_modules.values())
        }
