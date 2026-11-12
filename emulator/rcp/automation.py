"""
Advanced RED Command Protocol (RCP) Automation & Multi-Camera Orchestration Subsystem.
Provides:
  - Scriptable RCP sequence execution (SET, GET, ASSERT, WAIT, RAMP, TRIGGER).
  - Multi-camera studio network synchronization (Genlock, Timecode, Multi-Cam Record Broadcast).
  - Production presets (Rack Focus, Production Slate & Record Cycle, Exposure Bracketing, Multi-Cam Array).
  - Structured audit trail and assertion verification.
"""

import time
import math
from typing import Dict, Any, List, Optional, Tuple, Callable


class RcpScriptStep:
    """Individual instruction in an RCP automation sequence."""

    def __init__(
        self,
        action: str,
        param: str = "",
        value: Any = None,
        comparator: str = "==",
        duration_ms: float = 0.0,
        steps: int = 5,
        description: str = ""
    ):
        self.action = action.upper().strip()
        self.param = param.strip()
        self.value = value
        self.comparator = comparator.strip()
        self.duration_ms = float(duration_ms)
        self.steps = max(1, int(steps))
        self.description = description or f"{self.action} {self.param} {self.value}".strip()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "param": self.param,
            "value": self.value,
            "comparator": self.comparator,
            "duration_ms": self.duration_ms,
            "steps": self.steps,
            "description": self.description
        }


