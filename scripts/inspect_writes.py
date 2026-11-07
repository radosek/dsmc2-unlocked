import os

# Let's inspect the writes from test_pll_smart.py
# We can print unique write targets
from test_pll_smart import mmio_writes

print(f"Total MMIO writes: {len(mmio_writes)}")
unique_writes = {}
for pc, addr, size, val in mmio_writes:
    if addr not in unique_writes:
        unique_writes[addr] = (pc, size, val, 1)
    else:
        old_pc, old_sz, old_val, cnt = unique_writes[addr]
        unique_writes[addr] = (pc, size, val, cnt + 1)

for addr, (pc, size, val, count) in sorted(unique_writes.items()):
    print(f"  0x{addr:08x}: count={count:4d} (last write PC=0x{pc:08x} val=0x{val:08x})")
