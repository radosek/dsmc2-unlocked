"""
Trace probe & real-hardware stolen-instruction trampoline exporter (Priority 3, Tip #1).

Lets the emulator observe key firmware milestones and interrupt entry/exit points with
negligible overhead (per-address ``UC_HOOK_CODE`` hooks), and exports the exact displaced
32-bit ARM instruction + trampoline sequence needed to deploy the same trace probe onto
physical DSMC2 hardware.
"""

from dataclasses import dataclass, asdict
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

import unicorn
from unicorn import arm_const


# Stock 7.4.1 trace points: init milestones, filesystems, CDB2, ASIC upload, and IRQ vector.
DEFAULT_PROBE_POINTS: Tuple[Tuple[int, str, str], ...] = (
    (0x80021048, "early_init", "milestone"),
    (0x800201C0, "irq_vector_dispatch", "irq"),
    (0x806C761C, "late_init_entry", "milestone"),
    (0x80008310, "init_filesystem", "milestone"),
    (0x8067FED4, "mount_all_partitions", "milestone"),
    (0x8007FB58, "cdb2_init", "milestone"),
    (0x80670B10, "iob_isp_binary_download", "milestone"),
    (0x80664D18, "isp_load_from_embedded", "milestone"),
    (0x80664ECC, "iob_load_from_embedded", "milestone"),
    (0x806D588C, "spi_write_and_read", "milestone"),
    (0x80008CB4, "run_application", "milestone"),
)


def encode_arm_branch(from_pc: int, to_pc: int, link: bool = False) -> int:
    """Encode an unconditional ARMv7 ``B`` or ``BL`` instruction."""
    if (from_pc & 0x3) or (to_pc & 0x3):
        raise ValueError(f"Unaligned branch target: 0x{from_pc:08X} -> 0x{to_pc:08X}")
    offset = to_pc - (from_pc + 8)
    imm24 = offset >> 2
    if imm24 < -0x800000 or imm24 > 0x7FFFFF:
        raise ValueError(f"Branch out of 32 MiB ARM range: 0x{from_pc:08X} -> 0x{to_pc:08X}")
    opcode = 0xEB000000 if link else 0xEA000000
    return opcode | (imm24 & 0x00FFFFFF)


def build_trampoline_words(
    target_pc: int,
    probe_id: int,
    displaced_insn: int,
    trampoline_addr: int,
    logger_fn_addr: int,
) -> List[int]:
    """Build the 6-word ARM trampoline for patching ``target_pc`` on real hardware.

    Sequence at ``trampoline_addr``:
      +0x00: PUSH {r0-r3, r12, lr}   (0xE92D500F)
      +0x04: MOV  r0, #(probe_id)    (0xE3A00000 | (probe_id & 0xFF))
      +0x08: BL   logger_fn_addr
      +0x0C: POP  {r0-r3, r12, lr}   (0xE8BD500F)
      +0x10: <displaced_insn>        (re-execute original stolen word)
      +0x14: B    (target_pc + 4)    (resume straight-line flow)
    """
    return [
        0xE92D500F,
        0xE3A00000 | (probe_id & 0xFF),
        encode_arm_branch(trampoline_addr + 8, logger_fn_addr, link=True),
        0xE8BD500F,
        displaced_insn & 0xFFFFFFFF,
        encode_arm_branch(trampoline_addr + 20, target_pc + 4, link=False),
    ]


@dataclass
class TraceEvent:
    """Single runtime trace-probe observation recorded during emulation."""

    index: int
    instruction_count: int
    pc: int
    stock_pc: int
    label: str
    kind: str
    r0: int
    r1: int
    r2: int
    r3: int
    lr: int
    cpsr: int

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pc_hex"] = f"0x{self.pc:08X}"
        d["stock_pc_hex"] = f"0x{self.stock_pc:08X}"
        return d


@dataclass
class HwPatchDescriptor:
    """Real-hardware binary patch descriptor pairing displaced insn and trampoline."""

    probe_id: int
    target_pc: int
    label: str
    displaced_insn: int
    displaced_hex: str
    trampoline_addr: int
    hook_branch_insn: int
    trampoline_words: List[int]
    trampoline_hex: List[str]


