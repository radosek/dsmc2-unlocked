import os
import hashlib
import struct

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")

size = os.path.getsize(path)
h = hashlib.sha256(open(path, "rb").read()).hexdigest()
print(f"dsmc_program.mem size: {size} bytes")
print(f"dsmc_program.mem sha256: {h}")

with open(path, "rb") as f:
    first_64 = f.read(64)
    print("First 64 bytes (hex):")
    print(first_64.hex())
    words = struct.unpack("<16I", first_64)
    print("\nFirst 16 32-bit LE words:")
    for i, w in enumerate(words):
        print(f"  [{i:2d}] (0x{i*4:02x}): 0x{w:08x}")
