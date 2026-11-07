"""
Tests for Phase 3 and Phase 4: Dedicated Coprocessors (IOB0, IOB1, ISP1, ISP2),
TI TMS320C64x+ DSP Subsystem, C2C Transport, and Accessory Bus TLV Enumeration.
"""

import os
import json
import urllib.request
import threading
import pytest

from emulator.camera import Dsmc2Camera
from emulator.coprocessors.c2c import C2cTransport
from emulator.coprocessors.xtensa import XtensaCore, Iob0Coprocessor, Iob1Coprocessor, IspCoprocessor
from emulator.coprocessors.dsp import TiC64xDsp, DspLinkIpc, CImagingServer, RAudioServer
from emulator.devices.accessory_bus import AccessoryBus, ModuleDescriptor
from emulator.ui.web import WebStudio, ThreadedHTTPServer, create_handler, find_free_port


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def camera(workspace_root):
    cam = Dsmc2Camera(workspace_root)
    return cam


def test_xtensa_core_and_iob0_binaries(workspace_root):
    """Verify Xtensa coprocessor model loads genuine IOB0 binaries from firmware slot."""
    iob0 = Iob0Coprocessor()
    assert iob0.core_id == 0
    assert iob0.state == XtensaCore.STATE_UNINITIALIZED

    iram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "iob0", "iram.bin")
    dram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "iob0", "dram.bin")

    success = iob0.load_binaries(iram_path, dram_path)
    assert success is True
    assert iob0.state == XtensaCore.STATE_READY
    assert iob0.pc == XtensaCore.IRAM_BASE

    # Step execution
    iob0.step(10)
    assert iob0.instructions_executed == 10
    assert iob0.cycles_executed == 20
    assert iob0.state == XtensaCore.STATE_RUNNING


def test_iob0_sata_and_accelerometer():
    """Verify IOB0 SATA 3.0 DMA accounting and STACCELERO SPI horizon tilt calculations."""
    iob0 = Iob0Coprocessor()

    # SATA 3.0 HBA
    assert iob0.sata_link_up is True
    assert iob0.sata_link_speed_gbps == 6.0
    iob0.record_frame_dma(8 * 1024 * 1024) # 8 MB frame
    assert iob0.sata_dma_frames_written == 1
    assert iob0.sata_bytes_transferred == 8 * 1024 * 1024

    # STACCELERO Accelerometer
    # Level camera: x=0, y=0, z=1.0
    iob0.set_accelerometer(0.0, 0.0, 1.0)
    pitch, roll, is_level = iob0.get_tilt_angles()
    assert pitch == 0.0
    assert roll == 0.0
    assert is_level is True

    # Tilted camera: roll = 15°
    iob0.set_accelerometer(-0.2588, 0.0, 0.9659)
    pitch, roll, is_level = iob0.get_tilt_angles()
    assert abs(roll - 15.0) < 0.5
    assert is_level is False


def test_iob1_black_shading_and_defects(workspace_root):
    """Verify IOB1 sensor calibration coprocessor and defect table processing."""
    iob1 = Iob1Coprocessor()
    iram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "iob1", "iram.bin")
    dram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "iob1", "dram.bin")
    assert iob1.load_binaries(iram_path, dram_path) is True

    # Factory defect map
    assert len(iob1.factory_defects) == 3

    # Execute black shading calibration
    res = iob1.run_black_shading(sensor_temp_c=40.0, exposure="1/48")
    assert res["status"] == "CALIBRATED"
    assert res["target_temp_c"] == 40.0
    assert res["target_exposure"] == "1/48"
    assert res["defects_masked"] == 5 # 3 factory + 2 user
    assert len(iob1.user_defects) == 2

    # Process sensor frame defect replacement
    corrected = iob1.process_sensor_frame(5120, 2700)
    assert corrected == 5
    assert iob1.pixels_corrected_total == 5


