import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

for va_target in range(0x80ebec10, 0x80ebec30):
    p = struct.pack("<I", va_target)
    idx = data.find(p)
    if idx != -1:
        print(f"VA 0x{va_target:08x} referenced at offset 0x{idx:08x} (VA 0x{0x80000000+idx:08x})")
