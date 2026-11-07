"""
Integration and network tests for RED Command Protocol (RCP) TCP Server.
Connects real TCP client sockets to 127.0.0.1:1111 and verifies bidirectional
command handling, status updates, aliases, record state, and multi-client notifications.
"""

import socket
import time
import pytest
from emulator.camera import Dsmc2Camera
from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.server import RcpServer


@pytest.fixture
def rcp_env(tmp_path):
    slot_dir = tmp_path / "firmware_store" / "unpacked" / "scarlet_w_7_4_1" / "slot"
    slot_dir.mkdir(parents=True)
    (slot_dir / "dsmc_program.mem").write_bytes(b"\x00" * 4096)
    (slot_dir / "system.env").write_text("CAMERA_NAME=SCARLET-W 5K\nPIN=10042\n")

    camera = Dsmc2Camera(str(tmp_path))
    # Pick a dedicated test port to avoid conflicting with other running processes
    test_port = 11112
    camera.rcp_server.port = test_port
    camera.rcp_server.start()
    time.sleep(0.1)

    yield camera, test_port

    camera.rcp_server.stop()


def send_rcp_cmd(sock: socket.socket, cmd: str) -> str:
    """Helper to send a command line and receive response."""
    if not cmd.endswith("\n"):
        cmd += "\n"
    sock.sendall(cmd.encode("utf-8"))
    
    # Read response line
    resp = ""
    start_t = time.time()
    while "\n" not in resp and time.time() - start_t < 2.0:
        chunk = sock.recv(1024).decode("utf-8", errors="replace")
        if not chunk:
            break
        resp += chunk
    return resp


def test_rcp_tcp_connect_and_greeting(rcp_env):
    """Verify external client TCP connection and initial DSMC2 greeting banner."""
    camera, port = rcp_env
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.settimeout(2.0)

    # Initial banner
    greeting = client.recv(1024).decode("utf-8")
    assert "RED DSMC2 ONLINE" in greeting
    assert "READY" in greeting

    assert camera.rcp_server.get_client_count() == 1
    client.close()
    time.sleep(0.1)


def test_rcp_get_and_set_commands(rcp_env):
    """Verify standard GET and SET commands over TCP socket."""
    camera, port = rcp_env
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.settimeout(2.0)
    _ = client.recv(1024) # consume greeting

    # 1. Query ISO
    resp = send_rcp_cmd(client, "GET iso\n")
    assert "RED iso 800" in resp

    # 2. Set ISO to 1600
    resp = send_rcp_cmd(client, "SET iso 1600\n")
    assert "RED iso 1600" in resp
    assert camera.rcp.state["iso"] == "1600"

    # 3. Query Frame Rate
    resp = send_rcp_cmd(client, "GET frame_rate\n")
    assert "RED frame_rate 23.976" in resp

    # 4. Set Shutter Angle
    resp = send_rcp_cmd(client, "SET shutter_angle 90.0\n")
    assert "RED shutter_angle 90.0" in resp
    assert camera.rcp.state["shutter_angle"] == "90.0"

    client.close()


def test_rcp_lens_and_aperture_control(rcp_env):
    """Verify query and control of lens aperture and focal length over RCP."""
    camera, port = rcp_env
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.settimeout(2.0)
    _ = client.recv(1024)

    # Query attached lens name
    resp = send_rcp_cmd(client, "GET lens_name\n")
    assert "RED lens_name" in resp
    assert "Canon" in resp

    # Set aperture via alias 'iris'
    resp = send_rcp_cmd(client, "SET iris 4.0\n")
    assert "RED aperture f/4.0" in resp
    assert camera.lens_mount.current_aperture == 4.0

    # Set focal length
    resp = send_rcp_cmd(client, "SET focal_length 35\n")
    assert "RED focal_length 35mm" in resp
    assert camera.lens_mount.current_focal_length == 35.0

    client.close()


def test_rcp_record_start_stop(rcp_env):
    """Verify RECORD START, RECORD STOP, and RECORD TOGGLE over TCP."""
    camera, port = rcp_env
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.settimeout(2.0)
    _ = client.recv(1024)

    # Start Recording
    resp = send_rcp_cmd(client, "RECORD START\n")
    assert "RED record_state 2" in resp
    assert camera.rcp.state["record_state"] == "2"
    assert camera.recorder.is_recording is True

    # Stop Recording
    resp = send_rcp_cmd(client, "RECORD STOP\n")
    assert "RED record_state 0" in resp
    assert camera.rcp.state["record_state"] == "0"
    assert camera.recorder.is_recording is False

    client.close()


def test_rcp_ping_pong_and_status(rcp_env):
    """Verify keepalive PING and full STATUS dump."""
    camera, port = rcp_env
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.settimeout(2.0)
    _ = client.recv(1024)

    resp = send_rcp_cmd(client, "PING\n")
    assert "PONG" in resp

    resp = send_rcp_cmd(client, "STATUS\n")
    assert "STATUS" in resp
    assert "frame_rate=" in resp
    assert "iso=" in resp
    assert "camera_name=" in resp

    client.close()


def test_rcp_multiclient_broadcast(rcp_env):
    """Verify multi-client TCP broadcast notifications when parameters change."""
    camera, port = rcp_env

    # Connect Client 1
    c1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c1.connect(("127.0.0.1", port))
    c1.settimeout(2.0)
    _ = c1.recv(1024)

    # Connect Client 2
    c2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    c2.connect(("127.0.0.1", port))
    c2.settimeout(2.0)
    _ = c2.recv(1024)

    assert camera.rcp_server.get_client_count() == 2

    # Client 1 changes ISO
    _ = send_rcp_cmd(c1, "SET iso 3200\n")

    # Client 2 should receive broadcast NOTIFY iso 3200
    c2_notify = c2.recv(1024).decode("utf-8")
    assert "NOTIFY iso 3200" in c2_notify

    c1.close()
    c2.close()
    time.sleep(0.1)
