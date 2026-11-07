"""
Memory and MMIO Bus Controller for RED DSMC2 Emulator.
Routes memory accesses and dispatches MMIO transactions to peripheral models.
"""

import struct
from typing import Dict, Tuple, Optional
import unicorn


class Device:
    """Base class for all memory-mapped peripherals."""
    def read(self, offset: int, size: int) -> int:
        return 0

    def write(self, offset: int, size: int, value: int):
        pass


class SystemBus:
    """System interconnect routing physical memory and MMIO registers."""

    def __init__(self, cpu):
        self.cpu = cpu
        self.mu = cpu.mu
        self.devices: Dict[int, Tuple[int, Device]] = {} # base_addr -> (size, device)
        self.read_callbacks = []
        self.write_callbacks = []
        self.unknown_reads = {}
        self.unknown_writes = {}
        self._init_memory_maps()
        self._install_bus_hooks()

    @property
    def unknown_mmio(self) -> Dict[int, Dict[str, any]]:
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
        """Map standard physical RAM and peripheral address windows."""
        # 512 MB DDR RAM at 0x80000000
        self.mu.mem_map(0x80000000, 512 * 1024 * 1024)

        # OMAP L3/L4 Core and Peripherals (0x48000000 - 0x49100000)
        self.mu.mem_map(0x48000000, 0x01100000)

        # GPMC / NAND Window (0x68000000 - 0x70000000)
        self.mu.mem_map(0x68000000, 0x08000000)

        # OMAP Internal SRAM / Boot ROM window (0x40000000 - 0x40300000)
        self.mu.mem_map(0x40000000, 0x00400000)

    def register_device(self, base_addr: int, size: int, device: Device):
        """Register a peripheral model for an address range."""
        self.devices[base_addr] = (size, device)

    def _find_device(self, address: int) -> Optional[Tuple[int, Device]]:
        for base, (size, dev) in self.devices.items():
            if base <= address < base + size:
                return (address - base, dev)
        return None

    def _install_bus_hooks(self):
        """Install Unicorn memory hooks across the peripheral MMIO window."""
        def hook_mem_read(uc, access, address, size, value, user_data):
            pc = self.cpu.pc
            val = 0
            match = self._find_device(address)
            if match is not None:
                offset, dev = match
                val = dev.read(offset, size)
            else:
                self.unknown_reads[address] = self.unknown_reads.get(address, 0) + 1

            for cb in self.read_callbacks:
                cb(pc, address, size, val)

            # Write value to memory so Unicorn instruction receives it
            if size == 1:
                uc.mem_write(address, bytes([val & 0xFF]))
            elif size == 2:
                uc.mem_write(address, struct.pack("<H", val & 0xFFFF))
            elif size == 4:
                uc.mem_write(address, struct.pack("<I", val & 0xFFFFFFFF))

        def hook_mem_write(uc, access, address, size, value, user_data):
            pc = self.cpu.pc
            match = self._find_device(address)
            if match is not None:
                offset, dev = match
                dev.write(offset, size, value)
            else:
                self.unknown_writes[address] = self.unknown_writes.get(address, 0) + 1

            for cb in self.write_callbacks:
                cb(pc, address, size, value)

        # Intercept all peripheral and hardware register accesses (0x40000000..0x7fffffff)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_mem_read, begin=0x40000000, end=0x7FFFFFFF)
        self.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook_mem_write, begin=0x40000000, end=0x7FFFFFFF)

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
        data = self.mu.mem_read(address, size)
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
        if size == 1:
            data = bytes([val & 0xFF])
        elif size == 2:
            data = struct.pack("<H", val & 0xFFFF)
        elif size == 4:
            data = struct.pack("<I", val & 0xFFFFFFFF)
        else:
            data = val.to_bytes(size, "little")
        self.mu.mem_write(address, data)

    def read_u32(self, address: int) -> int:
        match = self._find_device(address)
        if match is not None:
            offset, dev = match
            return dev.read(offset, 4)
        data = self.mu.mem_read(address, 4)
        return struct.unpack("<I", data)[0]

    def write_u32(self, address: int, val: int):
        match = self._find_device(address)
        if match is not None:
            offset, dev = match
            dev.write(offset, 4, val)
            return
        self.mu.mem_write(address, struct.pack("<I", val & 0xFFFFFFFF))
