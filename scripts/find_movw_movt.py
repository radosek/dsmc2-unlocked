import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

def find_movw_movt(addr):
    low = addr & 0xffff
    high = (addr >> 16) & 0xffff
    print(f"Searching for movw/movt loading 0x{addr:08x} (low=0x{low:04x}, high=0x{high:04x}):")
    # movw encoding: cond[31:28] 0011 0000 imm4[19:16] rd[15:12] imm12[11:0]
    # imm4 = (low >> 12) & 0xf, imm12 = low & 0xfff
    # movt encoding: cond[31:28] 0011 0100 imm4[19:16] rd[15:12] imm12[11:0]
    # imm4 = (high >> 12) & 0xf, imm12 = high & 0xfff
    low_imm4 = (low >> 12) & 0xf
    low_imm12 = low & 0xfff
    high_imm4 = (high >> 12) & 0xf
    high_imm12 = high & 0xfff

    # Scan 4-byte aligned instructions
    for off in range(0, len(data) - 8, 4):
        w1 = struct.unpack("<I", data[off:off+4])[0]
        # Check if w1 is movw rd, #low
        if (w1 & 0x0ff00000) == 0x03000000:
            imm = ((w1 >> 4) & 0xf000) | (w1 & 0xfff)
            if imm == low:
                rd1 = (w1 >> 12) & 0xf
                # check if w2 is movt rd1, #high
                w2 = struct.unpack("<I", data[off+4:off+8])[0]
                if (w2 & 0x0ff00000) == 0x03400000:
                    imm2 = ((w2 >> 4) & 0xf000) | (w2 & 0xfff)
                    rd2 = (w2 >> 12) & 0xf
                    if imm2 == high and rd1 == rd2:
                        va = 0x80000000 + off
                        print(f"  Found at VA 0x{va:08x} (offset 0x{off:08x}) reg r{rd1}")

find_movw_movt(0x80ebec24)
find_movw_movt(0x80ebec20)
find_movw_movt(0x80ebec21)
find_movw_movt(0x80ebec22)
find_movw_movt(0x80ebec23)
