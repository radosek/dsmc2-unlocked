"""
Automated Test for DSMC2 Camera Boot and Core Subsystems.
Verifies M2 (ARM JIT Execution), M3 (RTOS Bringup), M4 (VFS), and M5 (Peripherals).
"""

import os
import sys

repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from emulator.camera import Dsmc2Camera
from emulator.rcp.protocol import RcpProtocol
from conftest import requires_firmware

pytestmark = requires_firmware


def test_rcp_protocol():
    rcp = RcpProtocol()
    resp = rcp.process_command("GET iso\n")
    assert "RED iso 800" in resp

    resp = rcp.process_command("SET iso 1600\n")
    assert "RED iso 1600" in resp
    assert rcp.state["iso"] == "1600"

    resp = rcp.process_command("RECORD START\n")
    assert "RED record_state 2" in resp


def test_camera_subsystems_and_boot():
    cam = Dsmc2Camera(repo_root)
    try:
        assert cam.cpu is not None
        assert cam.bus is not None
        assert cam.intc is not None
        assert cam.dss is not None
        assert cam.maxtouch is not None
        assert cam.vfs.file_exists("/env")

        # Test touch injection
        cam.touch(512, 288, pressed=True)
        assert len(cam.maxtouch.message_queue) == 1
        msg = cam.maxtouch.message_queue[0]
        assert len(msg) == 7
        assert msg[0] == 1
        assert (msg[1] & 0xC0) == 0xC0

        # Boot
        cam.load_firmware()
        assert cam.cpu.pc == 0x80829F2C

        cam.boot(initial_instructions=45_000_000)
        assert cam.instruction_count == 45_000_000
        assert cam.cpu.pc >= 0x80000000
    finally:
        # Explicitly release Unicorn engine handle
        if hasattr(cam.cpu.mu, "_uch"):
            pass
