"""
OMAP3630 / DM3725 HDQ / 1-Wire Controller & DSMC2 Secure Board EEPROM Subsystem.

TRM Reference: SPRUGN4 Chapter 22 (HDQ / 1-Wire Module at 0x480B2000, IRQ 58).
Firmware Reference: DSMC2 7.4.1 `onewire.c` (`onewire_ctor`, `onewire_reset`,
`onewire_search`, `onewire_read_bytes`, `onewire_compute_signature`,
`onewire_verify_signature`) and `HAL_1Wire_Scan_Thread`.

Public FW salt constant `DAT_80fd2bc8`: `27 a8 12 4f b3 ea`.
All default boards use strictly synthetic placeholder ROM IDs and serial strings.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from emulator.core.bus import Device


# Public firmware constant from DAT_80fd2bc8 (not unit-identifying)
ONEWIRE_MD5_SALT = bytes.fromhex("27a8124fb3ea")


def crc8_maxim(data: bytes) -> int:
    """Standard Dallas/Maxim 1-Wire CRC-8 (reflected polynomial 0x8C, init 0)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0x8C
            else:
                crc >>= 1
    return crc & 0xFF


def make_rom_id(family: int, serial48: int) -> bytes:
    """Construct a valid 8-byte Maxim 1-Wire ROM ID with valid CRC-8 in byte 7."""
    body = bytes([family & 0xFF]) + (serial48 & 0xFFFFFFFFFFFF).to_bytes(6, "little")
    return body + bytes([crc8_maxim(body)])


def compute_onewire_md5_signature(
    rom_id: bytes,
    s_20: str,
    s_31: str,
    field_42: bytes,
    sig_type: int,
    header_ver: int,
    s_46: str,
    s_57: str,
    s_68: str,
    s_79: str,
    extra_v2: Tuple[str, str] = ("", ""),
) -> bytes:
    """
    Reproduce `onewire_compute_signature` (`@0x80690028` in `clean/onewire.c`).

    Verified firmware record field layout and MD5 input order:
      - `+0x01..0x09` (8B): `rom_id`
      - `+0x09..0x19` (16B): computed MD5 signature output
      - `+0x20..0x31` (17B): `s_20` (board name)
      - `+0x31..0x42` (17B): `s_31` (revision)
      - `+0x42..0x44` (2B): `field_42`
      - `+0x44` (1B): `sig_type` (0, 1, or 2)
      - `+0x45` (1B): `header_ver`
      - `+0x46..0x57` (17B): `s_46` (board info)
      - `+0x57..0x68` (17B): `s_57` (module part number)
      - `+0x68..0x79` (17B): `s_68` (extra field)
      - `+0x79..0x8A` (17B): `s_79` (serial number)
      - `+0x8A..0x9B` (17B): `extra_v2[0]` (v2 assembly part number)
      - `+0x9B..0xAC` (17B): `extra_v2[1]` (v2 extra string)
      - `+0xBF..0xCF` (16B): stored MD5 signature compared by `onewire_verify_signature`

    Hash computation:
      sig_type == 0: 16 zero bytes
      sig_type == 1: MD5(salt(6) || rom_id(8) || s@0x20 || s@0x31 || field_42(2) ||
                         sig_type(1) || header_ver(1) || s@0x46 || s@0x57 ||
                         s@0x68 || s@0x79)
      sig_type == 2: same + s@0x8A + s@0x9B
    """
    if sig_type == 0:
        return b"\x00" * 16
    if sig_type not in (1, 2):
        raise ValueError(f"Unsupported sig_type {sig_type}")

    h = hashlib.md5()
    h.update(ONEWIRE_MD5_SALT)
    h.update(rom_id[:8])
    h.update(s_20.encode("ascii"))
    h.update(s_31.encode("ascii"))
    h.update(field_42[:2].ljust(2, b"\x00"))
    h.update(bytes([sig_type & 0xFF, header_ver & 0xFF]))
    h.update(s_46.encode("ascii"))
    h.update(s_57.encode("ascii"))
    h.update(s_68.encode("ascii"))
    h.update(s_79.encode("ascii"))
    if sig_type == 2:
        h.update(extra_v2[0].encode("ascii"))
        h.update(extra_v2[1].encode("ascii"))
    return h.digest()


def _write_cstr(buf: bytearray, offset: int, max_len: int, text: str):
    raw = text.encode("ascii", errors="replace")[: max(0, max_len - 1)]
    buf[offset : offset + max_len] = raw.ljust(max_len, b"\x00")


