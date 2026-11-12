"""
Unit tests for OMAP3630 System DMA (sDMA) controller model.
"""

import pytest
from emulator.devices.sdma import OmapSdma
from emulator.devices.intc import OmapIntc


def test_sdma_reset_and_revision():
    """Verify revision and reset status."""
    sdma = OmapSdma()
    assert sdma.read(OmapSdma.REG_REVISION, 4) == 0x40
    assert (sdma.read(OmapSdma.REG_SYSSTATUS, 4) & 0x01) == 0x01

    # Soft reset
    sdma.write(OmapSdma.REG_OCP_SYSCONFIG, 4, 0x02)
    assert (sdma.read(OmapSdma.REG_SYSSTATUS, 4) & 0x01) == 0x01


def test_sdma_channel_registers():
    """Verify read/write access to DMA channel registers."""
    sdma = OmapSdma()
    ch0_base = OmapSdma.CHANNEL_BASE # 0x80
    ch1_base = OmapSdma.CHANNEL_BASE + OmapSdma.CHANNEL_STRIDE # 0x80 + 0x60 = 0xE0

    # Write source / destination to channel 0
    sdma.write(ch0_base + 0x18, 4, 0x80000000) # CSSA
    sdma.write(ch0_base + 0x1C, 4, 0x81000000) # CDSA
    assert sdma.read(ch0_base + 0x18, 4) == 0x80000000
    assert sdma.read(ch0_base + 0x1C, 4) == 0x81000000

    # Channel 1 should still be 0
    assert sdma.read(ch1_base + 0x18, 4) == 0


def test_sdma_irq_line3_and_channel_completion():
    """Verify DMA completion triggers Line 3 IRQ 15 when enabled."""
    intc = OmapIntc()
    intc.write(0x88, 4, 1 << 15) # Unmask IRQ 15 in MIR_CLEAR0

    sdma = OmapSdma(intc=intc)

    # Enable Line 3 interrupt for Channel 0 (bit 0 = 1)
    sdma.write(OmapSdma.REG_IRQENABLE_L3, 4, 0x01)
    assert sdma.read(OmapSdma.REG_IRQENABLE_L3, 4) == 0x01

    # Trigger Channel 0 enable (CCR bit 7 = 0x80)
    ch0_ccr = OmapSdma.CHANNEL_BASE + 0x00
    ch0_csr = OmapSdma.CHANNEL_BASE + 0x0C
    sdma.write(ch0_ccr, 4, 0x80)

    # Channel CSR bit 5 (BLOCK_DONE = 0x20) should be set
    assert (sdma.read(ch0_csr, 4) & 0x20) == 0x20

    # IRQSTATUS_L3 should have bit 0 set
    assert (sdma.read(OmapSdma.REG_IRQSTATUS_L3, 4) & 0x01) == 0x01

    # INTC should have pending IRQ 15
    assert intc.has_pending_irq()
    assert intc.get_active_irq() == 15

    # Write-1-to-clear IRQSTATUS_L3 bit 0
    sdma.write(OmapSdma.REG_IRQSTATUS_L3, 4, 0x01)
    assert (sdma.read(OmapSdma.REG_IRQSTATUS_L3, 4) & 0x01) == 0
    assert not intc.has_pending_irq()
