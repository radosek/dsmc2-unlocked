"""
Unit test verifying Timer 2 ThreadX RTOS system tick generation.
In DSMC2 firmware, Timer 2 (IRQ 38) serves as the primary system clock tick (1000Hz).
"""

import pytest
from emulator.devices.intc import OmapIntc
from emulator.devices.gptimer import OmapGPTimer


def test_timer2_rtos_tick_generates_irq38():
    intc = OmapIntc()
    # Unmask Timer 2 IRQ (38 -> Bank 1 bit 6) via MIR_CLEAR1 (0xA8)
    intc.write(0xA8, 4, 1 << (38 - 32))

    timer2 = OmapGPTimer(2, 38, intc)

    # Firmware configures Timer 2:
    # TLDR = 0xFFFFFFE0 (-32 ticks reload)
    # TCRR = 0xFFFFFFE0
    # TIER = 0x02 (overflow interrupt enable)
    # TCLR = 0x03 (ST=1 start, AR=1 autoreload)
    timer2.write(0x2C, 4, 0xFFFFFFE0) # TLDR
    timer2.write(0x28, 4, 0xFFFFFFE0) # TCRR
    timer2.write(0x1C, 4, 0x02)       # TIER
    timer2.write(0x24, 4, 0x03)       # TCLR

    assert intc.has_pending_irq() is False

    # Tick 32 counts -> should overflow and assert IRQ 38
    timer2.tick(32)

    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 38
    assert (timer2.tisr & 0x02) != 0

    # ThreadX ISR acknowledges interrupt by writing 0x02 to TISR (0x18)
    timer2.write(0x18, 4, 0x02)
    assert (timer2.tisr & 0x02) == 0

    # Acknowledge INTC
    intc.write(0x48, 4, 0x01)
    intc.deassert_irq(38)
    assert intc.has_pending_irq() is False