def _read_cstr(buf: bytearray, start: int, end: int) -> str:
    return bytes(buf[start:end]).split(b"\x00", 1)[0].decode("ascii", errors="replace")


@dataclass
class OneWireBoardDevice:
    """
    Virtual DSMC2 board 1-Wire identity record (256-byte EEPROM / decoded record buffer).

    Note: `board_id` is an emulator-internal handle aligned to the power-sequencer
    index (`IOB=0`, `ISP=1`, `SENSOR=2`, `RSB=3`, `LSB=4`); it is not stored in
    1-Wire EEPROM. Firmware scan order per `SYSTEM_ERROR_34_FLOW.md` is:
    `IOB -> ISP_PRE -> SENSOR -> ISP -> RSB -> LSB`.
    """

    board_id: int
    name: str          # IOB, ISP, SENSOR, RSB, LSB (record +0x20)
    part_num: str      # e.g. "131-0725" (record +0x57)
    serial_num: str    # synthetic serial, e.g. "SYNTH-IOB-0001" (record +0x79)
    rev_str: str       # e.g. "3C" (record +0x31)
    rom_id: bytes
    header_ver: int = 1
    sig_type: int = 1
    field_42: bytes = b"\x00\x00"
    board_info: str = ""
    extra_field: str = ""
    s_8a: str = ""
    s_9b: str = ""
    eeprom: bytearray = field(default_factory=lambda: bytearray(256))

    def __post_init__(self):
        if len(self.rom_id) != 8 or crc8_maxim(self.rom_id) != 0:
            raise ValueError(f"Invalid 1-Wire ROM ID CRC for {self.name}: {self.rom_id.hex()}")
        if not self.board_info:
            self.board_info = self.name
        if len(self.eeprom) < 256:
            self.eeprom = bytearray(self.eeprom).ljust(256, b"\x00")
        self.rebuild_eeprom(sign=True)

    def rebuild_eeprom(self, sign: bool = True):
        """Populate record bytes at exact offsets read by `onewire_compute_signature` / `onewire_verify_signature`."""
        mem = bytearray(256)
        mem[0x01:0x09] = self.rom_id[:8]
        _write_cstr(mem, 0x20, 17, self.name)
        _write_cstr(mem, 0x31, 17, self.rev_str)
        mem[0x42:0x44] = self.field_42[:2].ljust(2, b"\x00")
        mem[0x44] = self.sig_type & 0xFF
        mem[0x45] = self.header_ver & 0xFF
        _write_cstr(mem, 0x46, 17, self.board_info)
        _write_cstr(mem, 0x57, 17, self.part_num)
        _write_cstr(mem, 0x68, 17, self.extra_field)
        _write_cstr(mem, 0x79, 17, self.serial_num)
        _write_cstr(mem, 0x8A, 17, self.s_8a)
        _write_cstr(mem, 0x9B, 17, self.s_9b)
        self.eeprom = mem
        if sign:
            sig = self.expected_signature()
            self.eeprom[0x09:0x19] = sig
            self.eeprom[0xBF:0xCF] = sig

    def stored_serial(self) -> str:
        return _read_cstr(self.eeprom, 0x79, 0x8A)

    def stored_part_num(self) -> str:
        return _read_cstr(self.eeprom, 0x57, 0x68)

    def expected_signature(self) -> bytes:
        return compute_onewire_md5_signature(
            rom_id=bytes(self.eeprom[0x01:0x09]),
            s_20=_read_cstr(self.eeprom, 0x20, 0x31),
            s_31=_read_cstr(self.eeprom, 0x31, 0x42),
            field_42=bytes(self.eeprom[0x42:0x44]),
            sig_type=self.eeprom[0x44],
            header_ver=self.eeprom[0x45],
            s_46=_read_cstr(self.eeprom, 0x46, 0x57),
            s_57=self.stored_part_num(),
            s_68=_read_cstr(self.eeprom, 0x68, 0x79),
            s_79=self.stored_serial(),
            extra_v2=(
                _read_cstr(self.eeprom, 0x8A, 0x9B),
                _read_cstr(self.eeprom, 0x9B, 0xAC),
            ),
        )

    def verify_signature(self) -> bool:
        if self.eeprom[0x44] == 0:
            return True
        return bytes(self.eeprom[0xBF:0xCF]) == self.expected_signature()


