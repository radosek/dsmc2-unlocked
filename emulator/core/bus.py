"""
Memory and MMIO Bus Controller for RED DSMC2 Emulator.
Routes memory accesses, dispatches MMIO transactions to peripheral models,
and enforces the DM3725 / OMAP3630 TRM Failsafe & Fallback Memory Protection Layer.

TRM Reference: SPRUGN4 (Texas Instruments AM/DM37x Multimedia Device Technical Reference Manual)
  - Chapter 2: Memory Mapping (L3, L4-Core 0x48000000, L4-Wakeup 0x48300000, L4-Per 0x49000000)
  - Chapter 11: GPMC (0x6E000000, CS0 NAND Window 0x08000000) & SDRC (0x6D000000)
"""

import json
import logging
import os
import struct
from typing import Dict, Tuple, Optional, List, Any
import unicorn

logger = logging.getLogger("emulator.bus")


class UnmappedMemoryAccessError(RuntimeError):
    """Raised in Strict Mode when an unmapped or non-TRM memory address is accessed."""
    pass


class Device:
    """Base class for all memory-mapped peripherals."""
    def read(self, offset: int, size: int) -> int:
        return 0

    def write(self, offset: int, size: int, value: int):
        pass


def load_trm_memory_map() -> Dict[int, Dict[str, Any]]:
    """Load the authoritative TI DM3725 / OMAP3630 TRM memory region table."""
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trm_memory_map.json")
    regions_by_base: Dict[int, Dict[str, Any]] = {}
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("regions", []):
            base = int(entry["base"], 16)
            size = int(entry["size"], 16)
            regions_by_base[base] = {
                "name": entry["name"],
                "base": base,
                "size": size,
                "category": entry.get("category", "PERIPHERAL"),
                "trm_section": entry.get("trm_section", ""),
            }
    return regions_by_base


DM37XX_TRM_MEMORY_MAP: Dict[int, Dict[str, Any]] = load_trm_memory_map()