class RcpScriptEngine:
    """
    Parses and executes scriptable RCP automation sequences against camera and protocol instances.
    Records per-step latency and assertion results.
    """

    PRESETS = {
        "RACK_FOCUS": {
            "name": "Rack Focus & Depth Sweep",
            "description": "Sets aperture to f/2.8, ramps electronic lens focus from 1.0m to 10.0m, steps iris to f/8.0.",
            "steps": [
                {"action": "SET", "param": "aperture", "value": "f/2.8", "description": "Set wide-open aperture f/2.8"},
                {"action": "ASSERT", "param": "aperture", "value": "f/2.8", "comparator": "=="},
                {"action": "RAMP", "param": "focus_distance", "value": "1.0m,10.0m", "duration_ms": 300, "steps": 6, "description": "Rack focus from 1.0m to 10.0m"},
                {"action": "ASSERT", "param": "focus_distance", "value": "10.0m", "comparator": "=="},
                {"action": "SET", "param": "aperture", "value": "f/5.6", "description": "Step iris to f/5.6"},
                {"action": "SET", "param": "aperture", "value": "f/8.0", "description": "Step iris to f/8.0 deep focus"}
            ]
        },
        "RECORD_CYCLE": {
            "name": "Production Slate & Record Cycle",
            "description": "Configures standard cinematic parameters (ISO 800, 5600K, 180°), triggers rolling record, verifies clip creation, and stops.",
            "steps": [
                {"action": "SET", "param": "iso", "value": "800", "description": "Set base ISO 800"},
                {"action": "SET", "param": "color_temperature", "value": "5600", "description": "Set Daylight 5600K"},
                {"action": "SET", "param": "shutter_angle", "value": "180.0", "description": "Set standard 180° shutter"},
                {"action": "TRIGGER", "param": "record_start", "description": "Trigger rolling record start"},
                {"action": "WAIT", "duration_ms": 200, "description": "Record clip roll"},
                {"action": "ASSERT", "param": "record_state", "value": "2", "comparator": "==", "description": "Verify recording active"},
                {"action": "TRIGGER", "param": "record_stop", "description": "Trigger record stop"},
                {"action": "WAIT", "duration_ms": 100, "description": "Wait for clip finalizing"},
                {"action": "ASSERT", "param": "record_state", "value": "0", "comparator": "==", "description": "Verify idle standby"}
            ]
        },
        "EXPOSURE_BRACKET": {
            "name": "Exposure Bracket Sweep",
            "description": "Steps sensor ISO through 250 -> 800 -> 1600 -> 3200 and shutter 180° -> 90° -> 45°.",
            "steps": [
                {"action": "SET", "param": "iso", "value": "250"},
                {"action": "ASSERT", "param": "iso", "value": "250", "comparator": "=="},
                {"action": "SET", "param": "iso", "value": "800"},
                {"action": "ASSERT", "param": "iso", "value": "800", "comparator": "=="},
                {"action": "SET", "param": "iso", "value": "1600"},
                {"action": "ASSERT", "param": "iso", "value": "1600", "comparator": "=="},
                {"action": "SET", "param": "iso", "value": "3200"},
                {"action": "ASSERT", "param": "iso", "value": "3200", "comparator": "=="},
                {"action": "SET", "param": "shutter_angle", "value": "90.0"},
                {"action": "SET", "param": "shutter_angle", "value": "45.0"},
                {"action": "SET", "param": "shutter_angle", "value": "180.0"}
            ]
        },
        "MULTICAM_SYNC": {
            "name": "Multi-Camera Master Broadcast",
            "description": "Synchronizes timecode and frame rate across camera network, locks Genlock, and issues simultaneous record trigger.",
            "steps": [
                {"action": "SET", "param": "frame_rate", "value": "23.976", "description": "Lock 23.976 FPS across array"},
                {"action": "SET", "param": "color_temperature", "value": "5600", "description": "Match daylight white balance"},
                {"action": "TRIGGER", "param": "multicam_genlock", "description": "Lock Tri-Level Genlock sync"},
                {"action": "TRIGGER", "param": "multicam_record_start", "description": "Broadcast synchronized record start"},
                {"action": "WAIT", "duration_ms": 250, "description": "Rolling multi-cam scene capture"},
                {"action": "TRIGGER", "param": "multicam_record_stop", "description": "Broadcast synchronized record stop"}
            ]
        }
    }

    def __init__(self):
        pass

    def parse_script_lines(self, lines: List[str]) -> List[RcpScriptStep]:
        """Parse human-readable DSL lines into RcpScriptStep instances."""
        steps = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue

            parts = line.split()
            cmd = parts[0].upper()

            if cmd == "SET" and len(parts) >= 3:
                steps.append(RcpScriptStep("SET", param=parts[1], value=" ".join(parts[2:])))
            elif cmd == "GET" and len(parts) >= 2:
                steps.append(RcpScriptStep("GET", param=parts[1]))
            elif cmd == "ASSERT" and len(parts) >= 4:
                steps.append(RcpScriptStep("ASSERT", param=parts[1], comparator=parts[2], value=" ".join(parts[3:])))
            elif cmd == "WAIT" and len(parts) >= 2:
                ms = float(parts[1].replace("ms", ""))
                steps.append(RcpScriptStep("WAIT", duration_ms=ms))
            elif cmd == "RAMP" and len(parts) >= 4:
                param = parts[1]
                start_val = parts[2]
                end_val = parts[3]
                ms = float(parts[4]) if len(parts) >= 5 else 500.0
                st = int(parts[5]) if len(parts) >= 6 else 5
                steps.append(RcpScriptStep("RAMP", param=param, value=f"{start_val},{end_val}", duration_ms=ms, steps=st))
            elif cmd == "TRIGGER" and len(parts) >= 2:
                steps.append(RcpScriptStep("TRIGGER", param=parts[1]))
        return steps

    def execute(
        self,
        steps: List[RcpScriptStep],
        camera: Any,
        rcp_protocol: Any,
        multicam: Optional["MultiCameraNetwork"] = None,
        script_name: str = "Custom Automation Script"
    ) -> Dict[str, Any]:
        """
        Execute sequence of RcpScriptStep objects against camera and protocol.
        Returns execution summary with step-by-step audit trace.
        """
        t0 = time.time()
        trace = []
        passed_assertions = 0
        failed_assertions = 0
        overall_success = True

        for idx, step in enumerate(steps, 1):
            step_t0 = time.time()
            step_record = {
                "step": idx,
                "action": step.action,
                "param": step.param,
                "value": step.value,
                "description": step.description,
                "status": "OK",
                "message": ""
            }

            try:
                if step.action == "SET":
                    resp = rcp_protocol.process_command(f"SET {step.param} {step.value}")
                    step_record["response"] = resp
                    step_record["message"] = f"Set {step.param} = {step.value}"

                elif step.action == "GET":
                    resp = rcp_protocol.process_command(f"GET {step.param}")
                    step_record["response"] = resp
                    step_record["message"] = f"Got {step.param}: {resp}"

                elif step.action == "ASSERT":
                    curr_val = rcp_protocol.get_param(step.param)
                    if curr_val is None:
                        curr_val = ""
                    expected_val = str(step.value)
                    curr_str = str(curr_val)

                    passed = False
                    if step.comparator == "==":
                        if curr_str == expected_val:
                            passed = True
                        else:
                            try:
                                cv = float(curr_str.replace("m", "").replace("f/", "").replace("K", "").replace("°", "").strip())
                                ev = float(expected_val.replace("m", "").replace("f/", "").replace("K", "").replace("°", "").strip())
                                passed = abs(cv - ev) < 0.05
                            except Exception:
                                passed = False
                    elif step.comparator == "!=":
                        passed = (curr_str != expected_val)
                    elif step.comparator in (">=", "<=", ">", "<"):
                        try:
                            cv = float(curr_str.replace("m", "").replace("f/", "").replace("K", "").replace("°", ""))
                            ev = float(expected_val.replace("m", "").replace("f/", "").replace("K", "").replace("°", ""))
                            if step.comparator == ">=":
                                passed = (cv >= ev)
                            elif step.comparator == "<=":
                                passed = (cv <= ev)
                            elif step.comparator == ">":
                                passed = (cv > ev)
                            elif step.comparator == "<":
                                passed = (cv < ev)
                        except Exception:
                            passed = False

                    if passed:
                        passed_assertions += 1
                        step_record["status"] = "PASSED"
                        step_record["message"] = f"Assertion passed: {step.param} {step.comparator} {expected_val} (actual: {curr_str})"
                    else:
                        failed_assertions += 1
                        overall_success = False
                        step_record["status"] = "FAILED"
                        step_record["message"] = f"Assertion failed: expected {step.param} {step.comparator} {expected_val}, got {curr_str}"

                elif step.action == "WAIT":
                    if step.duration_ms > 0:
                        time.sleep(min(2.0, step.duration_ms / 1000.0))
                    step_record["message"] = f"Waited {step.duration_ms:.0f}ms"

                elif step.action == "RAMP":
                    vals = str(step.value).split(",")
                    if len(vals) >= 2:
                        try:
                            s_num = float(vals[0].replace("m", "").replace("f/", "").replace("°", ""))
                            e_num = float(vals[1].replace("m", "").replace("f/", "").replace("°", ""))
                            st_count = max(2, step.steps)
                            interval = (step.duration_ms / 1000.0) / st_count

                            for s in range(st_count + 1):
                                frac = s / st_count
                                interpolated = s_num + frac * (e_num - s_num)
                                suffix = "m" if "m" in vals[0] else ""
                                val_str = f"{interpolated:.1f}{suffix}"
                                rcp_protocol.process_command(f"SET {step.param} {val_str}")
                                if interval > 0:
                                    time.sleep(min(0.1, interval))
                            step_record["message"] = f"Ramped {step.param} {vals[0]} -> {vals[1]} ({st_count} steps)"
                        except Exception as e:
                            step_record["status"] = "ERROR"
                            step_record["message"] = f"Ramp parse error: {e}"
                            overall_success = False

                elif step.action == "TRIGGER":
                    trig = step.param.lower()
                    if trig == "record_start":
                        camera.start_recording()
                        rcp_protocol.set_param("record_state", "2")
                        step_record["message"] = "Camera recording started"
                    elif trig == "record_stop":
                        camera.stop_recording()
                        rcp_protocol.set_param("record_state", "0")
                        step_record["message"] = "Camera recording stopped"
                    elif trig == "format_media":
                        res = camera.recorder.format_media()
                        step_record["message"] = f"Formatted media: {res}"
                    elif trig == "black_shading":
                        res = camera.run_black_shading()
                        step_record["message"] = f"Black shading completed: {res.get('status', 'OK')}"
                    elif trig == "multicam_genlock" and multicam:
                        res = multicam.sync_genlock()
                        step_record["message"] = f"Multi-camera Genlock synced: {res['genlock']}"
                    elif trig == "multicam_record_start" and multicam:
                        res = multicam.synchronized_record_trigger("START")
                        step_record["message"] = f"Multi-camera sync record started: {len(res['nodes'])} cameras"
                    elif trig == "multicam_record_stop" and multicam:
                        res = multicam.synchronized_record_trigger("STOP")
                        step_record["message"] = f"Multi-camera sync record stopped: {len(res['nodes'])} cameras"
                    else:
                        step_record["message"] = f"Triggered action: {trig}"

            except Exception as ex:
                step_record["status"] = "ERROR"
                step_record["message"] = f"Exception: {ex}"
                overall_success = False

            step_record["elapsed_ms"] = round((time.time() - step_t0) * 1000.0, 2)
            trace.append(step_record)

        total_elapsed_ms = round((time.time() - t0) * 1000.0, 2)
        return {
            "script_name": script_name,
            "status": "PASSED" if overall_success else "FAILED",
            "total_steps": len(steps),
            "passed_assertions": passed_assertions,
            "failed_assertions": failed_assertions,
            "duration_ms": total_elapsed_ms,
            "trace": trace
        }