def make_default_dsmc2_boards() -> List[OneWireBoardDevice]:
    """
    Create the 5 standard DSMC2 board 1-Wire identities with safe synthetic serials.

    Part numbers follow verified DSMC2 board PCA assignments (LSB = 131-0727, RSB = 131-0726).
    `board_id` values (`IOB=0`, `ISP=1`, `SENSOR=2`, `RSB=3`, `LSB=4`) are emulator-internal
    handles aligned to the power-sequencer index (`sensor=2`).
    """
    return [
        OneWireBoardDevice(
            board_id=0,
            name="IOB",
            part_num="131-0725",
            serial_num="SYNTH-IOB-0001",
            rev_str="3C",
            rom_id=make_rom_id(0x2D, 0x0001),
        ),
        OneWireBoardDevice(
            board_id=1,
            name="ISP",
            part_num="131-0724",
            serial_num="SYNTH-ISP-0002",
            rev_str="3A",
            rom_id=make_rom_id(0x2D, 0x0002),
        ),
        OneWireBoardDevice(
            board_id=2,
            name="SENSOR",
            part_num="131-0776",
            serial_num="SYNTH-SNS-0003",
            rev_str="5A",
            rom_id=make_rom_id(0x2D, 0x0003),
        ),
        OneWireBoardDevice(
            board_id=3,
            name="RSB",
            part_num="131-0726",
            serial_num="SYNTH-RSB-0005",
            rev_str="2A",
            rom_id=make_rom_id(0x2D, 0x0005),
        ),
        OneWireBoardDevice(
            board_id=4,
            name="LSB",
            part_num="131-0727",
            serial_num="SYNTH-LSB-0004",
            rev_str="2A",
            rom_id=make_rom_id(0x2D, 0x0004),
        ),
    ]


