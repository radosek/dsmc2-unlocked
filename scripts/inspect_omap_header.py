import struct
import os

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "bootloader_0x16.bin")
data = open(path, "rb").read()

# OMAP3 CH header format:
# offset 0x00: Section length (4 bytes)
# offset 0x04: Destination address (4 bytes)
# Look for TOC or CH sections:
print("Header inspection:")
for offset in range(0, 0x100, 4):
    w = struct.unpack("<I", data[offset:offset+4])[0]
    txt = data[offset:offset+4]
    print(f"0x{offset:02x}: 0x{w:08x}  ({txt})")
