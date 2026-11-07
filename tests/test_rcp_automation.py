"""
Unit and integration tests for Advanced RCP Automation & Multi-Camera Orchestration.
Verifies:
  - RcpScriptStep parsing & human-readable DSL syntax.
  - RcpScriptEngine execution, timing, and parameter assertions.
  - Production presets (Rack Focus, Production Slate & Record Cycle, Exposure Bracketing, Multi-Cam Broadcast).
  - MultiCameraNetwork Tri-Level Genlock sync, timecode distribution, and simultaneous record triggering.
  - Web Studio REST API automation & multi-cam endpoints.
"""

import os
import json
import socket
import urllib.request
import threading
import pytest

from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.automation import RcpScriptEngine, RcpScriptStep, MultiCameraNetwork
from emulator.camera import Dsmc2Camera
from emulator.ui.web import WebStudio, create_handler, ThreadedHTTPServer


@pytest.fixture
def workspace_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def find_free_port(start: int = 9300) -> int:
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 9350


def test_rcp_script_step_parsing_and_dsl():
    """Verify parsing of human-readable RCP automation DSL lines."""
    engine = RcpScriptEngine()
    dsl = [
        "# Initial exposure setup",
        "SET iso 1600",
        "GET iso",
        "ASSERT iso == 1600",
        "WAIT 150ms",
        "RAMP focus_distance 1.0m 10.0m 300 5",
        "TRIGGER record_start",
        "TRIGGER record_stop"
    ]
    steps = engine.parse_script_lines(dsl)
    assert len(steps) == 7

    assert steps[0].action == "SET"
    assert steps[0].param == "iso"
    assert steps[0].value == "1600"

    assert steps[1].action == "GET"
    assert steps[1].param == "iso"

    assert steps[2].action == "ASSERT"
    assert steps[2].comparator == "=="
    assert steps[2].value == "1600"

    assert steps[3].action == "WAIT"
    assert steps[3].duration_ms == 150.0

    assert steps[4].action == "RAMP"
    assert steps[4].value == "1.0m,10.0m"
    assert steps[4].duration_ms == 300.0
    assert steps[4].steps == 5

    assert steps[5].action == "TRIGGER"
    assert steps[5].param == "record_start"


def test_rcp_script_engine_execution_and_assertions(workspace_root):
    """Verify RcpScriptEngine execution and assertion verification against real camera."""
    camera = Dsmc2Camera(workspace_root)
    camera.power_on()
    engine = RcpScriptEngine()

    try:
        steps = [
            RcpScriptStep("SET", param="iso", value="800"),
            RcpScriptStep("ASSERT", param="iso", value="800", comparator="=="),
            RcpScriptStep("SET", param="color_temperature", value="5600"),
            RcpScriptStep("ASSERT", param="color_temperature", value="5600", comparator="=="),
            RcpScriptStep("WAIT", duration_ms=50),
            RcpScriptStep("TRIGGER", param="record_start"),
            RcpScriptStep("ASSERT", param="record_state", value="2", comparator="=="),
            RcpScriptStep("TRIGGER", param="record_stop"),
            RcpScriptStep("ASSERT", param="record_state", value="0", comparator="==")
        ]

        report = engine.execute(steps, camera=camera, rcp_protocol=camera.rcp)
        assert report["status"] == "PASSED"
        assert report["total_steps"] == 9
        assert report["passed_assertions"] == 4
        assert report["failed_assertions"] == 0
        assert len(report["trace"]) == 9
        assert report["duration_ms"] > 0
    finally:
        camera.power_off()


def test_rcp_automation_presets(workspace_root):
    """Verify built-in production automation presets execute and pass cleanly."""
    camera = Dsmc2Camera(workspace_root)
    camera.power_on()

    try:
        # 1. Preset: Rack Focus & Depth Sweep
        rep1 = camera.execute_rcp_script("RACK_FOCUS")
        assert rep1["status"] == "PASSED"
        assert rep1["passed_assertions"] >= 2

        # 2. Preset: Production Slate & Record Cycle
        rep2 = camera.execute_rcp_script("RECORD_CYCLE")
        assert rep2["status"] == "PASSED"
        assert rep2["passed_assertions"] >= 2

        # 3. Preset: Exposure Bracket Sweep
        rep3 = camera.execute_rcp_script("EXPOSURE_BRACKET")
        assert rep3["status"] == "PASSED"
        assert rep3["passed_assertions"] >= 4

        # 4. Preset: Multi-Camera Broadcast Sync
        rep4 = camera.execute_rcp_script("MULTICAM_SYNC")
        assert rep4["status"] == "PASSED"
    finally:
        camera.power_off()


