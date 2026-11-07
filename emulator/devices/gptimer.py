"""
OMAP3630 General Purpose Timer (GPTimer) Model.
Implements GPTimer1..11 with overflow interrupts and reload registers.
"""

from emulator.core.bus import Device


class OmapGPTimer(Device):
    """OMAP 32-bit General Purpose Timer."""

    def __init__(self, timer_id: int, irq_num: int, intc):
        self.timer_id = timer_id
        self.irq_num = irq_num
        self.intc = intc

        self.tcrr = 0       # Counter
        self.tldr = 0       # Load value
        self.tclr = 0       # Control (ST: bit 0, AR: bit 1)
        self.tier = 0       # Interrupt enable (OVF: bit 1)
        self.tisr = 0       # Interrupt status
        self.tiocp_cfg = 0
        self.twer = 0

    def tick(self, steps: int = 1):
        """Simulate clock ticks."""
        if not (self.tclr & 0x01): # Not running
            return

        self.tcrr = (self.tcrr + steps) & 0xFFFFFFFF
        # Check overflow (32-bit wrap)
        if self.tcrr < steps: # Wrapped
            self.tcrr = self.tldr
            self.tisr |= 0x02 # OVF_IT_FLAG
            if (self.tier & 0x02) and self.intc:
                self.intc.assert_irq(self.irq_num)

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00: # TIDR
            return 0x15
        elif offset == 0x10: # TIOCP_CFG
            return self.tiocp_cfg
        elif offset == 0x14: # TISTAT
            return 0x01 # RESETDONE
        elif offset == 0x18: # TISR (Timers 2..11) or TIER (Timer 1)
            return self.tier if self.timer_id == 1 else self.tisr
        elif offset == 0x1C: # TIER (Timers 2..11)
            return self.tier
        elif offset == 0x20: # TWER
            return self.twer
        elif offset == 0x24: # TCLR
            return self.tclr
        elif offset == 0x28: # TCRR (Timers 2..11) or TISR (Timer 1)
            return self.tisr if self.timer_id == 1 else self.tcrr
        elif offset == 0x2C: # TLDR (Timers 2..11)
            return self.tldr
        elif offset == 0x34: # TWPS (Write posting status)
            return 0
        elif offset == 0x3C: # TCRR (Timer 1)
            return self.tcrr
        elif offset == 0x40: # TLDR (Timer 1)
            return self.tldr
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == 0x10:
            self.tiocp_cfg = value
        elif offset == 0x18:
            if self.timer_id == 1:
                self.tier = value
            else:
                self.tisr &= ~value
                if not (self.tisr & self.tier) and self.intc:
                    self.intc.deassert_irq(self.irq_num)
        elif offset == 0x1C:
            self.tier = value
        elif offset == 0x20:
            self.twer = value
        elif offset == 0x24:
            self.tclr = value
        elif offset == 0x28:
            if self.timer_id == 1:
                self.tisr &= ~value
                if not (self.tisr & self.tier) and self.intc:
                    self.intc.deassert_irq(self.irq_num)
            else:
                self.tcrr = value
        elif offset == 0x2C:
            self.tldr = value
            self.tcrr = value
        elif offset == 0x3C:
            self.tcrr = value
        elif offset == 0x40:
            self.tldr = value
            self.tcrr = value


# Standard OMAP3 Timer Base Addresses and IRQs
TIMER_MAP = {
    1:  (0x48318000, 37),
    2:  (0x49032000, 38),
    3:  (0x49034000, 39),
    4:  (0x49036000, 40),
    5:  (0x49038000, 41),
    6:  (0x4903A000, 42),
    7:  (0x4903C000, 43),
    8:  (0x4903E000, 44),
    9:  (0x49040000, 45),
    10: (0x48086000, 46),
    11: (0x48088000, 47),
}
