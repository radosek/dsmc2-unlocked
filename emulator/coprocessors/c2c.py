"""
SPI-Backed Coprocessor Transport & C2C Mailbox Subsystem.

Architectural Provenance:
- On physical RED DSMC2 hardware (TI DM3725 / OMAP3630), address 0x49000000 is the
  L4-PER AP (Address Protection / Interconnect Firewall) per DM37xx TRM Table 2-4,
  NOT an external chip-to-chip bus.
- The OMAP3630 supervisor communicates with coprocessor ASICs (ISP1, ISP2, IOB0, IOB1,
  LSB FPGA, Sensor) over McSPI (Multichannel Serial Port Interface, McSPI 1..4) and
  shared-memory mailbox doorbells, as proven by native camera debug shell commands:
    `read spi ts_isp1 <addr> <len>`
    `read spi ts_isp2 <addr> <len>`
    `read spi ts_sensor <addr> <len>`
    `read spi ts_fpga <addr> <len>`
- High-bandwidth video DMA between IOB and ISP runs over the 4-lane XAUI SerDes bus,
  while `system_state_2_if` coordinates state transitions (`RUN (2)` -> `PREVIEW_START (6)`
  -> `READY_TO_RECORD (10)`) and heartbeats over SPI and mailbox interrupts without
  tripping `C2C_ERROR` (Event 25) or `FAILED_IOB` (Event 29).
"""

import struct
import zlib
from typing import Dict, Any, List, Optional, Tuple
from collections import deque
from emulator.core.bus import Device
from emulator.devices.mcspi import OmapMcspi, SpiTargetDevice


class CoprocessorSpiTarget(SpiTargetDevice):
    """
    SPI Target Bridge binding an OmapMcspi channel (`ts_isp1`, `ts_isp2`, `ts_fpga`,
    `ts_sensor`, `ts_iob0`, `ts_iob1`) to its underlying coprocessor model and C2C mailbox.
    """

    # Standard SPI Target Status & Identity Registers
    REG_DEVICE_ID = 0x0000
    REG_FW_VERSION = 0x0004
    REG_SYSTEM_STATE = 0x0008
    REG_HEARTBEAT = 0x000C
    REG_C2C_STATUS = 0x0010
    REG_MAILBOX_CMD = 0x0014
    REG_MAILBOX_CRC = 0x0018

    TARGET_DEVICE_IDS = {
        "ts_isp1": 0x49535031,    # 'ISP1'
        "ts_isp2": 0x49535032,    # 'ISP2'
        "ts_fpga": 0x46504741,    # 'FPGA' (Kintex-7 LSB)
        "ts_sensor": 0x53454E53,  # 'SENS' (DRAGON / HELIUM / MONSTRO)
        "ts_iob0": 0x494F4230,    # 'IOB0'
        "ts_iob1": 0x494F4231,    # 'IOB1'
        "ts_lma": 0x4C4D4130,     # 'LMA0'
        "ts_audio": 0x41554430,   # 'AUD0'
        "ts_wireless": 0x574C414E # 'WLAN'
    }

    def __init__(self, name: str, port_id: int, channel: int, core_id: int, transport: "C2cTransport"):
        super().__init__(name, port_id, channel)
        self.core_id = core_id
        self.transport = transport
        self.heartbeat_seq = 1
        self.registers[self.REG_DEVICE_ID] = self.TARGET_DEVICE_IDS.get(name, 0x52454432)
        self.registers[self.REG_FW_VERSION] = 0x00070401  # v7.4.1
        self.registers[self.REG_SYSTEM_STATE] = C2cTransport.STATE_READY_TO_RECORD
        self.registers[self.REG_HEARTBEAT] = 0x00000001
        self.registers[self.REG_C2C_STATUS] = 0x00000001  # Link OK, zero errors

    def transceive_word(self, tx_word: int) -> Optional[int]:
        """
        Process SPI word transfer.
        If the word is a framed C2C SPI mailbox header (magic upper byte 0xC2),
        route through the C2C mailbox protocol and return the ACK word.
        Otherwise return None so standard McSPI loopback behavior is preserved.
        """
        self.transfer_count += 1
        if (tx_word >> 24) == 0xC2:
            cmd = (tx_word >> 16) & 0xFF
            arg = tx_word & 0xFFFF
            resp = self.transport.send_packet(self.core_id, cmd, [arg])
            ack_payload = (resp[0] & 0xFFFF) if resp else 0x0001
            return (0xA5000000 | ((cmd & 0xFF) << 16) | ack_payload) & 0xFFFFFFFF
        return None

    def read_reg(self, addr: int, length: int = 4) -> bytes:
        self.transfer_count += 1
        self.heartbeat_seq = (self.heartbeat_seq + 1) & 0xFFFFFFFF
        self.registers[self.REG_HEARTBEAT] = self.heartbeat_seq
        self.registers[self.REG_SYSTEM_STATE] = self.transport.system_state
        return super().read_reg(addr, length)


