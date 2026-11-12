"""
RED DSMC2 Modular Rig & Physical Position Manager.

Provides comprehensive modeling of physical camera connector slots, modular accessories,
and spatial positioning (Top Pogo, Side Pogo, Rear Module Bus, Lens Mount, Media Bay).

Coordinates electrical detection lines (GPIOs), EEPROM identification handshakes (I2C/1-Wire),
serial communications (UART/SPI/C2C ts_lma), and synchronizes operational state with:
- Hardware controllers: OmapGpio, OmapDss, Twl4030Pmic, LensMount, R3dClipRecorder
- Display & UI routing: RedUiEngine, ScreenCompositor (Primary UI, EVF, rotation/flipping)
- Web Studio REST API & Developer UI
"""

import os
from typing import Dict, Any, List, Optional, Tuple, Callable
from emulator.devices.accessory_bus import ModuleDescriptor, AccessoryBus


class ConnectorPosition:
    """Standard physical connector locations on DSMC2 Brain."""
    TOP_POGO = "top_pogo"          # Pogo interface on top of brain (LCD / EVF)
    SIDE_POGO = "side_pogo"        # Pogo interface on operator/dumb side (EVF / Sidekick / LCD)
    REAR_MODULE = "rear_module"    # 26-pin / 13-pin rear module bus (Expanders, Battery adapters)
    LENS_MOUNT = "lens_mount"      # Front lens mount (EF, PL, Nikon, Dumb)
    MEDIA_BAY = "media_bay"        # Side Mini-Mag SSD slot (SATA Turbo)


class RigSlot:
    """Represents a physical mounting location on the camera body."""

    def __init__(
        self,
        slot_id: str,
        name: str,
        supported_categories: List[str],
        gpio_detect_bank: int = 5,
        gpio_detect_pin: int = 0
    ):
        self.slot_id = slot_id
        self.name = name
        self.supported_categories = supported_categories
        self.gpio_detect_bank = gpio_detect_bank
        self.gpio_detect_pin = gpio_detect_pin
        self.attached_module: Optional[Dict[str, Any]] = None
        self.orientation: str = "normal"  # "normal", "flipped", "rotated_90", "rotated_270"

    def is_occupied(self) -> bool:
        return self.attached_module is not None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "name": self.name,
            "supported_categories": self.supported_categories,
            "gpio_bank": self.gpio_detect_bank,
            "gpio_pin": self.gpio_detect_pin,
            "is_occupied": self.is_occupied(),
            "orientation": self.orientation,
            "module": self.attached_module
        }


