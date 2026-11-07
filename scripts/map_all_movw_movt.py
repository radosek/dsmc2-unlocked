import os
import struct
import time
from collections import defaultdict

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

print(f"Scanning {len(data)} bytes for ALL movw/movt address loads in a single pass...")
t0 = time.time()

# Map address -> list of VAs
addr_map = defaultdict(list)

# We can unpack all 32-bit integers at once using struct.unpack!
num_words = len(data) // 4
words = struct.unpack(f"<{num_words}I", data[:num_words*4])
print(f"Unpacked {num_words} words in {time.time()-t0:.2f}s")

t1 = time.time()
for i in range(num_words - 1):
    w1 = words[i]
    if (w1 & 0x0ff00000) == 0x03000000: # movw
        w2 = words[i+1]
        if (w2 & 0x0ff00000) == 0x03400000: # movt
            rd1 = (w1 >> 12) & 0xf
            rd2 = (w2 >> 12) & 0xf
            if rd1 == rd2:
                imm1 = ((w1 >> 4) & 0xf000) | (w1 & 0xfff)
                imm2 = ((w2 >> 4) & 0xf000) | (w2 & 0xfff)
                full_val = (imm2 << 16) | imm1
                va = 0x80000000 + (i * 4)
                addr_map[full_val].append(va)

print(f"Scanned in {time.time()-t1:.2f}s. Unique addresses loaded: {len(addr_map)}")

# Print MMIO addresses (0x40000000..0x7fffffff)
print("\n--- Detected MMIO Addresses (0x40000000 - 0x7FFFFFFF) ---")
mmio_addrs = [(a, vas) for a, vas in addr_map.items() if (0x40000000 <= a <= 0x7fffffff)]
for a, vas in sorted(mmio_addrs):
    print(f"  0x{a:08x}: {len(vas):3d} refs (sample: VA 0x{vas[0]:08x})")