class C2cTransport(Device):
    """
    SPI-Backed Chip-to-Chip (C2C) Mailbox and Coprocessor Transport Subsystem.

    Coordinates communication between the OMAP3630 ARM Cortex-A8 (ThreadX) and
    coprocessor targets (`ts_isp1`, `ts_isp2`, `ts_fpga`, `ts_sensor`, `ts_iob0`, `ts_iob1`)
    over McSPI controllers (McSPI 1..4) and shared DDR mailbox rings.
    """

    # Canonical McSPI4 Coprocessor Mailbox Host Base Address (TRM Table 2-3: McSPI4 @ 0x480BA000, IRQ 48)
    BASE_ADDR = 0x480BA000
    SIZE = 0x1000

    # Core IDs
    CORE_IOB0 = 0
    CORE_IOB1 = 1
    CORE_ISP1 = 2
    CORE_ISP2 = 3

    # system_state_2_if State Machine Constants
    STATE_INIT = 0
    STATE_RUN = 2
    STATE_PREVIEW_START = 6
    STATE_READY_TO_RECORD = 10

    # Event IDs (must remain clear during healthy operation)
    EVENT_C2C_ERROR = 25
    EVENT_FAILED_IOB = 29

    # Mailbox Register Offsets (for direct register/FIFO inspection & legacy tests)
    REG_CTRL = 0x00         # Control register (Reset, Enable, Flush)
    REG_STATUS = 0x04       # Status (TX Empty, TX Full, RX Valid, Busy, Error)
    REG_TARGET = 0x08       # Selected target coprocessor (0..3)
    REG_TX_DATA = 0x0C      # ARM -> Coprocessor 32-bit Data FIFO
    REG_RX_DATA = 0x10      # Coprocessor -> ARM 32-bit Data FIFO
    REG_IRQ_ENABLE = 0x14   # Interrupt enable mask
    REG_IRQ_STATUS = 0x18   # Interrupt status (write 1 to clear)
    REG_PACKET_LEN = 0x1C   # Current packet length in words
    REG_SEQ_NUM = 0x20      # Mailbox packet sequence counter
    REG_LAST_CRC = 0x24     # Last validated packet CRC32
    REG_SYS_STATE = 0x28    # system_state_2_if current state (2 -> 6 -> 10)

    # Status Flags
    STAT_TX_EMPTY = 0x01
    STAT_TX_FULL = 0x02
    STAT_RX_VALID = 0x04
    STAT_BUSY = 0x08
    STAT_ERROR = 0x10

    # Canonical SPI Target Topology -> (mcspi_port_id, channel, core_id)
    SPI_TARGET_MAP: Dict[str, Tuple[int, int, int]] = {
        "ts_isp1": (1, 0, CORE_ISP1),
        "ts_isp2": (1, 1, CORE_ISP2),
        "ts_fpga": (2, 0, CORE_IOB0),
        "ts_sensor": (2, 1, CORE_IOB1),
        "ts_iob0": (3, 0, CORE_IOB0),
        "ts_iob1": (3, 1, CORE_IOB1),
        "ts_lma": (3, 2, CORE_IOB0),
        "ts_audio": (3, 3, CORE_IOB0),
        "ts_wireless": (4, 0, CORE_IOB0),
    }

    def __init__(self, intc=None, mcspi: Optional[Dict[int, OmapMcspi]] = None):
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
        self.sequence_number = 0
        self.last_crc32 = 0x00000000

        # system_state_2_if state progression: RUN (2) -> PREVIEW_START (6) -> READY_TO_RECORD (10)
        self.state_history: List[int] = [
            self.STATE_RUN,
            self.STATE_PREVIEW_START,
            self.STATE_READY_TO_RECORD,
        ]
        self.system_state = self.STATE_READY_TO_RECORD
        self.active_events: Dict[int, bool] = {
            self.EVENT_C2C_ERROR: False,
            self.EVENT_FAILED_IOB: False,
        }

        # Named SPI targets bound to McSPI controllers
        self.spi_targets: Dict[str, CoprocessorSpiTarget] = {}
        self.mcspi_controllers: Dict[int, OmapMcspi] = {}
        self._init_spi_targets()
        if mcspi:
            self.bind_mcspi(mcspi)

    def _init_spi_targets(self):
        for name, (port_id, channel, core_id) in self.SPI_TARGET_MAP.items():
            self.spi_targets[name] = CoprocessorSpiTarget(
                name=name,
                port_id=port_id,
                channel=channel,
                core_id=core_id,
                transport=self,
            )

    def bind_mcspi(self, mcspi_controllers: Dict[int, OmapMcspi]):
        """Bind coprocessor SPI targets (`ts_isp1`, `ts_isp2`, `ts_fpga`, `ts_sensor`, etc.) to McSPI 1..4."""
        self.mcspi_controllers = mcspi_controllers
        for name, target in self.spi_targets.items():
            ctrl = mcspi_controllers.get(target.port_id)
            if ctrl is not None:
                ctrl.attach_target(target.channel, target)

    def register_coprocessor(self, core_id: int, coproc: Any):
        """Register a coprocessor model to receive C2C / SPI mailbox packets."""
        self.coprocessors[core_id] = coproc

    def read(self, offset: int, size: int) -> int:
        """Handle reads from C2C mailbox state registers."""
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
        elif offset == self.REG_SEQ_NUM:
            return self.sequence_number
        elif offset == self.REG_LAST_CRC:
            return self.last_crc32
        elif offset == self.REG_SYS_STATE:
            return self.system_state
        return 0x00000000

    def write(self, offset: int, size: int, val: int):
        """Handle writes to C2C mailbox state registers."""
        if offset == self.REG_CTRL:
            self.ctrl = val
            if val & 0x02:  # Flush
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
        elif offset == self.REG_SYS_STATE:
            self.transition_system_state(val)

    def transition_system_state(self, new_state: int) -> int:
        """Advance `system_state_2_if` state (`RUN (2)` -> `PREVIEW_START (6)` -> `READY_TO_RECORD (10)`)."""
        self.system_state = int(new_state)
        if self.system_state not in self.state_history:
            self.state_history.append(self.system_state)
        for t in self.spi_targets.values():
            t.registers[CoprocessorSpiTarget.REG_SYSTEM_STATE] = self.system_state
        return self.system_state

    def send_word(self, target_core: int, word: int):
        """Write a 32-bit word into target coprocessor TX FIFO and dispatch over SPI mailbox."""
        fifo = self.tx_fifos[target_core]
        fifo.append(word & 0xFFFFFFFF)
        self.packet_counter += 1

        if target_core in self.coprocessors:
            resp = self.coprocessors[target_core].handle_c2c_word(word)
            if resp is not None:
                self.rx_fifos[target_core].append(resp & 0xFFFFFFFF)
                if self.intc and (self.irq_enable & 0x01):
                    self.intc.assert_irq(48)  # McSPI4 / Mailbox IRQ 48

    @staticmethod
    def compute_packet_crc(words: List[int]) -> int:
        """Compute 32-bit CRC over a sequence of 32-bit mailbox packet words."""
        raw = b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in words)
        return zlib.crc32(raw) & 0xFFFFFFFF

    def send_packet(self, target_core: int, cmd: int, payload: List[int]) -> Optional[List[int]]:
        """
        Send a framed RTOS mailbox packet (header, sequence number, payload, CRC32)
        to a coprocessor and return the response words.
        """
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        # Header: (target << 24) | (cmd << 16) | len(payload)
        hdr = ((target_core & 0xFF) << 24) | ((cmd & 0xFF) << 16) | (len(payload) & 0xFFFF)
        frame_words = [hdr, self.sequence_number] + [w & 0xFFFFFFFF for w in payload]
        self.last_crc32 = self.compute_packet_crc(frame_words)

        self.send_word(target_core, hdr)
        for w in payload:
            self.send_word(target_core, w)

        # Handle heartbeat / state queries at transport layer if needed
        if cmd == 0x01:  # Heartbeat ping
            return [0x01, self.sequence_number, self.system_state, self.last_crc32]
        elif cmd == 0x02 and payload:  # system_state_2_if transition
            new_st = self.transition_system_state(payload[0])
            return [0x00, new_st]

        coproc = self.coprocessors.get(target_core)
        if coproc and hasattr(coproc, "handle_c2c_command"):
            return coproc.handle_c2c_command(cmd, payload)
        return [0x00000000]

    def spi_read(self, target_name: str, addr: int, length: int = 4) -> bytes:
        """
        Execute `read spi <target> <addr> <len>` against a named SPI target
        (`ts_isp1`, `ts_isp2`, `ts_sensor`, `ts_fpga`, `ts_iob0`, `ts_iob1`).
        """
        norm = target_name.strip().lower()
        target = self.spi_targets.get(norm)
        if target is None:
            raise KeyError(f"Unknown SPI target: {target_name}")
        self.packet_counter += 1
        return target.read_reg(addr, length)

    def spi_write(self, target_name: str, addr: int, data: bytes) -> bool:
        """
        Execute a register write to a named SPI target (`ts_isp1`, `ts_isp2`, `ts_sensor`, `ts_fpga`).
        """
        norm = target_name.strip().lower()
        target = self.spi_targets.get(norm)
        if target is None:
            raise KeyError(f"Unknown SPI target: {target_name}")
        self.packet_counter += 1
        return target.write_reg(addr, data)

    def get_status(self) -> Dict[str, Any]:
        """Return SPI-backed C2C diagnostic telemetry."""
        return {
            "enabled": bool(self.ctrl & 0x01),
            "transport": "McSPI (SPI-backed mailbox)",
            "target_core": self.target_core,
            "packets_transmitted": self.packet_counter,
            "sequence_number": self.sequence_number,
            "last_crc32": f"0x{self.last_crc32:08X}",
            "system_state": self.system_state,
            "state_history": list(self.state_history),
            "c2c_error_event_25": self.active_events[self.EVENT_C2C_ERROR],
            "failed_iob_event_29": self.active_events[self.EVENT_FAILED_IOB],
            "spi_targets": list(self.spi_targets.keys()),
            "connected_cores": list(self.coprocessors.keys()),
            "rx_queue_lengths": {c: len(f) for c, f in self.rx_fifos.items()},
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
            return 0x01  # Doorbell ready / enabled
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
