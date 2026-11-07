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

def hook_unmapped(uc, access, address, size, value, user_data):
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

mu.emu_start(0x80829f2c, 0x80e9c368)

tcb = 0x81f04d84
print(f"=== Inspecting TCB at 0x{tcb:08x} ===")
chunk = mu.mem_read(tcb, 0x80)
for i in range(0, 0x80, 4):
    w = struct.unpack("<I", chunk[i:i+4])[0]
    txt = chunk[i:i+4]
    print(f"  +0x{i:02x}: 0x{w:08x}  ({txt})")

# Read thread name if pointer is at +0x14 or +0x18
for off in (0x10, 0x14, 0x18, 0x1c, 0x20):
    ptr = struct.unpack("<I", chunk[off:off+4])[0]
    if 0x80000000 <= ptr < 0x8c000000:
        try:
            name_bytes = mu.mem_read(ptr, 32).split(b'\0')[0]
            print(f"  String at +0x{off:02x} (0x{ptr:08x}): {name_bytes.decode('latin1', errors='replace')}")
        except:
            pass
