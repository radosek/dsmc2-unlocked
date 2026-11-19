"""
OMAP3630 / DM3725 Multi-Channel Buffered Serial Port (McBSP 2..5) Model.

TRM Reference: SPRUGN4 Table 2-3 / Table 2-4 / Chapter 21 (McBSP), plus
verified firmware offsets from dsmc2-sdk/ghidra/scripts/omap_regs.tsv:
  - McBSP2 (L4-Per):  0x49022000 (IRQ 17) -- MCBSP2_DXR_REG (0x08)
  - McBSP3 (L4-Per):  0x49024000 (IRQ 22) -- MCBSP3_DXR_REG (0x08), MCBSP3_XCERA_REG (0x40)
  - McBSP4 (L4-Per):  0x49026000 (IRQ 23)
  - McBSP5 (L4-Core): 0x48096000 (IRQ 27) -- MCBSP5_SPCR2_REG (0x10)
"""

from collections import deque
from typing import Dict, Any, Optional
from emulator.core.bus import Device


MCBSP_MAP = {
    2: (0x49022000, 17),
    3: (0x49024000, 22),
    4: (0x49026000, 23),
    5: (0x48096000, 27),
}


class OmapMcBSP(Device):
    """OMAP3630 / DM3725 McBSP serial/audio controller."""

    SIZE = 0x1000

    REG_DRR = 0x00
    REG_DXR = 0x08
    REG_SPCR2 = 0x10
    REG_SPCR1 = 0x14
    REG_RCR2 = 0x18
    REG_RCR1 = 0x1C
    REG_XCR2 = 0x20
    REG_XCR1 = 0x24
    REG_SRGR2 = 0x28
    REG_SRGR1 = 0x2C
    REG_MCR2 = 0x30
    REG_MCR1 = 0x34
    REG_XCERA = 0x40
    REG_XCERB = 0x44
    REG_SYSCONFIG = 0x8C
    REG_IRQSTATUS = 0xA0
    REG_IRQENABLE = 0xA4

    # SPCR2 bits
    SPCR2_XRST = 0x0001
    SPCR2_XRDY = 0x0002
    SPCR2_XEMPTY = 0x0004

    # SPCR1 bits
    SPCR1_RRST = 0x0001
    SPCR1_RRDY = 0x0002
    SPCR1_DLB = 0x8000

    def __init__(self, mcbsp_id: int, irq_num: int, intc: Optional[Any] = None):
        self.mcbsp_id = mcbsp_id
        self.irq_num = irq_num
        self.intc = intc
        self.spcr2 = 0x0000
        self.spcr1 = 0x0000
        self.xcera = 0x0000
        self.sysconfig = 0x0000
        self.irqstatus = 0x0000
        self.irqenable = 0x0000
        self.tx_fifo: deque = deque(maxlen=256)
        self.rx_fifo: deque = deque(maxlen=256)
        self.tx_count = 0
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_DRR:
            if self.rx_fifo:
                val = self.rx_fifo.popleft()
                if not self.rx_fifo:
                    self.spcr1 &= ~self.SPCR1_RRDY
                return val
            return 0x00000000
        elif offset == self.REG_SPCR2:
            val = self.spcr2
            if val & self.SPCR2_XRST:
                val |= self.SPCR2_XRDY | self.SPCR2_XEMPTY
            return val
        elif offset == self.REG_SPCR1:
            return self.spcr1
        elif offset == self.REG_XCERA:
            return self.xcera
        elif offset == self.REG_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_IRQSTATUS:
            return self.irqstatus
        elif offset == self.REG_IRQENABLE:
            return self.irqenable
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_DXR:
            self.tx_fifo.append(val)
            self.tx_count += 1
            if self.spcr1 & self.SPCR1_DLB:
                self.rx_fifo.append(val)
                self.spcr1 |= self.SPCR1_RRDY
        elif offset == self.REG_SPCR2:
            self.spcr2 = val
        elif offset == self.REG_SPCR1:
            self.spcr1 = val
        elif offset == self.REG_XCERA:
            self.xcera = val
        elif offset == self.REG_SYSCONFIG:
            self.sysconfig = val & ~0x0002  # Auto-clear soft reset
        elif offset == self.REG_IRQSTATUS:
            self.irqstatus &= ~val
        elif offset == self.REG_IRQENABLE:
            self.irqenable = val
        else:
            self.registers[offset] = val

    def get_status(self) -> Dict[str, Any]:
        return {
            "mcbsp_id": self.mcbsp_id,
            "irq_num": self.irq_num,
            "spcr1": f"0x{self.spcr1:04X}",
            "spcr2": f"0x{self.spcr2:04X}",
            "tx_count": self.tx_count,
            "rx_depth": len(self.rx_fifo),
        }
