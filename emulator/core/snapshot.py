"""
Snapshot and state persistence manager for the RED DSMC2 Virtual Camera.
Serializes and restores ARM CPU registers, memory delta, peripheral states, and VFS data.
"""

import gzip
import json
import os
import struct
import time
from typing import Dict, Any, Optional

from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
    UC_ARM_REG_CPSR
)


class SnapshotManager:
    """Manages full-state snapshots for DSMC2 camera."""

    REG_MAP = {
        "r0": UC_ARM_REG_R0, "r1": UC_ARM_REG_R1, "r2": UC_ARM_REG_R2, "r3": UC_ARM_REG_R3,
        "r4": UC_ARM_REG_R4, "r5": UC_ARM_REG_R5, "r6": UC_ARM_REG_R6, "r7": UC_ARM_REG_R7,
        "r8": UC_ARM_REG_R8, "r9": UC_ARM_REG_R9, "r10": UC_ARM_REG_R10, "r11": UC_ARM_REG_R11,
        "r12": UC_ARM_REG_R12, "sp": UC_ARM_REG_SP, "lr": UC_ARM_REG_LR, "pc": UC_ARM_REG_PC,
        "cpsr": UC_ARM_REG_CPSR
    }

    MAGIC = b"DSMC2SNAP1\x00\x00"

    @classmethod
    def save(cls, camera, filepath: str, description: str = ""):
        """Serialize complete camera state to compressed snapshot file."""
        metadata = {
            "version": 1,
            "timestamp": time.time(),
            "description": description,
            "instruction_count": camera.instruction_count,
            "is_booted": camera.is_booted,
            "registers": {},
            "peripherals": {
                "intc": {
                    "mir": camera.intc.mir,
                    "itr": camera.intc.itr,
                    "ilr": camera.intc.ilr,
                    "active_irq": camera.intc.active_irq
                },
                "prcm": {
                    "cm_fclken_per": camera.prcm.cm_fclken_per,
                    "cm_fclken1_core": camera.prcm.cm_fclken1_core,
                    "cm_iclken1_core": camera.prcm.cm_iclken1_core,
                    "prm_rstst": camera.prcm.prm_rstst
                },
                "rcp_state": dict(camera.rcp.state)
            }
        }

        # Save CPU registers
        for reg_name, reg_id in cls.REG_MAP.items():
            metadata["registers"][reg_name] = camera.cpu.uc.reg_read(reg_id)

        # Dump memory: Save DDR and SRAM contents
        # For efficiency, we save SRAM (64KB) and active DDR regions
        sram_bytes = camera.cpu.uc.mem_read(0x40000000, 0x10000)
        # DDR 512MB: Read 16MB of active program and 16MB of stack/data
        ddr_prog_bytes = camera.cpu.uc.mem_read(0x80000000, 0x01000000) # 16MB
        ddr_data_bytes = camera.cpu.uc.mem_read(0x88000000, 0x01000000) # 16MB stack/bss

        meta_json = json.dumps(metadata).encode("utf-8")
        meta_len = len(meta_json)

        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with gzip.open(filepath, "wb") as f:
            f.write(cls.MAGIC)
            f.write(struct.pack("<I", meta_len))
            f.write(meta_json)
            # Write memory blocks
            f.write(struct.pack("<II", 0x40000000, len(sram_bytes)))
            f.write(sram_bytes)
            f.write(struct.pack("<II", 0x80000000, len(ddr_prog_bytes)))
            f.write(ddr_prog_bytes)
            f.write(struct.pack("<II", 0x88000000, len(ddr_data_bytes)))
            f.write(ddr_data_bytes)

    @classmethod
    def restore(cls, camera, filepath: str) -> Dict[str, Any]:
        """Restore camera state from compressed snapshot file."""
        with gzip.open(filepath, "rb") as f:
            magic = f.read(len(cls.MAGIC))
            if magic != cls.MAGIC:
                raise ValueError(f"Invalid snapshot magic: {magic}")

            meta_len = struct.unpack("<I", f.read(4))[0]
            meta_json = f.read(meta_len)
            metadata = json.loads(meta_json.decode("utf-8"))

            # Restore memory blocks
            while True:
                header = f.read(8)
                if not header or len(header) < 8:
                    break
                addr, size = struct.unpack("<II", header)
                chunk = f.read(size)
                camera.cpu.uc.mem_write(addr, chunk)

        # Restore CPU registers
        for reg_name, val in metadata["registers"].items():
            reg_id = cls.REG_MAP[reg_name]
            camera.cpu.uc.reg_write(reg_id, val)

        # Restore peripheral state
        camera.instruction_count = metadata["instruction_count"]
        camera.is_booted = metadata["is_booted"]

        intc_meta = metadata["peripherals"]["intc"]
        camera.intc.mir = intc_meta["mir"]
        camera.intc.itr = intc_meta["itr"]
        if "ilr" in intc_meta:
            camera.intc.ilr = intc_meta["ilr"]
        camera.intc.active_irq = intc_meta["active_irq"]

        prcm_meta = metadata["peripherals"].get("prcm", {})
        if prcm_meta:
            camera.prcm.cm_fclken_per = prcm_meta.get("cm_fclken_per", 0xFFFFFFFF)
            camera.prcm.cm_fclken1_core = prcm_meta.get("cm_fclken1_core", 0)
            camera.prcm.cm_iclken1_core = prcm_meta.get("cm_iclken1_core", 0)
            camera.prcm.prm_rstst = prcm_meta.get("prm_rstst", 0x30)

        camera.rcp.state = dict(metadata["peripherals"]["rcp_state"])

        return metadata
