"""
OMAP3630 PRCM (Power, Reset, and Clock Management) Model.
Implements clock and reset registers at 0x48004000 and 0x48005000.
"""

from emulator.core.bus import Device


class OmapPrcm(Device):
    """OMAP3630 PRCM Controller."""

    BASE_ADDR = 0x48004000
    SIZE = 0x2000

    def __init__(self, cpu):
        self.cpu = cpu
        self.cm_fclken_per = 0xFFFFFFFF
        self.cm_fclken1_core = 0
        self.cm_iclken1_core = 0
        self.prm_rstst = 0x00000030
        self.pll_locked = True
        self.registers = {}

    def read(self, offset: int, size: int) -> int:
        pc = self.cpu.pc
        if offset == 0x00: # PRM_REVISION
            return 0x01
        elif offset == 0x24: # CM_IDLEST_CKGEN
            # Dynamic DPLL lock sequence:
            # Polling at 0x80674a00 checks for unlock (bit 0 == 0)
            # Polling at 0x80674a64 checks for lock (bit 0 == 1)
            if pc == 0x80674A00:
                return 0x00
            return 0x01
        elif offset == 0xA00: # CM_FCLKEN1_CORE
            return self.cm_fclken1_core
        elif offset == 0xA10: # CM_ICLKEN1_CORE
            return self.cm_iclken1_core
        elif offset == 0xA40: # CM_FCLKEN_PER
            return self.cm_fclken_per
        elif offset == 0x1010: # PRM_RSTST (0x48005010)
            return self.prm_rstst
        return self.registers.get(offset, 0)

    def write(self, offset: int, size: int, value: int):
        self.registers[offset] = value
        if offset == 0xA00:
            self.cm_fclken1_core = value
        elif offset == 0xA10:
            self.cm_iclken1_core = value
        elif offset == 0xA40:
            self.cm_fclken_per = value
        elif offset == 0x1010:
            self.prm_rstst = value
