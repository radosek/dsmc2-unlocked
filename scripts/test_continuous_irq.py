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
    0x04: 0, 0x08: 0, 0x10: 1, 0x14: 0, 0x18: 0,
    0x1c: 0, 0x20: 0, 0x24: 0, 0x28: 0, 0x2c: 0,
    0x30: 0, 0x34: 0, 0x38: 0,
}
i2c_tx_count = 0
uart_output = []

def hook_read(uc, access, addr, size, value, user_data):
    global i2c_regs
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

    if size == 1: uc.mem_write(addr, bytes([val & 0xff]))
    elif size == 2: uc.mem_write(addr, struct.pack('<H', val & 0xffff))
    elif size == 4: uc.mem_write(addr, struct.pack('<I', val))

def hook_write(uc, access, addr, size, val, user_data):
    global i2c_regs, i2c_tx_count
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)

    # UART TX check
    if (addr & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000, 0x49042000) and (addr & 0xff) == 0:
        uart_output.append(chr(val & 0xff))

    if (addr & 0xffff0000) in (0x48060000, 0x48070000):
        reg = addr & 0xff
        if reg == 0x08:
            i2c_regs[0x08] &= ~val
        else:
            i2c_regs[reg] = val

        if reg == 0x24 and (val & 0x01): # CON: start transaction
            i2c_tx_count += 1
            sa = i2c_regs.get(0x2c, 0)
            cnt = i2c_regs.get(0x18, 0)
            trx = "TX" if (val & 0x200) else "RX"
            print(f"[I2C3 #{i2c_tx_count}] Address 0x{sa:02x} {trx} cnt={cnt} bytes")
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

print("Starting execution loop...")
# Run initial boot
mu.emu_start(0x80829f2c, 0, count=45_000_000)

for loop_idx in range(50):
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    cpsr = mu.reg_read(arm_const.UC_ARM_REG_CPSR)
    
    # Check if in idle loop and have pending IRQs
    if pc in (0x80e9c368, 0x80e9c36c, 0x80e9c370) and pending_irqs:
        irq = pending_irqs[0]
        # Inject IRQ
        mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x12 | 0x80)
        mu.reg_write(arm_const.UC_ARM_REG_SPSR, cpsr)
        mu.reg_write(arm_const.UC_ARM_REG_LR, pc + 4)
        mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f00)
        mu.emu_start(0x80829f00, 0, count=500_000)
    else:
        # Run a slice
        mu.emu_start(pc, 0, count=500_000)
        
    if i2c_tx_count >= 15:
        break

pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
print(f"\nLoop completed. Final PC=0x{pc:08x}, total I2C transactions={i2c_tx_count}")
if uart_output:
    print("UART Output: " + "".join(uart_output))
