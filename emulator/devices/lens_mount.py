"""
RED DSMC2 Electronic Lens Mount Subsystem.
Models Canon EF, Nikon F, and PL lens mounts with authentic electronic communication,
aperture/iris stepping, focal length tracking, focus distance, and firmware lens catalogs.
"""

import os
import re
import math
from typing import Dict, List, Optional, Tuple, Any


# Standard DSMC2 1/3 EV Aperture Scale
APERTURE_STOPS_THIRD = [
    1.0, 1.1, 1.2, 1.4, 1.6, 1.8,
    2.0, 2.2, 2.5, 2.8, 3.2, 3.5,
    4.0, 4.5, 5.0, 5.6, 6.3, 7.1,
    8.0, 9.0, 10.0, 11.0, 13.0, 14.0,
    16.0, 18.0, 20.0, 22.0, 25.0, 29.0, 32.0
]


class LensInfo:
    """Represents an electronic or smart cinema lens attached to DSMC2."""

    def __init__(
        self,
        model: str,
        brand: str,
        mount: str,
        focal_min: float,
        focal_max: float,
        max_aperture: float,
        min_aperture: float = 22.0,
        has_stabilization: bool = False,
        has_ultrasonic_motor: bool = True,
        serial: str = "CN-920412",
        cfg_filename: Optional[str] = None
    ):
        self.model = model
        self.brand = brand
        self.mount = mount
        self.focal_min = float(focal_min)
        self.focal_max = float(focal_max)
        self.is_zoom = (self.focal_min != self.focal_max)
        self.max_aperture = float(max_aperture)
        self.min_aperture = float(min_aperture)
        self.has_stabilization = has_stabilization
        self.has_ultrasonic_motor = has_ultrasonic_motor
        self.serial = serial
        self.cfg_filename = cfg_filename

    @property
    def focal_display(self) -> str:
        if self.is_zoom:
            return f"{int(self.focal_min)}-{int(self.focal_max)}mm"
        return f"{int(self.focal_min)}mm"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "brand": self.brand,
            "mount": self.mount,
            "focal_min": self.focal_min,
            "focal_max": self.focal_max,
            "focal_display": self.focal_display,
            "is_zoom": self.is_zoom,
            "max_aperture": self.max_aperture,
            "min_aperture": self.min_aperture,
            "has_stabilization": self.has_stabilization,
            "has_ultrasonic_motor": self.has_ultrasonic_motor,
            "serial": self.serial,
            "cfg_filename": self.cfg_filename
        }


def parse_firmware_lens_cfg(fpath: str) -> Optional[LensInfo]:
    """Parse lens metadata from authentic firmware config filenames in slot/lens/."""
    fname = os.path.basename(fpath)
    if fname.endswith("lens_list.cfg") or not fname.endswith(".cfg"):
        return None

    base = os.path.splitext(fname)[0]
    is_canon = "canon_mount" in fpath.replace("\\", "/")
    mount = "Canon EF" if is_canon else "Nikon F"

    # Identify brand
    brand = "Unknown"
    for b in ["Canon", "Nikon", "Nikkor", "Sigma", "Tamron", "Tokina", "Zeiss", "Cooke", "Angenieux", "Leica"]:
        if b.lower() in base.lower():
            brand = "Nikon" if b == "Nikkor" else b
            break

    # Format model name
    clean_name = base.replace("_", " ").replace("p", ".")
    # Fix common duplicate names
    clean_name = clean_name.replace("  ", " ").strip()

    # Extract focal length
    flen_match = re.search(r"(\d+)(?:-(\d+))?mm", base, re.IGNORECASE)
    if flen_match:
        fmin = float(flen_match.group(1))
        fmax = float(flen_match.group(2)) if flen_match.group(2) else fmin
    else:
        fmin, fmax = 50.0, 50.0

    # Extract max aperture (ensuring 'f' is preceded by '_' or space to avoid 'EF_')
    ap_match = re.search(r"(?:^|[_\s])f_?(\d+)(?:p(\d+))?(?:-(\d+)(?:p(\d+))?)?", base, re.IGNORECASE)
    if ap_match:
        ap_int = ap_match.group(1)
        ap_dec = ap_match.group(2) or "0"
        max_ap = float(f"{ap_int}.{ap_dec}")
    else:
        max_ap = 2.8

    has_is = any(tag in base for tag in ["_IS", "_VR", "_VC", "_OS"])
    has_usm = any(tag in base for tag in ["_USM", "_STM", "_HSM", "_USD", "_SWM", "AF-S", "AF-P"])

    # Synthetic serial from hash of name
    h = abs(hash(fname)) % 900000 + 100000
    serial = f"LNS-{h}"

    return LensInfo(
        model=clean_name,
        brand=brand,
        mount=mount,
        focal_min=fmin,
        focal_max=fmax,
        max_aperture=max_ap,
        min_aperture=22.0,
        has_stabilization=has_is,
        has_ultrasonic_motor=has_usm,
        serial=serial,
        cfg_filename=fname
    )


