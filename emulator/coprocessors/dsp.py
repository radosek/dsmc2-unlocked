"""
Texas Instruments TMS320C64x+ DSP Subsystem & Vision/Audio Processing Servers.
Models DSPLink IPC shared-memory queues, CImagingServer (Autofocus & Haar Face Detection),
and RAudioServer (4-channel audio peak metering & pre-amps).
Parses rdc_dsp_app.out TI COFF firmware executable.
"""

import os
import struct
import math
import io
import wave
from typing import Dict, Any, List, Optional, Tuple
from collections import deque


class TiC64xDsp:
    """
    Texas Instruments TMS320C64x+ Digital Signal Processor.
    Runs TI DSP/BIOS real-time kernel executing imaging and audio algorithms.
    """

    COFF_MAGIC = 0x00C2 # TMS320C6000 COFF magic

    def __init__(self):
        self.is_loaded = False
        self.entry_point = 0x8FA00000
        self.sections: List[Dict[str, Any]] = []
        self.symbols_count = 0
        self.bios_tick_count = 0
        self.dsp_state = "IDLE"

    def load_coff(self, coff_path: str) -> bool:
        """Parse TI COFF executable binary header and sections."""
        if not os.path.exists(coff_path):
            return False

        with open(coff_path, "rb") as f:
            header = f.read(20)
            if len(header) < 20:
                return False

            # COFF File Header:
            # uint16 f_magic, uint16 f_nscns, int32 f_timdat, int32 f_symptr, int32 f_nsyms, uint16 f_opthdr, uint16 f_flags
            magic, n_scns, timdat, symptr, n_syms, opt_hdr_size, flags = struct.unpack("<HHiiiHH", header)
            if magic != self.COFF_MAGIC:
                return False

            self.symbols_count = n_syms

            # Optional Header (usually 28 bytes)
            if opt_hdr_size > 0:
                opt_data = f.read(opt_hdr_size)
                if len(opt_data) >= 20:
                    opt_magic, vstamp, tsize, dsize, bsize, entry = struct.unpack("<hhIIII", opt_data[:20])
                    self.entry_point = entry

            # Section Headers
            self.sections.clear()
            for _ in range(n_scns):
                scn_data = f.read(48)
                if len(scn_data) < 48:
                    break
                s_name = scn_data[:8].split(b"\x00")[0].decode("ascii", errors="ignore")
                paddr, vaddr, size, scnptr = struct.unpack("<IIII", scn_data[8:24])
                self.sections.append({
                    "name": s_name,
                    "paddr": f"0x{paddr:08X}",
                    "vaddr": f"0x{vaddr:08X}",
                    "size_bytes": size
                })

        self.is_loaded = True
        self.dsp_state = "RUNNING"
        return True

    def tick(self, count: int = 1):
        """Advance DSP/BIOS kernel system ticks."""
        if self.is_loaded:
            self.bios_tick_count += count

    def get_status(self) -> Dict[str, Any]:
        return {
            "loaded": self.is_loaded,
            "state": self.dsp_state,
            "architecture": "TMS320C64x+ (TI DSP/BIOS)",
            "entry_point": f"0x{self.entry_point:08X}",
            "sections_count": len(self.sections),
            "symbols_count": self.symbols_count,
            "bios_ticks": self.bios_tick_count
        }