class RigManager:
    """
    Manager for camera rig configuration, accessory modules, and position toggling.
    """

    # Extended catalog of authentic DSMC2 accessories
    MODULE_CATALOG: Dict[str, Dict[str, Any]] = {
        # Displays & EVFs
        "730-0024": {
            "name": "RED Touch 7.0 LCD",
            "pin": "730-0024",
            "category": "DISPLAY",
            "ports": ["Pogo", "maXTouch 0x4B", "EDID 0x50"],
            "power_draw_w": 8,
            "allowed_slots": [ConnectorPosition.TOP_POGO, ConnectorPosition.SIDE_POGO],
            "display_spec": {"width": 1920, "height": 1120, "touch": True, "type": "LCD"}
        },
        "730-0025": {
            "name": "RED Touch 4.7 LCD",
            "pin": "730-0025",
            "category": "DISPLAY",
            "ports": ["Pogo", "maXTouch 0x4B", "EDID 0x50"],
            "power_draw_w": 6,
            "allowed_slots": [ConnectorPosition.TOP_POGO, ConnectorPosition.SIDE_POGO],
            "display_spec": {"width": 1280, "height": 720, "touch": True, "type": "LCD"}
        },
        "730-0026": {
            "name": "DSMC2 OLED EVF",
            "pin": "730-0026",
            "category": "DISPLAY",
            "ports": ["Pogo", "EDID 0x50"],
            "power_draw_w": 5,
            "allowed_slots": [ConnectorPosition.TOP_POGO, ConnectorPosition.SIDE_POGO],
            "display_spec": {"width": 1920, "height": 1080, "touch": False, "type": "EVF"}
        },
        "720-0043": {
            "name": "DSMC2 Sidekick",
            "pin": "720-0043",
            "category": "CONTROL",
            "ports": ["Side Pogo", "OLED 1.7", "Rotary Wheel", "Nav Keys"],
            "power_draw_w": 3,
            "allowed_slots": [ConnectorPosition.SIDE_POGO],
            "display_spec": None
        },

        # Rear Expanders & Power Modules
        "720-0033": {
            "name": "DSMC2 Base Expander",
            "pin": "720-0033",
            "category": "REAR_EXPANDER",
            "ports": ["HDMI", "3G-SDI", "DC IN", "SYNC", "CTRL", "Headphone 3.5mm"],
            "power_draw_w": 12,
            "allowed_slots": [ConnectorPosition.REAR_MODULE]
        },
        "720-0034": {
            "name": "DSMC2 REDVOLT Expander",
            "pin": "720-0034",
            "category": "REAR_EXPANDER",
            "ports": ["REDVOLT Battery", "2x XLR Audio", "Gigabit Ethernet", "AUX Power", "HDMI", "3G-SDI"],
            "power_draw_w": 28,
            "allowed_slots": [ConnectorPosition.REAR_MODULE]
        },
        "720-0035": {
            "name": "DSMC2 Jetpack-SDI Expander",
            "pin": "720-0035",
            "category": "REAR_EXPANDER",
            "ports": ["2x 3G-SDI", "DC IN (Lemo)", "AUX Power", "Giga Ethernet"],
            "power_draw_w": 10,
            "allowed_slots": [ConnectorPosition.REAR_MODULE]
        },
        "720-0045": {
            "name": "DSMC2 V-Lock I/O Expander",
            "pin": "720-0045",
            "category": "REAR_EXPANDER",
            "ports": ["V-Lock Mount", "DC IN", "HDMI", "HD-SDI", "SYNC", "CTRL", "Stereo Mic In"],
            "power_draw_w": 14,
            "allowed_slots": [ConnectorPosition.REAR_MODULE]
        },

        # Media
        "750-0075": {
            "name": "RED MINI-MAG 512GB",
            "pin": "750-0075",
            "category": "MEDIA",
            "ports": ["SATA0 Turbo"],
            "power_draw_w": 5,
            "allowed_slots": [ConnectorPosition.MEDIA_BAY]
        },
        "750-0082": {
            "name": "RED MINI-MAG 960GB",
            "pin": "750-0082",
            "category": "MEDIA",
            "ports": ["SATA0 Turbo"],
            "power_draw_w": 6,
            "allowed_slots": [ConnectorPosition.MEDIA_BAY]
        },
        "750-0074": {
            "name": "RED MINI-MAG 120GB",
            "pin": "750-0074",
            "category": "MEDIA",
            "ports": ["SATA0 Turbo"],
            "power_draw_w": 4,
            "allowed_slots": [ConnectorPosition.MEDIA_BAY]
        },

        # Lens Mounts
        "725-0022": {
            "name": "DSMC Titanium PL Mount",
            "pin": "725-0022",
            "category": "LENS_MOUNT",
            "ports": ["Cooke /i contacts", "ts_lma McSPI"],
            "power_draw_w": 2,
            "allowed_slots": [ConnectorPosition.LENS_MOUNT]
        },
        "725-0026": {
            "name": "DSMC Aluminum Canon EF Mount",
            "pin": "725-0026",
            "category": "LENS_MOUNT",
            "ports": ["Canon EF electronic pins", "ts_lma McSPI"],
            "power_draw_w": 3,
            "allowed_slots": [ConnectorPosition.LENS_MOUNT]
        },
        "725-0027": {
            "name": "DSMC Nikon F Mount",
            "pin": "725-0027",
            "category": "LENS_MOUNT",
            "ports": ["Nikon mechanical aperture / electronic pins"],
            "power_draw_w": 2,
            "allowed_slots": [ConnectorPosition.LENS_MOUNT]
        }
    }

    # Standard Rig Presets
    PRESETS: Dict[str, Dict[str, Any]] = {
        "cinema_production": {
            "name": "Cinema Production Rig",
            "description": "Top Touch 7.0\", V-Lock I/O Expander, Canon EF Mount, 512GB Mini-Mag",
            "slots": {
                ConnectorPosition.TOP_POGO: {"pin": "730-0024", "orientation": "normal"},
                ConnectorPosition.SIDE_POGO: None,
                ConnectorPosition.REAR_MODULE: {"pin": "720-0045"},
                ConnectorPosition.LENS_MOUNT: {"pin": "725-0026"},
                ConnectorPosition.MEDIA_BAY: {"pin": "750-0075"}
            }
        },
        "handheld_operator": {
            "name": "Operator Handheld Rig",
            "description": "Side OLED EVF, Sidekick, Base Expander, 512GB Mini-Mag",
            "slots": {
                ConnectorPosition.TOP_POGO: None,
                ConnectorPosition.SIDE_POGO: {"pin": "730-0026", "orientation": "normal"},
                ConnectorPosition.REAR_MODULE: {"pin": "720-0033"},
                ConnectorPosition.LENS_MOUNT: {"pin": "725-0026"},
                ConnectorPosition.MEDIA_BAY: {"pin": "750-0075"}
            }
        },
        "broadcast_studio": {
            "name": "Broadcast & Live Studio Rig",
            "description": "Top Touch 7.0\", Jetpack-SDI Expander, PL Mount (/i), 960GB Mini-Mag",
            "slots": {
                ConnectorPosition.TOP_POGO: {"pin": "730-0024", "orientation": "normal"},
                ConnectorPosition.SIDE_POGO: {"pin": "730-0026", "orientation": "normal"},
                ConnectorPosition.REAR_MODULE: {"pin": "720-0035"},
                ConnectorPosition.LENS_MOUNT: {"pin": "725-0022"},
                ConnectorPosition.MEDIA_BAY: {"pin": "750-0082"}
            }
        },
        "bare_brain": {
            "name": "Bare Brain (Minimal)",
            "description": "No displays, no expanders, raw brain DC-IN only",
            "slots": {
                ConnectorPosition.TOP_POGO: None,
                ConnectorPosition.SIDE_POGO: None,
                ConnectorPosition.REAR_MODULE: None,
                ConnectorPosition.LENS_MOUNT: None,
                ConnectorPosition.MEDIA_BAY: None
            }
        }
    }

    def __init__(self, camera=None):
        self.camera = camera

        # Define the hardware slots and their associated GPIO detect pins
        # (Bank 5 Pin 3 = Top Pogo, Bank 5 Pin 4 = Side Pogo, Bank 5 Pin 5 = Rear Expander, Bank 5 Pin 6 = Mount)
        self.slots: Dict[str, RigSlot] = {
            ConnectorPosition.TOP_POGO: RigSlot(
                ConnectorPosition.TOP_POGO, "Top Pogo Connector", ["DISPLAY"], gpio_detect_bank=5, gpio_detect_pin=3
            ),
            ConnectorPosition.SIDE_POGO: RigSlot(
                ConnectorPosition.SIDE_POGO, "Side Pogo Connector", ["DISPLAY", "CONTROL"], gpio_detect_bank=5, gpio_detect_pin=4
            ),
            ConnectorPosition.REAR_MODULE: RigSlot(
                ConnectorPosition.REAR_MODULE, "Rear Module Bus (26-pin)", ["REAR_EXPANDER"], gpio_detect_bank=5, gpio_detect_pin=5
            ),
            ConnectorPosition.LENS_MOUNT: RigSlot(
                ConnectorPosition.LENS_MOUNT, "Front Smart Lens Mount", ["LENS_MOUNT"], gpio_detect_bank=5, gpio_detect_pin=6
            ),
            ConnectorPosition.MEDIA_BAY: RigSlot(
                ConnectorPosition.MEDIA_BAY, "RED MINI-MAG Slot", ["MEDIA"], gpio_detect_bank=5, gpio_detect_pin=7
            )
        }

        # Apply initial default configuration matching cinema production
        self.apply_preset("cinema_production")

    def get_slot(self, slot_id: str) -> Optional[RigSlot]:
        return self.slots.get(slot_id)

    def attach_module_to_slot(
        self,
        slot_id: str,
        pin_or_name: str,
        orientation: str = "normal",
        serial: int = 100001
    ) -> Optional[Dict[str, Any]]:
        """
        Hot-plug an accessory module into a specific physical connector slot.
        Updates virtual GPIO lines, triggers bus discovery, and coordinates subsystem state.
        """
        slot = self.slots.get(slot_id)
        if not slot:
            if self.camera:
                self.camera.log_system(f"[RIG] Unknown slot '{slot_id}'")
            return None

        # Resolve module info from catalog
        mod_info = None
        for pin, info in self.MODULE_CATALOG.items():
            if pin == pin_or_name or info["name"].lower() == pin_or_name.lower():
                mod_info = info
                break

        if not mod_info:
            # Fallback to accessory bus known modules if present
            if hasattr(self.camera, "accessory_bus") and self.camera.accessory_bus:
                mod_info = self.camera.accessory_bus.KNOWN_MODULES.get(pin_or_name)
            if not mod_info:
                if self.camera:
                    self.camera.log_system(f"[RIG] Unknown module '{pin_or_name}'")
                return None

        # Verify slot compatibility
        allowed_slots = mod_info.get("allowed_slots", [])
        if allowed_slots and slot_id not in allowed_slots:
            if self.camera:
                self.camera.log_system(f"[RIG] Incompatible: {mod_info['name']} cannot be mounted on {slot.name}")
            return None

        # If slot was already occupied, detach the previous module first
        if slot.is_occupied():
            self.detach_slot(slot_id)

        # Build entry
        entry = {
            "pin": mod_info["pin"],
            "name": mod_info["name"],
            "category": mod_info["category"],
            "ports": mod_info.get("ports", []),
            "power_w": mod_info.get("power_draw_w", 5),
            "serial": f"SN-{serial:06d}",
            "orientation": orientation,
            "slot": slot_id,
            "status": "ONLINE"
        }

        slot.attached_module = entry
        slot.orientation = orientation

        # 1. Flip virtual GPIO detect line to high (assert presence)
        self._set_gpio_detect(slot, high=True)

        # 2. Register with legacy/lower-level accessory bus if appropriate
        if hasattr(self.camera, "accessory_bus") and self.camera.accessory_bus:
            # Avoid duplicate logs if already present
            if mod_info["pin"] not in self.camera.accessory_bus.attached_modules:
                self.camera.accessory_bus.attach_module(mod_info["pin"], serial=serial)

        # 3. Synchronize with specific subsystem
        self._sync_subsystem_on_attach(slot, entry)

        if self.camera:
            self.camera.log_system(f"[RIG] Attached {entry['name']} to {slot.name} (orientation={orientation}) -> DETECT HIGH")

        return entry

    def detach_slot(self, slot_id: str) -> bool:
        """
        Hot-unplug an accessory module from a physical connector slot.
        Flipping the GPIO detect line to low and updating subsystem routing.
        """
        slot = self.slots.get(slot_id)
        if not slot or not slot.is_occupied():
            return False

        detached = slot.attached_module
        slot.attached_module = None
        slot.orientation = "normal"

        # 1. Flip virtual GPIO detect line to low (assert absence)
        self._set_gpio_detect(slot, high=False)

        # 2. Unregister from accessory bus
        if hasattr(self.camera, "accessory_bus") and self.camera.accessory_bus:
            self.camera.accessory_bus.detach_module(detached["pin"])

        # 3. Synchronize subsystem on detach
        self._sync_subsystem_on_detach(slot, detached)

        if self.camera:
            self.camera.log_system(f"[RIG] Detached {detached['name']} from {slot.name} -> DETECT LOW")

        return True

    def toggle_slot_position(self, from_slot_id: str, to_slot_id: str) -> bool:
        """
        Move / toggle a module from one physical connector to another.
        Example: Move RED Touch 7.0 from Top Pogo to Side Pogo.
        """
        from_slot = self.slots.get(from_slot_id)
        to_slot = self.slots.get(to_slot_id)
        if not from_slot or not to_slot or not from_slot.is_occupied():
            return False

        mod = from_slot.attached_module
        pin = mod["pin"]
        orientation = mod.get("orientation", "normal")
        serial_int = 100001
        try:
            serial_int = int(mod["serial"].replace("SN-", ""))
        except Exception:
            pass

        # Check compatibility with destination
        mod_info = self.MODULE_CATALOG.get(pin)
        if mod_info and mod_info.get("allowed_slots") and to_slot_id not in mod_info["allowed_slots"]:
            if self.camera:
                self.camera.log_system(f"[RIG] Cannot move {mod['name']} to {to_slot.name}: incompatible slot.")
            return False

        # Execute detach from source
        self.detach_slot(from_slot_id)

        # Execute attach to destination
        res = self.attach_module_to_slot(to_slot_id, pin, orientation=orientation, serial=serial_int)
        if self.camera:
            self.camera.log_system(f"[RIG] Toggled module position from {from_slot.name} -> {to_slot.name}")
        return res is not None

    def set_slot_orientation(self, slot_id: str, orientation: str) -> bool:
        """Update orientation of a display module (normal, flipped, rotated_90, rotated_270)."""
        slot = self.slots.get(slot_id)
        if not slot or not slot.is_occupied():
            return False
        slot.orientation = orientation
        if slot.attached_module:
            slot.attached_module["orientation"] = orientation

        # Inform UI / compositor if present
        comp = getattr(self.camera, "compositor", None) if self.camera else None
        if comp and hasattr(comp, "display_orientation"):
            comp.display_orientation = orientation

        if self.camera:
            self.camera.log_system(f"[RIG] {slot.name} orientation changed to '{orientation}'")
        return True

    def apply_preset(self, preset_key: str) -> bool:
        """Load a predefined hardware rig preset."""
        preset = self.PRESETS.get(preset_key)
        if not preset:
            return False

        # Clear existing rig slots
        for s_id in list(self.slots.keys()):
            if self.slots[s_id].is_occupied():
                self.detach_slot(s_id)

        # Attach modules defined in preset
        for s_id, conf in preset["slots"].items():
            if conf and "pin" in conf:
                self.attach_module_to_slot(
                    s_id,
                    conf["pin"],
                    orientation=conf.get("orientation", "normal")
                )

        if self.camera:
            self.camera.log_system(f"[RIG] Applied rig preset '{preset['name']}' ({preset['description']})")
        return True

    def _set_gpio_detect(self, slot: RigSlot, high: bool):
        """Update virtual GPIO input pin for connector presence detection."""
        if not self.camera or not hasattr(self.camera, "gpio"):
            return
        gpio_bank = self.camera.gpio.get(slot.gpio_detect_bank)
        if gpio_bank:
            gpio_bank.set_input_pin(slot.gpio_detect_pin, high)

    def _sync_subsystem_on_attach(self, slot: RigSlot, entry: Dict[str, Any]):
        """Synchronize specific hardware subsystems when an accessory is mounted."""
        cat = entry.get("category")
        pin = entry.get("pin")

        # 1. Displays (Top Pogo / Side Pogo)
        if cat == "DISPLAY":
            comp = getattr(self.camera, "compositor", None) if self.camera else None
            if comp:
                # Top Pogo is primary overlay; Side Pogo acts as EVF / secondary
                if slot.slot_id == ConnectorPosition.TOP_POGO:
                    comp.active_display_output = "TOP_LCD"
                elif slot.slot_id == ConnectorPosition.SIDE_POGO:
                    comp.active_display_output = "SIDE_EVF"

        # 2. Lens Mount
        elif cat == "LENS_MOUNT":
            mount = getattr(self.camera, "lens_mount", None) if self.camera else None
            if mount:
                if pin == "725-0026":
                    mount.set_mount_type(mount.MOUNT_CANON_EF)
                elif pin == "725-0022":
                    mount.set_mount_type(mount.MOUNT_PL_INTELLIGENT)
                elif pin == "725-0027":
                    mount.set_mount_type(mount.MOUNT_NIKON_F)

        # 3. Media Bay
        elif cat == "MEDIA":
            recorder = getattr(self.camera, "recorder", None) if self.camera else None
            if recorder:
                recorder.is_media_mounted = True
                if pin == "750-0082":
                    recorder.media_total_capacity_gb = 960
                elif pin == "750-0074":
                    recorder.media_total_capacity_gb = 120
                else:
                    recorder.media_total_capacity_gb = 512

        # 4. Rear Expander (Audio / HDMI / SDI multiplexer)
        elif cat == "REAR_EXPANDER":
            iob0 = getattr(self.camera, "iob0", None) if self.camera else None
            if iob0 and "HDMI" in entry.get("ports", []):
                iob0.hdmi_connected = True

    def _sync_subsystem_on_detach(self, slot: RigSlot, detached: Dict[str, Any]):
        """Synchronize specific hardware subsystems when an accessory is removed."""
        cat = detached.get("category")

        if cat == "DISPLAY":
            # If the primary monitor is removed, fallback or disable compositor feed
            comp = getattr(self.camera, "compositor", None) if self.camera else None
            if comp:
                # Check if another display is mounted
                top_occ = self.slots[ConnectorPosition.TOP_POGO].is_occupied()
                side_occ = self.slots[ConnectorPosition.SIDE_POGO].is_occupied()
                if top_occ:
                    comp.active_display_output = "TOP_LCD"
                elif side_occ:
                    comp.active_display_output = "SIDE_EVF"
                else:
                    comp.active_display_output = "NONE"

        elif cat == "LENS_MOUNT":
            mount = getattr(self.camera, "lens_mount", None) if self.camera else None
            if mount:
                mount.attached_lens = None

        elif cat == "MEDIA":
            recorder = getattr(self.camera, "recorder", None) if self.camera else None
            if recorder:
                recorder.is_media_mounted = False

        elif cat == "REAR_EXPANDER":
            iob0 = getattr(self.camera, "iob0", None) if self.camera else None
            if iob0:
                iob0.hdmi_connected = False

    def get_status(self) -> Dict[str, Any]:
        """Return comprehensive rig status, occupied slots, total power, and available catalog."""
        occupied_count = sum(1 for s in self.slots.values() if s.is_occupied())
        total_pwr = sum(
            s.attached_module["power_w"]
            for s in self.slots.values()
            if s.is_occupied()
        )

        return {
            "occupied_slots_count": occupied_count,
            "total_slots": len(self.slots),
            "total_rig_power_w": total_pwr,
            "slots": {
                s_id: slot.to_dict()
                for s_id, slot in self.slots.items()
            },
            "presets": list(self.PRESETS.keys()),
            "catalog": [
                {
                    "pin": info["pin"],
                    "name": info["name"],
                    "category": info["category"],
                    "power_w": info.get("power_draw_w", 5),
                    "ports": info.get("ports", []),
                    "allowed_slots": info.get("allowed_slots", [])
                }
                for info in self.MODULE_CATALOG.values()
            ]
        }