def test_isp_wavelet_compression(workspace_root):
    """Verify ISP1/ISP2 REDCODE wavelet compression engine and DDR training."""
    isp = IspCoprocessor(core_id=2)
    iram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "isp", "iram.bin")
    dram_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "isp", "dram.bin")
    assert isp.load_binaries(iram_path, dram_path) is True

    # DDR training status
    assert isp.ddr_training_passed is True

    # Simulate raw frame compression at 8:1
    raw_frame = b"\x80" * (1024 * 1024) # 1 MB raw Bayer data
    res = isp.compress_frame(raw_frame, ratio="8:1")
    assert res["ratio"] == "8:1"
    assert res["compressed_size_bytes"] == len(raw_frame) // 8
    assert "slice_crcs" in res
    assert len(res["slice_crcs"]) == 4 # G1, B, R, G2
    assert isp.frames_compressed == 1


def test_c2c_mailbox_transport():
    """Verify Chip-to-Chip mailbox MMIO registers, FIFO, and coprocessor packet routing."""
    c2c = C2cTransport()
    assert c2c.read(C2cTransport.REG_CTRL, 4) == 0x01
    assert c2c.read(C2cTransport.REG_STATUS, 4) & C2cTransport.STAT_TX_EMPTY

    iob0 = Iob0Coprocessor()
    c2c.register_coprocessor(C2cTransport.CORE_IOB0, iob0)

    # Send command packet to IOB0 (cmd 0x10 = Query SATA)
    resp = c2c.send_packet(C2cTransport.CORE_IOB0, cmd=0x10, payload=[0x01])
    assert resp is not None
    assert resp[0] == 0x01 # SATA Link Up


