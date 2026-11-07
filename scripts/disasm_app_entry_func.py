import os
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

start_va = 0x80008060
start_off = start_va - 0x80000000

print(f"=== Disassembly at 0x{start_va:08x} ===")
for insn in md.disasm(data[start_off:start_off+0x100], start_va):
    print(f"0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")
