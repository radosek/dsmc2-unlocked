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

# Run to scheduler
mu.emu_start(0x80829f2c, 0x80e9c368)

print("Searching memory for all ThreadX TX_THREAD blocks (magic 'THRD' = 0x54485244)...")
# Scan mapped RAM: 0x80000000 to 0x88000000
ram_data = mu.mem_read(0x80000000, 0x08000000) # 128 MB

magic = b"DRHT" # LE 0x54485244
pos = 0
found_threads = []
while True:
    idx = ram_data.find(magic, pos)
    if idx == -1:
        break
    tcb_va = 0x80000000 + idx
    # Thread name is at offset +0x04 or +0x14 or +0x18
    # In standard ThreadX:
    # ULONG tx_thread_id (0x54485244)
    # ULONG tx_thread_run_count
    # VOID *tx_thread_stack_ptr
    # VOID *tx_thread_stack_start
    # VOID *tx_thread_stack_end
    # ULONG tx_thread_stack_size
    # ULONG tx_thread_current_state
    # CHAR *tx_thread_name
    # VOID (*tx_thread_entry)(ULONG)
    # ULONG tx_thread_entry_parameter
    # UINT tx_thread_priority
    tcb_bytes = ram_data[idx:idx+0x60]
    words = struct.unpack("<16I", tcb_bytes[:64])
    # check possible name pointers
    name = "unknown"
    for w in words[1:10]:
        if 0x80000000 <= w < 0x88000000:
            name_off = w - 0x80000000
            name_candidate = ram_data[name_off:name_off+32].split(b'\0')[0]
            if name_candidate and all(32 <= b < 127 for b in name_candidate):
                name = name_candidate.decode('latin1')
                break
    entry_fn = words[8]
    prio = words[10]
    found_threads.append((tcb_va, name, words))
    print(f"  TCB at 0x{tcb_va:08x}: name='{name}'")
    pos = idx + 4

print(f"\nTotal ThreadX threads discovered: {len(found_threads)}")
