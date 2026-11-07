import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

def dump_words(va, count):
    off = va - 0x80000000
    print(f"=== Dump at VA 0x{va:08x} (offset 0x{off:08x}) ===")
    for i in range(count):
        w = struct.unpack("<I", data[off+i*4:off+(i+1)*4])[0]
        print(f"  +0x{i*4:02x} (0x{va+i*4:08x}): 0x{w:08x}")

dump_words(0x80ff5450, 12)
dump_words(0x810c68d0, 12)
