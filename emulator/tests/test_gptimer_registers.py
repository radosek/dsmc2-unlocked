"""
Tests for OMAP3 GPTimer register layout and timer tick / interrupt operations.
Verifies distinction between Timer 1 (WKUP) and Timers 2..11 (GP) register offsets.
"""

import pytest
from emulator.devices.gptimer import OmapGPTimer
from emulator.devices.intc import OmapIntc


def test_gptimer2_register_layout():
    """Verify Timer 2 (GP Timer) register offsets matching TI OMAP3 TRM."""
    intc = OmapIntc()
    timer2 = OmapGPTimer(timer_id=2, irq_num=38, intc=intc)

    # TIDR
    assert timer2.read(0x00, 4) == 0x15

    # TISTAT
    assert timer2.read(0x14, 4) == 0x01

    # TIER at 0x1C (enable overflow interrupt bit 1)
    timer2.write(0x1C, 4, 0x02)
    assert timer2.read(0x1C, 4) == 0x02

    # TLDR at 0x2C (reload value)
    timer2.write(0x2C, 4, 0xFFFFFFE0)
    assert timer2.read(0x2C, 4) == 0xFFFFFFE0
    # Writing TLDR also sets initial TCRR
    assert timer2.read(0x28, 4) == 0xFFFFFFE0

    # TCRR at 0x28 (Counter write)
    timer2.write(0x28, 4, 0xFFFFFFF0)
    assert timer2.read(0x28, 4) == 0xFFFFFFF0

    # Start timer with autoreload: TCLR at 0x24 = 0x03 (ST=1, AR=1)
    timer2.write(0x24, 4, 0x03)
    assert timer2.read(0x24, 4) == 0x03

    # Tick 15 steps -> 0xFFFFFFF0 + 15 = 0xFFFFFFFF
    timer2.tick(15)
    assert timer2.read(0x28, 4) == 0xFFFFFFFF
    assert timer2.read(0x18, 4) == 0 # TISR no overflow yet

    # Unmask IRQ 38 in INTC
    intc.write(0xA8, 4, 1 << 6) # MIR_CLEAR1 IRQ 38

    # Tick 1 step -> wraps to 0, reloads to TLDR (0xFFFFFFE0), asserts IRQ 38
    timer2.tick(1)
    assert timer2.read(0x28, 4) == 0xFFFFFFE0
    assert timer2.read(0x18, 4) & 0x02 # TISR bit 1 set
    assert intc.has_pending_irq() is True
    assert intc.get_active_irq() == 38

    # Clear TISR at 0x18 (write-1-to-clear)
    timer2.write(0x18, 4, 0x02)
    assert timer2.read(0x18, 4) == 0
    assert intc.has_pending_irq() is False


def test_gptimer1_register_layout():
    """Verify Timer 1 uses authentic standard OMAP3 TRM register offsets (TISR 0x18, TIER 0x1C, TCRR 0x28, TLDR 0x2C)."""
    intc = OmapIntc()
    timer1 = OmapGPTimer(timer_id=1, irq_num=37, intc=intc)

    # TIER at 0x1C (enable overflow interrupt bit 1)
    timer1.write(0x1C, 4, 0x02)
    assert timer1.read(0x1C, 4) == 0x02

    # TLDR at 0x2C (reload value)
    timer1.write(0x2C, 4, 0xFFFFFF00)
    assert timer1.read(0x2C, 4) == 0xFFFFFF00
    assert timer1.read(0x28, 4) == 0xFFFFFF00 # TCRR updated

    # TCRR at 0x28 (Counter write)
    timer1.write(0x28, 4, 0xFFFFFFFE)
    assert timer1.read(0x28, 4) == 0xFFFFFFFE

    # Start timer
    timer1.write(0x24, 4, 0x03)
    intc.write(0xA8, 4, 1 << 5) # MIR_CLEAR1 IRQ 37

    timer1.tick(2) # wraps, reloads, flags OVF
    assert timer1.read(0x18, 4) & 0x02 # TISR at 0x18
    assert intc.get_active_irq() == 37

    # Clear TISR at 0x18 (write-1-to-clear)
    timer1.write(0x18, 4, 0x02)
    assert timer1.read(0x18, 4) == 0
    assert intc.has_pending_irq() is False
