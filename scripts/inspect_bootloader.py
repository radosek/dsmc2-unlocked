import os
import capstone
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "bootloader_0x16.bin")
data = open(path, "rb").read()
print(f"bootloader length: {len(data)} bytes")
print("First 32 bytes hex:", data[:32].hex())

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
print("\nDisassembly of first 16 instructions assuming base 0x80008000 or 0x40200000 or 0x80000000:")
for insn in md.disasm(data[:64], 0x80000000):
    print(f"0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")

# Search for strings in bootloader
strings = []
cur = []
for b in data:
    if 32 <= b < 127:
        cur.append(chr(b))
    else:
        if len(cur) >= 4:
            strings.append("".join(cur))
        cur = []
print(f"\nFound {len(strings)} strings. Sample strings:")
for s in strings[:30]:
    print("  ", s)
