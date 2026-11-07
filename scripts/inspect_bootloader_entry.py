import os
import capstone
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "bootloader_0x16.bin")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

print("Words at 0x1f0 - 0x240:")
for offset in range(0x1f0, 0x240, 4):
    w = struct.unpack("<I", data[offset:offset+4])[0]
    print(f"0x{offset:03x}: 0x{w:08x}")

print("\nDisassembly from 0x200:")
for insn in md.disasm(data[0x200:0x280], 0x40200200):
    print(f"0x{insn.address:08x} (offset 0x{insn.address-0x40200000:03x}):  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")
