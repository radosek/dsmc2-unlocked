import os
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
md.detail = True

# Disassemble around 0x80ff5454
off = 0x80ff5454 - 0x80000000
print(f"Data at 0x80ff5454: {data[off:off+32].hex()}")
