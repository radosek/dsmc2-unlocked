"""
Tests for OMAP3 I2C Controller Interrupt Dispatch and ThreadX Synchronization.
Verifies OMAP3 register offsets (IE, STAT, CON, SA), ARDY transaction completion,
IRQ 61 assertion/deassertion, and RTOS SystemInitThread execution.
"""

import pytest
from emulator.devices.i2c import OmapI2c, I2cSlave
from emulator.devices.intc import OmapIntc
from emulator.camera import Dsmc2Camera


class MockI2cDevice(I2cSlave):
    def __init__(self, addr):
        super().__init__(addr)
        self.written = []

    def write(self, reg_addr: int, data: bytes) -> bool:
        self.written.append((reg_addr, data))
        return True


def test_i2c_register_offsets_and_bus_busy():
    """Verify I2C registers and Bus Busy (BB, bit 12) behavior."""
    intc = OmapIntc()
    i2c = OmapI2c(bus_id=3, irq_num=61, intc=intc)

    # Initial STAT should be 0 (Bus idle, BB bit 12 = 0)
    stat = i2c.read(0x08, 2)
    assert (stat & 0x1000) == 0 # BB bit is 0

    # Write to STAT with 0xFFFF (write 1 to clear)
    i2c.write(0x08, 2, 0xFFFF)
    assert i2c.read(0x08, 2) == 0

    # Write IE (Interrupt Enable at 0x04) with ARDY enable (bit 2 = 0x04)
    i2c.write(0x04, 2, 0x0004)
    assert i2c.read(0x04, 2) == 0x0004


def test_i2c_transaction_irq61_assertion():
    """Verify Master Write transaction sets ARDY and asserts IRQ 61."""
    intc = OmapIntc()
    # Unmask IRQ 61 in INTC Bank 1 (bit 61 - 32 = 29)
    intc.write(0xA8, 4, 1 << 29) # MIR_CLEAR1

    i2c = OmapI2c(bus_id=3, irq_num=61, intc=intc)
    dev = MockI2cDevice(0x1B)
    i2c.attach_slave(dev)

    # Enable ARDY interrupt (IE bit 2 = 0x04)
    i2c.write(0x04, 2, 0x0004)

    # Set SA (Slave Address at 0x2C)
    i2c.write(0x2C, 2, 0x1B)

    # Set CNT (1 byte at 0x18)
    i2c.write(0x18, 2, 1)

    # Write 1 byte to DATA FIFO (0x1C)
    i2c.write(0x1C, 2, 0x55)

    # Start Transaction: CON (0x24) = EN (0x8000) | MST (0x0400) | TRX (0x0200) | STT (0x0001) = 0x8601
    i2c.write(0x24, 2, 0x8601)

    # ARDY should be set (bit 2)
    assert (i2c.read(0x08, 2) & 0x04) != 0

    # INTC should have active IRQ 61
    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 61

    # Acknowledge / clear ARDY bit in STAT
    i2c.write(0x08, 2, 0x04)
    assert (i2c.read(0x08, 2) & 0x04) == 0
    assert intc.has_pending_irq() is False


def test_camera_boot_services_i2c_interrupts():
    """Verify full camera boot services hardware I2C interrupts and advances SystemInitThread."""
    cam = Dsmc2Camera(workspace_root=".")
    cam.load_firmware()
    cam.boot(initial_instructions=45_000_000)

    # Verify SystemInitThread is running/ready with multiple executed slices
    threads = cam.get_threads()
    sys_init = next((t for t in threads if t["name"] == "SystemInitThread"), None)
    assert sys_init is not None
    assert sys_init["run_count"] >= 1