class DspLinkIpc:
    """
    DSPLink Inter-Processor Communication (IPC) Bridge.
    Connects ARM Cortex-A8 (ThreadX) to C64x+ DSP via shared-memory message queues (MSGQ).
    """

    def __init__(self, dsp: TiC64xDsp):
        self.dsp = dsp
        self.host_to_dsp_queue: deque = deque(maxlen=64)
        self.dsp_to_host_queue: deque = deque(maxlen=64)
        self.messages_exchanged = 0

    def send_to_dsp(self, msg_id: int, payload: Dict[str, Any]):
        """Host sends message to DSP queue."""
        self.host_to_dsp_queue.append({"id": msg_id, "payload": payload})
        self.messages_exchanged += 1
        self.dsp.tick(5)

    def recv_from_dsp(self) -> Optional[Dict[str, Any]]:
        """Host dequeues completed message from DSP."""
        if self.dsp_to_host_queue:
            return self.dsp_to_host_queue.popleft()
        return None

    def post_from_dsp(self, msg_id: int, payload: Dict[str, Any]):
        """DSP posts message back to host."""
        self.dsp_to_host_queue.append({"id": msg_id, "payload": payload})


class CImagingServer:
    """
    TI DSP Imaging Command Server (`CImagingServer`).
    Computes autofocus contrast-gradient sharpness curves and executes Haar face detection.
    """

    def __init__(self, ipc: DspLinkIpc):
        self.ipc = ipc
        self.is_af_active = False
        self.last_contrast_score = 85.4
        self.detected_faces: List[Dict[str, Any]] = []

    def compute_focus_contrast(self, roi_box: Tuple[int, int, int, int], focus_distance_m: float) -> float:
        """
        Compute high-frequency spatial luminance contrast for an autofocus ROI.
        Returns sharpness score 0.0 .. 100.0 peaking near target optimal focus (e.g. 2.5m).
        """
        optimal_dist = 2.5 # Simulated sharpest subject plane
        sigma = 0.8
        diff = focus_distance_m - optimal_dist
        # Gaussian sharpness gradient curve
        score = 98.5 * math.exp(-(diff**2) / (2 * sigma**2))
        self.last_contrast_score = round(max(5.0, score), 1)

        self.ipc.send_to_dsp(0x101, {"roi": roi_box, "focus_score": self.last_contrast_score})
        return self.last_contrast_score

    def detect_faces(self, width: int = 1024, height: int = 576) -> List[Dict[str, Any]]:
        """
        Simulate TI VLIB accelerated Haar-cascade face detection on sensor frame.
        Returns list of bounding boxes [x, y, w, h, confidence].
        """
        # Primary cinema subject face in center-left quadrant
        faces = [
            {
                "x": int(width * 0.42),
                "y": int(height * 0.32),
                "w": int(width * 0.18),
                "h": int(height * 0.28),
                "confidence": 0.94,
                "label": "Face 01"
            }
        ]
        self.detected_faces = faces
        self.ipc.send_to_dsp(0x102, {"faces_count": len(faces)})
        return faces

    def get_status(self) -> Dict[str, Any]:
        return {
            "autofocus_sharpness": self.last_contrast_score,
            "detected_faces": self.detected_faces,
            "vlib_acceleration": True
        }


