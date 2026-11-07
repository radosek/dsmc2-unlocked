import struct

fw = open('firmware_store/unpacked/scarlet_w_7_4_1/slot/dsmc_program.mem', 'rb').read()
# Let's find 'LCD7, EDID'
idx = fw.find(b'LCD7, EDID')
print(f"'LCD7, EDID' found at offset 0x{idx:08x} (VA 0x{0x80000000+idx:08x})")

# Let's inspect the 64 bytes before and after
for i in range(-5, 10):
    entry = idx + i * 48
    chunk = fw[entry:entry+48]
    words = struct.unpack('<12I', chunk)
    name = chunk[20:48].split(b'\0')[0].decode('latin1', errors='replace')
    print(f"[{i:+2d}] w0=0x{words[0]:08x} w1=0x{words[1]:08x} w2=0x{words[2]:08x} w3=0x{words[3]:08x} w4=0x{words[4]:08x} name='{name}'")
