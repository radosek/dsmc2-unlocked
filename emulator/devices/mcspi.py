"""
OMAP3630 Multichannel Serial Port Interface (McSPI) Controller Model.
Implements the 4 McSPI controllers at:
  - McSPI 1: 0x48098000 (IRQ 65)
  - McSPI 2: 0x4809A000 (IRQ 66)
  - McSPI 3: 0x480B8000 (IRQ 91)
  - McSPI 4: 0x480BA000 (IRQ 48)
"""

from typing import Dict, Optional, List
from emulator.core.bus import Device


class OmapMcspi(Device):
    """OMAP3630 McSPI Master Controller."""

    # Register Offsets
    REG_REVISION = 0x00
    REG_SYSCONFIG = 0x10
    REG_SYSSTATUS = 0x14
    REG_IRQSTATUS = 0x18
    REG_IRQENABLE = 0x1C
    REG_WAKEUPENABLE = 0x20
    REG_SYST = 0x24
    REG_MODULCTRL = 0x28

    CH_BASE = 0x2C
    CH_STRIDE = 0x14
    NUM_CHANNELS = 4

    def __init__(self, port_id: int, base_addr: int, irq_num: int, intc=None):
        self.port_id = port_id
        self.base_addr = base_addr
        self.irq_num = irq_num
        self.intc = intc

        self.revision = 0x00000021
        self.sysconfig = 0x00000015
        self.sysstatus = 0x00000001  # Bit 0: RESETDONE = 1
        self.irqstatus = 0x00000000
        self.irqenable = 0x00000000
        self.wakeupenable = 0x00000000
        self.syst = 0x00000000
        self.modulctrl = 0x00000000

        # Channel state (4 channels per McSPI)
        # Each channel has: chconf, chstat, chctrl, tx, rx
        self.chconf = [0] * self.NUM_CHANNELS
        self.chstat = [0x00000006] * self.NUM_CHANNELS  # Bit 1 (TXS=1: TX empty), Bit 2 (EOT=1: End of transfer)
        self.chctrl = [0] * self.NUM_CHANNELS
        self.tx = [0] * self.NUM_CHANNELS
        self.rx = [0] * self.NUM_CHANNELS

        self.generic_regs: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_REVISION:
            return self.revision
        elif offset == self.REG_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_SYSSTATUS:
            return self.sysstatus
        elif offset == self.REG_IRQSTATUS:
            return self.irqstatus
        elif offset == self.REG_IRQENABLE:
            return self.irqenable
        elif offset == self.REG_WAKEUPENABLE:
            return self.wakeupenable
        elif offset == self.REG_SYST:
            return self.syst
        elif offset == self.REG_MODULCTRL:
            return self.modulctrl
        elif self.CH_BASE <= offset < self.CH_BASE + (self.NUM_CHANNELS * self.CH_STRIDE):
            ch_off = offset - self.CH_BASE
            ch_num = ch_off // self.CH_STRIDE
            reg_off = ch_off % self.CH_STRIDE
            if reg_off == 0x00:  # MCSPI_CHCONF
                return self.chconf[ch_num]
            elif reg_off == 0x04:  # MCSPI_CHSTAT
                return self.chstat[ch_num]
            elif reg_off == 0x08:  # MCSPI_CHCTRL
                return self.chctrl[ch_num]
            elif reg_off == 0x0C:  # MCSPI_TX
                return self.tx[ch_num]
            elif reg_off == 0x10:  # MCSPI_RX
                # Reading RX clears RXS bit 0 in CHSTAT
                val = self.rx[ch_num]
                self.chstat[ch_num] &= ~0x01
                return val

        return self.generic_regs.get(offset, 0)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_SYSCONFIG:
            self.sysconfig = val
            if val & 0x02:  # SOFTRESET
                self.sysstatus |= 0x01  # Instant reset done
        elif offset == self.REG_SYSSTATUS:
            pass  # Read-only
        elif offset == self.REG_IRQSTATUS:
            self.irqstatus &= ~val  # Write-1-to-clear
            if not (self.irqstatus & self.irqenable) and self.intc:
                self.intc.deassert_irq(self.irq_num)
        elif offset == self.REG_IRQENABLE:
            self.irqenable = val
            if (self.irqstatus & self.irqenable) and self.intc:
                self.intc.assert_irq(self.irq_num)
        elif offset == self.REG_WAKEUPENABLE:
            self.wakeupenable = val
        elif offset == self.REG_SYST:
            self.syst = val
        elif offset == self.REG_MODULCTRL:
            self.modulctrl = val
        elif self.CH_BASE <= offset < self.CH_BASE + (self.NUM_CHANNELS * self.CH_STRIDE):
            ch_off = offset - self.CH_BASE
            ch_num = ch_off // self.CH_STRIDE
            reg_off = ch_off % self.CH_STRIDE
            if reg_off == 0x00:  # MCSPI_CHCONF
                self.chconf[ch_num] = val
            elif reg_off == 0x04:  # MCSPI_CHSTAT
                pass  # Read-only status
            elif reg_off == 0x08:  # MCSPI_CHCTRL
                self.chctrl[ch_num] = val
            elif reg_off == 0x0C:  # MCSPI_TX
                self.tx[ch_num] = val
                # Loopback or simulated slave response: load into RX, assert RXS (bit 0)
                self.rx[ch_num] = val & 0xFFFFFFFF
                self.chstat[ch_num] |= 0x01  # RXS = 1 (RX full)
                self.chstat[ch_num] |= 0x06  # TXS = 1, EOT = 1
            elif reg_off == 0x10:  # MCSPI_RX
                self.rx[ch_num] = val
        else:
            self.generic_regs[offset] = val


MCSPI_MAP = {
    1: (0x48098000, 65),
    2: (0x4809A000, 66),
    3: (0x480B8000, 91),
    4: (0x480BA000, 48),
}
