import struct
import unicorn
from unicorn import arm_const
import time

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

pending_irqs = []
i2c_regs = {
    0x04: 0, # IE
    0x08: 0, # STAT
    0x10: 1, # SYSS
    0x14: 0, # BUF
    0x18: 0, # CNT
    0x1c: 0, # DATA
    0x20: 0, # SYSC
    0x24: 0, # CON
    0x28: 0, # OA
    0x2c: 0, # SA
    0x30: 0, # PSC
    0x34: 0, # SCLL
    0x38: 0, # SCLH
}
in_irq = False

def hook_read(uc, access, addr, size, value, user_data):
    global i2c_regs, in_irq
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
        reg = addr & 0xff
        val = i2c_regs.get(reg, 0)
    elif (addr & 0xfffff000) in (0x48088000, 0x48086000, 0x49032000, 0x49034000, 0x49036000, 0x49038000, 0x4903a000, 0x4903c000, 0x4903e000, 0x49040000, 0x48318000):
        reg = addr & 0xfff
        if reg == 0x14: val = 0x01
    elif addr == 0x48200040: # INTC_SIR_IRQ
        val = pending_irqs[0] if pending_irqs else 0x7f

    if in_irq:
        print(f"  [IRQ READ]  PC=0x{pc:08x} addr=0x{addr:08x} sz={size} -> 0x{val:08x}")
            
    if size == 1: uc.mem_write(addr, bytes([val & 0xff]))
    elif size == 2: uc.mem_write(addr, struct.pack('<H', val & 0xffff))
    elif size == 4: uc.mem_write(addr, struct.pack('<I', val))

def hook_write(uc, access, addr, size, val, user_data):
    global i2c_regs, in_irq
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    if in_irq:
        print(f"  [IRQ WRITE] PC=0x{pc:08x} addr=0x{addr:08x} sz={size} val=0x{val:08x}")

    if (addr & 0xffff0000) in (0x48060000, 0x48070000):
        reg = addr & 0xff
        if reg == 0x08: # STAT (write 1 to clear)
            i2c_regs[0x08] &= ~val
        else:
            i2c_regs[reg] = val

        if reg == 0x24 and (val & 0x01): # CON: start transaction
            i2c_regs[0x08] |= 0x04 # Set ARDY
            if 61 not in pending_irqs:
                pending_irqs.append(61)
    elif addr == 0x48200048: # INTC_CONTROL (ack)
        if pending_irqs:
            pending_irqs.pop(0)

mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_read, begin=0x40000000, end=0x7fffffff)
mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook_write, begin=0x40000000, end=0x7fffffff)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

print("Running first 45M instructions...")
mu.emu_start(0x80829f2c, 0, count=45_000_000)
pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
cpsr = mu.reg_read(arm_const.UC_ARM_REG_CPSR)
print(f"Reached PC=0x{pc:08x}, CPSR=0x{cpsr:08x}, pending_irqs={pending_irqs}")

print(f"\n--- Injecting IRQ 61 ---")
in_irq = True
old_cpsr = cpsr
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x12 | 0x80)
mu.reg_write(arm_const.UC_ARM_REG_SPSR, old_cpsr)
mu.reg_write(arm_const.UC_ARM_REG_LR, pc + 4)
mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f00)

mu.emu_start(0x80829f00, 0, count=50_000)
in_irq = False

new_pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
new_cpsr = mu.reg_read(arm_const.UC_ARM_REG_CPSR)
print(f"IRQ finished at PC=0x{new_pc:08x}, CPSR=0x{new_cpsr:08x}")

tcb = 0x814cad40
chunk = mu.mem_read(tcb, 0x40)
state = struct.unpack('<I', chunk[0x30:0x34])[0]
state_names = {0: 'READY', 1: 'COMPLETED', 2: 'TERMINATED', 3: 'SUSPENDED', 4: 'SLEEP', 5: 'QUEUE', 6: 'SEMAPHORE', 7: 'EVENT_FLAG'}
print(f"SystemInitThread state={state_names.get(state, state)} ({state})")
exec_thread = struct.unpack('<I', mu.mem_read(0x8149dde8, 4))[0]
print(f"execute_thread = 0x{exec_thread:08x} (should be SystemInitThread: 0x814cad40)")
