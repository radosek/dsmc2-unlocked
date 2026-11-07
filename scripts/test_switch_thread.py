import os
import struct
import unicorn
from unicorn import arm_const

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
fw_data = open(path, "rb").read()

mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
mu.mem_map(0x80000000, 208 * 1024 * 1024)
mu.mem_write(0x80000000, fw_data)

def hook_intr(uc, intno, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    if pc == 0x80a294b0 or pc == 0x80a294ac:
        uc.reg_write(arm_const.UC_ARM_REG_R0, 0)
        uc.reg_write(arm_const.UC_ARM_REG_PC, pc + 4)

mu.hook_add(unicorn.UC_HOOK_INTR, hook_intr)

mmio_log = []
def hook_unmapped(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    access_type = "WRITE" if access == unicorn.UC_MEM_WRITE_UNMAPPED else "READ"
    mmio_log.append((pc, access_type, address, size, value))
    print(f"[MMIO #{len(mmio_log):2d}] PC=0x{pc:08x} {access_type} addr=0x{address:08x} size={size} val=0x{value:08x}")
    page = address & ~0xfff
    try:
        uc.mem_map(page, 0x1000)
    except:
        pass
    return True

mu.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED, hook_unmapped)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

# Run until reaching scheduler idle loop
mu.emu_start(0x80829f2c, 0x80e9c368)
print("Reached scheduler idle loop.")

# Set _tx_thread_execute_ptr (0x8149ce60) to SystemInitThread (0x814cad40)
SYS_INIT_TCB = 0x814cad40
mu.mem_write(0x8149ce60, struct.pack("<I", SYS_INIT_TCB))
print(f"Set _tx_thread_execute_ptr to SystemInitThread (0x{SYS_INIT_TCB:08x})!")

# Also disassemble what _tx_thread_schedule does after 0x80e9c370
print("Resuming execution...")
try:
    # Run 100,000 instructions
    mu.emu_start(0x80e9c368, 0, count=100_000)
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
    print(f"Executed 100k instructions. Final PC=0x{pc:08x}, SP=0x{sp:08x}")
except unicorn.UcError as e:
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    print(f"Stopped: {e} at PC=0x{pc:08x}")
