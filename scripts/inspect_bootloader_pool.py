import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "bootloader_0x16.bin")
data = open(path, "rb").read()

print("Literal pool constants for bootloader entry:")
for off in range(0x270, 0x2c0, 4):
    w = struct.unpack("<I", data[off:off+4])[0]
    print(f"offset 0x{off:03x}: 0x{w:08x}")
