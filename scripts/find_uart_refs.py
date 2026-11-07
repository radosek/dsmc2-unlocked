import os
import struct
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

table_va = 0x80ff5460
table_pattern = struct.pack("<I", table_va)

pos = 0
refs = []
while True:
    idx = data.find(table_pattern, pos)
    if idx == -1:
        break
    refs.append(idx)
    pos = idx + 4

print(f"References to UART table 0x{table_va:08x}:")
for r in refs:
    va = 0x80000000 + r
    print(f"  At VA 0x{va:08x} (offset 0x{r:08x})")

# Also check who references the string at 0x80ff5470 "Unable to allocate..."
str_va = 0x80ff5470
str_pattern = struct.pack("<I", str_va)
pos = 0
while True:
    idx = data.find(str_pattern, pos)
    if idx == -1:
        break
    va = 0x80000000 + idx
    print(f"  String at 0x{str_va:08x} referenced at VA 0x{va:08x}")
    pos = idx + 4
