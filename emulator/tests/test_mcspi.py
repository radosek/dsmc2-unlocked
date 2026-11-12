"""
Unit tests for OMAP3630 Multichannel Serial Port Interface (McSPI) controller model.
"""

import pytest
from emulator.devices.mcspi import OmapMcspi, MCSPI_MAP
from emulator.devices.intc import OmapIntc


class MockIntc:
    def __init__(self):
        self.asserted = []
        self.deasserted = []

    def assert_irq(self, irq_num: int):
        self.asserted.append(irq_num)

    def deassert_irq(self, irq_num: int):
        self.deasserted.append(irq_num)


def test_mcspi_map_and_instantiation():
    """Verify standard base addresses and IRQ numbers for McSPI 1..4."""
    assert MCSPI_MAP[1] == (0x48098000, 65)
    assert MCSPI_MAP[2] == (0x4809A000, 66)
    assert MCSPI_MAP[3] == (0x480B8000, 91)
    assert MCSPI_MAP[4] == (0x480BA000, 48)

    intc = MockIntc()
    mcspi = OmapMcspi(1, 0x48098000, 65, intc=intc)
    assert mcspi.port_id == 1
    assert mcspi.base_addr == 0x48098000
    assert mcspi.irq_num == 65
    assert mcspi.read(OmapMcspi.REG_REVISION, 4) == 0x00000021
    assert mcspi.read(OmapMcspi.REG_SYSSTATUS, 4) == 0x00000001  # RESETDONE


def test_mcspi_soft_reset():
    """Verify that writing SOFTRESET (bit 1) to SYSCONFIG asserts RESETDONE in SYSSTATUS."""
    mcspi = OmapMcspi(1, 0x48098000, 65)
    mcspi.sysstatus = 0x0
    mcspi.write(OmapMcspi.REG_SYSCONFIG, 4, 0x02)
    assert mcspi.read(OmapMcspi.REG_SYSSTATUS, 4) & 0x01 == 1


def test_mcspi_channel_configuration_and_transfer():
    """Verify channel configuration and TX/RX data transfer loopback."""
    mcspi = OmapMcspi(1, 0x48098000, 65)

    for ch in range(4):
        ch_offset = OmapMcspi.CH_BASE + ch * OmapMcspi.CH_STRIDE

        # Initial status: TXS=1 (empty), EOT=1, RXS=0
        stat = mcspi.read(ch_offset + 0x04, 4)
        assert stat & 0x02 != 0  # TXS
        assert stat & 0x04 != 0  # EOT
        assert stat & 0x01 == 0  # RXS empty

        # Configure channel
        mcspi.write(ch_offset + 0x00, 4, 0x12345678)
        assert mcspi.read(ch_offset + 0x00, 4) == 0x12345678

        # Enable channel
        mcspi.write(ch_offset + 0x08, 4, 0x00000001)
        assert mcspi.read(ch_offset + 0x08, 4) == 0x00000001

        # Transmit word
        test_val = 0xDEADBEEF + ch
        mcspi.write(ch_offset + 0x0C, 4, test_val)

        # Status should now indicate RXS=1
        stat = mcspi.read(ch_offset + 0x04, 4)
        assert stat & 0x01 != 0  # RXS full

        # Read received word
        rx_val = mcspi.read(ch_offset + 0x10, 4)
        assert rx_val == test_val

        # Reading RX should clear RXS
        stat_after = mcspi.read(ch_offset + 0x04, 4)
        assert stat_after & 0x01 == 0


def test_mcspi_irq_handling():
    """Verify IRQ status write-1-to-clear and INTC signaling."""
    intc = MockIntc()
    mcspi = OmapMcspi(2, 0x4809A000, 66, intc=intc)

    # Enable IRQ mask
    mcspi.write(OmapMcspi.REG_IRQENABLE, 4, 0x00000001)

    # Manually trigger status
    mcspi.irqstatus = 0x00000001
    # Trigger check via irqenable write
    mcspi.write(OmapMcspi.REG_IRQENABLE, 4, 0x00000001)
    assert 66 in intc.asserted

    # Clear status with write-1-to-clear
    mcspi.write(OmapMcspi.REG_IRQSTATUS, 4, 0x00000001)
    assert mcspi.read(OmapMcspi.REG_IRQSTATUS, 4) == 0
    assert 66 in intc.deasserted


def test_mcspi_generic_registers():
    """Verify generic register access for non-standard offsets."""
    mcspi = OmapMcspi(3, 0x480B8000, 91)
    mcspi.write(0x100, 4, 0xCAFEBABE)
    assert mcspi.read(0x100, 4) == 0xCAFEBABE
