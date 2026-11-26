"""
Tensilica Xtensa 32-bit Coprocessor Architecture & Coprocessor Subsystems.
Models IOB0 (SATA, HDMI, Accelerometer), IOB1 (Sensor Calibration & Defect Tables),
and ISP1/ISP2 (Wavelet REDCODE compression and DDR training).
"""

import os
import math
import zlib
import struct
from typing import Dict, Any, Callable, List, Optional, Tuple


class XtensaCore:
    """
    32-bit Tensilica Xtensa LX Coprocessor Core.
    IRAM: 0x40000000, DRAM: 0x3FFE0000.
    """

    IRAM_BASE = 0x40000000
    DRAM_BASE = 0x3FFE0000
    IRAM_SIZE = 64 * 1024
    DRAM_SIZE = 64 * 1024

    STATE_UNINITIALIZED = "UNINITIALIZED"
    STATE_READY = "READY"
    STATE_RUNNING = "RUNNING"
    STATE_IDLE = "IDLE"
    STATE_HALTED = "HALTED"

    def __init__(self, name: str, core_id: int):
        self.name = name
        self.core_id = core_id
        self.state = self.STATE_UNINITIALIZED

        # Register File: a0..a15 (Windowed registers)
        self.regs = [0] * 16
        self.regs[1] = self.DRAM_BASE + self.DRAM_SIZE - 0x100  # default DRAM stack top 0x3FFEFF00
        self.pc = self.IRAM_BASE
        self.ps = 0x00040020  # WOE=1, User/Supervisor mode, IRQ enabled
        self.sar = 0
        self.litbase = 0
        self.vecbase = self.IRAM_BASE
        self.windowbase = 0
        self.windowstart = 1

        # Memory Buffers
        self.iram = bytearray(self.IRAM_SIZE)
        self.dram = bytearray(self.DRAM_SIZE)

        self.cycles_executed = 0
        self.instructions_executed = 0
        self.real_instructions_retired = 0
        self.last_decoded_mnemonic = "NONE"
        self.mmio_writes: Dict[int, int] = {}

        # Real-FW ASIC upload telemetry (Priority 3, Tip #2)
        self.fw_upload_count = 0
        self.iram_uploaded_bytes = 0
        self.dram_uploaded_bytes = 0
        self.launched_by_fw = False
        self.upload_log: List[Tuple[int, int]] = []
        self.on_mmio_write: Optional[Callable[[int, int, int], None]] = None

    @staticmethod
    def _sign_extend(val: int, bits: int) -> int:
        sign_bit = 1 << (bits - 1)
        return (val & (sign_bit - 1)) - (val & sign_bit)

    def read_u32(self, addr: int) -> int:
        """Read a 32-bit little-endian word from Xtensa private IRAM, DRAM, or MMIO."""
        addr &= 0xFFFFFFFF
        if self.IRAM_BASE <= addr <= self.IRAM_BASE + self.IRAM_SIZE - 4:
            off = addr - self.IRAM_BASE
            return struct.unpack_from("<I", self.iram, off)[0]
        if self.DRAM_BASE <= addr <= self.DRAM_BASE + self.DRAM_SIZE - 4:
            off = addr - self.DRAM_BASE
            return struct.unpack_from("<I", self.dram, off)[0]
        return self.mmio_writes.get(addr, 0)

    def write_u32(self, addr: int, val: int) -> None:
        """Write a 32-bit little-endian word into Xtensa private DRAM/IRAM or local MMIO."""
        addr &= 0xFFFFFFFF
        val &= 0xFFFFFFFF
        if self.DRAM_BASE <= addr <= self.DRAM_BASE + self.DRAM_SIZE - 4:
            off = addr - self.DRAM_BASE
            struct.pack_into("<I", self.dram, off, val)
        elif self.IRAM_BASE <= addr <= self.IRAM_BASE + self.IRAM_SIZE - 4:
            off = addr - self.IRAM_BASE
            struct.pack_into("<I", self.iram, off, val)
        if not (self.DRAM_BASE <= addr < self.DRAM_BASE + self.DRAM_SIZE) or (0x3FFE8000 <= addr < 0x3FFE9000):
            self.mmio_writes[addr] = val
            if self.on_mmio_write is not None and 0x3FFE8000 <= addr < 0x3FFE9000:
                self.on_mmio_write(self.core_id, addr, val)

    def decode_and_step(self) -> str:
        """Decode and execute one real Tensilica Xtensa LX instruction at ``self.pc``."""
        if not (self.IRAM_BASE <= self.pc < self.IRAM_BASE + self.IRAM_SIZE - 3):
            self.pc = self.IRAM_BASE
            self.last_decoded_mnemonic = "RESET_PC"
            return "RESET_PC"

        off = self.pc - self.IRAM_BASE
        b0 = self.iram[off]
        b1 = self.iram[off + 1]
        is_narrow = (b0 & 0x08) != 0
        mnemonic = "NOP"

        if is_narrow:
            op0 = b0 & 0x0F
            n1 = (b0 >> 4) & 0x0F
            n2 = b1 & 0x0F
            n3 = (b1 >> 4) & 0x0F
            next_pc = self.pc + 2

            if op0 == 0x08:  # L32I.N at, as, imm4*4 (t=n1, s=n2, imm4=n3)
                addr = (self.regs[n2] + (n3 << 2)) & 0xFFFFFFFF
                self.regs[n1] = self.read_u32(addr)
                mnemonic = "L32I.N"
            elif op0 == 0x09:  # S32I.N at, as, imm4*4 (t=n1, s=n2, imm4=n3)
                addr = (self.regs[n2] + (n3 << 2)) & 0xFFFFFFFF
                self.write_u32(addr, self.regs[n1])
                mnemonic = "S32I.N"
            elif op0 == 0x0A:  # ADD.N ar, as, at (t=n1, s=n2, r=n3)
                self.regs[n3] = (self.regs[n2] + self.regs[n1]) & 0xFFFFFFFF
                mnemonic = "ADD.N"
            elif op0 == 0x0B:  # ADDI.N ar, as, imm4 (imm=n1 (0->-1), s=n2, r=n3)
                imm = -1 if n1 == 0 else n1
                self.regs[n3] = (self.regs[n2] + imm) & 0xFFFFFFFF
                mnemonic = "ADDI.N"
            elif op0 == 0x0C:  # MOVI.N as, imm7
                raw7 = ((n1 & 0x07) << 4) | n3
                if (raw7 & 0x60) == 0x60:
                    raw7 -= 128
                self.regs[n2] = raw7 & 0xFFFFFFFF
                mnemonic = "MOVI.N"
            elif op0 == 0x0D:
                if b1 == 0xF0 and n1 == 0:
                    mnemonic = "RET.N"
                    next_pc = self.regs[0] if self.IRAM_BASE <= self.regs[0] < self.IRAM_BASE + self.IRAM_SIZE else self.pc
                    self.state = self.STATE_IDLE
                elif b1 == 0xF0 and n1 == 1:
                    mnemonic = "RETW.N"
                    next_pc = self.regs[0] if self.IRAM_BASE <= self.regs[0] < self.IRAM_BASE + self.IRAM_SIZE else self.pc
                    self.state = self.STATE_IDLE
                elif b1 == 0xF0 and n1 == 3:
                    mnemonic = "NOP.N"
                else:
                    self.regs[n1] = self.regs[n2]
                    mnemonic = "MOV.N"
            self.pc = next_pc
        else:
            b2 = self.iram[off + 2]
            insn24 = b0 | (b1 << 8) | (b2 << 16)
            op0 = insn24 & 0xF
            t = (insn24 >> 4) & 0xF
            s = (insn24 >> 8) & 0xF
            r = (insn24 >> 12) & 0xF
            imm8 = (insn24 >> 16) & 0xFF
            next_pc = self.pc + 3

            if insn24 == 0:
                mnemonic = "ILL"
            elif (b0 & 0x3F) == 0x36:  # ENTRY as, imm12*8
                imm12 = (insn24 >> 12) & 0xFFF
                self.regs[s] = (self.regs[s] - (imm12 << 3)) & 0xFFFFFFFF
                mnemonic = "ENTRY"
            elif op0 == 1:  # L32R at, sym16
                imm16 = (insn24 >> 8) & 0xFFFF
                off32 = self._sign_extend(imm16, 16) << 2
                target = (((self.pc + 3) & ~0x3) + off32) & 0xFFFFFFFF
                self.regs[t] = self.read_u32(target)
                mnemonic = "L32R"
            elif op0 == 2:
                if r == 0x2:  # L32I at, as, imm8*4
                    self.regs[t] = self.read_u32(self.regs[s] + (imm8 << 2))
                    mnemonic = "L32I"
                elif r == 0x6:  # S32I at, as, imm8*4
                    self.write_u32(self.regs[s] + (imm8 << 2), self.regs[t])
                    mnemonic = "S32I"
                elif r == 0x0:  # L8UI
                    addr = (self.regs[s] + imm8) & 0xFFFFFFFF
                    self.regs[t] = (self.read_u32(addr & ~3) >> ((addr & 3) * 8)) & 0xFF
                    mnemonic = "L8UI"
                elif r == 0x1:  # L16UI
                    addr = (self.regs[s] + (imm8 << 1)) & 0xFFFFFFFF
                    self.regs[t] = (self.read_u32(addr & ~3) >> ((addr & 2) * 8)) & 0xFFFF
                    mnemonic = "L16UI"
                elif r == 0xA:  # MOVI at, imm12
                    imm12 = ((s << 8) | imm8)
                    self.regs[t] = self._sign_extend(imm12, 12) & 0xFFFFFFFF
                    mnemonic = "MOVI"
                elif r == 0xC:  # ADDI at, as, simm8
                    self.regs[t] = (self.regs[s] + self._sign_extend(imm8, 8)) & 0xFFFFFFFF
                    mnemonic = "ADDI"
                elif r == 0xD:  # ADDMI at, as, simm8*256
                    self.regs[t] = (self.regs[s] + (self._sign_extend(imm8, 8) << 8)) & 0xFFFFFFFF
                    mnemonic = "ADDMI"
            elif op0 == 0:
                op1 = (insn24 >> 16) & 0xF
                op2 = (insn24 >> 20) & 0xF
                if op1 == 0 and op2 == 0 and r == 0:
                    if s == 8 and t == 0:
                        mnemonic = "RET"
                        next_pc = self.regs[0] if self.IRAM_BASE <= self.regs[0] < self.IRAM_BASE + self.IRAM_SIZE else self.pc
                        self.state = self.STATE_IDLE
                    elif s == 9 and t == 0:
                        mnemonic = "RETW"
                        next_pc = self.regs[0] if self.IRAM_BASE <= self.regs[0] < self.IRAM_BASE + self.IRAM_SIZE else self.pc
                        self.state = self.STATE_IDLE
                    elif s == 10 and t == 0:
                        mnemonic = "JX"
                        target = self.regs[t]
                        if self.IRAM_BASE <= target < self.IRAM_BASE + self.IRAM_SIZE:
                            next_pc = target
                elif op2 == 1 and op1 == 3:  # WSR at, sr
                    sr = (s << 4) | r
                    if sr == 231:
                        self.vecbase = self.regs[t]
                    elif sr == 230:
                        self.ps = self.regs[t]
                    elif sr == 3:
                        self.sar = self.regs[t] & 0x3F
                    mnemonic = "WSR"
                elif op2 == 0 and op1 == 3:  # RSR at, sr
                    sr = (s << 4) | r
                    if sr == 231:
                        self.regs[t] = self.vecbase
                    elif sr == 230:
                        self.regs[t] = self.ps
                    elif sr == 3:
                        self.regs[t] = self.sar
                    mnemonic = "RSR"
                elif op2 == 8 and op1 == 0:  # ADD ar, as, at
                    self.regs[r] = (self.regs[s] + self.regs[t]) & 0xFFFFFFFF
                    mnemonic = "ADD"
                elif op2 == 0xC and op1 == 0:  # SUB ar, as, at
                    self.regs[r] = (self.regs[s] - self.regs[t]) & 0xFFFFFFFF
                    mnemonic = "SUB"
                elif op2 == 1 and op1 == 0:  # AND
                    self.regs[r] = self.regs[s] & self.regs[t]
                    mnemonic = "AND"
                elif op2 == 2 and op1 == 0:  # OR
                    self.regs[r] = self.regs[s] | self.regs[t]
                    mnemonic = "OR"
                elif op2 == 3 and op1 == 0:  # XOR
                    self.regs[r] = self.regs[s] ^ self.regs[t]
                    mnemonic = "XOR"
                elif op2 in (0, 1) and op1 == 1:  # SLLI
                    sa = 32 - ((op2 & 1) << 4 | s)
                    self.regs[r] = (self.regs[t] << (sa & 0x1F)) & 0xFFFFFFFF
                    mnemonic = "SLLI"
                elif op2 == 4 and op1 == 1:  # SRLI
                    self.regs[r] = (self.regs[t] & 0xFFFFFFFF) >> (s & 0xF)
                    mnemonic = "SRLI"
                elif op2 in (4, 5):  # EXTUI
                    shift = ((op1 & 1) << 4) | s
                    mask = (1 << (op2 + 1)) - 1
                    self.regs[r] = (self.regs[t] >> shift) & mask
                    mnemonic = "EXTUI"
            elif op0 == 5:  # CALL4 / CALL8 / CALL12
                off18 = self._sign_extend((insn24 >> 6) & 0x3FFFF, 18) << 2
                target = (((self.pc >> 2) << 2) + off18 + 4) & 0xFFFFFFFF
                self.regs[0] = next_pc
                if self.IRAM_BASE <= target < self.IRAM_BASE + self.IRAM_SIZE:
                    next_pc = target
                mnemonic = "CALL"
            elif op0 == 6 and (b0 & 0x3F) == 0x06:  # J offset18
                off18 = self._sign_extend((insn24 >> 6) & 0x3FFFF, 18)
                target = (self.pc + off18 + 4) & 0xFFFFFFFF
                if self.IRAM_BASE <= target < self.IRAM_BASE + self.IRAM_SIZE:
                    next_pc = target
                mnemonic = "J"
            elif op0 == 6 and (b0 & 0x3F) in (0x16, 0x26, 0x36):  # BZ / BEQZ / BNEZ
                kind = (r >> 2) & 0x3
                imm12 = self._sign_extend((insn24 >> 12) & 0xFFF, 12)
                cond = (self.regs[s] == 0) if kind == 0 else (self.regs[s] != 0)
                if cond:
                    target = (self.pc + imm12 + 4) & 0xFFFFFFFF
                    if self.IRAM_BASE <= target < self.IRAM_BASE + self.IRAM_SIZE:
                        next_pc = target
                mnemonic = "BEQZ" if kind == 0 else "BNEZ"
            elif op0 == 7:  # BEQ / BNE / BLT / BGE / BLTU / BGEU
                imm8s = self._sign_extend(imm8, 8)
                vs, vt = self.regs[s], self.regs[t]
                ss, st = self._sign_extend(vs, 32), self._sign_extend(vt, 32)
                cond = (
                    (vs == vt) if r == 1 else
                    (vs != vt) if r == 9 else
                    (ss < st) if r == 2 else
                    (ss >= st) if r == 10 else
                    (vs < vt) if r == 3 else
                    (vs >= vt) if r == 11 else False
                )
                if cond:
                    target = (self.pc + imm8s + 4) & 0xFFFFFFFF
                    if self.IRAM_BASE <= target < self.IRAM_BASE + self.IRAM_SIZE:
                        next_pc = target
                mnemonic = "BCOND"

            self.pc = next_pc

        self.real_instructions_retired += 1
        self.instructions_executed += 1
        self.cycles_executed += 2
        self.last_decoded_mnemonic = mnemonic
        return mnemonic

    def upload_segment(self, dest_addr: int, data: bytes) -> int:
        """Accept a firmware-uploaded binary segment into IRAM (@0x40000000) or DRAM (@0x3FFE0000)."""
        if not data:
            return 0
        if self.IRAM_BASE <= dest_addr < self.IRAM_BASE + self.IRAM_SIZE:
            off = dest_addr - self.IRAM_BASE
            n = min(len(data), self.IRAM_SIZE - off)
            self.iram[off : off + n] = data[:n]
            self.iram_uploaded_bytes += n
            self.state = self.STATE_READY
            self.pc = self.IRAM_BASE
        elif self.DRAM_BASE <= dest_addr < self.DRAM_BASE + self.DRAM_SIZE:
            off = dest_addr - self.DRAM_BASE
            n = min(len(data), self.DRAM_SIZE - off)
            self.dram[off : off + n] = data[:n]
            self.dram_uploaded_bytes += n
            n_written = n
            self.fw_upload_count += 1
            self.upload_log.append((dest_addr, n_written))
            return n_written
        else:
            return 0

        self.fw_upload_count += 1
        self.upload_log.append((dest_addr, n))
        return n

    def release_reset(self) -> None:
        """Transition core to RUNNING and start executing loaded Xtensa entry code on reset release."""
        self.launched_by_fw = True
        self.state = self.STATE_RUNNING
        entry = struct.unpack_from("<I", self.dram, 12)[0]
        ps_init = struct.unpack_from("<I", self.dram, 16)[0]
        if self.IRAM_BASE <= entry < self.IRAM_BASE + self.IRAM_SIZE - 16:
            self.ps = ps_init if ps_init else 0x00040020
            self.regs[1] = self.DRAM_BASE + self.DRAM_SIZE - 0x100
            entry_off = entry - self.IRAM_BASE
            # Shipped RED Xtensa binaries place an 8-byte literal header before ENTRY at +8
            if entry_off + 8 < self.IRAM_SIZE and self.iram[entry_off + 8] == 0x36:
                self.pc = entry + 8
            else:
                self.pc = entry
        elif self.iram[0x300] != 0:
            self.pc = self.IRAM_BASE + 0x300
        self.step(16)

    def load_binaries(self, iram_path: str, dram_path: Optional[str] = None) -> bool:
        """Load firmware binaries into IRAM and DRAM."""
        if os.path.exists(iram_path):
            with open(iram_path, "rb") as f:
                data = f.read()
            size = min(len(data), self.IRAM_SIZE)
            self.iram[:size] = data[:size]
            self.state = self.STATE_READY
            self.pc = self.IRAM_BASE

        if dram_path and os.path.exists(dram_path):
            with open(dram_path, "rb") as f:
                data = f.read()
            size = min(len(data), self.DRAM_SIZE)
            self.dram[:size] = data[:size]

        return self.state == self.STATE_READY

    def step(self, count: int = 1):
        """Execute real Xtensa instructions if loaded at PC, else advance simulated cycles."""
        if self.state in (self.STATE_READY, self.STATE_IDLE, self.STATE_RUNNING):
            self.state = self.STATE_RUNNING
            for _ in range(count):
                if self.state != self.STATE_RUNNING:
                    break
                off = self.pc - self.IRAM_BASE
                if 0 <= off < self.IRAM_SIZE - 3 and self.iram[off : off + 3] != b"\x00\x00\x00":
                    self.decode_and_step()
                else:
                    self.instructions_executed += 1
                    self.cycles_executed += 2
                    self.pc = self.IRAM_BASE + ((self.pc - self.IRAM_BASE + 3) % self.IRAM_SIZE)

    def handle_c2c_word(self, word: int) -> Optional[int]:
        """Process incoming 32-bit C2C mailbox word. Default echo with ACK."""
        return (word ^ 0xA5A50000) & 0xFFFFFFFF

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Process structured C2C command packet and trigger Xtensa MMIO doorbell ACK."""
        self.write_u32(0x3FFE8010, cmd & 0xFFFFFFFF)
        self.write_u32(0x3FFE8014, payload[0] & 0xFFFFFFFF if payload else 0)
        self.step(4)
        self.write_u32(0x3FFE8000, 0x00020000 | (cmd & 0xFF))
        return [0x00000000] # Default Success ACK

    def get_status(self) -> Dict[str, Any]:
        """Return core status."""
        return {
            "name": self.name,
            "core_id": self.core_id,
            "state": self.state,
            "pc": f"0x{self.pc:08X}",
            "instructions": self.instructions_executed,
            "cycles": self.cycles_executed,
            "iram_loaded": any(self.iram),
            "dram_loaded": any(self.dram),
            "fw_upload_count": self.fw_upload_count,
            "iram_uploaded_bytes": self.iram_uploaded_bytes,
            "dram_uploaded_bytes": self.dram_uploaded_bytes,
            "launched_by_fw": self.launched_by_fw,
            "real_instructions_retired": self.real_instructions_retired,
            "last_decoded_mnemonic": self.last_decoded_mnemonic,
            "mmio_writes_count": len(self.mmio_writes),
        }


class Iob0Coprocessor(XtensaCore):
    """
    IOB0 Coprocessor (Input/Output Bridge 0).
    Controls SATA 3.0 HBA storage link, HDMI transmitter, and STACCELERO SPI accelerometer.
    """

    def __init__(self):
        super().__init__("IOB0", 0)

        # 1. SATA 3.0 HBA Subsystem
        self.sata_link_speed_gbps = 6.0   # SATA 3.0 (6 Gbps)
        self.sata_link_up = True
        self.sata_port_cmd = 0x00010001   # Start & Active
        self.sata_dma_frames_written = 0
        self.sata_bytes_transferred = 0

        # 2. HDMI 1080p Video Transmitter
        self.hdmi_connected = True
        self.hdmi_resolution = (1920, 1080)
        self.hdmi_fps = 60.0
        self.hdmi_hdcp_authenticated = True
        self.hdmi_mode = "CLEAN"  # Options: "CLEAN", "BROADCAST_TALLY", "FRAME_GUIDES"
        self.hdmi_frames_rendered = 0

        # 3. STACCELERO SPI Accelerometer
        self.accel_x = 0.02
        self.accel_y = 0.01
        self.accel_z = 0.98

    def set_accelerometer(self, x: float, y: float, z: float):
        """Set accelerometer force vector in g-force."""
        self.accel_x = float(x)
        self.accel_y = float(y)
        self.accel_z = float(z)

    def get_tilt_angles(self) -> Tuple[float, float, bool]:
        """
        Return (pitch_deg, roll_deg, is_level).
        Feeds the RedUi horizon level assist.
        """
        pitch = math.atan2(self.accel_y, math.sqrt(self.accel_x**2 + self.accel_z**2)) * (180.0 / math.pi)
        roll = math.atan2(-self.accel_x, self.accel_z) * (180.0 / math.pi)
        is_level = abs(pitch) < 1.0 and abs(roll) < 1.0
        return (round(pitch, 1), round(roll, 1), is_level)

    def record_frame_dma(self, frame_size_bytes: int):
        """Simulate high-speed SATA DMA frame write to RED MINI-MAG."""
        self.sata_dma_frames_written += 1
        self.sata_bytes_transferred += frame_size_bytes
        self.step(50)

    def set_hdmi_mode(self, mode: str):
        """Set HDMI output overlay mode: 'CLEAN', 'BROADCAST_TALLY', or 'FRAME_GUIDES'."""
        m = mode.strip().upper()
        if m in ("CLEAN", "BROADCAST_TALLY", "FRAME_GUIDES"):
            self.hdmi_mode = m

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Handle C2C storage or display commands."""
        super().handle_c2c_command(cmd, payload)
        if cmd == 0x10: # Query SATA Status
            return [0x01 if self.sata_link_up else 0x00, self.sata_dma_frames_written]
        elif cmd == 0x20: # Query Tilt
            pitch, roll, level = self.get_tilt_angles()
            return [int(pitch * 10), int(roll * 10), 1 if level else 0]
        elif cmd == 0x26: # Monitor Pipeline Config
            mode_flag = payload[1] if len(payload) > 1 else 0
            if mode_flag == 1:
                self.hdmi_mode = "BROADCAST_TALLY"
            elif mode_flag == 2:
                self.hdmi_mode = "FRAME_GUIDES"
            else:
                self.hdmi_mode = "CLEAN"
            return [0x00000000]
        return [0x00]

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        pitch, roll, level = self.get_tilt_angles()
        base.update({
            "sata": {
                "link_up": self.sata_link_up,
                "speed_gbps": self.sata_link_speed_gbps,
                "frames_written": self.sata_dma_frames_written,
                "mb_transferred": round(self.sata_bytes_transferred / (1024 * 1024), 2)
            },
            "hdmi": {
                "connected": self.hdmi_connected,
                "resolution": f"{self.hdmi_resolution[0]}x{self.hdmi_resolution[1]} @ {int(self.hdmi_fps)}Hz",
                "hdcp": self.hdmi_hdcp_authenticated,
                "mode": self.hdmi_mode,
                "frames_rendered": self.hdmi_frames_rendered
            },
            "accelerometer": {
                "pitch_deg": pitch,
                "roll_deg": roll,
                "is_level": level,
                "vector": [round(self.accel_x, 2), round(self.accel_y, 2), round(self.accel_z, 2)]
            }
        })
        return base


