"""
Unit tests for OMAP3 INTC (Interrupt Controller) register map and operation.
Validates exact register addresses according to TI OMAP35x TRM (SPRUF98Y) Chapter 6:
- Bank 0: ITR0=0x80, MIR0=0x84, MIR_CLEAR0=0x88, MIR_SET0=0x8C, ISR_SET0=0x90, ISR_CLEAR0=0x94, PENDING_IRQ0=0x98
- Bank 1: ITR1=0xA0, MIR1=0xA4, MIR_CLEAR1=0xA8, MIR_SET1=0xAC, ISR_SET1=0xB0, ISR_CLEAR1=0xB4, PENDING_IRQ1=0xB8
- Bank 2: ITR2=0xC0, MIR2=0xC4, MIR_CLEAR2=0xC8, MIR_SET2=0xCC, ISR_SET2=0xD0, ISR_CLEAR2=0xD4, PENDING_IRQ2=0xD8
"""

import pytest
from emulator.devices.intc import OmapIntc


def test_intc_mir_clear_and_set_across_all_banks():
    intc = OmapIntc()

    # Initial state: all interrupts masked
    assert intc.read(0x84, 4) == 0xFFFFFFFF
    assert intc.read(0xA4, 4) == 0xFFFFFFFF
    assert intc.read(0xC4, 4) == 0xFFFFFFFF

    # Bank 0: Unmask IRQ 12 (write 1 << 12 to MIR_CLEAR0 at 0x88)
    intc.write(0x88, 4, 1 << 12)
    assert (intc.read(0x84, 4) & (1 << 12)) == 0
    # Re-mask IRQ 12 (write 1 << 12 to MIR_SET0 at 0x8C)
    intc.write(0x8C, 4, 1 << 12)
    assert (intc.read(0x84, 4) & (1 << 12)) != 0

    # Bank 1: Unmask IRQ 38 (Timer 2 -> bit 6, write 1 << 6 to MIR_CLEAR1 at 0xA8)
    intc.write(0xA8, 4, 1 << 6)
    assert (intc.read(0xA4, 4) & (1 << 6)) == 0
    # Re-mask IRQ 38 (write 1 << 6 to MIR_SET1 at 0xAC)
    intc.write(0xAC, 4, 1 << 6)
    assert (intc.read(0xA4, 4) & (1 << 6)) != 0

    # Bank 2: Unmask IRQ 80 (UART4 -> bit 16, write 1 << 16 to MIR_CLEAR2 at 0xC8)
    intc.write(0xC8, 4, 1 << 16)
    assert (intc.read(0xC4, 4) & (1 << 16)) == 0
    # Re-mask IRQ 80 (write 1 << 16 to MIR_SET2 at 0xCC)
    intc.write(0xCC, 4, 1 << 16)
    assert (intc.read(0xC4, 4) & (1 << 16)) != 0


def test_intc_software_interrupt_and_pending():
    intc = OmapIntc()

    # Unmask IRQ 38 (Timer 2, Bank 1 bit 6)
    intc.write(0xA8, 4, 1 << 6)

    # Assert software interrupt for IRQ 38 via ISR_SET1 (0xB0)
    intc.write(0xB0, 4, 1 << 6)

    # Raw status ITR1 (0xA0) should have bit 6 set
    assert (intc.read(0xA0, 4) & (1 << 6)) != 0
    # Pending PENDING_IRQ1 (0xB8) should have bit 6 set
    assert (intc.read(0xB8, 4) & (1 << 6)) != 0
    # Active IRQ should be 38
    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 38

    # Clear software interrupt via ISR_CLEAR1 (0xB4)
    intc.write(0xB4, 4, 1 << 6)
    assert (intc.read(0xA0, 4) & (1 << 6)) == 0
    assert (intc.read(0xB8, 4) & (1 << 6)) == 0
    assert intc.has_pending_irq() is False
