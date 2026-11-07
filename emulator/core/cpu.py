"""
ARM CPU Core implementation using Unicorn Engine for RED DSMC2 Emulator.
Targets Cortex-A8 (ARMv7-A) architecture of TI DM3725 / OMAP3630 SoC.
"""

import unicorn
from unicorn import arm_const


class ArmCpu:
    """Wraps Unicorn ARM engine with DSMC2-specific exception and mode handling."""

    MODE_USR = 0x10
    MODE_FIQ = 0x11
    MODE_IRQ = 0x12
    MODE_SVC = 0x13
    MODE_ABT = 0x17
    MODE_UND = 0x1B
    MODE_SYS = 0x1F

    def __init__(self):
        self.mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
        self.uc = self.mu # Convenient alias
        self._setup_exception_hooks()

    def _setup_exception_hooks(self):
        """Install exception hooks for OMAP TrustZone SMC calls."""
        def hook_intr(uc, intno, user_data):
            pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
            # OMAP3 PPA ROM TrustZone monitor calls (smc #0)
            if pc in (0x80a294b0, 0x80a294ac):
                uc.reg_write(arm_const.UC_ARM_REG_R0, 0)
                uc.reg_write(arm_const.UC_ARM_REG_PC, pc + 4)

        self.mu.hook_add(unicorn.UC_HOOK_INTR, hook_intr)

    @property
    def pc(self) -> int:
        return self.mu.reg_read(arm_const.UC_ARM_REG_PC)

    @pc.setter
    def pc(self, value: int):
        self.mu.reg_write(arm_const.UC_ARM_REG_PC, value)

    @property
    def sp(self) -> int:
        return self.mu.reg_read(arm_const.UC_ARM_REG_SP)

    @sp.setter
    def sp(self, value: int):
        self.mu.reg_write(arm_const.UC_ARM_REG_SP, value)

    @property
    def lr(self) -> int:
        return self.mu.reg_read(arm_const.UC_ARM_REG_LR)

    @lr.setter
    def lr(self, value: int):
        self.mu.reg_write(arm_const.UC_ARM_REG_LR, value)

    @property
    def cpsr(self) -> int:
        return self.mu.reg_read(arm_const.UC_ARM_REG_CPSR)

    @cpsr.setter
    def cpsr(self, value: int):
        self.mu.reg_write(arm_const.UC_ARM_REG_CPSR, value)

    def read_reg(self, reg_id: int) -> int:
        return self.mu.reg_read(reg_id)

    def write_reg(self, reg_id: int, val: int):
        self.mu.reg_write(reg_id, val)

    def get_r(self, idx: int) -> int:
        reg_map = [
            arm_const.UC_ARM_REG_R0, arm_const.UC_ARM_REG_R1, arm_const.UC_ARM_REG_R2,
            arm_const.UC_ARM_REG_R3, arm_const.UC_ARM_REG_R4, arm_const.UC_ARM_REG_R5,
            arm_const.UC_ARM_REG_R6, arm_const.UC_ARM_REG_R7, arm_const.UC_ARM_REG_R8,
            arm_const.UC_ARM_REG_R9, arm_const.UC_ARM_REG_R10, arm_const.UC_ARM_REG_R11,
            arm_const.UC_ARM_REG_R12
        ]
        return self.mu.reg_read(reg_map[idx])

    def set_r(self, idx: int, val: int):
        reg_map = [
            arm_const.UC_ARM_REG_R0, arm_const.UC_ARM_REG_R1, arm_const.UC_ARM_REG_R2,
            arm_const.UC_ARM_REG_R3, arm_const.UC_ARM_REG_R4, arm_const.UC_ARM_REG_R5,
            arm_const.UC_ARM_REG_R6, arm_const.UC_ARM_REG_R7, arm_const.UC_ARM_REG_R8,
            arm_const.UC_ARM_REG_R9, arm_const.UC_ARM_REG_R10, arm_const.UC_ARM_REG_R11,
            arm_const.UC_ARM_REG_R12
        ]
        self.mu.reg_write(reg_map[idx], val)

    def are_interrupts_enabled(self) -> bool:
        """Check if IRQ bit (bit 7) is clear in CPSR."""
        return (self.cpsr & 0x80) == 0

    def inject_irq(self, vector: int = 0x80829F00) -> bool:
        """
        Deliver a hardware IRQ exception to the CPU.
        Returns True if IRQ was accepted, False if masked.
        """
        if not self.are_interrupts_enabled():
            return False

        current_cpsr = self.cpsr
        current_pc = self.pc

        # Switch to IRQ mode, set IRQ disable flag
        self.mu.reg_write(arm_const.UC_ARM_REG_CPSR, self.MODE_IRQ | 0x80)
        self.mu.reg_write(arm_const.UC_ARM_REG_SPSR, current_cpsr)
        self.mu.reg_write(arm_const.UC_ARM_REG_LR, current_pc + 4)
        self.mu.reg_write(arm_const.UC_ARM_REG_PC, vector)
        return True

    def run(self, start_addr: int = None, until_addr: int = 0, count: int = 0, timeout_us: int = 0):
        if start_addr is None:
            start_addr = self.pc
        self.mu.emu_start(start_addr, until_addr, timeout=timeout_us, count=count)

    def stop(self):
        self.mu.emu_stop()