class Iob1Coprocessor(XtensaCore):
    """
    IOB1 Coprocessor (Sensor Calibration Engine).
    Executes black shading dark-level calibration, defect pixel table lookups, and Bayer green alignment.
    """

    def __init__(self):
        super().__init__("IOB1", 1)

        # Calibration state
        self.is_calibrating = False
        self.cal_progress = 1.0
        self.calibrated_temp_c = 39.0
        self.calibrated_exposure = "1/48"
        self.cal_map_count = 3

        # Defect pixel defect maps (Factory & User)
        self.factory_defects: List[Tuple[int, int]] = [(1024, 768), (2048, 1152), (3072, 1536)]
        self.user_defects: List[Tuple[int, int]] = []
        self.pixels_corrected_total = 0

    def run_black_shading(self, sensor_temp_c: float = 39.0, exposure: str = "1/48") -> Dict[str, Any]:
        """
        Execute full sensor dark-level calibration.
        Analyzes dark current slope and generates calibration map.
        """
        self.is_calibrating = True
        self.cal_progress = 0.0
        self.step(1500)

        # Discover 2 user hot pixels during thermal analyze_slope
        self.user_defects = [(1536, 920), (2800, 1400)]
        self.calibrated_temp_c = sensor_temp_c
        self.calibrated_exposure = exposure
        self.cal_progress = 1.0
        self.is_calibrating = False

        return {
            "status": "CALIBRATED",
            "target_temp_c": self.calibrated_temp_c,
            "target_exposure": self.calibrated_exposure,
            "defects_masked": len(self.factory_defects) + len(self.user_defects),
            "cal_map": f"cal_{int(sensor_temp_c)}c_exp{exposure.replace('/', '_')}.cal"
        }

    def process_sensor_frame(self, width: int, height: int) -> int:
        """Simulate real-time defective pixel replacement and Bayer green alignment."""
        total_defects = len(self.factory_defects) + len(self.user_defects)
        self.pixels_corrected_total += total_defects
        self.step(100)
        return total_defects

    def handle_c2c_command(self, cmd: int, payload: List[int]) -> List[int]:
        """Handle C2C black shading calibration commands."""
        super().handle_c2c_command(cmd, payload)
        if cmd == 0x30:  # Trigger Black Shading
            t_c = payload[0] if payload else 39
            res = self.run_black_shading(float(t_c))
            return [0x01, res["defects_masked"]]
        return [0x00]

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "black_shading": {
                "calibrated": not self.is_calibrating,
                "target_temp_c": self.calibrated_temp_c,
                "target_exposure": self.calibrated_exposure,
                "progress": self.cal_progress
            },
            "defect_tables": {
                "factory_defects": len(self.factory_defects),
                "user_defects": len(self.user_defects),
                "pixels_corrected": self.pixels_corrected_total
            }
        })
        return base


