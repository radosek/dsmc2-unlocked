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
uart_output = []

def hook_unmapped(uc, access, address, size, value, user_data):
    pc = uc.reg_read(arm_const.UC_ARM_REG_PC)
    access_type = "WRITE" if access == unicorn.UC_MEM_WRITE_UNMAPPED else "READ"
    mmio_log.append((pc, access_type, address, size, value))
    
    # Check if writing to UART TX FIFO (offset 0 of any UART)
    if access == unicorn.UC_MEM_WRITE_UNMAPPED:
        if (address & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000, 0x49042000):
            reg = address & 0xff
            if reg == 0:
                char = chr(value & 0xff)
                uart_output.append(char)
                print(f"[UART OUT (0x{address:08x})] '{char}' (0x{value:02x})")
    
    # Map page on demand if not mapped
    page = address & ~0xfff
    try:
        uc.mem_map(page, 0x1000)
    except:
        pass
        
    # Provide intelligent device responses
    if access == unicorn.UC_MEM_READ_UNMAPPED:
        resp = 0
        if address == 0x48004a40: # PRCM CM_FCLKEN_PER
            resp = 0xffffffff
        elif address == 0x48005010: # PRCM revision
            resp = 0x00000030
        elif (address & 0xffffff00) == 0x49042000: # UART4
            reg = address & 0xff
            if reg == 0x58: # SSR: bit 0 = TX FIFO not full, bit 1 = TX FIFO empty
                resp = 0x03
            elif reg == 0x14: # LSR: bit 5 = TX empty, bit 6 = TEMT
                resp = 0x60
        elif (address & 0xffffff00) in (0x4806a000, 0x4806c000, 0x49020000): # other UARTs
            reg = address & 0xff
            if reg == 0x14:
                resp = 0x60
            elif reg == 0x58:
                resp = 0x03
        
        # Write response into page so Unicorn can read it
        if size == 1:
            uc.mem_write(address, bytes([resp & 0xff]))
        elif size == 2:
            uc.mem_write(address, struct.pack("<H", resp & 0xffff))
        elif size == 4:
            uc.mem_write(address, struct.pack("<I", resp))
            
    if len(mmio_log) <= 30 or len(mmio_log) % 10 == 0:
        print(f"[MMIO #{len(mmio_log):3d}] PC=0x{pc:08x} {access_type} addr=0x{address:08x} size={size} val=0x{value:08x}")
        
    if len(mmio_log) >= 200:
        print("Reached 200 MMIO accesses.")
        uc.emu_stop()
    return True

mu.hook_add(unicorn.UC_HOOK_MEM_READ_UNMAPPED | unicorn.UC_HOOK_MEM_WRITE_UNMAPPED, hook_unmapped)

mu.reg_write(arm_const.UC_ARM_REG_PC, 0x80829f2c)
mu.reg_write(arm_const.UC_ARM_REG_SP, 0x881d2690)
mu.reg_write(arm_const.UC_ARM_REG_CPSR, 0x13 | 0xc0)

# Run to scheduler
mu.emu_start(0x80829f2c, 0x80e9c368)
print("Reached scheduler idle loop. Context switching to SystemInitThread...")
mu.mem_write(0x8149ce60, struct.pack("<I", 0x814cad40))

try:
    mu.emu_start(0x80e9c368, 0, count=5_000_000)
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    sp = mu.reg_read(arm_const.UC_ARM_REG_SP)
    print(f"Executed 5M instructions. Final PC=0x{pc:08x}, SP=0x{sp:08x}")
except unicorn.UcError as e:
    pc = mu.reg_read(arm_const.UC_ARM_REG_PC)
    print(f"Stopped: {e} at PC=0x{pc:08x}")

print(f"\nTotal MMIO accesses: {len(mmio_log)}")
if uart_output:
    print("UART Output captured: " + "".join(uart_output))
