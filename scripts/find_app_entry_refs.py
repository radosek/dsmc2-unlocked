import os
import struct
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

str_va = 0x80ebec24 # "ApplicationEntry"
p = struct.pack("<I", str_va)

pos = 0
while True:
    idx = data.find(p, pos)
    if idx == -1:
        break
    va = 0x80000000 + idx
    print(f"String 0x{str_va:08x} referenced at VA 0x{va:08x} (offset 0x{idx:08x})")
    pos = idx + 4