def test_dsp_coff_parser_and_dsplink(workspace_root):
    """Verify TI TMS320C64x+ DSP parses rdc_dsp_app.out COFF binary and DSPLink IPC queues."""
    dsp = TiC64xDsp()
    coff_path = os.path.join(workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsp", "rdc_dsp_app.out")

    success = dsp.load_coff(coff_path)
    assert success is True
    assert dsp.is_loaded is True
    assert dsp.dsp_state == "RUNNING"
    assert dsp.symbols_count > 0
    assert len(dsp.sections) > 0

    # DSPLink IPC
    dsplink = DspLinkIpc(dsp)
    dsplink.send_to_dsp(0x10, {"cmd": "INIT"})
    assert dsplink.messages_exchanged == 1
    assert dsp.bios_tick_count > 0


def test_dsp_imaging_and_audio_servers():
    """Verify CImagingServer (Autofocus contrast & Haar face detection) and RAudioServer."""
    dsp = TiC64xDsp()
    dsplink = DspLinkIpc(dsp)
    imaging = CImagingServer(dsplink)
    audio = RAudioServer(dsplink)

    # 1. Autofocus contrast calculation
    score_near = imaging.compute_focus_contrast((400, 200, 600, 400), focus_distance_m=2.5)
    score_far = imaging.compute_focus_contrast((400, 200, 600, 400), focus_distance_m=10.0)
    assert score_near > score_far
    assert score_near > 90.0

    # 2. Haar Face Detection
    faces = imaging.detect_faces(1024, 576)
    assert len(faces) >= 1
    assert faces[0]["confidence"] > 0.9

    # 3. Audio Server 4-Channel Peak Metering
    audio.set_preamp_gain(0, 18.0)
    audio.set_preamp_gain(1, 18.0)
    audio.process_audio_frame(-24.0, -25.0)
    assert audio.peak_dbfs[0] == -6.0
    assert audio.peak_dbfs[1] == -7.0
    assert audio.is_clipping[0] is False


def test_accessory_bus_tlv_enumeration():
    """Verify ModuleDescriptor binary TLV serialization and AccessoryBus enumeration."""
    # 1. Binary TLV Serialization
    desc = ModuleDescriptor("DSMC2 Base Expander", "720-0033", 104921, max_power_w=12)
    data = desc.serialize()
    assert data[:7] == b"REDMOD\x01"

    # Base64 UART transmission
    b64_str = desc.to_base64()
    decoded_desc = ModuleDescriptor.from_base64(b64_str)
    assert decoded_desc is not None
    assert decoded_desc.name == "DSMC2 Base Expander"
    assert decoded_desc.pin == "720-0033"
    assert decoded_desc.serial == 104921
    assert decoded_desc.max_power_w == 12

    # 2. Accessory Bus
    bus = AccessoryBus()
    assert "720-0033" in bus.attached_modules
    assert "730-0024" in bus.attached_modules # RED Touch 7.0
    assert "750-0075" in bus.attached_modules # MINI-MAG 512GB

    # UART Protocol Handshake: WHO, VERSION, REDINFO
    assert bus.handle_uart_handshake("WHO") == "BASE_EXPANDER"
    assert "7.4.1" in bus.handle_uart_handshake("VERSION")
    assert bus.handle_uart_handshake("REDINFO") != "NONE"

    # Hot-plug attach REDVOLT Expander
    res = bus.attach_module("720-0034", serial=501234)
    assert res is not None
    assert res["name"] == "DSMC2 REDVOLT Expander"
    assert "720-0034" in bus.attached_modules

    # Detach module
    detached = bus.detach_module("720-0034")
    assert detached is True
    assert "720-0034" not in bus.attached_modules


def test_camera_coprocessors_and_dsp_integration(camera):
    """Verify camera initializes and orchestrates all coprocessors, DSP, and accessories."""
    assert hasattr(camera, "c2c")
    assert hasattr(camera, "iob0")
    assert hasattr(camera, "iob1")
    assert hasattr(camera, "isp1")
    assert hasattr(camera, "isp2")
    assert hasattr(camera, "dsp")
    assert hasattr(camera, "imaging_server")
    assert hasattr(camera, "audio_server")
    assert hasattr(camera, "accessory_bus")

    # Camera power on loads and boots coprocessors
    camera.power_on()
    assert camera.iob0.state == XtensaCore.STATE_READY
    assert camera.iob1.state == XtensaCore.STATE_READY
    assert camera.dsp.is_loaded is True

    # Camera helper methods
    shading_res = camera.run_black_shading()
    assert shading_res["status"] == "CALIBRATED"

    faces = camera.detect_faces()
    assert len(faces) >= 1

    contrast = camera.compute_focus_contrast()
    assert contrast > 50.0

    # Attached modules
    status = camera.accessory_bus.get_status()
    assert status["count"] >= 3


def test_web_studio_coprocessors_endpoints(workspace_root):
    """Verify Web Studio REST API handles coprocessors, calibration, and accessories."""
    test_port = find_free_port(9100)
    studio = WebStudio(workspace_root, host="127.0.0.1", port=test_port)
    studio.start_camera()

    handler = create_handler(studio)
    server = ThreadedHTTPServer(("127.0.0.1", test_port), handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    base_url = f"http://127.0.0.1:{test_port}"

    try:
        # 1. GET /api/status telemetry contains coprocessors and accessories
        resp = urllib.request.urlopen(f"{base_url}/api/status")
        assert resp.status == 200
        status = json.loads(resp.read().decode("utf-8"))
        assert "coprocessors" in status
        assert "accessories" in status
        assert status["coprocessors"]["iob0"]["sata"]["speed_gbps"] == 6.0
        assert status["accessories"]["count"] >= 3

        # 2. POST /api/hardware/calibrate
        req = urllib.request.Request(f"{base_url}/api/hardware/calibrate", data=b"{}", headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        cal_data = json.loads(resp.read().decode("utf-8"))
        assert cal_data["status"] == "CALIBRATED"

        # 3. POST /api/hardware/face_detect
        req = urllib.request.Request(f"{base_url}/api/hardware/face_detect", data=b"{}", headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        face_data = json.loads(resp.read().decode("utf-8"))
        assert len(face_data["faces"]) >= 1

        # 4. POST /api/hardware/accessory/attach
        req = urllib.request.Request(
            f"{base_url}/api/hardware/accessory/attach",
            data=json.dumps({"pin": "720-0035"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        attach_data = json.loads(resp.read().decode("utf-8"))
        assert attach_data["status"] == "ok"
        assert attach_data["module"]["name"] == "DSMC2 Jetpack-SDI Expander"

        # 5. POST /api/hardware/accessory/detach
        req = urllib.request.Request(
            f"{base_url}/api/hardware/accessory/detach",
            data=json.dumps({"pin": "720-0035"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        detach_data = json.loads(resp.read().decode("utf-8"))
        assert detach_data["detached"] is True

    finally:
        server.shutdown()
        studio.stop()
