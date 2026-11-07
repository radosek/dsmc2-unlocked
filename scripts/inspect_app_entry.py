import os

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

off = 0x80ebebc0 - 0x80000000
for i in range(20):
    chunk = data[off+i*32:off+(i+1)*32]
    printable = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print(f"0x{0x80ebebc0+i*32:08x}: {printable}")