class TraceProbe:
    """Structured PC/IRQ trace probe bridging emulator execution and real HW trampolines."""

    def __init__(
        self,
        points: Optional[Tuple[Tuple[int, str, str], ...]] = None,
        max_events: int = 4096,
    ):
        self.points: Dict[int, Tuple[str, str]] = {}
        for pc, label, kind in (points if points is not None else DEFAULT_PROBE_POINTS):
            self.points[pc & 0xFFFFFFFF] = (label, kind)
        self.max_events = max_events
        self.events: List[TraceEvent] = []
        self._hook_handles: List[int] = []
        self._attached_cam = None

    def add_point(self, stock_pc: int, label: str, kind: str = "milestone"):
        """Register an additional stock PC milestone or interrupt handler."""
        self.points[stock_pc & 0xFFFFFFFF] = (label, kind)

    def attach(self, cam) -> int:
        """Install zero-overhead per-address Unicorn code hooks onto ``cam.cpu.mu``."""
        self.detach()
        self._attached_cam = cam
        mu = cam.cpu.mu
        addr_map = cam.cpu.addr_map

        for stock_pc, (label, kind) in self.points.items():
            target_pc = addr_map.to_loaded(stock_pc) if hasattr(addr_map, "to_loaded") else stock_pc

            def _cb(_uc, address, _size, _ud, lbl=label, k=kind, spc=stock_pc):
                if len(self.events) >= self.max_events:
                    return
                uc = self._attached_cam.cpu.mu
                ev = TraceEvent(
                    index=len(self.events),
                    instruction_count=getattr(self._attached_cam, "instruction_count", 0),
                    pc=address,
                    stock_pc=spc,
                    label=lbl,
                    kind=k,
                    r0=uc.reg_read(arm_const.UC_ARM_REG_R0),
                    r1=uc.reg_read(arm_const.UC_ARM_REG_R1),
                    r2=uc.reg_read(arm_const.UC_ARM_REG_R2),
                    r3=uc.reg_read(arm_const.UC_ARM_REG_R3),
                    lr=uc.reg_read(arm_const.UC_ARM_REG_LR),
                    cpsr=uc.reg_read(arm_const.UC_ARM_REG_CPSR),
                )
                self.events.append(ev)

            handle = mu.hook_add(unicorn.UC_HOOK_CODE, _cb, begin=target_pc, end=target_pc)
            self._hook_handles.append(handle)

        return len(self._hook_handles)

    def detach(self):
        """Remove any active Unicorn hooks."""
        if self._attached_cam is not None and self._hook_handles:
            mu = self._attached_cam.cpu.mu
            for handle in self._hook_handles:
                try:
                    mu.hook_del(handle)
                except Exception:
                    pass
        self._hook_handles.clear()
        self._attached_cam = None

    def milestones_hit(self) -> List[str]:
        """Return unique milestone labels observed, preserving first-hit order."""
        seen = []
        for ev in self.events:
            if ev.label not in seen:
                seen.append(ev.label)
        return seen

    def build_hw_patch_table(
        self,
        cam,
        trampoline_base: int = 0x80F00000,
        logger_fn_addr: int = 0x808438C4,
        stride_bytes: int = 32,
    ) -> List[HwPatchDescriptor]:
        """Generate real-HW patch descriptors reading displaced words from loaded RAM."""
        descriptors: List[HwPatchDescriptor] = []
        addr_map = cam.cpu.addr_map
        for idx, (stock_pc, (label, _kind)) in enumerate(sorted(self.points.items())):
            target_pc = addr_map.to_loaded(stock_pc) if hasattr(addr_map, "to_loaded") else stock_pc
            raw = cam.cpu.mu.mem_read(target_pc, 4)
            displaced_insn = struct.unpack("<I", raw)[0]
            trampoline_addr = trampoline_base + idx * stride_bytes
            hook_branch = encode_arm_branch(target_pc, trampoline_addr, link=False)
            words = build_trampoline_words(
                target_pc=target_pc,
                probe_id=idx,
                displaced_insn=displaced_insn,
                trampoline_addr=trampoline_addr,
                logger_fn_addr=logger_fn_addr,
            )
            descriptors.append(
                HwPatchDescriptor(
                    probe_id=idx,
                    target_pc=target_pc,
                    label=label,
                    displaced_insn=displaced_insn,
                    displaced_hex=f"0x{displaced_insn:08X}",
                    trampoline_addr=trampoline_addr,
                    hook_branch_insn=hook_branch,
                    trampoline_words=words,
                    trampoline_hex=[f"0x{w:08X}" for w in words],
                )
            )
        return descriptors

    def summary(self) -> Dict[str, Any]:
        return {
            "probe_count": len(self.points),
            "event_count": len(self.events),
            "milestones_hit": self.milestones_hit(),
        }
