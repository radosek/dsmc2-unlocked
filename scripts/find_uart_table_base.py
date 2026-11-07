import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

for va_target in range(0x80ff5440, 0x80ff5470, 4):
    p = struct.pack("<I", va_target)
    pos = 0
    while True:
        idx = data.find(p, pos)
        if idx == -1:
            break
        va = 0x80000000 + idx
        print(f"Target 0x{va_target:08x} referenced at VA 0x{va:08x}")
        pos = idx + 4
