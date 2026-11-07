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

uart_buffers = {0x4806a000: [], 0x4806c000: [], 0x49020000: [], 0x49042000: []}
uart_lines = {0x4806a000: [], 0x4806c000: [], 0x49020000: [], 0x49042000: []}

mmio_read_counts = {}
mmio_write_counts = {}

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
        if reg == 0x58: val = 0x03 # SSR: TX FIFO empty/not full
        elif reg == 0x14: val = 0x60 # LSR: TEMT | THRE
        elif reg == 0x00: val = 0x00
    elif (addr & 0xffff0000) in (0x48060000, 0x48070000):
        reg = addr & 0xffff
        if (reg & 0xff) == 0x10: val = 0x01 # I2C_SYSS RDONE
        elif (reg & 0xff) == 0x08: val = 0x04 # I2C_STAT ARDY
    elif (addr & 0xfffff000) in (0x48088000, 0x48086000, 0x49032000, 0x49034000, 0x49036000, 0x49038000, 0x4903a000, 0x4903c000, 0x4903e000, 0x49040000, 0x48318000):
        reg = addr & 0xfff
        if reg == 0x14: val = 0x01 # TISTAT RESETDONE
        elif reg == 0x28: val = 0x00 # TISR
        elif reg == 0x3c: val = 0x1000 # TCVR
            
    mmio_read_counts[addr] = mmio_read_counts.get(addr, 0) + 1
    if size == 1: uc.mem_write(addr, bytes([val & 0xff]))
    elif size == 2: uc.mem_write(addr, struct.pack('<H', val & 0xffff))
    elif size == 4: uc.mem_write(addr, struct.pack('<I', val))

def hook_write(uc, access, addr, size, val, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    mmio_write_counts[addr] = mmio_write_counts.get(addr, 0) + 1
    
    # Check UART TX
    uart_base = addr & 0xffffff00
    if uart_base in uart_buffers and (addr & 0xff) == 0:
        ch = chr(val & 0xff)
        uart_buffers[uart_base].append(ch)
        if ch == '\n':
            line = "".join(uart_buffers[uart_base])
            uart_lines[uart_base].append(line)
            uart_buffers[uart_base] = []
            print(f"[UART 0x{uart_base:08x}] {line.strip()}")

mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_read, begin=0x40000000, end=0x7fffffff)
mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook_write, begin=0x40000000, end=0x7fffffff)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

print("Running emulator from reset vector...")
t0 = time.time()
try:
    mu.emu_start(0x80829f2c, 0, count=50_000_000)
except Exception as e:
    print(f"Emulator exception: {e}")
t1 = time.time()

pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
cpsr = mu.reg_read(arm_const.UC_ARM_REG_CPSR)
curr_thread = struct.unpack('<I', mu.mem_read(0x8149ce60, 4))[0]
exec_thread = struct.unpack('<I', mu.mem_read(0x8149dde8, 4))[0]

print(f"\nExecution finished in {t1-t0:.2f}s:")
print(f"  PC=0x{pc:08x}, SP=0x{sp:08x}, CPSR=0x{cpsr:08x}")
print(f"  current_thread=0x{curr_thread:08x}, execute_thread=0x{exec_thread:08x}")

for uart_base, lines in uart_lines.items():
    if lines or uart_buffers[uart_base]:
        remaining = "".join(uart_buffers[uart_base])
        print(f"UART 0x{uart_base:08x} ({len(lines)} lines):")
        for line in lines[-10:]:
            print(f"  {line.strip()}")
        if remaining:
            print(f"  [tail]: {remaining}")

print("\nTop 10 MMIO Read Addresses:")
for addr, count in sorted(mmio_read_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  0x{addr:08x}: {count:8d} reads")

print("\nTop 10 MMIO Write Addresses:")
for addr, count in sorted(mmio_write_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  0x{addr:08x}: {count:8d} writes")
