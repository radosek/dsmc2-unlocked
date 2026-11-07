import os
import time
import unicorn
from unicorn import arm_const

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
fw_data = open(path, "rb").read()

mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)

# Map DDR memory: 0x80000000 - 0x8CFFFFFF (208 MB)
DDR_BASE = 0x80000000
DDR_SIZE = 208 * 1024 * 1024
mu.mem_map(DDR_BASE, DDR_SIZE)
mu.mem_write(DDR_BASE, fw_data)

# Hook interrupt
def hook_intr(uc, intno, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    r12 = uc.reg_read(arm_const.UC_ARM_REG_R12)
    if pc == 0x80a294b0 or pc == 0x80a294ac:
        uc.reg_write(arm_const.UC_ARM_REG_R0, 0)
        uc.reg_write(arm_const.UC_ARM_REG_PC, pc + 4)
    else:
        print(f"[INTERRUPT] intno={intno} at PC=0x{pc:08x}, R12=0x{r12:08x}")

mu.hook_add(unicorn.UC_HOOK_INTR, hook_intr)

# Hook unmapped MMIO
mmio_log = []
def hook_unmapped(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    access_type = "WRITE" if access == unicorn.UC_MEM_WRITE_UNMAPPED else "READ"
    mmio_log.append((pc, access_type, address, size, value))
    print(f"[UNMAPPED MMIO #{len(mmio_log)}] PC=0x{pc:08x} {access_type} addr=0x{address:08x} size={size} val=0x{value:08x}")
    page = address & ~0xfff
    try:
        uc.mem_map(page, 0x1000)
    except:
        pass
    if len(mmio_log) >= 50:
        print("Reached 50 MMIO accesses, pausing...")
        uc.emu_stop()
    return True

mu.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED, hook_unmapped)

ENTRY_POINT = 0x80829f2c
STACK_POINTER = 0x881d2690

mu.reg_write(arm_const.UC_ARM_REG_PC, ENTRY_POINT)
mu.reg_write(arm_const.UC_ARM_REG_SP, STACK_POINTER)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

print(f"Starting execution up to 50M instructions...")
t0 = time.time()

try:
    mu.emu_start(ENTRY_POINT, 0, count=50_000_000)
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
    print(f"Execution finished normally. Final PC=0x{pc:08x}, SP=0x{sp:08x} in {time.time()-t0:.2f}s")
except unicorn.UcError as e:
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
    print(f"Execution stopped: {e} at PC=0x{pc:08x}, SP=0x{sp:08x} in {time.time()-t0:.2f}s")

print(f"Total unmapped MMIO accesses: {len(mmio_log)}")