def test_multi_camera_network_sync_and_broadcast(workspace_root):
    """Verify MultiCameraNetwork Genlock, timecode sync, and synchronized record trigger."""
    camera = Dsmc2Camera(workspace_root)
    camera.power_on()
    net = MultiCameraNetwork(camera)

    try:
        status = net.get_status()
        assert status["genlock"] == "LOCKED"
        assert status["nodes_count"] == 3
        assert len(status["nodes"]) == 3

        # Synchronize Tri-Level Genlock & Timecode
        sync_res = net.sync_genlock(timecode="01:30:00:00")
        assert sync_res["genlock"] == "LOCKED"
        assert sync_res["timecode"] == "01:30:00:00"

        # Broadcast parameter
        b_res = net.broadcast_parameter("iso", "1280")
        assert b_res["value"] == "1280"
        assert len(b_res["nodes"]) == 3

        # Simultaneous record trigger (START)
        rec_start = net.synchronized_record_trigger("START")
        assert rec_start["record_state"] == 2
        for node in rec_start["nodes"]:
            assert node["state"] == 2

        # Simultaneous record trigger (STOP)
        rec_stop = net.synchronized_record_trigger("STOP")
        assert rec_stop["record_state"] == 0
        for node in rec_stop["nodes"]:
            assert node["state"] == 0

    finally:
        camera.power_off()


def test_web_studio_rcp_automation_endpoints(workspace_root):
    """Verify Web Studio REST API endpoints for automation scripts and multi-camera network."""
    port = find_free_port(9310)
    studio = WebStudio(workspace_root, host="127.0.0.1", port=port)
    studio.start_camera()

    handler = create_handler(studio)
    server = ThreadedHTTPServer(("127.0.0.1", port), handler)
    srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
    srv_thread.start()

    base_url = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /api/rcp/automation/presets
        resp = urllib.request.urlopen(f"{base_url}/api/rcp/automation/presets")
        assert resp.status == 200
        p_data = json.loads(resp.read().decode("utf-8"))
        assert "presets" in p_data
        assert "RACK_FOCUS" in p_data["presets"]

        # 2. POST /api/rcp/automation/run (Preset: RACK_FOCUS)
        req = urllib.request.Request(
            f"{base_url}/api/rcp/automation/run",
            data=json.dumps({"preset": "RACK_FOCUS"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        run_res = json.loads(resp.read().decode("utf-8"))
        assert run_res["status"] == "PASSED"
        assert run_res["total_steps"] > 0

        # 3. GET /api/rcp/multicam/status
        resp = urllib.request.urlopen(f"{base_url}/api/rcp/multicam/status")
        assert resp.status == 200
        mc_stat = json.loads(resp.read().decode("utf-8"))
        assert mc_stat["genlock"] == "LOCKED"
        assert mc_stat["nodes_count"] == 3

        # 4. POST /api/rcp/multicam/sync
        req = urllib.request.Request(
            f"{base_url}/api/rcp/multicam/sync",
            data=json.dumps({"timecode": "02:15:00:00"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        sync_data = json.loads(resp.read().decode("utf-8"))
        assert sync_data["sync"]["timecode"] == "02:15:00:00"

        # 5. POST /api/rcp/multicam/broadcast
        req = urllib.request.Request(
            f"{base_url}/api/rcp/multicam/broadcast",
            data=json.dumps({"param": "iso", "value": "1600"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        bc_data = json.loads(resp.read().decode("utf-8"))
        assert bc_data["status"] == "ok"

        # 6. POST /api/rcp/multicam/record
        req = urllib.request.Request(
            f"{base_url}/api/rcp/multicam/record",
            data=json.dumps({"action": "START"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        rec_data = json.loads(resp.read().decode("utf-8"))
        assert rec_data["record"]["record_state"] == 2

    finally:
        server.shutdown()
        studio.stop()
