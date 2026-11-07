import os
import struct
import capstone
from collections import Counter, defaultdict

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True

print(f"Scanning 32-bit constants and literal pools in dsmc_program.mem ({len(data)} bytes)...")

# Scan all 32-bit words that look like memory addresses outside DDR (0x80000000 - 0x8fffffff)
address_words = Counter()
for offset in range(0, len(data) - 4, 4):
    w = struct.unpack("<I", data[offset:offset+4])[0]
    # Check if w looks like MMIO address (e.g. 0x40000000..0x7fffffff or 0x90000000..0xffffffff)
    if (0x48000000 <= w <= 0x4fffffff) or (0x68000000 <= w <= 0x6fffffff) or (0x00000000 <= w <= 0x00010000):
        # Round to 4KB page
        page = w & 0xfffff000
        address_words[page] += 1

print("\nTop 4KB MMIO pages referenced in binary data/literal pools:")
for page, count in sorted(address_words.items()):
    if count >= 5:
        print(f"  0x{page:08x}: {count:5d} refs")
