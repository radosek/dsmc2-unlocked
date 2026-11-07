import os
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

va = 0x80e9c3dc
off = va - 0x80000000
val = struct.unpack("<I", data[off:off+4])[0]
print(f"Address at 0x{va:08x}: 0x{val:08x} (This is _tx_thread_execute_ptr!)")

va2 = 0x80e9c378 + 8 + 0x5c
off2 = va2 - 0x80000000
val2 = struct.unpack("<I", data[off2:off2+4])[0]
print(f"Address at 0x{va2:08x}: 0x{val2:08x} (This is _tx_thread_current_ptr!)")
