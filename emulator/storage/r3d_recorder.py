"""
RED DSMC2 R3D Clip Recorder & RED MINI-MAG Media Subsystem.
Models authentic RED MINI-MAG media storage, directory layouts,
clip naming conventions (e.g. A001_C001_0101AB_001.RDC),
.R3D ISO container generation, and .RMD XML metadata sidecars.
"""

import os
import struct
import time
import threading
from typing import Dict, Any, List, Optional


class R3dClipRecorder:
    """
    Simulates REDCODE R3D recording to virtual RED MINI-MAG media.
    Manages reel progression, clip numbering, container generation, and metadata sidecars.
    """

    MEDIA_CAPACITY_GB = 512.0
    DATA_RATE_MB_PER_SEC = 96.0 # ~5K 16:9 REDCODE 5:1 @ 24fps

    def __init__(self, camera: Any, storage_root: str):
        self.camera = camera
        self.storage_root = os.path.abspath(storage_root)
        self.media_dir = os.path.join(self.storage_root, "persistent_store", "media")
        os.makedirs(self.media_dir, exist_ok=True)

        # Media Reel State
        self.camera_letter = "A"
        self.reel_number = 1
        self.clip_number = 1
        self.camera_id_code = "0101AB"
        self.total_capacity_mb = self.MEDIA_CAPACITY_GB * 1024.0
        self.used_space_mb = 112.0 * 1024.0 # Baseline demo usage
        self.is_media_mounted = True

        # Active Recording State
        self.is_recording = False
        self.current_clip_name: Optional[str] = None
        self.current_rdc_path: Optional[str] = None
        self.current_r3d_path: Optional[str] = None
        self.current_rmd_path: Optional[str] = None
        self.record_start_time: float = 0.0
        self.record_frames: int = 0
        self.record_start_tc = "01:00:00:00"

        # Lock and worker thread
        self._lock = threading.RLock()
        self._worker: Optional[threading.Thread] = None

    @property
    def record_state(self) -> int:
        """DSMC2 record state: 0 = idle, 2 = recording."""
        return 2 if self.is_recording else 0

    @property
    def current_reel_id(self) -> str:
        return f"{self.camera_letter}{self.reel_number:03d}"

    @property
    def free_space_mb(self) -> float:
        return max(0.0, self.total_capacity_mb - self.used_space_mb)

    @property
    def media_remaining_percent(self) -> int:
        if self.total_capacity_mb <= 0:
            return 0
        return int((self.free_space_mb / self.total_capacity_mb) * 100)

    def start_recording(self) -> bool:
        """Begin recording a new authentic REDCODE R3D clip."""
        with self._lock:
            if self.is_recording:
                return True
            if not self.is_media_mounted:
                if hasattr(self.camera, "log_system"):
                    self.camera.log_system("[REC] ERROR: No RED MINI-MAG mounted.")
                return False
            if self.free_space_mb < 500.0:
                if hasattr(self.camera, "log_system"):
                    self.camera.log_system("[REC] ERROR: RED MINI-MAG is FULL.")
                return False

            self.is_recording = True
            self.record_start_time = time.time()
            self.record_frames = 0

            # Generate DSMC2 Clip Identifier: e.g. A001_C001_0101AB_001
            clip_id = f"{self.current_reel_id}_C{self.clip_number:03d}_{self.camera_id_code}_001"
            self.current_clip_name = clip_id

            # Reel Folder & Clip .RDC Container
            reel_dir = os.path.join(self.media_dir, f"{self.current_reel_id}_{self.camera_id_code}")
            rdc_dir = os.path.join(reel_dir, f"{clip_id}.RDC")
            os.makedirs(rdc_dir, exist_ok=True)

            self.current_rdc_path = rdc_dir
            self.current_r3d_path = os.path.join(rdc_dir, f"{clip_id}.R3D")
            self.current_rmd_path = os.path.join(rdc_dir, f"{clip_id}.RMD")
            rtn_path = os.path.join(rdc_dir, f"{clip_id}.rtn")

            # Calculate start timecode
            base_min = (self.clip_number * 3) % 60
            self.record_start_tc = f"01:{base_min:02d}:00:00"

            # Touch rtn thumbnail marker
            with open(rtn_path, "wb") as f:
                f.write(b"RED_THUMBNAIL_STREAM_CACHE_V2\x00")

            # Write Initial R3D Header Atom
            self._write_initial_r3d_file(self.current_r3d_path, clip_id)

            # Sync RCP and camera
            if hasattr(self.camera, "rcp"):
                self.camera.rcp.state["record_state"] = "2"
                self.camera.rcp.state["media_remaining_percent"] = str(self.media_remaining_percent)

            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[REC] ● Started recording: {clip_id}.RDC (TC: {self.record_start_tc})")

            # Start background frame generator
            self._worker = threading.Thread(target=self._record_worker, daemon=True, name="R3dClipRecorder")
            self._worker.start()
            return True

    def stop_recording(self) -> bool:
        """Stop active recording and finalize .R3D and .RMD sidecar files."""
        with self._lock:
            if not self.is_recording:
                return False

            self.is_recording = False
            duration = max(0.1, time.time() - self.record_start_time)
            fps_val = float(self.camera.rcp.state.get("frame_rate", "24.00")) if hasattr(self.camera, "rcp") else 24.0
            total_frames = max(1, int(duration * fps_val))
            self.record_frames = total_frames

            # Calculate end timecode
            secs = total_frames // int(fps_val)
            rem_frames = total_frames % int(fps_val)
            start_parts = [int(p) for p in self.record_start_tc.split(":")]
            end_s = start_parts[2] + secs
            end_m = start_parts[1] + (end_s // 60)
            end_s %= 60
            end_h = start_parts[0] + (end_m // 60)
            end_m %= 60
            end_tc = f"{end_h:02d}:{end_m:02d}:{end_s:02d}:{rem_frames:02d}"

            # Finalize .R3D container and append simulated media payload
            clip_mb = (duration * self.DATA_RATE_MB_PER_SEC)
            self.used_space_mb += clip_mb
            self._finalize_r3d_file(self.current_r3d_path, self.current_clip_name, total_frames, clip_mb)

            # Write Authentic .RMD XML Sidecar
            self._write_rmd_sidecar(self.current_rmd_path, self.current_clip_name, total_frames, self.record_start_tc, end_tc)

            # Increment clip counter
            saved_name = self.current_clip_name
            self.clip_number += 1
            self.current_clip_name = None

            # Sync RCP and camera
            if hasattr(self.camera, "rcp"):
                self.camera.rcp.state["record_state"] = "0"
                self.camera.rcp.state["media_remaining_percent"] = str(self.media_remaining_percent)

            if hasattr(self.camera, "log_system"):
                self.camera.log_system(
                    f"[REC] ■ Closed clip {saved_name}.RDC ({total_frames} frames, {clip_mb:.1f} MB, {duration:.1f}s)"
                )
            return True

    def toggle_recording(self) -> bool:
        """Toggle recording state."""
        if self.is_recording:
            return self.stop_recording()
        else:
            return self.start_recording()

    def format_media(self) -> bool:
        """Format the virtual RED MINI-MAG, reinitializing reel structure."""
        with self._lock:
            if self.is_recording:
                self.stop_recording()

            # Clean all files in media directory
            if os.path.exists(self.media_dir):
                for item in os.listdir(self.media_dir):
                    item_path = os.path.join(self.media_dir, item)
                    try:
                        if os.path.isdir(item_path):
                            import shutil
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                    except Exception:
                        pass

            self.reel_number += 1
            self.clip_number = 1
            self.used_space_mb = 12.0 # Minimal filesystem overhead
            self.is_media_mounted = True

            if hasattr(self.camera, "rcp"):
                self.camera.rcp.state["media_remaining_percent"] = str(self.media_remaining_percent)

            if hasattr(self.camera, "log_system"):
                self.camera.log_system(
                    f"[MEDIA] RED MINI-MAG {int(self.MEDIA_CAPACITY_GB)}GB formatted (UDF/FAT32). Reel {self.current_reel_id} initialized."
                )
            return True

    def eject_media(self) -> bool:
        """Unmount virtual RED MINI-MAG."""
        with self._lock:
            if self.is_recording:
                self.stop_recording()
            self.is_media_mounted = False
            if hasattr(self.camera, "rcp"):
                self.camera.rcp.state["media_remaining_percent"] = "0"
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[MEDIA] RED MINI-MAG unmounted and ejected safely.")
            return True

    def mount_media(self) -> bool:
        """Mount virtual RED MINI-MAG."""
        with self._lock:
            self.is_media_mounted = True
            if hasattr(self.camera, "rcp"):
                self.camera.rcp.state["media_remaining_percent"] = str(self.media_remaining_percent)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[MEDIA] RED MINI-MAG {int(self.MEDIA_CAPACITY_GB)}GB mounted on SATA0.")
            return True

    def list_clips(self) -> List[Dict[str, Any]]:
        """Scan media directory and return list of recorded clips with full metadata."""
        clips = []
        if not os.path.isdir(self.media_dir):
            return clips

        for root, dirs, _ in os.walk(self.media_dir):
            for d in sorted(dirs):
                if d.endswith(".RDC"):
                    clip_id = d[:-4]
                    rdc_path = os.path.join(root, d)
                    r3d_path = os.path.join(rdc_path, f"{clip_id}.R3D")
                    rmd_path = os.path.join(rdc_path, f"{clip_id}.RMD")

                    size_mb = 0.0
                    if os.path.exists(r3d_path):
                        size_mb = round(os.path.getsize(r3d_path) / (1024.0 * 1024.0), 2)

                    rmd_content = ""
                    if os.path.exists(rmd_path):
                        try:
                            with open(rmd_path, "r", encoding="utf-8", errors="ignore") as f:
                                rmd_content = f.read()
                        except Exception:
                            pass

                    clips.append({
                        "clip_name": clip_id,
                        "rdc_dir": rdc_path,
                        "r3d_path": r3d_path,
                        "rmd_path": rmd_path,
                        "size_mb": size_mb,
                        "rmd_metadata": rmd_content
                    })
        return clips

    def _record_worker(self):
        """Worker thread executing during active recording."""
        while self.is_recording:
            time.sleep(0.5)
            # Increment frames and adjust media space in real-time
            with self._lock:
                if not self.is_recording:
                    break
                duration = time.time() - self.record_start_time
                fps = float(self.camera.rcp.state.get("frame_rate", "24.00")) if hasattr(self.camera, "rcp") else 24.0
                self.record_frames = int(duration * fps)

                # Periodic update of media space remaining in RCP
                if hasattr(self.camera, "rcp"):
                    self.camera.rcp.state["media_remaining_percent"] = str(self.media_remaining_percent)

    def _write_initial_r3d_file(self, path: str, clip_name: str):
        """Create authentic RED R3D ISO file container with 'RED2' magic and metadata atom."""
        with open(path, "wb") as f:
            # 1. 'ftyp' box
            # 4 bytes size, 4 bytes type, 4 bytes major brand, 4 bytes minor version, 4 bytes compatible brands
            ftyp_box = struct.pack(">I4s4sI4s", 20, b"ftyp", b"RED2", 1, b"r3d ")
            f.write(ftyp_box)

            # 2. 'rdxm' (RED Metadata Atom)
            cam_name = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K") if hasattr(self.camera, "vfs") else "SCARLET-W"
            header_meta = f"CLIP={clip_name};CAM={cam_name};FMT=5K;CODEC=REDCODE-RAW;DATE={time.strftime('%Y-%m-%d %H:%M:%S')}"
            meta_bytes = header_meta.encode("utf-8")
            rdxm_len = 8 + len(meta_bytes)
            f.write(struct.pack(">I4s", rdxm_len, b"rdxm"))
            f.write(meta_bytes)

            # 3. 'mdat' header (Media Data Atom)
            f.write(struct.pack(">I4s", 0, b"mdat")) # 0 = runs to EOF or updated later

    def _finalize_r3d_file(self, path: str, clip_name: str, total_frames: int, clip_mb: float):
        """Finalize .R3D file by padding simulated raw wavelet frames and updating footer."""
        if not path or not os.path.exists(path):
            return

        with open(path, "ab") as f:
            # Append simulated wavelet frame markers
            for i in range(min(total_frames, 64)):
                frame_hdr = struct.pack(">4sII", b"REDf", i, 65536) # Frame box
                f.write(frame_hdr)
                f.write(b"\x00" * 512) # Frame payload chunk

            # Write R3D footer index
            footer_data = f"INDEX_EOF;FRAMES={total_frames};SIZE_MB={clip_mb:.2f};STATUS=FINAL".encode("utf-8")
            f.write(struct.pack(">I4s", len(footer_data) + 8, b"r3di"))
            f.write(footer_data)

    def _write_rmd_sidecar(self, path: str, clip_name: str, total_frames: int, start_tc: str, end_tc: str):
        """Generate authentic RED .RMD XML sidecar containing full camera, exposure, and lens metadata."""
        if not path:
            return

        rcp = self.camera.rcp if hasattr(self.camera, "rcp") else None
        fps = rcp.state.get("frame_rate", "23.976") if rcp else "23.976"
        iso = rcp.state.get("iso", "800") if rcp else "800"
        kelvin = rcp.state.get("color_temperature", "5600") if rcp else "5600"
        shutter = rcp.state.get("shutter_angle", "180.0") if rcp else "180.0"
        format_name = rcp.state.get("record_format", "5K 16:9") if rcp else "5K 16:9"
        cam_model = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K") if hasattr(self.camera, "vfs") else "SCARLET-W"
        cam_pin = self.camera.vfs.env.get("CAMERA_PIN", "10042") if hasattr(self.camera, "vfs") else "10042"

        lm = getattr(self.camera, "lens_mount", None)
        lens_name = lm.attached_lens.model if (lm and lm.attached_lens) else "Unknown Lens"
        lens_brand = lm.attached_lens.brand if (lm and lm.attached_lens) else "N/A"
        lens_mount = lm.mount_type if lm else "Canon EF"
        lens_serial = lm.attached_lens.serial if (lm and lm.attached_lens) else "N/A"
        lens_focal = f"{int(lm.current_focal_length)}" if lm else "50"
        lens_aperture = f"{lm.current_aperture:.1f}" if lm else "2.8"
        lens_dist = f"{lm.current_focus_distance:.2f}" if lm else "2.50"

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<RED_METADATA version="1.0">
  <CLIP_NAME>{clip_name}</CLIP_NAME>
  <CAMERA_MODEL>{cam_model}</CAMERA_MODEL>
  <CAMERA_PIN>{cam_pin}</CAMERA_PIN>
  <REEL_ID>{self.current_reel_id}</REEL_ID>
  <CLIP_INDEX>{self.clip_number}</CLIP_INDEX>
  <FRAME_RATE>{fps}</FRAME_RATE>
  <TOTAL_FRAMES>{total_frames}</TOTAL_FRAMES>
  <RESOLUTION>5120x2700</RESOLUTION>
  <RECORD_FORMAT>{format_name}</RECORD_FORMAT>
  <COMPRESSION_RATIO>5:1</COMPRESSION_RATIO>
  <ISO>{iso}</ISO>
  <COLOR_TEMP>{kelvin}</COLOR_TEMP>
  <TINT>0.0</TINT>
  <SHUTTER_ANGLE>{shutter}</SHUTTER_ANGLE>
  <TIMECODE_START>{start_tc}</TIMECODE_START>
  <TIMECODE_END>{end_tc}</TIMECODE_END>
  <LENS>
    <MOUNT>{lens_mount}</MOUNT>
    <NAME>{lens_name}</NAME>
    <BRAND>{lens_brand}</BRAND>
    <SERIAL>{lens_serial}</SERIAL>
    <FOCAL_LENGTH>{lens_focal}</FOCAL_LENGTH>
    <APERTURE>{lens_aperture}</APERTURE>
    <FOCUS_DISTANCE>{lens_dist}</FOCUS_DISTANCE>
  </LENS>
  <CREATION_TIME>{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}</CREATION_TIME>
</RED_METADATA>
"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
