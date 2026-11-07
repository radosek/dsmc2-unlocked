import os
import struct
import unicorn
from unicorn import arm_const

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
fw_data = open(path, "rb").read()

mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)

# Map DDR memory: 0x80000000 - 0x88FFFFFF (144 MB)
DDR_BASE = 0x80000000
DDR_SIZE = 144 * 1024 * 1024 # 144 MB
mu.mem_map(DDR_BASE, DDR_SIZE)

# Write firmware to DDR_BASE
mu.mem_write(DDR_BASE, fw_data)

# Hook unmapped memory accesses
mmio_log = []
def hook_unmapped(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    access_type = "WRITE" if access == unicorn.UC_MEM_WRITE_UNMAPPED else "READ"
    mmio_log.append((pc, access_type, address, size, value))
    print(f"[UNMAPPED MMIO] PC=0x{pc:08x} {access_type} addr=0x{address:08x} size={size} val=0x{value:08x}")
    # Map a page on the fly so execution can continue or return 0
    page = address & ~0xfff
    try:
        uc.mem_map(page, 0x1000)
    except:
        pass
    return True

mu.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED, hook_unmapped)

# Set initial registers
ENTRY_POINT = 0x80829f2c
STACK_POINTER = 0x881d2690

mu.reg_write(arm_const.UC_ARM_REG_PC, ENTRY_POINT)
mu.reg_write(arm_const.UC_ARM_REG_SP, STACK_POINTER)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

print(f"Starting execution at PC=0x{ENTRY_POINT:08x}, SP=0x{STACK_POINTER:08x}...")

instruction_count = 0
def hook_code(uc, address, size, user_data):
    global instruction_count
    instruction_count += 1
    if instruction_count <= 25 or instruction_count % 200 == 0:
        r0 = uc.reg_read(arm_const.UC_ARM_REG_R0)
        sp = uc.reg_read(arm_const.UC_ARM_REG_SP)
        print(f"  Step {instruction_count:5d} | PC=0x{address:08x} SP=0x{sp:08x} R0=0x{r0:08x}")

mu.hook_add(unicorn.UC_HOOK_CODE, hook_code)

try:
    mu.emu_start(ENTRY_POINT, 0, count=2000)
    print(f"Execution finished normally after {instruction_count} instructions.")
except unicorn.UcError as e:
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    print(f"Execution stopped with UcError: {e} at PC=0x{pc:08x} after {instruction_count} instructions.")
