import os
import struct
import unicorn
from unicorn import arm_const

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
fw_data = open(path, "rb").read()

mu = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
mu.mem_map(0x80000000, 208 * 1024 * 1024)
mu.mem_write(0x80000000, fw_data)

# Pre-map peripheral MMIO pages
mu.mem_map(0x48000000, 0x01100000)
mu.mem_map(0x68000000, 0x08000000)
mu.mem_map(0x40000000, 0x01000000)

def hook_intr(uc, intno, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    if pc == 0x80a294b0 or pc == 0x80a294ac:
        uc.reg_write(arm_const.UC_ARM_REG_R0, 0)
        uc.reg_write(arm_const.UC_ARM_REG_PC, pc + 4)

mu.hook_add(unicorn.UC_HOOK_INTR, hook_intr)

mmio_reads = []
mmio_writes = []
uart_chars = []

def hook_mmio_read(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    val = 0
    
    # Device models
    if address == 0x48004024: # PRCM CM_IDLEST_CKGEN (PLL Lock status)
        val = 0x01 # Bit 0 = 1 (LOCKED)
    elif address == 0x48004000: # CM_FCLKEN_IVA2
        val = 0x00000001
    elif address == 0x48004a40: # CM_FCLKEN_PER
        val = 0xffffffff
    elif address == 0x48005010: # PRCM rev
        val = 0x00000030
    elif (address & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000, 0x49042000):
        # OMAP UARTs
        reg = address & 0xff
        if reg == 0x58: # SSR
            val = 0x03 # TX FIFO not full, TX FIFO empty
        elif reg == 0x14: # LSR
            val = 0x60 # TEMT | THRE (Transmitter Empty)
        elif reg == 0x54: # MDR1 / SCR
            val = 0x00
        elif reg == 0x00: # RHR (Receiver holding)
            val = 0x00
            
    mmio_reads.append((pc, address, size, val))
    if len(mmio_reads) <= 30 or len(mmio_reads) % 20 == 0:
        print(f"[MMIO READ #{len(mmio_reads):4d}] PC=0x{pc:08x} addr=0x{address:08x} size={size} -> val=0x{val:08x}")
        
    if size == 1:
        uc.mem_write(address, bytes([val & 0xff]))
    elif size == 2:
        uc.mem_write(address, struct.pack("<H", val & 0xffff))
    elif size == 4:
        uc.mem_write(address, struct.pack("<I", val))

def hook_mmio_write(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    mmio_writes.append((pc, address, size, value))
    
    # Check UART TX
    if (address & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000, 0x49042000):
        reg = address & 0xff
        if reg == 0:
            ch = chr(value & 0xff)
            uart_chars.append(ch)
            print(f">>> [UART TX 0x{address:08x}] '{ch}' (0x{value:02x})")
            
    if len(mmio_writes) <= 30 or len(mmio_writes) % 20 == 0:
        print(f"[MMIO WRITE #{len(mmio_writes):4d}] PC=0x{pc:08x} addr=0x{address:08x} size={size} val=0x{value:08x}")

mu.hook_add(unicorn.UC_HOOK_MEM_READ, hook_mmio_read, begin=0x40000000, end=0x7fffffff)
mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, hook_mmio_write, begin=0x40000000, end=0x7fffffff)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

print("Starting execution with PLL lock modeled...")
mu.emu_start(0x80829f2c, 0x80e9c368)
mu.mem_write(0x8149ce60, struct.pack("<I", 0x814cad40))

try:
    mu.emu_start(0x80e9c368, 0, count=5_000_000)
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
    print(f"Executed 5M instructions. Final PC=0x{pc:08x}, SP=0x{sp:08x}")
except unicorn.UcError as e:
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    print(f"Stopped: {e} at PC=0x{pc:08x}")

print(f"\nTotal MMIO Reads: {len(mmio_reads)}, Writes: {len(mmio_writes)}")
if uart_chars:
    print("UART Output:\n" + "".join(uart_chars))
