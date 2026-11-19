"""
RED Command Protocol (RCP) Parser and Serializer for DSMC2.
Supports both the authentic RED RCP2 framed wire protocol (`#[@TGT]$SRC:CMD:PARAM:...:*CK\\n`)
and the legacy plain-text helper syntax (`GET`/`SET`/`RECORD`/`AF`/`PING`/`STATUS`) for
backward compatibility with automation scripts and Web Studio.
"""

from typing import Dict, Any, Tuple, Optional, List, Callable
from emulator.rcp.wire import (
    Rcp2Packet,
    build_packet,
    parse_frame,
    CMD_SET,
    CMD_GET,
    CMD_CURRENT,
    CMD_GET_LIST,
    CMD_CURRENT_LIST,
    CMD_SET_RELATIVE,
    CMD_GET_PERIODIC,
    CMD_GET_DEFAULT,
    CMD_CURRENT_DEFAULT,
    CMD_FAIL,
)


class RcpProtocol:
    """Handles RED Command Protocol framing, parsing, and dispatching."""

    # Standard DSMC2 Parameter IDs
    PARAM_RECORD_STATE = "record_state"
    PARAM_FPS = "frame_rate"
    PARAM_FRAME_RATE = "frame_rate"
    PARAM_ISO = "iso"
    PARAM_COLOR_TEMP = "color_temperature"
    PARAM_SHUTTER = "shutter_angle"
    PARAM_SHUTTER_ANGLE = "shutter_angle"
    PARAM_RESOLUTION = "resolution"
    PARAM_FORMAT = "record_format"
    PARAM_BATTERY_PERCENT = "battery_percent"
    PARAM_MEDIA_REMAINING = "media_remaining_percent"
    PARAM_CAMERA_NAME = "camera_name"
    PARAM_CAMERA_PIN = "camera_pin"

    # Lens & Optical Parameters
    PARAM_LENS_NAME = "lens_name"
    PARAM_LENS_BRAND = "lens_brand"
    PARAM_LENS_MOUNT = "lens_mount"
    PARAM_LENS_SERIAL = "lens_serial"
    PARAM_APERTURE = "aperture"
    PARAM_FOCAL_LENGTH = "focal_length"
    PARAM_FOCUS_DIST = "focus_distance"
    PARAM_AF_STATE = "af_state"
    PARAM_LENS_FLEN_MIN = "lens_flen_min"
    PARAM_LENS_FLEN_MAX = "lens_flen_max"

    # Extended RCP2 parameters verified from dsmc2-sdk
    PARAM_REDCODE = "redcode"
    PARAM_SERIAL_PORT_2_USE = "serial_port_2_use"

    # Canonical alias dictionary mapping various naming conventions to canonical state keys
    ALIASES = {
        "fps": "frame_rate",
        "framerate": "frame_rate",
        "frame_rate": "frame_rate",
        "rcp_param_frame_rate": "frame_rate",
        "sensor_frame_rate": "frame_rate",
        "rcp_param_sensor_frame_rate": "frame_rate",
        "project_frame_rate": "frame_rate",
        "shutter": "shutter_angle",
        "shutter_speed": "shutter_angle",
        "rcp_param_shutter": "shutter_angle",
        "shutter_angle": "shutter_angle",
        "iso": "iso",
        "gain": "iso",
        "rcp_param_iso": "iso",
        "kelvin": "color_temperature",
        "rcp_param_kelvin": "color_temperature",
        "color_temp": "color_temperature",
        "color_temperature": "color_temperature",
        "rcp_param_color_temperature": "color_temperature",
        "iris": "aperture",
        "f_stop": "aperture",
        "fstop": "aperture",
        "rcp_param_aperture": "aperture",
        "lens": "lens_name",
        "rcp_param_lens_meta_name": "lens_name",
        "lens_brand": "lens_brand",
        "rcp_param_lens_meta_manufacturer": "lens_brand",
        "lens_mount": "lens_mount",
        "focal": "focal_length",
        "focal_len": "focal_length",
        "rcp_param_focal_length": "focal_length",
        "focus": "focus_distance",
        "focus_dist": "focus_distance",
        "rcp_param_focus_dist": "focus_distance",
        "record": "record_state",
        "rec": "record_state",
        "rcp_param_record_state": "record_state",
        "redcode": "redcode",
        "custom_redcode": "redcode",
        "max_redcode": "redcode",
        "rcp_param_redcode": "redcode",
        "camera_name": "camera_name",
        "rcp_param_camera_name": "camera_name",
        "serial_port_2_use": "serial_port_2_use",
        "comm_serial_port_2_protocol": "serial_port_2_use",
        "comm_msg_set_serial_port_2_use": "serial_port_2_use",
        "comm_msg_get_serial_port_2_use": "serial_port_2_use",
        "format": "record_format",
        "res": "resolution",
        "resolution": "resolution",
        "battery": "battery_percent",
        "media": "media_remaining_percent",
        "media_remaining": "media_remaining_percent",
    }

    DEFAULTS: Dict[str, str] = {
        "frame_rate": "23.976",
        "iso": "800",
        "color_temperature": "5600",
        "shutter_angle": "180.0",
        "redcode": "8:1",
        "serial_port_2_use": "RCP",
        "record_state": "0",
    }

    PARAM_LISTS: Dict[str, List[str]] = {
        "iso": ["250", "320", "400", "500", "640", "800", "1000", "1280", "1600", "2000", "3200"],
        "frame_rate": ["23.976", "24.000", "25.000", "29.970", "30.000", "48.000", "50.000", "60.000"],
        "color_temperature": ["2800", "3200", "4000", "4500", "5000", "5600", "6500"],
        "redcode": ["5:1", "6:1", "7:1", "8:1", "10:1", "12:1", "14:1", "16:1"],
        "serial_port_2_use": ["RCP", "Media", "Timecode", "General"],
    }

    def __init__(self, camera: Optional[Any] = None, camera_state: Optional[Dict[str, Any]] = None):
        self.camera = camera
        self.state: Dict[str, str] = {
            self.PARAM_RECORD_STATE: "0",        # 0 = idle, 1 = pre-record, 2 = recording
            self.PARAM_FPS: "23.976",
            self.PARAM_ISO: "800",
            self.PARAM_COLOR_TEMP: "5600",
            self.PARAM_SHUTTER: "180.0",
            self.PARAM_RESOLUTION: "5120x2700",  # 5K
            self.PARAM_FORMAT: "5K 16:9",
            self.PARAM_REDCODE: "8:1",
            self.PARAM_SERIAL_PORT_2_USE: "RCP",
            self.PARAM_BATTERY_PERCENT: "95",
            self.PARAM_MEDIA_REMAINING: "78",
            self.PARAM_CAMERA_NAME: "SCARLET-W 5K",
            self.PARAM_CAMERA_PIN: "10042",
            self.PARAM_LENS_NAME: "Canon EF 24-70mm f/2.8L II USM",
            self.PARAM_LENS_BRAND: "Canon",
            self.PARAM_LENS_MOUNT: "Canon EF",
            self.PARAM_LENS_SERIAL: "CN-748921",
            self.PARAM_APERTURE: "f/2.8",
            self.PARAM_FOCAL_LENGTH: "50mm",
            self.PARAM_FOCUS_DIST: "2.50m",
            self.PARAM_AF_STATE: "IDLE",
            self.PARAM_LENS_FLEN_MIN: "24",
            self.PARAM_LENS_FLEN_MAX: "70",
        }
        if camera_state:
            self.state.update({k: str(v) for k, v in camera_state.items()})

        # Change listeners (e.g. for broadcast to TCP clients)
        self.listeners: List[Callable[..., None]] = []

    def add_listener(self, callback: Callable[..., None]):
        """Register a callback for state changes (param, val, [origin])."""
        self.listeners.append(callback)

    def remove_listener(self, callback: Callable[..., None]):
        """Unregister a state change listener."""
        if callback in self.listeners:
            self.listeners.remove(callback)

    def _notify(self, param: str, val: str, origin: Optional[Any] = None):
        """Invoke change listeners."""
        for cb in self.listeners:
            try:
                cb(param, val, origin)
            except TypeError:
                try:
                    cb(param, val)
                except Exception:
                    pass
            except Exception:
                pass

    def resolve_param(self, raw_param: str) -> str:
        """Resolve a raw parameter name or alias to its canonical state key."""
        clean = raw_param.strip().lower()
        return self.ALIASES.get(clean, clean)

    def get_param(self, raw_param: str) -> Optional[str]:
        """Query parameter value."""
        canonical = self.resolve_param(raw_param)
        return self.state.get(canonical)

    def set_param(self, raw_param: str, val: str, source: str = "RCP", origin: Optional[Any] = None) -> Tuple[bool, str, str]:
        """
        Set parameter value and propagate to hardware models (Lens, Recorder, etc.).
        Returns (success, canonical_param, final_val).
        """
        canonical = self.resolve_param(raw_param)
        val_str = str(val).strip()

        # Handle hardware model sync if camera reference exists
        if self.camera:
            if canonical == "aperture":
                lm = getattr(self.camera, "lens_mount", None)
                if lm:
                    # Clean "f/2.8" -> 2.8
                    clean_ap = val_str.lower().replace("f/", "").replace("f", "").strip()
                    try:
                        f_num = float(clean_ap)
                        lm.set_aperture(f_num)
                        val_str = f"f/{lm.current_aperture:.1f}"
                    except ValueError:
                        pass
            elif canonical == "focal_length":
                lm = getattr(self.camera, "lens_mount", None)
                if lm:
                    clean_flen = val_str.lower().replace("mm", "").strip()
                    try:
                        f_mm = float(clean_flen)
                        lm.set_focal_length(f_mm)
                        val_str = f"{int(lm.current_focal_length)}mm"
                    except ValueError:
                        pass
            elif canonical == "focus_distance":
                lm = getattr(self.camera, "lens_mount", None)
                if lm:
                    clean_dist = val_str.lower().replace("m", "").replace("ft", "").strip()
                    if clean_dist.upper() == "INF":
                        lm.set_focus_distance(999.0)
                        val_str = "INF"
                    else:
                        try:
                            d = float(clean_dist)
                            lm.set_focus_distance(d)
                            val_str = f"{lm.current_focus_distance:.2f}m"
                        except ValueError:
                            pass
            elif canonical == "record_state":
                if val_str in ("2", "start", "record"):
                    if hasattr(self.camera, "start_recording"):
                        self.camera.start_recording()
                    val_str = "2"
                elif val_str in ("0", "stop"):
                    if hasattr(self.camera, "stop_recording"):
                        self.camera.stop_recording()
                    val_str = "0"

        self.state[canonical] = val_str
        self._notify(canonical, val_str, origin=origin)

        if self.camera and hasattr(self.camera, "log_system") and source != "INTERNAL":
            self.camera.log_system(f"[RCP] {source} SET {canonical} = {val_str}")

        return True, canonical, val_str

    def process_rcp2_frame(self, raw_frame: bytes, origin: Optional[Any] = None) -> bytes:
        """
        Dispatch one framed RCP2 wire packet (`#[@TGT]$SRC:CMD:PARAM:[ARGS...]:*CK\\n`).
        Returns encoded reply frame bytes, or b"" if frame/checksum is invalid (dropped).
        """
        pkt = parse_frame(raw_frame)
        if pkt is None:
            return b""

        reply_target = pkt.source
        raw_param = pkt.param
        param_upper = raw_param.strip().upper()
        canonical = self.resolve_param(raw_param)

        # DIY Serial-2 Handle Handshake Verbs (`clean/serial_port_2.c`)
        if param_upper in ("WHO", "GET_WHO"):
            return build_packet(CMD_CURRENT, raw_param, ["RED DSMC2"], source="CAM", target=reply_target)
        if param_upper in ("VERSION", "GET_VERSION"):
            return build_packet(CMD_CURRENT, raw_param, ["7.4.1"], source="CAM", target=reply_target)
        if param_upper in ("REDINFO", "GET_REDINFO"):
            cam_name = self.state.get("camera_name", "SCARLET-W 5K")
            return build_packet(
                CMD_CURRENT, raw_param, [f"{cam_name};7.4.1;SYNTH"], source="CAM", target=reply_target
            )

        if pkt.cmd in (CMD_GET, CMD_GET_PERIODIC):
            val = self.state.get(canonical)
            if val is None:
                return build_packet(CMD_FAIL, raw_param, ["UNKNOWN_PARAM"], source="CAM", target=reply_target)
            return build_packet(CMD_CURRENT, raw_param, [val], source="CAM", target=reply_target)

        if pkt.cmd == CMD_SET:
            if not pkt.args:
                return build_packet(CMD_FAIL, raw_param, ["MISSING_VALUE"], source="CAM", target=reply_target)
            _, _, final_val = self.set_param(raw_param, pkt.args[0], source="RCP2", origin=origin)
            return build_packet(CMD_CURRENT, raw_param, [final_val], source="CAM", target=reply_target)

        if pkt.cmd == CMD_SET_RELATIVE:
            cur = self.state.get(canonical)
            if cur is None or not pkt.args:
                return build_packet(CMD_FAIL, raw_param, ["INVALID_RELATIVE"], source="CAM", target=reply_target)
            try:
                delta = float(pkt.args[0])
                new_num = float(cur) + delta
                if canonical == "iso":
                    final_str = str(max(100, int(round(new_num))))
                elif canonical == "color_temperature":
                    final_str = str(max(1700, min(10000, int(round(new_num)))))
                else:
                    final_str = f"{max(0.001, round(new_num, 3))}"
                _, _, final_val = self.set_param(raw_param, final_str, source="RCP2", origin=origin)
                return build_packet(CMD_CURRENT, raw_param, [final_val], source="CAM", target=reply_target)
            except ValueError:
                return build_packet(CMD_FAIL, raw_param, ["NON_NUMERIC"], source="CAM", target=reply_target)

        if pkt.cmd == CMD_GET_DEFAULT:
            dval = self.DEFAULTS.get(canonical, self.state.get(canonical))
            if dval is None:
                return build_packet(CMD_FAIL, raw_param, ["UNKNOWN_PARAM"], source="CAM", target=reply_target)
            return build_packet(CMD_CURRENT_DEFAULT, raw_param, [dval], source="CAM", target=reply_target)

        if pkt.cmd == CMD_GET_LIST:
            choices = self.PARAM_LISTS.get(canonical)
            if choices is None:
                val = self.state.get(canonical)
                if val is None:
                    return build_packet(CMD_FAIL, raw_param, ["UNKNOWN_PARAM"], source="CAM", target=reply_target)
                choices = [val]
            return build_packet(CMD_CURRENT_LIST, raw_param, choices, source="CAM", target=reply_target)

        return build_packet(CMD_FAIL, raw_param, [f"UNSUPPORTED_CMD_{pkt.cmd}"], source="CAM", target=reply_target)

    def process_command(self, cmd_line: str, origin: Optional[Any] = None) -> str:
        """
        Process an incoming RCP command line (RCP2 `#...` frame or legacy text command).
        Legacy Formats:
          GET <param>
          SET <param> <value>
          RECORD [START|STOP|TOGGLE]
          STATUS
          PING
          HELP
        """
        line = cmd_line.strip()
        if not line:
            return ""

        if line.startswith("#"):
            return self.process_rcp2_frame(line.encode("utf-8"), origin=origin).decode("utf-8")

        parts = line.split(maxsplit=2)
        verb = parts[0].upper()

        if verb == "GET":
            if len(parts) < 2:
                return "ERR INVALID_SYNTAX\n"
            raw_param = parts[1]
            canonical = self.resolve_param(raw_param)
            val = self.state.get(canonical)
            if val is not None:
                return f"RED {canonical} {val}\n"
            return f"ERR UNKNOWN_PARAM {raw_param}\n"

        elif verb == "SET":
            if len(parts) < 3:
                return "ERR INVALID_SYNTAX\n"
            raw_param = parts[1]
            val = parts[2]
            ok, canonical, final_val = self.set_param(raw_param, val, source="TCP", origin=origin)
            return f"RED {canonical} {final_val}\n"

        elif verb == "RECORD":
            action = parts[1].upper() if len(parts) >= 2 else "TOGGLE"
            if action in ("START", "1", "2"):
                self.set_param(self.PARAM_RECORD_STATE, "2", source="TCP", origin=origin)
                return f"RED {self.PARAM_RECORD_STATE} 2\n"
            elif action in ("STOP", "0"):
                self.set_param(self.PARAM_RECORD_STATE, "0", source="TCP", origin=origin)
                return f"RED {self.PARAM_RECORD_STATE} 0\n"
            elif action == "TOGGLE":
                curr = self.state.get(self.PARAM_RECORD_STATE, "0")
                new_state = "0" if curr == "2" else "2"
                self.set_param(self.PARAM_RECORD_STATE, new_state, source="TCP", origin=origin)
                return f"RED {self.PARAM_RECORD_STATE} {new_state}\n"
            return "ERR INVALID_RECORD_ACTION\n"

        elif verb == "AF":
            # Autofocus trigger command
            if self.camera and hasattr(self.camera, "lens_mount"):
                self.camera.lens_mount.trigger_autofocus()
                return f"RED af_state LOCKED\n"
            return "ERR AF_UNAVAILABLE\n"

        elif verb == "PING":
            return "PONG\n"

        elif verb == "STATUS":
            items = " ".join(f"{k}={v}" for k, v in sorted(self.state.items()))
            return f"STATUS {items}\n"

        elif verb in ("HELP", "PARAMS"):
            keys = " ".join(sorted(self.state.keys()))
            return f"PARAMS {keys}\n"

        return f"ERR UNKNOWN_COMMAND {verb}\n"
