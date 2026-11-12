"""
Unit and integration tests for Host Audio & Video Streams.
Verifies:
  - TI DSP RAudioServer 48kHz 24-bit/16-bit PCM and RIFF WAV stream generation.
  - 1kHz SMPTE calibrated reference test tone & pre-amp gain scaling.
  - IOB0 Coprocessor HDMI 1080p60 clean & broadcast video rendering (Clean, Broadcast Tally + TC, Frame Guides).
  - Web Studio REST API audio and HDMI stream endpoints.
"""

import os
import io
import wave
import json
import socket
import struct
import urllib.request
import threading
import pytest
from PIL import Image

from emulator.coprocessors.dsp import TiC64xDsp, DspLinkIpc, RAudioServer
from emulator.coprocessors.xtensa import Iob0Coprocessor
from emulator.camera import Dsmc2Camera
from emulator.ui.web import WebStudio, create_handler, ThreadedHTTPServer
from conftest import requires_firmware


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def find_free_port(start: int = 9200) -> int:
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 9250


def test_raudio_server_pcm_and_wav_generation():
    """Verify RAudioServer synthesizes valid 48kHz PCM and RIFF WAVE streams."""
    dsp = TiC64xDsp()
    ipc = DspLinkIpc(dsp)
    audio = RAudioServer(ipc)

    # 1. Verify default audio configuration
    assert audio.sample_rate == 48000
    assert audio.channels_count == 4
    assert audio.headphone_volume_pct == 75

    # 2. Test raw PCM generation (0.1 sec = 4800 samples * 4 bytes = 19200 bytes)
    pcm_bytes = audio.generate_pcm_samples(duration_sec=0.1)
    assert len(pcm_bytes) == 4800 * 4

    # 3. Test RIFF WAV serialization
    wav_bytes = audio.get_wav_bytes(duration_sec=0.1)
    assert len(wav_bytes) > 44
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes[8:12] == b"WAVE"

    # 4. Verify standard wave reader can unpack the stream
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2 # 16-bit
        assert wf.getframerate() == 48000
        frames = wf.readframes(wf.getnframes())
        assert len(frames) == len(pcm_bytes)

    # 5. Test 1kHz reference tone mode
    audio.set_test_tone(True, freq_hz=1000.0)
    assert audio.test_tone_enabled is True
    audio.process_audio_frame()
    assert audio.peak_dbfs[0] == -20.0
    assert audio.peak_dbfs[1] == -20.0

    tone_wav = audio.get_wav_bytes(duration_sec=0.05)
    assert len(tone_wav) > 44


@requires_firmware
def test_iob0_hdmi_output_modes_and_rendering(workspace_root):
    """Verify IOB0 Coprocessor HDMI video modes (Clean, Broadcast Tally, Frame Guides)."""
    camera = Dsmc2Camera(workspace_root)
    camera.power_on()
    studio = WebStudio(workspace_root, camera=camera)

    try:
        assert camera.iob0.hdmi_connected is True
        assert camera.iob0.hdmi_mode == "CLEAN"

        # 1. Clean mode: pristine sensor feed
        img_clean = studio.compositor.compose_hdmi_frame(mode="CLEAN")
        assert isinstance(img_clean, Image.Image)
        assert img_clean.size == (1024, 576)
        assert camera.iob0.hdmi_frames_rendered >= 1

        # 2. Broadcast Tally mode
        camera.start_recording()
        img_tally = studio.compositor.compose_hdmi_frame(mode="BROADCAST_TALLY")
        assert isinstance(img_tally, Image.Image)
        camera.stop_recording()

        # 3. Frame Guides mode (2.39:1 scope)
        img_guides = studio.compositor.compose_hdmi_frame(mode="FRAME_GUIDES")
        assert isinstance(img_guides, Image.Image)
        assert camera.iob0.hdmi_mode == "FRAME_GUIDES"

        # 4. JPEG byte stream export
        jpeg_bytes = studio.get_hdmi_jpeg_bytes(quality=85)
        assert len(jpeg_bytes) > 1000
        assert jpeg_bytes[:2] == b"\xff\xd8" # JPEG SOI magic
    finally:
        camera.power_off()


@requires_firmware
def test_web_studio_audio_and_hdmi_endpoints(workspace_root):
    """Verify Web Studio HTTP API endpoints for audio and HDMI streams."""
    port = find_free_port(9210)
    studio = WebStudio(workspace_root, host="127.0.0.1", port=port)
    studio.start_camera()

    handler = create_handler(studio)
    server = ThreadedHTTPServer(("127.0.0.1", port), handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /api/video/hdmi
        resp = urllib.request.urlopen(f"{base_url}/api/video/hdmi")
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "image/jpeg"
        frame_bytes = resp.read()
        assert frame_bytes[:2] == b"\xff\xd8"

        # 2. GET and POST /api/video/hdmi/mode
        resp = urllib.request.urlopen(f"{base_url}/api/video/hdmi/mode")
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "mode" in data

        req = urllib.request.Request(
            f"{base_url}/api/video/hdmi/mode",
            data=json.dumps({"mode": "BROADCAST_TALLY"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        res_mode = json.loads(resp.read().decode("utf-8"))
        assert res_mode["mode"] == "BROADCAST_TALLY"

        # 3. GET /api/audio/wav
        resp = urllib.request.urlopen(f"{base_url}/api/audio/wav")
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "audio/wav"
        wav_data = resp.read()
        assert wav_data[:4] == b"RIFF"

        # 4. GET /api/audio/status
        resp = urllib.request.urlopen(f"{base_url}/api/audio/status")
        assert resp.status == 200
        aud_stat = json.loads(resp.read().decode("utf-8"))
        assert aud_stat["status"] == "ok"
        assert len(aud_stat["audio"]["channels"]) == 4

        # 5. POST /api/audio/control
        req = urllib.request.Request(
            f"{base_url}/api/audio/control",
            data=json.dumps({"test_tone": True, "headphone_vol": 85, "preamp_ch": 1, "gain_db": 22.0}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        ctrl_res = json.loads(resp.read().decode("utf-8"))
        assert ctrl_res["audio"]["test_tone_enabled"] is True
        assert ctrl_res["audio"]["headphone_volume_pct"] == 85
        assert ctrl_res["audio"]["channels"][0]["gain_db"] == 22.0

    finally:
        server.shutdown()
        studio.stop()
