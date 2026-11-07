import struct, unicorn
from unicorn import arm_const

path = 'firmware_store/unpacked/scarlet_w_7_4_1/slot/dsmc_program.mem'
fw = open(path, 'rb').read()

mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
mu.mem_map(0x80000000, 208 * 1024 * 1024)
mu.mem_write(0x80000000, fw)
mu.mem_map(0x48000000, 0x01100000)
mu.mem_map(0x68000000, 0x08000000)
mu.mem_map(0x40000000, 0x01000000)

def hook_intr(uc, intno, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    if pc in (0x80a294b0, 0x80a294ac):
        uc.reg_write(arm_const.UC_ARM_REG_R0, 0)
        uc.reg_write(arm_const.UC_ARM_REG_PC, pc + 4)

mu.hook_add(unicorn.UC_HOOK_INTR, hook_intr)

def hook_read(uc, access, addr, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    val = 0
    if addr == 0x48004024:
        val = 0 if pc == 0x80674a00 else 1
    elif addr == 0x48004000:
        val = 1
    elif addr == 0x48004a40:
        val = 0xffffffff
    elif addr == 0x48005010:
        val = 0x30
    elif (addr & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000, 0x49042000):
        reg = addr & 0xff
        if reg == 0x58: val = 0x03
        elif reg == 0x14: val = 0x60
    elif (addr & 0xffff0000) in (0x48060000, 0x48070000):
        reg = addr & 0xffff
        if (reg & 0xff) == 0x10: val = 0x01 # I2C_SYSS RDONE
        elif (reg & 0xff) == 0x08: val = 0x04 # I2C_STAT ARDY
    elif (addr & 0xfffff000) in (0x48088000, 0x48086000, 0x49032000, 0x49034000, 0x49036000, 0x49038000, 0x4903a000, 0x4903c000, 0x4903e000, 0x49040000, 0x48318000):
        reg = addr & 0xfff
        if reg == 0x14: val = 0x01 # TISTAT RESETDONE
            
    if size == 1: uc.mem_write(addr, bytes([val & 0xff]))
    elif size == 2: uc.mem_write(addr, struct.pack('<H', val & 0xffff))
    elif size == 4: uc.mem_write(addr, struct.pack('<I', val))

mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_read, begin=0x40000000, end=0x7fffffff)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

mu.emu_start(0x80829f2c, 0x80e9c368)
mu.mem_write(0x8149ce60, struct.pack('<I', 0x814cad40))
mu.emu_start(0x80e9c368, 0, count=100000)

created_ptr = struct.unpack('<I', mu.mem_read(0x8149ce68, 4))[0]
exec_ptr = struct.unpack('<I', mu.mem_read(0x8149ce60, 4))[0]
curr_ptr = struct.unpack('<I', mu.mem_read(0x8149ce5c, 4))[0]
print(f'execute_ptr: 0x{exec_ptr:08x}, current_ptr: 0x{curr_ptr:08x}, created_ptr: 0x{created_ptr:08x}')

cur = created_ptr
visited = set()
while cur and cur not in visited:
    visited.add(cur)
    tcb_data = mu.mem_read(cur, 160)
    tx_id, name_ptr = struct.unpack('<II', tcb_data[0:8])
    state = struct.unpack('<I', tcb_data[8:12])[0]
    sp_val = struct.unpack('<I', tcb_data[12:16])[0]
    stk_start, stk_end = struct.unpack('<II', tcb_data[16:24])
    prio = struct.unpack('<I', tcb_data[24:28])[0]
    next_created = struct.unpack('<I', tcb_data[36:40])[0]
    
    try:
        raw_name = mu.mem_read(name_ptr, 64)
        name = raw_name.split(b'\x00')[0].decode('latin1')
    except:
        name = 'UNKNOWN'
        
    state_names = {0: 'READY', 1: 'COMPLETED', 2: 'TERMINATED', 3: 'SUSPENDED', 4: 'SLEEP', 5: 'QUEUE', 6: 'SEMAPHORE', 7: 'EVENT_FLAG', 8: 'BLOCK_MEMORY', 9: 'BYTE_MEMORY', 10: 'IO_DRIVER', 11: 'FILE', 12: 'NETWORK', 13: 'MUTEX'}
    st_name = state_names.get(state, f'STATE_{state}')
    print(f'Thread [0x{cur:08x}] name="{name}" state={st_name} ({state}) prio={prio} SP=0x{sp_val:08x}')
    cur = next_created
