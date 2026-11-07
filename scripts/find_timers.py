import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

timers = [
    (0x48318000, "GPTIMER1"),
    (0x49032000, "GPTIMER2"),
    (0x49034000, "GPTIMER3"),
    (0x49036000, "GPTIMER4"),
    (0x49038000, "GPTIMER5"),
    (0x4903a000, "GPTIMER6"),
    (0x4903c000, "GPTIMER7"),
    (0x4903e000, "GPTIMER8"),
    (0x49040000, "GPTIMER9"),
    (0x48086000, "GPTIMER10"),
    (0x48088000, "GPTIMER11"),
    (0x48304000, "32K_TIMER"),
]

for addr, name in timers:
    low = addr & 0xffff
    high = (addr >> 16) & 0xffff
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
                        print(f"{name:12} (0x{addr:08x}) loaded via movw/movt at VA 0x{va:08x} (offset 0x{j:08x})")
