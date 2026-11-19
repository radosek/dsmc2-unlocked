"""
OMAP3630 / DM3725 Internal Camera Image Signal Processor (CAM_ISP / CCDC) Model.

TRM Reference: SPRUGN4 Table 2-3 / Chapter 6 (Camera ISP @ 0x480BC000, size 0x4000).
Key verified firmware registers from dsmc2-sdk/ghidra/scripts/omap_regs.tsv:
  - 0x004: ISP_SYSCONFIG
  - 0x008: ISP_SYSSTATUS (RESETDONE = 1)
  - 0x00C: ISP_IRQ0ENABLE
  - 0x010: ISP_IRQ0STATUS (W1C)
  - 0x604: CCDC_PCR
  - 0x62C: CCDC_SDR_ADDR
"""

from typing import Dict, Any
from emulator.core.bus import Device


class OmapCamIsp(Device):
    """OMAP3630 / DM3725 on-chip Camera ISP & CCDC controller (16 KB aperture)."""

    BASE_ADDR = 0x480BC000
    SIZE = 0x4000

    REG_ISP_REVISION = 0x0000
    REG_ISP_SYSCONFIG = 0x0004
    REG_ISP_SYSSTATUS = 0x0008
    REG_ISP_IRQ0ENABLE = 0x000C
    REG_ISP_IRQ0STATUS = 0x0010
    REG_CCDC_PCR = 0x0604
    REG_CCDC_SDR_ADDR = 0x062C

    def __init__(self):
        self.sysconfig = 0x00000001
        self.sysstatus = 0x00000001  # RESETDONE = 1
        self.irq0enable = 0x00000000
        self.irq0status = 0x00000000
        self.ccdc_pcr = 0x00000000
        self.ccdc_sdr_addr = 0x00000000
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_ISP_REVISION:
            return 0x00000020
        elif offset == self.REG_ISP_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_ISP_SYSSTATUS:
            return self.sysstatus
        elif offset == self.REG_ISP_IRQ0ENABLE:
            return self.irq0enable
        elif offset == self.REG_ISP_IRQ0STATUS:
            return self.irq0status
        elif offset == self.REG_CCDC_PCR:
            return self.ccdc_pcr
        elif offset == self.REG_CCDC_SDR_ADDR:
            return self.ccdc_sdr_addr
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_ISP_SYSCONFIG:
            self.sysconfig = val & ~0x0002
            if val & 0x0002:  # Soft reset
                self.sysstatus = 0x00000001
                self.irq0status = 0x00000000
                self.ccdc_pcr = 0x00000000
        elif offset == self.REG_ISP_IRQ0ENABLE:
            self.irq0enable = val
        elif offset == self.REG_ISP_IRQ0STATUS:
            self.irq0status &= ~val
        elif offset == self.REG_CCDC_PCR:
            self.ccdc_pcr = val
        elif offset == self.REG_CCDC_SDR_ADDR:
            self.ccdc_sdr_addr = val
        else:
            self.registers[offset] = val

    def get_status(self) -> Dict[str, Any]:
        return {
            "base_addr": f"0x{self.BASE_ADDR:08X}",
            "sysstatus": f"0x{self.sysstatus:08X}",
            "ccdc_pcr": f"0x{self.ccdc_pcr:08X}",
            "ccdc_sdr_addr": f"0x{self.ccdc_sdr_addr:08X}",
        }