class OmapHdq1Wire(Device):
    """
    TI DM3725 HDQ / 1-Wire Controller (`0x480B2000`, size `0x1000`, IRQ `58`).

    Implements the DM3730 TRM Chapter 22 register interface and a bit/byte-accurate
    Maxim 1-Wire virtual bus FSM supporting Reset/Presence Detect, Search ROM (`0xF0`),
    Match ROM (`0x55`), Skip ROM (`0xCC`), and Read Memory (`0xF0 <TA1> <TA2>`).
    """

    BASE_ADDR = 0x480B2000
    SIZE = 0x1000
    IRQ_NUM = 58

    # DM3730 TRM Chapter 22 Table 22-4 register offsets
    REG_REVISION = 0x00
    REG_TX_DATA = 0x04
    REG_RX_DATA = 0x08
    REG_CTRL_STATUS = 0x0C
    REG_INT_STATUS = 0x10
    REG_SYSCONFIG = 0x14
    REG_SYSSTATUS = 0x18

    # CTRL_STATUS bitmasks (verified in clean/onewire.c)
    BIT_MODE = 0x01
    BIT_DIR_RX = 0x02
    BIT_INITIALIZATION = 0x04
    BIT_PRESENCE_DETECT = 0x08
    BIT_GO = 0x10
    BIT_CLOCKENABLE = 0x20
    BIT_INTERRUPTMASK = 0x40
    BIT_SINGLE = 0x80

    # INT_STATUS bits (read-to-clear)
    INT_TIMEOUT = 0x01
    INT_RXCOMPLETE = 0x02
    INT_TXCOMPLETE = 0x04

    # SYSCONFIG / SYSSTATUS bits
    BIT_SOFTRESET = 0x02
    BIT_RESETDONE = 0x01

    # Virtual 1-Wire Bus FSM states
    _FSM_IDLE = "IDLE"
    _FSM_WAIT_ROM_CMD = "WAIT_ROM_CMD"
    _FSM_SEARCH_ROM = "SEARCH_ROM"
    _FSM_MATCH_ROM = "MATCH_ROM"
    _FSM_WAIT_MEM_CMD = "WAIT_MEM_CMD"
    _FSM_WAIT_ADDR_LO = "WAIT_ADDR_LO"
    _FSM_WAIT_ADDR_HI = "WAIT_ADDR_HI"
    _FSM_READ_MEM = "READ_MEM"

    def __init__(self, intc: Optional[Any] = None, boards: Optional[List[OneWireBoardDevice]] = None):
        self.intc = intc
        self.revision = 0x00000006
        self.tx_data = 0x00000000
        self.rx_data = 0x00000000
        self.ctrl_status = 0x00000000
        self.int_status = 0x00000000
        self.sysconfig = 0x00000000
        self.sysstatus = self.BIT_RESETDONE

        self.bus_fault: bool = False
        self._irq_asserted_by_hdq: bool = False
        self.devices: List[OneWireBoardDevice] = (
            list(boards) if boards is not None else make_default_dsmc2_boards()
        )
        self._reset_fsm(presence=False)

    def _reset_fsm(self, presence: bool):
        self._fsm_state = self._FSM_WAIT_ROM_CMD if presence else self._FSM_IDLE
        self._rx_bit_acc = 0
        self._rx_bit_cnt = 0
        self._active_devices: List[OneWireBoardDevice] = list(self.devices) if presence else []
        self._selected: Optional[OneWireBoardDevice] = None
        self._search_bit_idx = 0
        self._search_phase = 0
        self._match_bits = bytearray()
        self._mem_addr = 0
        self._out_bit_queue: List[int] = []

    def _read_bus_bit(self) -> int:
        if self.bus_fault or not self._active_devices:
            return 1

        if self._fsm_state == self._FSM_SEARCH_ROM:
            byte_i = self._search_bit_idx // 8
            bit_mask = 1 << (self._search_bit_idx % 8)
            if self._search_phase == 0:
                # True bit AND across active devices
                val = 1 if all(d.rom_id[byte_i] & bit_mask for d in self._active_devices) else 0
                self._search_phase = 1
                return val
            elif self._search_phase == 1:
                # Complement bit AND across active devices
                val = 1 if all(not (d.rom_id[byte_i] & bit_mask) for d in self._active_devices) else 0
                self._search_phase = 2
                return val
            return 1

        if self._fsm_state == self._FSM_READ_MEM and self._selected is not None:
            if not self._out_bit_queue:
                b = self._selected.eeprom[self._mem_addr % len(self._selected.eeprom)]
                self._mem_addr = (self._mem_addr + 1) % len(self._selected.eeprom)
                self._out_bit_queue = [(b >> i) & 1 for i in range(8)]
            return self._out_bit_queue.pop(0)

        return 1

    def _write_bus_bit(self, bit: int):
        bit = 1 if (bit & 1) else 0
        if self.bus_fault or self._fsm_state == self._FSM_IDLE:
            return

        if self._fsm_state == self._FSM_SEARCH_ROM and self._search_phase == 2:
            byte_i = self._search_bit_idx // 8
            bit_mask = 1 << (self._search_bit_idx % 8)
            self._active_devices = [
                d for d in self._active_devices
                if (1 if (d.rom_id[byte_i] & bit_mask) else 0) == bit
            ]
            self._search_bit_idx += 1
            self._search_phase = 0
            if self._search_bit_idx >= 64:
                self._selected = self._active_devices[0] if self._active_devices else None
                self._fsm_state = self._FSM_WAIT_MEM_CMD
            return

        if self._fsm_state == self._FSM_MATCH_ROM:
            self._match_bits.append(bit)
            if len(self._match_bits) == 64:
                rom_bytes = bytearray(8)
                for idx, bval in enumerate(self._match_bits):
                    if bval:
                        rom_bytes[idx // 8] |= 1 << (idx % 8)
                target = bytes(rom_bytes)
                self._selected = next((d for d in self.devices if d.rom_id == target), None)
                self._active_devices = [self._selected] if self._selected else []
                self._fsm_state = self._FSM_WAIT_MEM_CMD if self._selected else self._FSM_IDLE
            return

        # Accumulate 8-bit command / address byte LSB first
        self._rx_bit_acc |= bit << self._rx_bit_cnt
        self._rx_bit_cnt += 1
        if self._rx_bit_cnt < 8:
            return

        byte_val = self._rx_bit_acc & 0xFF
        self._rx_bit_acc = 0
        self._rx_bit_cnt = 0

        if self._fsm_state == self._FSM_WAIT_ROM_CMD:
            if byte_val == 0xF0:  # Search ROM
                self._active_devices = list(self.devices)
                self._search_bit_idx = 0
                self._search_phase = 0
                self._fsm_state = self._FSM_SEARCH_ROM
            elif byte_val == 0x55:  # Match ROM
                self._match_bits = bytearray()
                self._fsm_state = self._FSM_MATCH_ROM
            elif byte_val == 0xCC:  # Skip ROM
                self._selected = self.devices[0] if self.devices else None
                self._active_devices = [self._selected] if self._selected else []
                self._fsm_state = self._FSM_WAIT_MEM_CMD if self._selected else self._FSM_IDLE
        elif self._fsm_state == self._FSM_WAIT_MEM_CMD:
            if byte_val == 0xF0:  # DS2431 Read Memory
                self._fsm_state = self._FSM_WAIT_ADDR_LO
        elif self._fsm_state == self._FSM_WAIT_ADDR_LO:
            self._mem_addr = byte_val
            self._fsm_state = self._FSM_WAIT_ADDR_HI
        elif self._fsm_state == self._FSM_WAIT_ADDR_HI:
            self._mem_addr |= byte_val << 8
            self._out_bit_queue = []
            self._fsm_state = self._FSM_READ_MEM

    def _finish_go_transaction(self):
        if self.ctrl_status & self.BIT_INITIALIZATION:
            present = (not self.bus_fault) and len(self.devices) > 0
            if present:
                self.ctrl_status |= self.BIT_PRESENCE_DETECT
            else:
                self.ctrl_status &= ~self.BIT_PRESENCE_DETECT
            self.ctrl_status &= ~(self.BIT_GO | self.BIT_INITIALIZATION)
            self.int_status |= self.INT_TIMEOUT
            self._reset_fsm(presence=present)
        elif self.ctrl_status & self.BIT_DIR_RX:
            if self.ctrl_status & self.BIT_SINGLE:
                self.rx_data = self._read_bus_bit()
            else:
                val = 0
                for i in range(8):
                    val |= self._read_bus_bit() << i
                self.rx_data = val
            self.ctrl_status &= ~self.BIT_GO
            self.int_status |= self.INT_RXCOMPLETE
        else:
            if self.ctrl_status & self.BIT_SINGLE:
                self._write_bus_bit(self.tx_data & 1)
            else:
                byte_val = self.tx_data & 0xFF
                for i in range(8):
                    self._write_bus_bit((byte_val >> i) & 1)
            self.ctrl_status &= ~self.BIT_GO
            self.int_status |= self.INT_TXCOMPLETE

        if self.intc and (self.ctrl_status & self.BIT_INTERRUPTMASK):
            self._irq_asserted_by_hdq = True
            self.intc.assert_irq(self.IRQ_NUM)

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_REVISION:
            return self.revision
        elif offset == self.REG_TX_DATA:
            return self.tx_data
        elif offset == self.REG_RX_DATA:
            return self.rx_data
        elif offset == self.REG_CTRL_STATUS:
            return self.ctrl_status
        elif offset == self.REG_INT_STATUS:
            val = self.int_status
            self.int_status = 0
            if self.intc and self._irq_asserted_by_hdq:
                self._irq_asserted_by_hdq = False
                self.intc.deassert_irq(self.IRQ_NUM)
            return val
        elif offset == self.REG_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_SYSSTATUS:
            return self.sysstatus
        return 0

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_TX_DATA:
            self.tx_data = val & 0xFF
        elif offset == self.REG_RX_DATA:
            # Allow clean/onewire.c style writes if TX alias maps to 0x08
            self.tx_data = val & 0xFF
        elif offset == self.REG_CTRL_STATUS:
            self.ctrl_status = val
            if val & self.BIT_GO:
                self._finish_go_transaction()
        elif offset == self.REG_SYSCONFIG:
            self.sysconfig = val & ~self.BIT_SOFTRESET
            if val & self.BIT_SOFTRESET:
                self.sysstatus = self.BIT_RESETDONE
                self.int_status = 0
                self._reset_fsm(presence=False)

    # ---- High-level inspection / fault-injection helpers ----

    def list_boards(self) -> List[Dict[str, Any]]:
        return [
            {
                "board_id": d.board_id,
                "name": d.name,
                "part_num": d.stored_part_num(),
                "serial_num": d.stored_serial(),
                "rev_str": d.rev_str,
                "rom_id": d.rom_id.hex(),
                "signature_valid": d.verify_signature(),
            }
            for d in self.devices
        ]

    def get_board(self, name: str) -> Optional[OneWireBoardDevice]:
        target = name.strip().upper()
        return next((d for d in self.devices if d.name.upper() == target), None)

    def verify_board(self, name: str) -> bool:
        dev = self.get_board(name)
        return dev.verify_signature() if dev is not None else False

    def corrupt_board_serial(self, name: str, new_serial: str) -> bool:
        """Overwrite stored EEPROM serial without recomputing MD5 signature (triggers 0x03/sig fail)."""
        dev = self.get_board(name)
        if dev is None:
            return False
        dev.serial_num = new_serial
        _write_cstr(dev.eeprom, 0x79, 17, new_serial)
        return True

    def remove_board(self, name: str) -> bool:
        target = name.strip().upper()
        before = len(self.devices)
        self.devices = [d for d in self.devices if d.name.upper() != target]
        return len(self.devices) < before

    def restore_default_boards(self):
        self.bus_fault = False
        self.devices = make_default_dsmc2_boards()