class SystemBus:
    """
    System interconnect routing physical memory and MMIO registers.

    Supports two operating modes:
    - Permissive Mode (`strict_mode=False`, default for emulation runtime):
      Any unmapped access in peripheral space (`0x48000000..0x490FFFFF` or `0x40000000..0x7FFFFFFF`)
      logs a warning with the program counter (PC) and returns `default_ack_value` (`0x00000000`)
      without raising an unhandled exception or crashing ThreadX.
    - Strict Mode (`strict_mode=True`, for testing and TRM validation):
      Raises `UnmappedMemoryAccessError` on unmapped or non-TRM peripheral reads/writes
      and rejects device registrations outside the official DM37xx TRM memory map.
    """

    L4_PERIPHERAL_START = 0x48000000
    L4_PERIPHERAL_END = 0x490FFFFF

    def __init__(self, cpu, strict_mode: bool = False, default_ack_value: int = 0x00000000):
        self.cpu = cpu
        self.mu = cpu.mu
        self.strict_mode = bool(strict_mode)
        self.default_ack_value = int(default_ack_value) & 0xFFFFFFFF
        self.devices: Dict[int, Tuple[int, Device]] = {}  # base_addr -> (size, device)
        self.read_callbacks = []
        self.write_callbacks = []
        self.unknown_reads: Dict[int, int] = {}
        self.unknown_writes: Dict[int, int] = {}
        self.fallback_warnings: List[Dict[str, Any]] = []
        self._warned_addresses = set()
        self.ram_regions: List[Tuple[int, int]] = []
        self._init_memory_maps()
        self._install_bus_hooks()

    def set_mode(self, strict: bool):
        """Switch bus between Strict Mode (True) and Permissive Mode (False)."""
        self.strict_mode = bool(strict)

    @property
    def unknown_mmio(self) -> Dict[int, Dict[str, Any]]:
        """Consolidated report of unknown MMIO accesses."""
        combined = {}
        for addr, count in self.unknown_reads.items():
            combined[addr] = {"count": count, "last_val": 0, "type": "read"}
        for addr, count in self.unknown_writes.items():
            if addr in combined:
                combined[addr]["count"] += count
            else:
                combined[addr] = {"count": count, "last_val": 0, "type": "write"}
        return combined

    def _init_memory_maps(self):
        """Map standard DM3725 / OMAP3630 physical RAM, GPMC CS0, and peripheral address windows."""
        # 1. GPMC CS0 NAND Flash Window at 0x08000000 (16 MB mapped window within 128 MB CS0 aperture)
        self.mu.mem_map(0x08000000, 0x01000000)
        self.add_ram_region(0x08000000, 0x01000000)

        # 2. 512 MB DDR RAM at 0x80000000
        self.mu.mem_map(0x80000000, 512 * 1024 * 1024)
        self.add_ram_region(0x80000000, 512 * 1024 * 1024)

        # 3. OMAP L4-Core, L4-Wakeup, and L4-Per Peripherals (0x48000000 - 0x49100000)
        self.mu.mem_map(0x48000000, 0x01100000)

        # 4. L3 Control / SDRC (0x6D000000) / GPMC Registers (0x6E000000) Window (0x68000000 - 0x70000000)
        self.mu.mem_map(0x68000000, 0x08000000)
        self.add_ram_region(0x68000000, 0x08000000)

        # 5. OMAP Internal SRAM (0x40200000) / Boot ROM Window (0x40000000 - 0x40400000)
        self.mu.mem_map(0x40000000, 0x00400000)
        self.add_ram_region(0x40000000, 0x00400000)

    def add_ram_region(self, base_addr: int, size: int):
        """Register an address range backed by mapped RAM."""
        self.ram_regions.append((base_addr, size))

    def is_ram(self, address: int) -> bool:
        """Check if an address is backed by mapped RAM (and not claimed by an MMIO device)."""
        if self._find_device(address) is not None:
            return False
        for base, size in self.ram_regions:
            if base <= address < base + size:
                return True
        return False

    def is_trm_region(self, base_addr: int, size: int = 4) -> bool:
        """Return True if `[base_addr, base_addr + size)` falls within an official DM37xx TRM region."""
        for reg_base, info in DM37XX_TRM_MEMORY_MAP.items():
            reg_size = info["size"]
            if reg_base <= base_addr and (base_addr + size) <= (reg_base + reg_size):
                return True
        return False

    def register_device(self, base_addr: int, size: int, device: Device):
        """Register a peripheral model for an address range."""
        if self.strict_mode and not self.is_trm_region(base_addr, size):
            raise UnmappedMemoryAccessError(
                f"[STRICT BUS FAULT] Attempted to register non-TRM device {device.__class__.__name__} "
                f"at 0x{base_addr:08X} (size=0x{size:X})"
            )
        self.devices[base_addr] = (size, device)

    def validate_trm_compliance(self) -> List[str]:
        """
        Verify all registered bus devices against the official DM37xx TRM memory map.
        Returns a list of violation descriptions (empty list when 100% compliant).
        """
        violations: List[str] = []
        for base_addr, (size, dev) in sorted(self.devices.items()):
            if not self.is_trm_region(base_addr, size):
                violations.append(
                    f"Device {dev.__class__.__name__} at 0x{base_addr:08X} (size=0x{size:X}) "
                    f"is not in DM37XX_TRM_MEMORY_MAP"
                )
        return violations

    def _find_device(self, address: int) -> Optional[Tuple[int, Device]]:
        for base, (size, dev) in self.devices.items():
            if base <= address < base + size:
                return (address - base, dev)
        return None

    def _record_unmapped_access(self, access_type: str, address: int, size: int, pc: int, value: int = 0):
        """Record an unmapped peripheral access, logging a warning in Permissive Mode or raising in Strict Mode."""
        if access_type == "read":
            self.unknown_reads[address] = self.unknown_reads.get(address, 0) + 1
        else:
            self.unknown_writes[address] = self.unknown_writes.get(address, 0) + 1

        msg = (
            f"[BUS FALLBACK] Unmapped peripheral {access_type.upper()} at 0x{address:08X} "
            f"(size={size}, val=0x{value:08X}, PC=0x{pc:08X})"
        )
        if len(self.fallback_warnings) < 1024:
            self.fallback_warnings.append({
                "pc": pc,
                "address": address,
                "size": size,
                "access": access_type,
                "value": value,
                "message": msg,
            })

        if address not in self._warned_addresses:
            self._warned_addresses.add(address)
            logger.warning(msg)

        if self.strict_mode:
            raise UnmappedMemoryAccessError(msg)

    def _install_bus_hooks(self):
        """Install Unicorn memory hooks across the peripheral MMIO window and unmapped regions."""
        def hook_mem_read(uc, access, address, size, value, user_data):
            pc = self.cpu.pc
            val = self.default_ack_value
            match = self._find_device(address)
            if match is not None:
                offset, dev = match
                val = dev.read(offset, size)
                if size == 1:
                    uc.mem_write(address, bytes([val & 0xFF]))
                elif size == 2:
                    uc.mem_write(address, struct.pack("<H", val & 0xFFFF))
                elif size == 4:
                    uc.mem_write(address, struct.pack("<I", val & 0xFFFFFFFF))
            elif self.is_ram(address):
                # Address is backed by mapped RAM: preserve existing RAM contents
                try:
                    raw = uc.mem_read(address, size)
                    if size == 1:
                        val = raw[0]
                    elif size == 2:
                        val = struct.unpack("<H", raw)[0]
                    elif size == 4:
                        val = struct.unpack("<I", raw)[0]
                    else:
                        val = int.from_bytes(raw, "little")
                except Exception:
                    val = self.default_ack_value
            else:
                self._record_unmapped_access("read", address, size, pc)
                val = self.default_ack_value
                if size == 1:
                    uc.mem_write(address, bytes([val & 0xFF]))
                elif size == 2:
                    uc.mem_write(address, struct.pack("<H", val & 0xFFFF))
                elif size == 4:
                    uc.mem_write(address, struct.pack("<I", val & 0xFFFFFFFF))

            for cb in self.read_callbacks:
                cb(pc, address, size, val)

        def hook_mem_write(uc, access, address, size, value, user_data):
            pc = self.cpu.pc
            match = self._find_device(address)
            if match is not None:
                offset, dev = match
                dev.write(offset, size, value)
            elif not self.is_ram(address):
                self._record_unmapped_access("write", address, size, pc, value)

            for cb in self.write_callbacks:
                cb(pc, address, size, value)

        def hook_mem_unmapped(uc, access, address, size, value, user_data):
            pc = self.cpu.pc
            access_type = "write" if access == unicorn.UC_MEM_WRITE_UNMAPPED else "read"
            if self.strict_mode:
                self._record_unmapped_access(access_type, address, size, pc, value)
                return False
            # Permissive mode: map the missing 4KB page dynamically and return True so ThreadX continues
            page_base = address & ~0xFFF
            try:
                uc.mem_map(page_base, 0x1000)
            except Exception:
                pass
            self._record_unmapped_access(access_type, address, size, pc, value)
            return True

        # Intercept all peripheral and hardware register accesses (0x40000000..0x7fffffff)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_mem_read, begin=0x40000000, end=0x7FFFFFFF)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook_mem_write, begin=0x40000000, end=0x7FFFFFFF)
        self.mu.hook_add(
            unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED,
            hook_mem_unmapped,
        )

    def load_binary(self, address: int, data: bytes):
        """Write raw binary image into memory."""
        self.mu.mem_write(address, data)

    def read_mem(self, address: int, size: int) -> bytes:
        return self.mu.mem_read(address, size)

    def write_mem(self, address: int, data: bytes):
        self.mu.mem_write(address, data)

    def read(self, address: int, size: int = 4) -> int:
        """Read 1, 2, or 4-byte integer from memory or peripheral device."""
        match = self._find_device(address)
        if match is not None:
            offset, dev = match
            return dev.read(offset, size)
        if not self.is_ram(address):
            self._record_unmapped_access("read", address, size, self.cpu.pc)
            return self.default_ack_value
        try:
            data = self.mu.mem_read(address, size)
        except Exception:
            self._record_unmapped_access("read", address, size, self.cpu.pc)
            return self.default_ack_value
        if size == 1:
            return data[0]
        elif size == 2:
            return struct.unpack("<H", data)[0]
        elif size == 4:
            return struct.unpack("<I", data)[0]
        return int.from_bytes(data, "little")

    def write(self, address: int, size: int, val: int):
        """Write 1, 2, or 4-byte integer to memory or peripheral device."""
        match = self._find_device(address)
        if match is not None:
            offset, dev = match
            dev.write(offset, size, val)
            return
        if not self.is_ram(address):
            self._record_unmapped_access("write", address, size, self.cpu.pc, val)
            return
        if size == 1:
            data = bytes([val & 0xFF])
        elif size == 2:
            data = struct.pack("<H", val & 0xFFFF)
        elif size == 4:
            data = struct.pack("<I", val & 0xFFFFFFFF)
        else:
            data = val.to_bytes(size, "little")
        try:
            self.mu.mem_write(address, data)
        except Exception:
            self._record_unmapped_access("write", address, size, self.cpu.pc, val)

    def read_u32(self, address: int) -> int:
        return self.read(address, 4)

    def write_u32(self, address: int, val: int):
        self.write(address, 4, val)
