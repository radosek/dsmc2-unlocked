import os
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

va = 0x807026a0
off = va - 0x80000000

print(f"=== Disassembly at 0x{va:08x} ===")
for insn in md.disasm(data[off:off+0x60], va):
    marker = "  >>> " if insn.address == 0x807026d0 else "      "
    print(f"{marker}0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")
