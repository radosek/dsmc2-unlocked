"""
RED DSMC2 Firmware Inspection, Staging & Custom Execution Engine.
Validates, parses entry vectors, computes cryptographic hashes, and executes custom
firmware binaries (.bin, .mem, .pkg) loaded from the RED MINI-MAG bay into DDR memory.
"""

import hashlib
import os
import struct
from typing import Optional, Dict, Any, Union


class FirmwareInspectionResult:
    """Diagnostic analysis and metadata for a staged firmware binary."""

    def __init__(
        self,
        filename: str,
        size_bytes: int,
        sha256: str,
        md5: str,
        sp: int,
        reset_pc: int,
        format_name: str,
        is_valid: bool,
        is_runnable: bool,
        error_message: Optional[str] = None
    ):
        self.filename = filename
        self.size_bytes = size_bytes
        self.size_mb = round(size_bytes / (1024 * 1024), 2)
        self.sha256 = sha256
        self.md5 = md5
        self.sp = sp
        self.reset_pc = reset_pc
        self.format_name = format_name
        self.is_valid = is_valid
        self.is_runnable = is_runnable
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "size_mb": self.size_mb,
            "sha256": self.sha256,
            "md5": self.md5,
            "sp": f"0x{self.sp:08X}",
            "reset_pc": f"0x{self.reset_pc:08X}",
            "format_name": self.format_name,
            "is_valid": self.is_valid,
            "is_runnable": self.is_runnable,
            "error_message": self.error_message
        }