class RAudioServer:
    """
    TI DSP Audio Server (`RAudioServer`).
    Processes 4-channel 24-bit 48kHz audio streams, pre-amp gain, and peak level metering.
    Synthesizes 48kHz PCM / RIFF WAV live audio streams.
    """

    def __init__(self, ipc: DspLinkIpc):
        self.ipc = ipc
        self.sample_rate = 48000
        self.channels_count = 4
        self.preamp_gain_db = [18.0, 18.0, 0.0, 0.0] # Ch1-Ch4 pre-amp gains
        self.peak_dbfs = [-18.5, -19.2, -60.0, -60.0]
        self.is_clipping = [False, False, False, False]
        self.headphone_volume_pct = 75
        self.test_tone_enabled = False
        self.test_tone_freq = 1000.0

    def set_preamp_gain(self, channel: int, gain_db: float):
        """Set pre-amp gain in dB (0.0 to +36.0 dB) for channel (0..3)."""
        if 0 <= channel < 4:
            self.preamp_gain_db[channel] = max(0.0, min(36.0, float(gain_db)))

    def set_test_tone(self, enabled: bool, freq_hz: float = 1000.0):
        """Enable or disable 1kHz calibrated reference tone."""
        self.test_tone_enabled = bool(enabled)
        self.test_tone_freq = float(freq_hz)

    def process_audio_frame(self, ch1_in_db: float = -24.0, ch2_in_db: float = -25.0):
        """Compute live peak metering with pre-amp stage."""
        if self.test_tone_enabled:
            ch1_post = -20.0
            ch2_post = -20.0
        else:
            ch1_post = ch1_in_db + self.preamp_gain_db[0]
            ch2_post = ch2_in_db + self.preamp_gain_db[1]

        self.peak_dbfs[0] = round(max(-60.0, min(0.0, ch1_post)), 1)
        self.peak_dbfs[1] = round(max(-60.0, min(0.0, ch2_post)), 1)
        self.is_clipping[0] = self.peak_dbfs[0] >= -0.5
        self.is_clipping[1] = self.peak_dbfs[1] >= -0.5

    def generate_pcm_samples(self, duration_sec: float = 0.5) -> bytes:
        """
        Generate 48kHz 16-bit stereo PCM audio samples.
        Synthesizes calibrated reference tone or ambient microphone capture with pre-amps.
        """
        total_samples = int(self.sample_rate * max(0.05, min(5.0, duration_sec)))
        vol_scale = self.headphone_volume_pct / 100.0
        
        if self.test_tone_enabled:
            # -20 dBFS reference tone
            amp1 = (10 ** (-20.0 / 20.0)) * 32767.0 * vol_scale
            amp2 = amp1
            omega = 2.0 * math.pi * self.test_tone_freq / self.sample_rate
        else:
            gain1_lin = 10 ** (self.preamp_gain_db[0] / 20.0)
            gain2_lin = 10 ** (self.preamp_gain_db[1] / 20.0)
            base_amp = (10 ** (-42.0 / 20.0)) * 32767.0 * vol_scale
            amp1 = min(32767.0, base_amp * (gain1_lin / 4.0))
            amp2 = min(32767.0, base_amp * (gain2_lin / 4.0))
            omega1 = 2.0 * math.pi * 120.0 / self.sample_rate # Camera body hum
            omega2 = 2.0 * math.pi * 240.0 / self.sample_rate # Harmonic

        buf = bytearray(total_samples * 4) # 2 channels * 2 bytes
        idx = 0
        for i in range(total_samples):
            if self.test_tone_enabled:
                val = int(amp1 * math.sin(omega * i))
                val1 = max(-32768, min(32767, val))
                val2 = val1
            else:
                # Acoustic hum + gentle modulation
                hum = (math.sin(omega1 * i) * 0.7 + math.sin(omega2 * i) * 0.3)
                noise = (((i * 1103515245 + 12345) & 0x7FFF) / 32768.0 - 0.5) * 0.3
                sample_val = hum * 0.7 + noise
                val1 = max(-32768, min(32767, int(amp1 * sample_val)))
                val2 = max(-32768, min(32767, int(amp2 * sample_val)))

            struct.pack_into("<hh", buf, idx, val1, val2)
            idx += 4

        return bytes(buf)

    def get_wav_bytes(self, duration_sec: float = 0.5) -> bytes:
        """Encode 48kHz stereo PCM into standard RIFF WAVE format."""
        pcm = self.generate_pcm_samples(duration_sec)
        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        return out.getvalue()

    def get_status(self) -> Dict[str, Any]:
        return {
            "sample_rate_hz": self.sample_rate,
            "test_tone_enabled": self.test_tone_enabled,
            "test_tone_freq_hz": self.test_tone_freq,
            "channels": [
                {
                    "ch": i + 1,
                    "gain_db": self.preamp_gain_db[i],
                    "peak_dbfs": self.peak_dbfs[i],
                    "clipping": self.is_clipping[i]
                }
                for i in range(4)
            ],
            "headphone_volume_pct": self.headphone_volume_pct
        }
