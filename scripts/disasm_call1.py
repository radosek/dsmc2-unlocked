import os
import capstone

path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem")
data = open(path, "rb").read()

md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

target_va = 0x80ebebc4
target_off = target_va - 0x80000000

print(f"=== Disassembly at 0x{target_va:08x} (offset 0x{target_off:08x}) ===")
for insn in md.disasm(data[target_off:target_off+0x80], target_va):
    print(f"0x{insn.address:08x}:  {insn.bytes.hex():12}  {insn.mnemonic:8} {insn.op_str}")