class MultiCameraNetwork:
    """
    Multi-Camera Studio Network.
    Manages an array of DSMC2 cameras in master/slave topology with Genlock sync,
    synchronized timecode distribution, and broadcast parameter dispatch.
    """

    def __init__(self, master_camera: Any):
        self.master_camera = master_camera
        self.genlock_state = "LOCKED"
        self.timecode_master = "A-CAM (Master)"
        self.sync_timecode = "01:00:00:00"
        cam_name = getattr(master_camera, "brain_model", "SCARLET-W 5K") if master_camera else "SCARLET-W 5K"

        # Initialize studio multi-camera node array
        self.nodes: Dict[str, Dict[str, Any]] = {
            "A-CAM": {
                "id": "A-CAM",
                "role": "MASTER",
                "name": cam_name,
                "camera_ref": master_camera,
                "fps": 23.976,
                "iso": 800,
                "color_temp": 5600,
                "record_state": 0,
                "timecode": self.sync_timecode,
                "genlock": "LOCKED"
            },
            "B-CAM": {
                "id": "B-CAM",
                "role": "SLAVE",
                "name": "RED DRAGON-X 5K",
                "camera_ref": None,
                "fps": 23.976,
                "iso": 800,
                "color_temp": 5600,
                "record_state": 0,
                "timecode": self.sync_timecode,
                "genlock": "LOCKED"
            },
            "C-CAM": {
                "id": "C-CAM",
                "role": "SLAVE",
                "name": "RED RAVEN 4.5K",
                "camera_ref": None,
                "fps": 23.976,
                "iso": 800,
                "color_temp": 5600,
                "record_state": 0,
                "timecode": self.sync_timecode,
                "genlock": "LOCKED"
            }
        }

    def sync_genlock(self, timecode: str = "01:00:00:00") -> Dict[str, Any]:
        """Synchronize Tri-Level Genlock and SMPTE timecode across array."""
        self.genlock_state = "LOCKED"
        self.sync_timecode = timecode
        for node in self.nodes.values():
            node["genlock"] = "LOCKED"
            node["timecode"] = self.sync_timecode
        return {
            "genlock": self.genlock_state,
            "master": self.timecode_master,
            "timecode": self.sync_timecode,
            "synced_count": len(self.nodes)
        }

    def broadcast_parameter(self, param: str, value: str) -> Dict[str, Any]:
        """Broadcast an RCP parameter value across all camera nodes."""
        results = {}
        for node_id, node in self.nodes.items():
            node[param] = value
            # If local master camera has protocol, update it
            if node["role"] == "MASTER" and self.master_camera and hasattr(self.master_camera, "rcp_protocol"):
                self.master_camera.rcp_protocol.process_command(f"SET {param} {value}")
            results[node_id] = {"param": param, "value": value, "status": "SYNCED"}
        return {"broadcast_param": param, "value": value, "nodes": results}

    def synchronized_record_trigger(self, action: str = "START") -> Dict[str, Any]:
        """Simultaneously trigger rolling record start or stop across all bodies."""
        act = action.upper().strip()
        rec_state = 2 if act == "START" else 0

        if act == "START":
            self.master_camera.start_recording()
        else:
            self.master_camera.stop_recording()

        for node in self.nodes.values():
            node["record_state"] = rec_state

        return {
            "action": act,
            "record_state": rec_state,
            "nodes": [
                {"id": nid, "name": n["name"], "state": n["record_state"], "genlock": n["genlock"]}
                for nid, n in self.nodes.items()
            ]
        }

    def get_status(self) -> Dict[str, Any]:
        """Return full network topology and telemetry."""
        # Update Master node dynamically from actual camera
        if self.master_camera:
            self.nodes["A-CAM"]["name"] = getattr(self.master_camera, "brain_model", "SCARLET-W 5K")
            if hasattr(self.master_camera, "recorder") and self.master_camera.recorder:
                self.nodes["A-CAM"]["record_state"] = self.master_camera.recorder.record_state
        return {
            "genlock": self.genlock_state,
            "timecode_master": self.timecode_master,
            "sync_timecode": self.sync_timecode,
            "nodes_count": len(self.nodes),
            "nodes": [
                {k: v for k, v in node.items() if not k.endswith("_ref")}
                for node in self.nodes.values()
            ]
        }