class LensMount:
    """
    DSMC2 Smart Electronic Lens Mount Controller.
    Supports Canon EF Mount, Nikon F Mount, and PL Intelligent Mount.
    """

    MOUNT_CANON_EF = "Canon EF"
    MOUNT_NIKON_F = "Nikon F"
    MOUNT_PL_INTELLIGENT = "PL Mount (/i)"

    def __init__(self, camera: Any, lens_database_dir: Optional[str] = None):
        self.camera = camera
        self.mount_type = self.MOUNT_CANON_EF
        self.lens_database: List[LensInfo] = []
        self.attached_lens: Optional[LensInfo] = None

        # Current Optical State
        self.current_aperture: float = 2.8
        self.current_focal_length: float = 50.0
        self.current_focus_distance: float = 2.50   # In meters (e.g. 2.5m, 999.0 = Inf)
        self.image_stabilization_enabled: bool = True
        self.autofocus_state: str = "IDLE"           # IDLE, SEARCHING, LOCKED, ERROR

        # Populate lens catalog
        self._load_lens_database(lens_database_dir)

        # Attach default workhorse lens on start
        self._attach_default_lens()

    def _load_lens_database(self, database_dir: Optional[str]):
        """Load authentic RED lens catalog from slot/lens directory if present."""
        if database_dir and os.path.isdir(database_dir):
            for root, _, files in os.walk(database_dir):
                for f in sorted(files):
                    if f.endswith(".cfg") and not f.endswith("lens_list.cfg"):
                        full_p = os.path.join(root, f)
                        info = parse_firmware_lens_cfg(full_p)
                        if info:
                            self.lens_database.append(info)

        # Fallback/standard reference lenses if firmware store is missing or sparse
        if len(self.lens_database) < 4:
            self._inject_standard_lenses()

    def _inject_standard_lenses(self):
        """Standard high-profile cinema and photo lenses available on DSMC2."""
        standards = [
            LensInfo("Canon EF 24-70mm f/2.8L II USM", "Canon", "Canon EF", 24.0, 70.0, 2.8, 22.0, False, True, "CN-748921"),
            LensInfo("Canon EF 50mm f/1.2L USM", "Canon", "Canon EF", 50.0, 50.0, 1.2, 16.0, False, True, "CN-501243"),
            LensInfo("Canon EF 70-200mm f/2.8L IS II USM", "Canon", "Canon EF", 70.0, 200.0, 2.8, 22.0, True, True, "CN-702008"),
            LensInfo("Canon CN-E 17-120mm T2.95 Cine-Servo", "Canon", "Canon EF", 17.0, 120.0, 2.8, 22.0, False, True, "CN-171200"),
            LensInfo("Canon EF 100mm f/2.8L Macro IS USM", "Canon", "Canon EF", 100.0, 100.0, 2.8, 32.0, True, True, "CN-100284"),
            LensInfo("Sigma 18-35mm f/1.8 DC HSM Art", "Sigma", "Canon EF", 18.0, 35.0, 1.8, 16.0, False, True, "SG-183590"),
            LensInfo("Nikon AF-S Nikkor 24-70mm f/2.8G ED", "Nikon", "Nikon F", 24.0, 70.0, 2.8, 22.0, False, True, "NK-247011"),
            LensInfo("Nikon AF-S Nikkor 70-200mm f/2.8G ED VR II", "Nikon", "Nikon F", 70.0, 200.0, 2.8, 22.0, True, True, "NK-702012"),
            LensInfo("Cooke S4/i 35mm T2.0 Prime", "Cooke", "PL Mount (/i)", 35.0, 35.0, 2.0, 22.0, False, False, "CK-350020"),
            LensInfo("Zeiss Supreme Prime 50mm T1.5", "Zeiss", "PL Mount (/i)", 50.0, 50.0, 1.5, 22.0, False, False, "ZS-500015"),
        ]
        # Append only if not already present
        existing_names = {l.model for l in self.lens_database}
        for st in standards:
            if st.model not in existing_names:
                self.lens_database.append(st)

    def _attach_default_lens(self):
        """Attach primary reference lens matching current mount."""
        matches = [l for l in self.lens_database if l.mount == self.mount_type]
        if matches:
            # Prefer 24-70 or first lens
            workhorse = next((l for l in matches if "24-70mm" in l.model), matches[0])
            self.attach_lens(workhorse)

    def attach_lens(self, lens: LensInfo):
        """Physically mount an electronic lens to the DSMC2 body."""
        self.attached_lens = lens
        self.mount_type = lens.mount

        # Optical initialization: start aperture at nearest stop >= max_aperture
        avail_stops = self.get_available_aperture_stops()
        self.current_aperture = avail_stops[0] if avail_stops else lens.max_aperture
        self.current_focal_length = lens.focal_min if not lens.is_zoom else round((lens.focal_min + lens.focal_max) / 2.0, 1)
        self.current_focus_distance = 2.50
        self.autofocus_state = "IDLE"

        # Sync to RCP and Camera
        self._sync_state_to_rcp()

        if hasattr(self.camera, "log_system"):
            self.camera.log_system(
                f"[LENS] Electronic {self.mount_type} lens attached: {lens.model} (SN: {lens.serial}, max f/{lens.max_aperture:.1f})"
            )

    def detach_lens(self):
        """Detach currently mounted lens (body cap / bare mount)."""
        if not self.attached_lens:
            return
        old_model = self.attached_lens.model
        self.attached_lens = None
        self.current_aperture = 0.0
        self.current_focal_length = 0.0
        self.current_focus_distance = 0.0
        self.autofocus_state = "IDLE"

        self._sync_state_to_rcp()

        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[LENS] Lens detached from mount ({old_model}).")

    def get_available_aperture_stops(self) -> List[float]:
        """Return valid 1/3-stop apertures supported by the attached lens."""
        if not self.attached_lens:
            return []
        fmin = self.attached_lens.max_aperture
        fmax = self.attached_lens.min_aperture

        stops = [s for s in APERTURE_STOPS_THIRD if (s >= (fmin - 0.05) and s <= (fmax + 0.05))]
        if not stops or (stops[0] > fmin + 0.1):
            stops.insert(0, fmin)
        return sorted(list(set(stops)))

    def set_aperture(self, f_number: float) -> bool:
        """Drive electronic aperture motor to desired f-number."""
        if not self.attached_lens:
            return False

        stops = self.get_available_aperture_stops()
        if not stops:
            return False

        # Snap to closest available stop
        closest = min(stops, key=lambda s: abs(s - f_number))
        self.current_aperture = closest
        self._sync_state_to_rcp()

        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[LENS] Iris stepped to f/{self.current_aperture:.1f}")
        return True

    def step_aperture(self, step_delta: int) -> bool:
        """Step aperture up (+1 stop down / darker) or down (-1 open up / brighter)."""
        stops = self.get_available_aperture_stops()
        if not stops:
            return False

        try:
            curr_idx = min(range(len(stops)), key=lambda i: abs(stops[i] - self.current_aperture))
            new_idx = max(0, min(len(stops) - 1, curr_idx + step_delta))
            return self.set_aperture(stops[new_idx])
        except Exception:
            return False

    def set_focal_length(self, focal_mm: float) -> bool:
        """Adjust zoom ring focal length."""
        if not self.attached_lens:
            return False
        clamped = max(self.attached_lens.focal_min, min(self.attached_lens.focal_max, focal_mm))
        self.current_focal_length = round(clamped, 1)
        self._sync_state_to_rcp()

        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[LENS] Focal length adjusted to {self.current_focal_length:.0f}mm")
        return True

    def set_focus_distance(self, distance_m: float) -> bool:
        """Drive ultrasonic / stepper focus motor to target distance (m)."""
        if not self.attached_lens:
            return False
        # Minimum focus distance typically 0.25m, max 999m (Infinity)
        self.current_focus_distance = max(0.25, min(999.0, distance_m))
        self._sync_state_to_rcp()

        dist_str = "INF" if self.current_focus_distance >= 500.0 else f"{self.current_focus_distance:.2f}m"
        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[LENS] Focus distance set to {dist_str}")
        return True

    def trigger_autofocus(self, target_point: Optional[Tuple[int, int]] = None) -> bool:
        """Execute electronic autofocus sweep at target reticle."""
        if not self.attached_lens:
            return False

        self.autofocus_state = "SEARCHING"
        if hasattr(self.camera, "log_system"):
            pt_str = f"at ({target_point[0]}, {target_point[1]})" if target_point else "center reticle"
            self.camera.log_system(f"[AF] AF sweep initiated {pt_str}...")

        # Calculate simulated target distance based on reticle location
        # Reticles near bottom/corners simulate nearer objects; center is subject distance
        dist = 2.45
        if target_point:
            tx, ty = target_point
            dist = round(1.2 + ((tx % 300) / 100.0) + ((ty % 200) / 100.0), 2)

        self.current_focus_distance = dist
        self.autofocus_state = "LOCKED"
        self._sync_state_to_rcp()

        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[AF] Contrast AF Phase-Lock ACHIEVED: {self.current_focus_distance:.2f}m")
        return True

    def set_mount_type(self, mount_type: str):
        """Swap physical lens mount (Canon EF, Nikon F, PL)."""
        if mount_type == self.mount_type:
            return
        self.detach_lens()
        self.mount_type = mount_type
        if hasattr(self.camera, "log_system"):
            self.camera.log_system(f"[MOUNT] Swapped lens mount to {mount_type}")
        self._attach_default_lens()

    def _sync_state_to_rcp(self):
        """Propagate current optical parameters to camera RCP state table."""
        if not hasattr(self.camera, "rcp"):
            return

        rcp = self.camera.rcp
        if self.attached_lens:
            rcp.state["lens_name"] = self.attached_lens.model
            rcp.state["lens_brand"] = self.attached_lens.brand
            rcp.state["lens_mount"] = self.attached_lens.mount
            rcp.state["lens_serial"] = self.attached_lens.serial
            rcp.state["aperture"] = f"f/{self.current_aperture:.1f}"
            rcp.state["aperture_num"] = str(self.current_aperture)
            rcp.state["focal_length"] = f"{int(self.current_focal_length)}mm"
            rcp.state["focal_length_num"] = str(self.current_focal_length)
            rcp.state["focus_distance"] = "INF" if self.current_focus_distance >= 500.0 else f"{self.current_focus_distance:.2f}m"
            rcp.state["focus_distance_m"] = str(self.current_focus_distance)
            rcp.state["lens_flen_min"] = str(self.attached_lens.focal_min)
            rcp.state["lens_flen_max"] = str(self.attached_lens.focal_max)
            rcp.state["af_state"] = self.autofocus_state
        else:
            rcp.state["lens_name"] = "No Lens"
            rcp.state["lens_brand"] = "None"
            rcp.state["lens_mount"] = self.mount_type
            rcp.state["lens_serial"] = "N/A"
            rcp.state["aperture"] = "f/--"
            rcp.state["aperture_num"] = "0.0"
            rcp.state["focal_length"] = "--mm"
            rcp.state["focal_length_num"] = "0"
            rcp.state["focus_distance"] = "--"
            rcp.state["focus_distance_m"] = "0"
            rcp.state["lens_flen_min"] = "0"
            rcp.state["lens_flen_max"] = "0"
            rcp.state["af_state"] = "IDLE"

    def get_status(self) -> Dict[str, Any]:
        """Return full JSON-serializable status dictionary for Web Studio and API."""
        return {
            "mount_type": self.mount_type,
            "attached": self.attached_lens is not None,
            "lens": self.attached_lens.to_dict() if self.attached_lens else None,
            "current_aperture": self.current_aperture,
            "aperture_display": f"f/{self.current_aperture:.1f}" if self.attached_lens else "f/--",
            "available_stops": self.get_available_aperture_stops(),
            "current_focal_length": self.current_focal_length,
            "focal_display": f"{int(self.current_focal_length)}mm" if self.attached_lens else "--mm",
            "current_focus_distance": self.current_focus_distance,
            "focus_display": ("INF" if self.current_focus_distance >= 500.0 else f"{self.current_focus_distance:.2f}m") if self.attached_lens else "--",
            "image_stabilization_enabled": self.image_stabilization_enabled,
            "autofocus_state": self.autofocus_state,
            "catalog_count": len(self.lens_database)
        }
