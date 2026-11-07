"""
RED DSMC2 Camera Environment (/env) Configuration.
Supplies hardware identity, camera model ID, sensor parameters, and serial numbers.
"""

from typing import Dict, Any, List


class CameraEnvironment:
    """Manages the persistent /env partition configuration for DSMC2."""

    # Official DSMC2 Camera Model Profiles extracted from 7.4.1 Combo Package
    CAMERA_PROFILES: Dict[str, Dict[str, str]] = {
        "0x16": {
            "CAMERA_TYPE": "0x16",
            "CAMERA_NAME": "SCARLET-W 5K",
            "CAMERA_PIN": "10042",
            "SERIAL_NUMBER": "016-10042",
            "SENSOR_TYPE": "0x04",
            "SENSOR_NAME": "RED DRAGON 5K S35",
            "SENSOR_WIDTH": "5120",
            "SENSOR_HEIGHT": "2700",
            "MAX_FPS": "60",
            "DEFAULT_FORMAT": "5K 16:9",
            "FORMAT_OPTIONS": ["5K 16:9", "5K 2:1", "5K 2.4:1", "4.5K 16:9", "4K 16:9", "3K 16:9", "2K 16:9"],
            "FPS_OPTIONS": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00"],
            "FIRMWARE_DIR": "firmware_store/unpacked/scarlet_w_7_4_1",
            "DESCRIPTION": "Super35 Dragon sensor, 5K resolution up to 60 fps, 4K up to 150 fps.",
            "RELEASE_TAG": "DSMC2 SCARLET-W",
        },
        "0x15": {
            "CAMERA_TYPE": "0x15",
            "CAMERA_NAME": "RED RAVEN 4.5K",
            "CAMERA_PIN": "10041",
            "SERIAL_NUMBER": "015-10041",
            "SENSOR_TYPE": "0x03",
            "SENSOR_NAME": "RED DRAGON 4.5K S35",
            "SENSOR_WIDTH": "4608",
            "SENSOR_HEIGHT": "2160",
            "MAX_FPS": "120",
            "DEFAULT_FORMAT": "4.5K 16:9",
            "FORMAT_OPTIONS": ["4.5K 16:9", "4.5K 2:1", "4.5K 2.4:1", "4K 16:9", "3K 16:9", "2K 16:9"],
            "FPS_OPTIONS": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00", "120.00"],
            "FIRMWARE_DIR": "firmware_store/unpacked/raven_7_4_1",
            "DESCRIPTION": "Integrated EF mount lightweight DSMC2, 4.5K up to 120 fps, 2K up to 240 fps.",
            "RELEASE_TAG": "DSMC2 RAVEN",
        },
        "0x11": {
            "CAMERA_TYPE": "0x11",
            "CAMERA_NAME": "WEAPON 8K VV",
            "CAMERA_PIN": "10043",
            "SERIAL_NUMBER": "011-10043",
            "SENSOR_TYPE": "0x06",
            "SENSOR_NAME": "RED MONSTRO 8K VV",
            "SENSOR_WIDTH": "8192",
            "SENSOR_HEIGHT": "4320",
            "MAX_FPS": "60",
            "DEFAULT_FORMAT": "8K 16:9",
            "FORMAT_OPTIONS": ["8K 16:9", "8K 2:1", "8K 2.4:1", "7K 16:9", "6K 16:9", "5K 16:9", "4K 16:9"],
            "FPS_OPTIONS": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00"],
            "FIRMWARE_DIR": "firmware_store/unpacked/weapon_7_4_1",
            "DESCRIPTION": "Flagship 35.4 Megapixel VistaVision full-frame sensor, 8K up to 60 fps.",
            "RELEASE_TAG": "DSMC2 MONSTRO 8K VV",
        },
        "0x14": {
            "CAMERA_TYPE": "0x14",
            "CAMERA_NAME": "DSMC2 DRAGON-X 5K",
            "CAMERA_PIN": "10044",
            "SERIAL_NUMBER": "014-10044",
            "SENSOR_TYPE": "0x04",
            "SENSOR_NAME": "RED DRAGON-X 5K S35",
            "SENSOR_WIDTH": "5120",
            "SENSOR_HEIGHT": "2700",
            "MAX_FPS": "96",
            "DEFAULT_FORMAT": "5K 16:9",
            "FORMAT_OPTIONS": ["5K 16:9", "5K 2:1", "5K 2.4:1", "4.5K 16:9", "4K 16:9", "3K 16:9", "2K 16:9"],
            "FPS_OPTIONS": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00", "96.00"],
            "FIRMWARE_DIR": "firmware_store/unpacked/dragon_x_7_4_1",
            "DESCRIPTION": "Award-winning DRAGON sensor with unified IPP2 pipeline, 5K up to 96 fps.",
            "RELEASE_TAG": "DSMC2 DRAGON-X",
        },
        "0x17": {
            "CAMERA_TYPE": "0x17",
            "CAMERA_NAME": "EPIC-W 8K S35",
            "CAMERA_PIN": "10045",
            "SERIAL_NUMBER": "017-10045",
            "SENSOR_TYPE": "0x05",
            "SENSOR_NAME": "RED HELIUM 8K S35",
            "SENSOR_WIDTH": "8192",
            "SENSOR_HEIGHT": "4320",
            "MAX_FPS": "60",
            "DEFAULT_FORMAT": "8K 16:9",
            "FORMAT_OPTIONS": ["8K 16:9", "8K 2:1", "8K 2.4:1", "7K 16:9", "6K 16:9", "5K 16:9", "4K 16:9"],
            "FPS_OPTIONS": ["23.98", "24.00", "25.00", "29.97", "48.00", "50.00", "59.94", "60.00"],
            "FIRMWARE_DIR": "firmware_store/unpacked/epic_w_7_4_1",
            "DESCRIPTION": "35.4 Megapixel Super35 HELIUM sensor, 8K up to 60 fps, 16.5+ stops dynamic range.",
            "RELEASE_TAG": "DSMC2 HELIUM 8K",
        },
    }

    # Default Reference Model: 0x16 = SCARLET-W 5K
    DEFAULT_CONFIG = {
        "CAMERA_TYPE": "0x16",
        "CAMERA_NAME": "SCARLET-W 5K",
        "CAMERA_PIN": "10042",
        "SERIAL_NUMBER": "016-10042",
        "BOARD_REV": "0x01",
        "SENSOR_TYPE": "0x04",
        "SENSOR_NAME": "RED DRAGON 5K S35",
        "SENSOR_WIDTH": "5120",
        "SENSOR_HEIGHT": "2700",
        "MAX_FPS": "60",
        "MAC_ADDR": "00:1E:A9:10:04:20",
        "BUILD_VERSION": "7.4.1",
        "BOOT_SLOT": "2",
        "HARDWARE_VERSION": "DSMC2-BRAIN-V1",
        "SECURITY_SALT": "27A8124FB3EA",
    }

    def __init__(self, overrides: Dict[str, Any] = None):
        self.config = dict(self.DEFAULT_CONFIG)
        if overrides:
            self.config.update(overrides)

    def get(self, key: str, default: str = "") -> str:
        return self.config.get(key, default)

    def set(self, key: str, value: str):
        self.config[key] = str(value)

    def apply_profile(self, model_id: str) -> bool:
        """Apply a predefined camera profile to /env."""
        profile = self.CAMERA_PROFILES.get(model_id)
        if not profile:
            # Try case-insensitive or name match
            match = next((p for p in self.CAMERA_PROFILES.values() if p["CAMERA_NAME"].lower() == model_id.lower()), None)
            if match:
                profile = match
        if profile:
            for k, v in profile.items():
                if k in self.DEFAULT_CONFIG:
                    self.config[k] = v
            return True
        return False

    def list_profiles(self) -> List[Dict[str, Any]]:
        """Return list of all supported DSMC2 models with metadata."""
        current_type = self.get("CAMERA_TYPE", "0x16")
        out = []
        for mid, prof in self.CAMERA_PROFILES.items():
            item = dict(prof)
            item["is_active"] = (mid == current_type)
            out.append(item)
        return out

    def serialize(self) -> bytes:
        """Format as standard null-terminated key=value pairs for flash /env block."""
        entries = []
        for k, v in sorted(self.config.items()):
            entries.append(f"{k}={v}".encode("utf-8"))
        return b"\x00".join(entries) + b"\x00\x00"

    @classmethod
    def deserialize(cls, data: bytes) -> "CameraEnvironment":
        env = cls()
        for chunk in data.split(b"\x00"):
            if b"=" in chunk:
                try:
                    k, v = chunk.decode("utf-8").split("=", 1)
                    env.set(k.strip(), v.strip())
                except Exception:
                    pass
        return env
