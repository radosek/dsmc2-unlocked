"""
OMAP3630 GPIO Controller Model.
Implements GPIO modules 1 through 6 with pin state tracking, edge detection, and IRQ generation.
"""

from typing import Dict, Optional, Callable
from emulator.core.bus import Device


class OmapGpio(Device):
    """OMAP 32-pin GPIO Module."""

    def __init__(self, module_id: int, irq_num: int, intc):
        self.module_id = module_id
        self.irq_num = irq_num
        self.intc = intc

        # Registers
        self.sysconfig = 0
        self.oe = 0xFFFFFFFF            # 1 = input, 0 = output
        self.datain = 0x00000000        # Input levels
        self.dataout = 0x00000000       # Output levels
        self.irqstatus1 = 0x00000000
        self.irqenable1 = 0x00000000
        self.irqstatus2 = 0x00000000
        self.irqenable2 = 0x00000000
        self.risingdetect = 0x00000000
        self.fallingdetect = 0x00000000
        self.debouncenable = 0
        self.debouncingtime = 0

        self.on_pin_changed: Optional[Callable[[int, bool], None]] = None

    def set_input_pin(self, pin: int, high: bool):
        """Set state of an external input pin (0..31) and evaluate edge interrupts."""
        if not (0 <= pin < 32):
            return

        old_level = bool(self.datain & (1 << pin))
        new_level = bool(high)

        if new_level:
            self.datain |= (1 << pin)
        else:
            self.datain &= ~(1 << pin)

        # Check edge triggers
        bit = 1 << pin
        if not old_level and new_level: # Rising edge
            if self.risingdetect & bit:
                self.irqstatus1 |= bit
                if (self.irqenable1 & bit) and self.intc:
                    self.intc.assert_irq(self.irq_num)
        elif old_level and not new_level: # Falling edge
            if self.fallingdetect & bit:
                self.irqstatus1 |= bit
                if (self.irqenable1 & bit) and self.intc:
                    self.intc.assert_irq(self.irq_num)

        if self.on_pin_changed:
            self.on_pin_changed(pin, new_level)

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00: # REVISION
            return 0x25
        elif offset == 0x14: # SYSSTATUS
            return 0x01 # RESETDONE
        elif offset == 0x18: # IRQSTATUS1
            return self.irqstatus1
        elif offset == 0x1C: # IRQENABLE1
            return self.irqenable1
        elif offset == 0x24: # IRQSTATUS2
            return self.irqstatus2
        elif offset == 0x28: # IRQENABLE2
            return self.irqenable2
        elif offset == 0x34: # OE
            return self.oe
        elif offset == 0x38: # DATAIN
            return self.datain
        elif offset == 0x3C: # DATAOUT
            return self.dataout
        elif offset == 0x48: # RISINGDETECT
            return self.risingdetect
        elif offset == 0x4C: # FALLINGDETECT
            return self.fallingdetect
        return 0

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == 0x18: # IRQSTATUS1 (write 1 to clear)
            self.irqstatus1 &= ~val
            if not (self.irqstatus1 & self.irqenable1) and self.intc:
                self.intc.deassert_irq(self.irq_num)
        elif offset == 0x1C: # IRQENABLE1
            self.irqenable1 = val
        elif offset == 0x24: # IRQSTATUS2
            self.irqstatus2 &= ~val
        elif offset == 0x28: # IRQENABLE2
            self.irqenable2 = val
        elif offset == 0x34: # OE
            self.oe = val
        elif offset == 0x3C: # DATAOUT
            old = self.dataout
            self.dataout = val
            if self.on_pin_changed:
                diff = old ^ val
                while diff:
                    pin = (diff & -diff).bit_length() - 1
                    self.on_pin_changed(pin, bool(val & (1 << pin)))
                    diff &= ~(1 << pin)
        elif offset == 0x48: # RISINGDETECT
            self.risingdetect = val
        elif offset == 0x4C: # FALLINGDETECT
            self.fallingdetect = val
        elif offset == 0x60: # CLEARIRQENABLE1
            self.irqenable1 &= ~val
        elif offset == 0x64: # SETIRQENABLE1
            self.irqenable1 |= val
        elif offset == 0x90: # CLEARDATAOUT
            old = self.dataout
            self.dataout &= ~val
            if self.on_pin_changed:
                diff = old ^ self.dataout
                while diff:
                    pin = (diff & -diff).bit_length() - 1
                    self.on_pin_changed(pin, False)
                    diff &= ~(1 << pin)
        elif offset == 0x94: # SETDATAOUT
            old = self.dataout
            self.dataout |= val
            if self.on_pin_changed:
                diff = old ^ self.dataout
                while diff:
                    pin = (diff & -diff).bit_length() - 1
                    self.on_pin_changed(pin, True)
                    diff &= ~(1 << pin)


GPIO_MAP = {
    1: (0x48310000, 29),
    2: (0x49050000, 30),
    3: (0x49052000, 31),
    4: (0x49054000, 32),
    5: (0x49056000, 33),
    6: (0x49058000, 34),
}
