import struct
"""
Chip-to-Chip (C2C) Transport Subsystem.
Base address: 0x49000000, Size: 0x1000.
Bidirectional shared-memory mailbox and FIFO protocol exchanging telemetry and commands
between ARM Cortex-A8 (ThreadX) and Tensilica Xtensa coprocessor ASICs (IOB0, IOB1, ISP1, ISP2).
"""

from typing import Dict, Any, List, Optional
from collections import deque
from emulator.core.bus import Device


class C2cTransport(Device):
    """
    Hardware C2C Bridge connecting OMAP3630 to IOB and ISP coprocessor ASICs.
    """

    BASE_ADDR = 0x49000000
    SIZE = 0x1000

    # Core IDs
    CORE_IOB0 = 0
    CORE_IOB1 = 1
    CORE_ISP1 = 2
    CORE_ISP2 = 3

    # C2C Register Offsets
    REG_CTRL = 0x00         # Control register (Reset, Enable, Flush)
    REG_STATUS = 0x04       # Status (TX Full, RX Empty, Busy, Error)
    REG_TARGET = 0x08       # Selected target coprocessor (0..3)
    REG_TX_DATA = 0x0C      # ARM -> Coprocessor 32-bit Data FIFO
    REG_RX_DATA = 0x10      # Coprocessor -> ARM 32-bit Data FIFO
    REG_IRQ_ENABLE = 0x14   # Interrupt enable mask
    REG_IRQ_STATUS = 0x18   # Interrupt status (write 1 to clear)
    REG_PACKET_LEN = 0x1C   # Current packet length in words

    # Status Flags
    STAT_TX_EMPTY = 0x01
    STAT_TX_FULL = 0x02
    STAT_RX_VALID = 0x04
    STAT_BUSY = 0x08
    STAT_ERROR = 0x10

    def __init__(self, intc=None):
        self.intc = intc
        self.ctrl = 0x01         # Enabled
        self.target_core = self.CORE_IOB0
        self.irq_enable = 0x00
        self.irq_status = 0x00

        # Dedicated Core FIFOs: core_id -> deque of 32-bit words
        self.tx_fifos: Dict[int, deque] = {i: deque(maxlen=256) for i in range(4)}
        self.rx_fifos: Dict[int, deque] = {i: deque(maxlen=256) for i in range(4)}

        # Registered coprocessor models
        self.coprocessors: Dict[int, Any] = {}
        self.packet_counter = 0

    def register_coprocessor(self, core_id: int, coproc: Any):
        """Register a coprocessor model to receive C2C packets."""
        self.coprocessors[core_id] = coproc

    def read(self, offset: int, size: int) -> int:
        """Handle MMIO reads from C2C register space."""
        if offset == self.REG_CTRL:
            return self.ctrl
        elif offset == self.REG_STATUS:
            status = self.STAT_TX_EMPTY
            if self.rx_fifos[self.target_core]:
                status |= self.STAT_RX_VALID
            return status
        elif offset == self.REG_TARGET:
            return self.target_core
        elif offset == self.REG_RX_DATA:
            if self.rx_fifos[self.target_core]:
                return self.rx_fifos[self.target_core].popleft()
            return 0x00000000
        elif offset == self.REG_IRQ_ENABLE:
            return self.irq_enable
        elif offset == self.REG_IRQ_STATUS:
            return self.irq_status
        elif offset == self.REG_PACKET_LEN:
            return len(self.rx_fifos[self.target_core])
        return 0x00000000

    def write(self, offset: int, size: int, val: int):
        """Handle MMIO writes to C2C register space."""
        if offset == self.REG_CTRL:
            self.ctrl = val
            if val & 0x02: # Flush
                for f in self.tx_fifos.values():
                    f.clear()
                for f in self.rx_fifos.values():
                    f.clear()
        elif offset == self.REG_TARGET:
            self.target_core = val & 0x03
        elif offset == self.REG_TX_DATA:
            self.send_word(self.target_core, val)
        elif offset == self.REG_IRQ_ENABLE:
            self.irq_enable = val
        elif offset == self.REG_IRQ_STATUS:
            self.irq_status &= ~val

    def send_word(self, target_core: int, word: int):
        """Write a 32-bit word into target coprocessor TX FIFO and dispatch if complete."""
        fifo = self.tx_fifos[target_core]
        fifo.append(word & 0xFFFFFFFF)
        self.packet_counter += 1

        # If coprocessor registered, dispatch packet
        if target_core in self.coprocessors:
            resp = self.coprocessors[target_core].handle_c2c_word(word)
            if resp is not None:
                self.rx_fifos[target_core].append(resp & 0xFFFFFFFF)
                if self.intc and (self.irq_enable & 0x01):
                    self.intc.assert_irq(48) # C2C Host IRQ

    def send_packet(self, target_core: int, cmd: int, payload: List[int]) -> Optional[List[int]]:
        """High-level Python API sending packet to coprocessor and returning response."""
        # Header: (target << 24) | (cmd << 16) | len(payload)
        hdr = ((target_core & 0xFF) << 24) | ((cmd & 0xFF) << 16) | (len(payload) & 0xFFFF)
        self.send_word(target_core, hdr)
        for w in payload:
            self.send_word(target_core, w)

        coproc = self.coprocessors.get(target_core)
        if coproc and hasattr(coproc, "handle_c2c_command"):
            return coproc.handle_c2c_command(cmd, payload)
        return None

    def get_status(self) -> Dict[str, Any]:
        """Return C2C diagnostic telemetry."""
        return {
            "enabled": bool(self.ctrl & 0x01),
            "target_core": self.target_core,
            "packets_transmitted": self.packet_counter,
            "connected_cores": list(self.coprocessors.keys()),
            "rx_queue_lengths": {c: len(f) for c, f in self.rx_fifos.items()}
        }


class IobDoorbellDevice(Device):
    """
    Hardware Doorbell MMIO device for Tensilica IOB0 (0x3FFE8000) and IOB1 (0x4FFE8000).
    Triggered by ARM Cortex-A8 ThreadX at 0x3FFE8004 and 0x4FFE8004 to dispatch shared-memory C2C mailbox packets.
    """

    BASE_ADDR_IOB0 = 0x3FFE8000
    BASE_ADDR_IOB1 = 0x4FFE8000
    SIZE = 0x1000

    def __init__(self, core_id: int, bus, coprocessor, mailbox_base_addr: int):
        self.core_id = core_id
        self.bus = bus
        self.coprocessor = coprocessor
        self.mailbox_base_addr = mailbox_base_addr
        self.doorbell_count = 0
        self.last_command = 0
        self.last_payload: List[int] = []

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00:
            return 0x01 # Doorbell ready / enabled
        elif offset == 0x04:
            return self.doorbell_count
        return 0

    def write(self, offset: int, size: int, val: int):
        if offset == 0x04:
            self.doorbell_count = val & 0xFFFFFFFF
            # Fetch 16-byte mailbox descriptor from DDR shared memory
            try:
                raw = self.bus.read_mem(self.mailbox_base_addr, 16)
                cmd, arg0, arg1, arg2 = struct.unpack("<4I", raw)
                self.last_command = cmd
                self.last_payload = [arg0, arg1, arg2]
                if self.coprocessor and hasattr(self.coprocessor, "handle_c2c_command"):
                    self.coprocessor.handle_c2c_command(cmd, [arg0, arg1, arg2])
            except Exception:
                pass
