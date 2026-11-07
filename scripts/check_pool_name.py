import os

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

off = 0x80ff8be0 - 0x80000000
print("Pool name:", data[off:off+32].split(b'\0')[0].decode('latin1'))
