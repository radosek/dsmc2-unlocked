"""
RED Command Protocol (RCP) Subsystem package.
Provides protocol parsing, TCP server bridge, scriptable automation, and multi-camera orchestration.
"""

from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.server import RcpServer
from emulator.rcp.automation import RcpScriptEngine, RcpScriptStep, MultiCameraNetwork

__all__ = [
    "RcpProtocol",
    "RcpServer",
    "RcpScriptEngine",
    "RcpScriptStep",
    "MultiCameraNetwork"
]
