import os
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

print("=== Base 0x80000000 (File offset 0x00) ===")
for insn in md.disasm(data[:0x40], 0x80000000):
    print(f"0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")

entry_va = 0x80829f2c
entry_offset = entry_va - 0x80000000
print(f"\n=== Entry Point 0x{entry_va:08x} (File offset 0x{entry_offset:08x}) ===")
for insn in md.disasm(data[entry_offset:entry_offset + 0x100], entry_va):
    print(f"0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")
