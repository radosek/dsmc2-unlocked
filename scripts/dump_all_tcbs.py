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

tcbs = [0x8149d494, 0x814cad40, 0x827109b0, 0x82710ca0]
for tcb in tcbs:
    print(f"\n=== TCB at 0x{tcb:08x} ===")
    chunk = mu.mem_read(tcb, 0x60)
    words = struct.unpack("<24I", chunk)
    for idx, w in enumerate(words):
        extra = ""
        if 0x80000000 <= w < 0x88000000:
            try:
                s = mu.mem_read(w, 32).split(b'\0')[0].decode('latin1', errors='replace')
                if s and all(32 <= ord(c) < 127 for c in s):
                    extra = f" -> str: '{s}'"
            except:
                pass
        print(f"  +0x{idx*4:02x}: 0x{w:08x}{extra}")