class IspCoprocessor(XtensaCore):
    """
    Image Signal Processor (ISP1 & ISP2).
    Dual high-performance coprocessors executing REDCODE Discrete Wavelet Transform (DWT),
    component sub-band slicing (G1/B/R/G2), and DDR self-training.
    """

    def __init__(self, core_id: int = 2):
        name = f"ISP{core_id - 1}"
        super().__init__(name, core_id)

        self.ddr_training_passed = True
        self.wavelet_compression_ratio = "8:1"
        self.frames_compressed = 0
        self.wavelet_dwt_levels = 3

    def compress_frame(self, raw_bytes: bytes, ratio: str = "8:1") -> Dict[str, Any]:
        """
        Simulate REDCODE Discrete Wavelet Transform compression.
        Splits Bayer raw data into 4 sub-bands (G1, B, R, G2) and generates CRC32.
        """
        self.wavelet_compression_ratio = ratio
        ratio_int = int(ratio.split(":")[0]) if ":" in ratio else 8
        compressed_size = max(64, len(raw_bytes) // ratio_int)

        # Component slice sub-bands
        slice_crcs = {
            "G1": zlib.crc32(b"G1" + raw_bytes[:100]) & 0xFFFFFFFF,
            "B": zlib.crc32(b"B" + raw_bytes[100:200]) & 0xFFFFFFFF,
            "R": zlib.crc32(b"R" + raw_bytes[200:300]) & 0xFFFFFFFF,
            "G2": zlib.crc32(b"G2" + raw_bytes[300:400]) & 0xFFFFFFFF,
        }

        self.frames_compressed += 1
        self.step(200)

        return {
            "compressed_size_bytes": compressed_size,
            "ratio": ratio,
            "dwt_levels": self.wavelet_dwt_levels,
            "slice_crcs": slice_crcs,
            "crc32": zlib.crc32(raw_bytes[:compressed_size]) & 0xFFFFFFFF
        }

    def get_status(self) -> Dict[str, Any]:
        base = super().get_status()
        base.update({
            "ddr_training": "PASS (Modified SCL V2)",
            "compression_ratio": self.wavelet_compression_ratio,
            "frames_compressed": self.frames_compressed,
            "dwt_levels": self.wavelet_dwt_levels
        })
        return base
