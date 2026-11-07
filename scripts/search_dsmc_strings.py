import os
import re

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

print(f"Total size: {len(data)} bytes")

# Find occurrences of key strings
targets = [
    b"main",
    b"tx_kernel_enter",
    b"tx_thread_create",
    b"RedUi",
    b"gw3400",
    b"atmel_init_touch",
    b"LCDPanel",
    b"DEBUG_ENABLE_SHELL",
    b"COMM_SERIAL_PORT_PROTOCOL",
    b"dsh>",
    b"NAND File System",
    b"initializing cpu usage",
    b"READY_TO_RECORD",
]

for t in targets:
    pos = 0
    count = 0
    first_offset = -1
    while True:
        idx = data.find(t, pos)
        if idx == -1:
            break
        if count == 0:
            first_offset = idx
        count += 1
        pos = idx + len(t)
    va = 0x80000000 + first_offset if first_offset != -1 else 0
    print(f"{t.decode('latin1', errors='replace'):30} count={count:3d} first_va=0x{va:08x} (offset=0x{first_offset:08x})")
