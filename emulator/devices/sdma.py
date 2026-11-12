"""
OMAP3630 System DMA (sDMA) Controller Model.
Implements the 32-channel DMA controller mapped at 0x48056000 (size 0x1000).
Supports OCP reset handshake, global configuration, interrupt enable/status,
and channel configuration registers.
"""

from typing import Dict
from emulator.core.bus import Device


class OmapSdma(Device):
    """OMAP3630 System DMA (sDMA) Controller."""

    BASE_ADDR = 0x48056000
    SIZE = 0x1000

    # Common System Registers
    REG_REVISION = 0x00
    REG_IRQSTATUS_L0 = 0x08
    REG_IRQSTATUS_L1 = 0x0C
    REG_IRQSTATUS_L2 = 0x10
    REG_IRQSTATUS_L3 = 0x14
    REG_IRQENABLE_L0 = 0x18
    REG_IRQENABLE_L1 = 0x1C
    REG_IRQENABLE_L2 = 0x20
    REG_IRQENABLE_L3 = 0x24
    REG_SYSSTATUS = 0x28
    REG_OCP_SYSCONFIG = 0x2C
    REG_CAPS_0 = 0x64
    REG_CAPS_2 = 0x6C
    REG_CAPS_3 = 0x70
    REG_CAPS_4 = 0x74
    REG_GCR = 0x78

    NUM_CHANNELS = 32
    CHANNEL_STRIDE = 0x60
    CHANNEL_BASE = 0x80

    def __init__(self, intc=None, cpu=None):
        self.intc = intc
        self.cpu = cpu
        self.revision = 0x00000040  # OMAP3 sDMA revision 4.0
        self.sysstatus = 0x00000001 # bit 0: RESETDONE = 1
        self.ocp_sysconfig = 0x00000015 # AUTOIDLE=1, SIDLEMODE=smart, MIDLEMODE=smart
        self.gcr = 0x00010010
        self.irqstatus = [0, 0, 0, 0]
        self.irqenable = [0, 0, 0, 0]

        # 32 DMA channels, each with a register dict
        self.channels: Dict[int, Dict[int, int]] = {
            ch: {} for ch in range(self.NUM_CHANNELS)
        }
        self.generic_regs: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_REVISION:
            return self.revision
        elif offset == self.REG_SYSSTATUS:
            # Bit 0 is RESETDONE
            return self.sysstatus
        elif offset == self.REG_OCP_SYSCONFIG:
            return self.ocp_sysconfig
        elif offset == self.REG_GCR:
            return self.gcr
        elif self.REG_IRQSTATUS_L0 <= offset <= self.REG_IRQSTATUS_L3:
            idx = (offset - self.REG_IRQSTATUS_L0) // 4
            return self.irqstatus[idx]
        elif self.REG_IRQENABLE_L0 <= offset <= self.REG_IRQENABLE_L3:
            idx = (offset - self.REG_IRQENABLE_L0) // 4
            return self.irqenable[idx]
        elif offset >= self.CHANNEL_BASE:
            ch_offset = offset - self.CHANNEL_BASE
            ch_num = ch_offset // self.CHANNEL_STRIDE
            reg_offset = ch_offset % self.CHANNEL_STRIDE
            if 0 <= ch_num < self.NUM_CHANNELS:
                return self.channels[ch_num].get(reg_offset, 0)

        return self.generic_regs.get(offset, 0)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_OCP_SYSCONFIG:
            self.ocp_sysconfig = val
            if val & 0x02: # SOFTRESET
                # Reset performed instantly, RESETDONE asserted
                self.sysstatus |= 0x01
        elif offset == self.REG_SYSSTATUS:
            # Read-only status
            pass
        elif offset == self.REG_GCR:
            self.gcr = val
        elif self.REG_IRQSTATUS_L0 <= offset <= self.REG_IRQSTATUS_L3:
            idx = (offset - self.REG_IRQSTATUS_L0) // 4
            # Write 1 to clear
            self.irqstatus[idx] &= ~val
            if idx == 3:
                # Line 3 maps to INTC IRQ 15
                if not (self.irqstatus[3] & self.irqenable[3]) and self.intc:
                    self.intc.deassert_irq(15)
        elif self.REG_IRQENABLE_L0 <= offset <= self.REG_IRQENABLE_L3:
            idx = (offset - self.REG_IRQENABLE_L0) // 4
            self.irqenable[idx] = val
            if idx == 3 and (self.irqstatus[3] & self.irqenable[3]) and self.intc:
                self.intc.assert_irq(15)
        elif offset >= self.CHANNEL_BASE:
            ch_offset = offset - self.CHANNEL_BASE
            ch_num = ch_offset // self.CHANNEL_STRIDE
            reg_offset = ch_offset % self.CHANNEL_STRIDE
            if 0 <= ch_num < self.NUM_CHANNELS:
                if reg_offset == 0x00: # DMA4_CCR (Channel Control)
                    self.channels[ch_num][reg_offset] = val
                    if val & 0x80: # Channel Enable
                        # Complete transfer instantly for NAND / memory DMA
                        if self.cpu and hasattr(self.cpu, "mu"):
                            cdsa = self.channels[ch_num].get(0x20, 0) # DMA4_CDSA
                            cen = self.channels[ch_num].get(0x14, 0) & 0xFFFF # DMA4_CEN
                            cfn = self.channels[ch_num].get(0x18, 0) & 0xFFFF # DMA4_CFN
                            csdp = self.channels[ch_num].get(0x10, 0) # DMA4_CSDP
                            elem_size = 1 << (csdp & 3)
                            total_bytes = (cen if cen else 1) * (cfn if cfn else 1) * elem_size
                            if total_bytes > 0 and 0x40000000 <= cdsa < 0x90000000:
                                try:
                                    self.cpu.mu.mem_write(cdsa, b"\xFF" * min(total_bytes, 8192))
                                except Exception:
                                    pass

                        # Set CSR bit 5 (BLOCK_DONE = 0x20)
                        self.channels[ch_num][0x0C] = (self.channels[ch_num].get(0x0C, 0) | 0x20) & ~0x80
                        # Assert IRQ on Line 3 (IRQ 15)
                        self.irqstatus[3] |= (1 << ch_num)
                        if (self.irqenable[3] & (1 << ch_num)) and self.intc:
                            self.intc.assert_irq(15)
                elif reg_offset == 0x0C: # DMA4_CSR (Write 1 to clear status bits)
                    current_csr = self.channels[ch_num].get(0x0C, 0)
                    self.channels[ch_num][0x0C] = current_csr & ~val
                else:
                    self.channels[ch_num][reg_offset] = val
        else:
            self.generic_regs[offset] = val
