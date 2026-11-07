import os
import capstone
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "bootloader_0x16.bin")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

# In OMAP3, boot header has length field.
# Let's inspect words around 0x100 - 0x300
for offset in range(0x100, 0x300, 0x10):
    chunk = data[offset:offset+16]
    insns = list(md.disasm(chunk, 0x40200000 + offset))
    if len(insns) == 4 and all(i.mnemonic not in ('andeq', 'undefined') for i in insns):
        print(f"Possible code at offset 0x{offset:x}:")
        for i in insns:
            print(f"  0x{i.address:08x}: {i.mnemonic} {i.op_str}")
        break
else:
    # scan whole file for first non-zero code
    for offset in range(0, 0x1000, 4):
        insns = list(md.disasm(data[offset:offset+16], 0x40200000 + offset))
        if len(insns) == 4 and not any(i.mnemonic == 'andeq' for i in insns):
            print(f"Code found at offset 0x{offset:x}:")
            for i in insns:
                print(f"  0x{i.address:08x}: {i.mnemonic} {i.op_str}")
            break
