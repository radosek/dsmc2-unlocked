"""
Texas Instruments DM3725 / OMAP3630 L4 Interconnect, System Control Module (SCM),
Power/Reset Management (PRM), and SDRAM Controller (SDRC) Models.

TRM Provenance (SPRUGN4 / OMAP36xx & DM37xx Technical Reference Manual):
- 0x48000000 (size 0x2000): L4-Core Address Protection (L4_CORE_AP) & Link Agent (Table 2-3)
- 0x48002000 (size 0x2000): System Control Module (SCM / PADCONF) (Table 2-3, Chapter 7)
- 0x48306000 (size 0x2000): L4-Wakeup Power and Reset Management (PRM) (Table 2-5, Chapter 3)
- 0x49000000 (size 0x1000): L4-Per Address Protection (L4_PER_AP / Interconnect Firewall) (Table 2-4, Chapter 2)
- 0x6D000000 (size 0x1000): SDRAM Controller (SDRC) (Table 2-1, Chapter 11)
"""

from typing import Dict, Any
from emulator.core.bus import Device


class OmapL4Ap(Device):
    """
    TI Sonics S3220 L4 Interconnect Address Protection (AP) and Firewall Module.
    Models L4-Core AP (0x48000000) and L4-Per AP (0x49000000).
    Returns valid interconnect component identification and non-blocking region
    protection permissions so supervisor/user bus probes succeed cleanly.
    """

    BASE_ADDR_L4_CORE = 0x48000000
    BASE_ADDR_L4_PER = 0x49000000
    SIZE = 0x1000

    # Standard Sonics S3220 L4 AP / LA Register Offsets (TRM Section 2.4)
    REG_COMPONENT = 0x0000          # Component code & revision (0x40000800)
    REG_NETWORK = 0x0008            # Interconnect network ID
    REG_INIT_PRESSURE = 0x0020      # Initiator pressure control
    REG_ERROR_LOG = 0x0040          # Firewall / interconnect error log (0 = no error)
    REG_ERROR_ADDR = 0x0048         # Faulting address log

    def __init__(self, name: str = "L4_PER_AP", base_addr: int = 0x49000000):
        self.name = name
        self.base_addr = base_addr
        self.component_rev = 0x40000800
        self.network_id = 0x00000001 if base_addr == self.BASE_ADDR_L4_PER else 0x00000000
        self.init_pressure = 0x00000000
        self.error_log = 0x00000000
        self.error_addr = 0x00000000
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_COMPONENT:
            return self.component_rev
        elif offset == self.REG_NETWORK:
            return self.network_id
        elif offset == self.REG_INIT_PRESSURE:
            return self.init_pressure
        elif offset == self.REG_ERROR_LOG:
            return self.error_log
        elif offset == self.REG_ERROR_ADDR:
            return self.error_addr
        elif 0x0100 <= offset < 0x0400:
            # Protection group masks: all groups enabled
            return self.registers.get(offset, 0xFFFFFFFF)
        elif 0x0800 <= offset < 0x0C00:
            # Request info permission registers: full R/W access for all initiators
            return self.registers.get(offset, 0xFFFFFFFF)
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_INIT_PRESSURE:
            self.init_pressure = val
        elif offset == self.REG_ERROR_LOG:
            # Write-1-to-clear interconnect error log
            self.error_log &= ~val
        else:
            self.registers[offset] = val

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_addr": f"0x{self.base_addr:08X}",
            "component_rev": f"0x{self.component_rev:08X}",
            "error_log": self.error_log,
        }


class OmapScm(Device):
    """
    OMAP3630 / DM3725 System Control Module (SCM) at 0x48002000 (size 0x2000).
    Handles pad configuration (CONTROL_PADCONF_*), device ID code (DM3725 Hawkeye 0xB891),
    and boot strap status (CONTROL_STATUS).
    Note: Real hardware has a power-off latch at 0x480025F8-0x480025FC; the emulator
    tracks reads/writes there without dropping power.
    """

    BASE_ADDR = 0x48002000
    SIZE = 0x2000

    REG_REVISION = 0x0000
    REG_SYSCONFIG = 0x0010
    REG_IDCODE = 0x0204          # DM3725 / OMAP3630 IDCODE: 0x1B89102F
    REG_CONTROL_STATUS = 0x02F0  # SYS_BOOT strap configuration (NAND boot)
    REG_DEVCONF0 = 0x0274
    REG_DEVCONF1 = 0x02D8

    def __init__(self):
        self.sysconfig = 0x00000001
        self.idcode = 0x1B89102F          # ES1.2 DM3725 / OMAP3630
        self.control_status = 0x0000030D  # Normal device, NAND CS0 boot order
        self.devconf0 = 0x05000000
        self.devconf1 = 0x00000040
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_REVISION:
            return 0x00000010
        elif offset == self.REG_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_IDCODE:
            return self.idcode
        elif offset == self.REG_CONTROL_STATUS:
            return self.control_status
        elif offset == self.REG_DEVCONF0:
            return self.devconf0
        elif offset == self.REG_DEVCONF1:
            return self.devconf1
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_SYSCONFIG:
            self.sysconfig = val
        elif offset == self.REG_DEVCONF0:
            self.devconf0 = val
        elif offset == self.REG_DEVCONF1:
            self.devconf1 = val
        else:
            self.registers[offset] = val


