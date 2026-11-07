import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

# "Starter Thread" is around 0x80ebebe0
off = 0x80ebebe0 - 0x80000000
for i in range(32):
    if data[off+i:off+i+7] == b"Starter":
        starter_va = 0x80ebebe0 + i
        print(f"Starter Thread string at VA 0x{starter_va:08x}")
        # Search for movw/movt or pointer
        low = starter_va & 0xffff
        high = (starter_va >> 16) & 0xffff
        print(f"  Looking for low=0x{low:04x}, high=0x{high:04x}")
        for j in range(0, len(data)-8, 4):
            w1 = struct.unpack("<I", data[j:j+4])[0]
            if (w1 & 0x0ff00000) == 0x03000000:
                imm = ((w1 >> 4) & 0xf000) | (w1 & 0xfff)
                if imm == low:
                    w2 = struct.unpack("<I", data[j+4:j+8])[0]
                    if (w2 & 0x0ff00000) == 0x03400000:
                        imm2 = ((w2 >> 4) & 0xf000) | (w2 & 0xfff)
                        if imm2 == high:
                            va = 0x80000000 + j
                            print(f"  Referenced via movw/movt at VA 0x{va:08x} (offset 0x{j:08x})")
        break