class FirmwareManager:
    """Manages firmware validation, staging, and custom execution in the virtual camera."""

    # Standard RED DSMC2 DDR Memory Limits
    DDR_BASE = 0x80000000
    DDR_SIZE = 512 * 1024 * 1024 # 512 MB
    DDR_LIMIT = DDR_BASE + DDR_SIZE

    # Default DSMC2 Entry Point
    DEFAULT_SP = 0x881D2690
    DEFAULT_RESET_PC = 0x80829F2C

    @classmethod
    def inspect(cls, source: Union[str, bytes], filename: str = "firmware.bin") -> FirmwareInspectionResult:
        """Inspect and validate a firmware file path or raw byte buffer."""
        if isinstance(source, str):
            filename = os.path.basename(source)
            if not os.path.exists(source):
                return FirmwareInspectionResult(
                    filename=filename, size_bytes=0, sha256="", md5="",
                    sp=0, reset_pc=0, format_name="File Not Found",
                    is_valid=False, is_runnable=False, error_message=f"File not found: {source}"
                )
            with open(source, "rb") as f:
                data = f.read()
        else:
            data = source

        size = len(data)
        if size == 0:
            return FirmwareInspectionResult(
                filename=filename, size_bytes=0, sha256="", md5="",
                sp=0, reset_pc=0, format_name="Empty File",
                is_valid=False, is_runnable=False, error_message="Firmware file is empty (0 bytes)"
            )

        sha = hashlib.sha256(data).hexdigest()
        md5 = hashlib.md5(data).hexdigest()

        # Check for minimum reasonable size
        if size < 64:
            return FirmwareInspectionResult(
                filename=filename, size_bytes=size, sha256=sha, md5=md5,
                sp=0, reset_pc=0, format_name="Truncated Header",
                is_valid=False, is_runnable=False, error_message="File too small for ARM vector table (< 64 bytes)"
            )

        # Inspect first 16 32-bit words (64 bytes)
        words = struct.unpack("<16I", data[:64])
        word0 = words[0]
        sp = words[10]
        reset_pc = words[11]

        # Check for standard RED DSMC2 Vector Table
        # In stock DSMC2 DDR binaries:
        # Word 10 = Initial Stack Pointer (e.g. 0x881D2690)
        # Word 11 = Reset Vector PC (e.g. 0x80829F2C)
        is_sp_valid = cls.DDR_BASE <= sp < cls.DDR_LIMIT
        is_pc_valid = cls.DDR_BASE <= reset_pc < cls.DDR_LIMIT

        if is_sp_valid and is_pc_valid:
            format_name = "RED DSMC2 DDR Memory Image (.mem)"
            return FirmwareInspectionResult(
                filename=filename, size_bytes=size, sha256=sha, md5=md5,
                sp=sp, reset_pc=reset_pc, format_name=format_name,
                is_valid=True, is_runnable=True
            )

        # Check if first word is an ARM branch (0xEAxxxxxx) or vector branch
        is_arm_branch = (word0 & 0xFF000000) in (0xEA000000, 0xEB000000)
        if is_arm_branch:
            # Raw ARM binary starting at base
            target_pc = cls.DDR_BASE
            format_name = "Raw ARM Executable Binary (.bin)"
            return FirmwareInspectionResult(
                filename=filename, size_bytes=size, sha256=sha, md5=md5,
                sp=cls.DEFAULT_SP, reset_pc=target_pc, format_name=format_name,
                is_valid=True, is_runnable=True
            )

        # Check for RED Package / Container Header
        magic = data[:8]
        if b"RED" in magic or b"COMBO" in magic or b"PKG" in magic:
            format_name = "RED Combo Firmware Package (.pkg)"
            return FirmwareInspectionResult(
                filename=filename, size_bytes=size, sha256=sha, md5=md5,
                sp=cls.DEFAULT_SP, reset_pc=cls.DEFAULT_RESET_PC, format_name=format_name,
                is_valid=True, is_runnable=True
            )

        # Fallback raw executable assumption if size > 64KB
        if size >= 65536:
            format_name = "Unsigned Custom ARM Image"
            return FirmwareInspectionResult(
                filename=filename, size_bytes=size, sha256=sha, md5=md5,
                sp=cls.DEFAULT_SP, reset_pc=cls.DEFAULT_RESET_PC, format_name=format_name,
                is_valid=True, is_runnable=True
            )

        return FirmwareInspectionResult(
            filename=filename, size_bytes=size, sha256=sha, md5=md5,
            sp=0, reset_pc=0, format_name="Unrecognized Binary Format",
            is_valid=False, is_runnable=False,
            error_message="Missing valid ARM vector table or entry point in DDR range"
        )

    @classmethod
    def boot_custom(cls, camera, firmware_path: str) -> Dict[str, Any]:
        """Load and boot custom firmware binary into the active camera emulator."""
        meta = cls.inspect(firmware_path)
        if not meta.is_runnable:
            camera.log_system(f"[UPGRADE] Rejected custom firmware: {meta.error_message}")
            return {
                "status": "error",
                "message": meta.error_message or "Invalid firmware",
                "metadata": meta.to_dict()
            }

        camera.log_system(f"[UPGRADE] Flashing staged custom firmware from RED MINI-MAG slot: {meta.filename}")
        camera.log_system(f"[UPGRADE] Size: {meta.size_mb:.2f} MB | SHA-256: {meta.sha256[:16]}... | Format: {meta.format_name}")
        camera.log_system(f"[UPGRADE] Vector initialization: SP=0x{meta.sp:08X}, Reset PC=0x{meta.reset_pc:08X}")

        # Cleanly reinitialize SoC hardware & peripheral state
        camera._init_hardware()

        # Load binary directly into DDR at 0x80000000
        with open(firmware_path, "rb") as f:
            fw_bytes = f.read()
        camera.bus.load_binary(cls.DDR_BASE, fw_bytes)

        # Configure reset vector and supervisor mode
        camera.cpu.pc = meta.reset_pc
        camera.cpu.sp = meta.sp
        from emulator.core.cpu import ArmCpu
        camera.cpu.cpsr = ArmCpu.MODE_SVC | 0xC0

        # Execute initial instruction slice
        try:
            initial_count = min(45_000_000, 45_000_000)
            camera.cpu.run(camera.cpu.pc, 0, count=initial_count)
            camera.instruction_count += initial_count
            camera.is_booted = True
            camera.power_state = camera.POWER_ON
            camera.rcp_server.start()

            threads = camera.get_threads()
            camera.log_system("[UPGRADE] Custom firmware boot SUCCESSFUL! ThreadX RTOS operational.")
            for t in threads:
                camera.log_system(f"[RTOS] Custom Thread [{t['name']}] state={t['state']} prio={t['priority']}")

            return {
                "status": "ok",
                "message": "Custom firmware running",
                "metadata": meta.to_dict(),
                "threads": threads,
                "pc": f"0x{camera.cpu.pc:08X}"
            }
        except Exception as e:
            # Execution crash or illegal instruction in custom binary
            reg_dump = {
                "pc": f"0x{camera.cpu.pc:08X}",
                "sp": f"0x{camera.cpu.sp:08X}",
                "lr": f"0x{camera.cpu.lr:08X}",
                "cpsr": f"0x{camera.cpu.cpsr:08X}"
            }
            for i in range(13):
                reg_dump[f"r{i}"] = f"0x{camera.cpu.get_r(i):08X}"

            camera.log_system(f"[FATAL] Custom firmware execution halted at PC 0x{camera.cpu.pc:08X}: {e}")
            camera.power_state = camera.POWER_STANDBY
            camera.is_booted = False
            return {
                "status": "crash",
                "error": str(e),
                "pc": f"0x{camera.cpu.pc:08X}",
                "registers": reg_dump,
                "metadata": meta.to_dict()
            }