class OmapPrm(Device):
    """
    OMAP3630 / DM3725 L4-Wakeup Power and Reset Management (PRM) at 0x48306000 (size 0x2000).
    """

    BASE_ADDR = 0x48306000
    SIZE = 0x2000

    REG_PRM_REVISION = 0x0804
    REG_PRM_SYSCONFIG = 0x0814
    REG_PRM_IRQSTATUS_MPU = 0x0818
    REG_PRM_IRQENABLE_MPU = 0x081C
    REG_PRM_RSTCTRL = 0x1250
    REG_PRM_RSTTIME = 0x1254
    REG_PRM_RSTST = 0x1258
    REG_PRM_CLKSRC_CTRL = 0x1270

    def __init__(self):
        self.sysconfig = 0x00000001
        self.irqstatus_mpu = 0x00000000
        self.irqenable_mpu = 0x00000000
        self.rstctrl = 0x00000000
        self.rsttime = 0x00001006
        self.rstst = 0x00000001       # GLOBAL_COLD_RST
        self.clksrc_ctrl = 0x00000080 # SYSCLK = 26 MHz
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_PRM_REVISION:
            return 0x00000010
        elif offset == self.REG_PRM_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_PRM_IRQSTATUS_MPU:
            return self.irqstatus_mpu
        elif offset == self.REG_PRM_IRQENABLE_MPU:
            return self.irqenable_mpu
        elif offset == self.REG_PRM_RSTCTRL:
            return self.rstctrl
        elif offset == self.REG_PRM_RSTTIME:
            return self.rsttime
        elif offset == self.REG_PRM_RSTST:
            return self.rstst
        elif offset == self.REG_PRM_CLKSRC_CTRL:
            return self.clksrc_ctrl
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_PRM_SYSCONFIG:
            self.sysconfig = val
        elif offset == self.REG_PRM_IRQSTATUS_MPU:
            self.irqstatus_mpu &= ~val
        elif offset == self.REG_PRM_IRQENABLE_MPU:
            self.irqenable_mpu = val
        elif offset == self.REG_PRM_RSTCTRL:
            self.rstctrl = val
        elif offset == self.REG_PRM_RSTTIME:
            self.rsttime = val
        elif offset == self.REG_PRM_RSTST:
            self.rstst &= ~val
        elif offset == self.REG_PRM_CLKSRC_CTRL:
            self.clksrc_ctrl = val
        else:
            self.registers[offset] = val


class OmapSdrc(Device):
    """
    OMAP3630 / DM3725 SDRAM Controller (SDRC) at 0x6D000000 (size 0x1000).
    Initialized with hardware-proven DSMC2 CHRAM timings from docs/hardware-fw/rom-boot-recovery.md:
      MCFG_0        = 0x03588019
      ACTIM_CTRLA_0 = 0x7326D948
      ACTIM_CTRLB_0 = 0x00021213
      RFR_CTRL_0    = 0x0004E201
      MR_0          = 0x00000032
    """

    BASE_ADDR = 0x6D000000
    SIZE = 0x1000

    REG_REVISION = 0x0000
    REG_SYSCONFIG = 0x0010
    REG_SYSSTATUS = 0x0014
    REG_CS_CFG = 0x0040
    REG_SHARING = 0x0044
    REG_DLLA_CTRL = 0x0060
    REG_DLLA_STATUS = 0x0064
    REG_POWER = 0x0070
    REG_MCFG_0 = 0x0080
    REG_MR_0 = 0x0084
    REG_ACTIM_CTRLA_0 = 0x009C
    REG_ACTIM_CTRLB_0 = 0x00A0
    REG_RFR_CTRL_0 = 0x00A4

    def __init__(self):
        self.sysconfig = 0x00000010
        self.sysstatus = 0x00000001  # RESETDONE = 1
        self.dlla_ctrl = 0x0000000A
        self.dlla_status = 0x00000004  # LOCKED = 1
        self.power = 0x00000081
        self.mcfg_0 = 0x03588019
        self.mr_0 = 0x00000032
        self.actim_ctrla_0 = 0x7326D948
        self.actim_ctrlb_0 = 0x00021213
        self.rfr_ctrl_0 = 0x0004E201
        self.registers: Dict[int, int] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.REG_REVISION:
            return 0x00000040
        elif offset == self.REG_SYSCONFIG:
            return self.sysconfig
        elif offset == self.REG_SYSSTATUS:
            return self.sysstatus
        elif offset == self.REG_DLLA_CTRL:
            return self.dlla_ctrl
        elif offset == self.REG_DLLA_STATUS:
            return self.dlla_status
        elif offset == self.REG_POWER:
            return self.power
        elif offset == self.REG_MCFG_0:
            return self.mcfg_0
        elif offset == self.REG_MR_0:
            return self.mr_0
        elif offset == self.REG_ACTIM_CTRLA_0:
            return self.actim_ctrla_0
        elif offset == self.REG_ACTIM_CTRLB_0:
            return self.actim_ctrlb_0
        elif offset == self.REG_RFR_CTRL_0:
            return self.rfr_ctrl_0
        return self.registers.get(offset, 0x00000000)

    def write(self, offset: int, size: int, value: int):
        val = value & 0xFFFFFFFF
        if offset == self.REG_SYSCONFIG:
            self.sysconfig = val
            if val & 0x02:
                self.sysstatus = 0x01
        elif offset == self.REG_DLLA_CTRL:
            self.dlla_ctrl = val
        elif offset == self.REG_POWER:
            self.power = val
        elif offset == self.REG_MCFG_0:
            self.mcfg_0 = val
        elif offset == self.REG_MR_0:
            self.mr_0 = val
        elif offset == self.REG_ACTIM_CTRLA_0:
            self.actim_ctrla_0 = val
        elif offset == self.REG_ACTIM_CTRLB_0:
            self.actim_ctrlb_0 = val
        elif offset == self.REG_RFR_CTRL_0:
            self.rfr_ctrl_0 = val
        else:
            self.registers[offset] = val
