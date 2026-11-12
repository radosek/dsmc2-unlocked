"""
OMAP3630 Interrupt Controller (INTC) Model.
Implements the 96-channel MPU interrupt controller at 0x48200000.
"""

from typing import Optional, List
from emulator.core.bus import Device


class OmapIntc(Device):
    """OMAP3630 / DM3725 Interrupt Controller."""

    BASE_ADDR = 0x48200000
    SIZE = 0x1000

    def __init__(self, on_irq_asserted=None):
        self.on_irq_asserted = on_irq_asserted
        # 96 interrupt channels organized into 3 banks of 32 bits each
        self.itr: List[int] = [0, 0, 0]         # Raw interrupt inputs
        self.mir: List[int] = [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF] # Mask registers (1 = masked)
        self.ilr: List[int] = [0] * 96          # Interrupt Priority and Steering
        self.active_irq: Optional[int] = None
        self.sysconfig = 0

    def assert_irq(self, irq: int):
        """Raise an interrupt line."""
        if 0 <= irq < 96:
            bank = irq // 32
            bit = 1 << (irq % 32)
            self.itr[bank] |= bit
            self._evaluate_irqs()

    def deassert_irq(self, irq: int):
        """Clear an interrupt line."""
        if 0 <= irq < 96:
            bank = irq // 32
            bit = 1 << (irq % 32)
            self.itr[bank] &= ~bit
            if self.active_irq == irq:
                self.active_irq = self._find_next_irq()
            else:
                self._evaluate_irqs()

    def _evaluate_irqs(self):
        """Find highest priority pending unmasked IRQ."""
        self.active_irq = self._find_next_irq()
        if self.active_irq is not None and self.on_irq_asserted:
            self.on_irq_asserted()

    def _find_next_irq(self) -> Optional[int]:
        for bank in range(3):
            pending = self.itr[bank] & ~self.mir[bank]
            if pending:
                bit_idx = (pending & -pending).bit_length() - 1
                return bank * 32 + bit_idx
        return None

    def has_pending_irq(self) -> bool:
        if self.active_irq is not None:
            bank = self.active_irq // 32
            bit = 1 << (self.active_irq % 32)
            if (self.itr[bank] & ~self.mir[bank] & bit) == 0:
                self.active_irq = self._find_next_irq()
        return self.active_irq is not None or self._find_next_irq() is not None

    def get_active_irq(self) -> Optional[int]:
        if self.active_irq is None:
            self.active_irq = self._find_next_irq()
        return self.active_irq

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00: # INTC_REVISION
            return 0x20
        elif offset == 0x14: # INTC_SYSSTATUS
            return 0x01 # RESETDONE
        elif offset == 0x40: # INTC_SIR_IRQ
            irq = self.get_active_irq()
            return irq if irq is not None else 0x7F
        elif offset == 0x44: # INTC_SIR_FIQ
            return 0x7F
        elif offset == 0x48: # INTC_CONTROL
            return 0
        # Raw status registers: ITR0 (0x80), ITR1 (0xA0), ITR2 (0xC0)
        elif offset == 0x80:
            return self.itr[0]
        elif offset == 0xA0:
            return self.itr[1]
        elif offset == 0xC0:
            return self.itr[2]
        # Mask registers: MIR0 (0x84), MIR1 (0xA4), MIR2 (0xC4)
        elif offset == 0x84:
            return self.mir[0]
        elif offset == 0xA4:
            return self.mir[1]
        elif offset == 0xC4:
            return self.mir[2]
        # Pending registers: PENDING_IRQ0 (0x98), PENDING_IRQ1 (0xB8), PENDING_IRQ2 (0xD8)
        elif offset == 0x98:
            return self.itr[0] & ~self.mir[0]
        elif offset == 0xB8:
            return self.itr[1] & ~self.mir[1]
        elif offset == 0xD8:
            return self.itr[2] & ~self.mir[2]
        # Pending FIQ registers: PENDING_FIQ0 (0x9C), PENDING_FIQ1 (0xBC), PENDING_FIQ2 (0xDC)
        elif offset == 0x9C or offset == 0xBC or offset == 0xDC:
            return 0
        elif 0x100 <= offset < 0x280: # ILR registers
            idx = (offset - 0x100) // 4
            return self.ilr[idx] if idx < 96 else 0
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == 0x10: # INTC_SYSCONFIG
            self.sysconfig = value
        elif offset == 0x48: # INTC_CONTROL (NEWIRQAGR: bit 0)
            if value & 0x01:
                # Acknowledge current active IRQ
                if self.active_irq is not None:
                    # Deassert pulse if it was an edge interrupt
                    self.active_irq = None
                self._evaluate_irqs()
        # Direct MIR writes: MIR0 (0x84), MIR1 (0xA4), MIR2 (0xC4)
        elif offset == 0x84:
            self.mir[0] = value
            self._evaluate_irqs()
        elif offset == 0xA4:
            self.mir[1] = value
            self._evaluate_irqs()
        elif offset == 0xC4:
            self.mir[2] = value
            self._evaluate_irqs()
        # MIR clear registers (write 1 to unmask): MIR_CLEAR0 (0x88), MIR_CLEAR1 (0xA8), MIR_CLEAR2 (0xC8)
        elif offset == 0x88:
            self.mir[0] &= ~value
            self._evaluate_irqs()
        elif offset == 0xA8:
            self.mir[1] &= ~value
            self._evaluate_irqs()
        elif offset == 0xC8:
            self.mir[2] &= ~value
            self._evaluate_irqs()
        # MIR set registers (write 1 to mask): MIR_SET0 (0x8C), MIR_SET1 (0xAC), MIR_SET2 (0xCC)
        elif offset == 0x8C:
            self.mir[0] |= value
            self._evaluate_irqs()
        elif offset == 0xAC:
            self.mir[1] |= value
            self._evaluate_irqs()
        elif offset == 0xCC:
            self.mir[2] |= value
            self._evaluate_irqs()
        # Software interrupt set (write 1 to assert): ISR_SET0 (0x90), ISR_SET1 (0xB0), ISR_SET2 (0xD0)
        elif offset == 0x90:
            self.itr[0] |= value
            self._evaluate_irqs()
        elif offset == 0xB0:
            self.itr[1] |= value
            self._evaluate_irqs()
        elif offset == 0xD0:
            self.itr[2] |= value
            self._evaluate_irqs()
        # Software interrupt clear: ISR_CLEAR0 (0x94), ISR_CLEAR1 (0xB4), ISR_CLEAR2 (0xD4)
        elif offset == 0x94:
            self.itr[0] &= ~value
            self._evaluate_irqs()
        elif offset == 0xB4:
            self.itr[1] &= ~value
            self._evaluate_irqs()
        elif offset == 0xD4:
            self.itr[2] &= ~value
            self._evaluate_irqs()
        elif 0x100 <= offset < 0x280:
            idx = (offset - 0x100) // 4
            if idx < 96:
                self.ilr[idx] = value
