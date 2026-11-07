import os
import subprocess
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
combo_bin_path = os.path.join(root_dir, "firmware_store", "extracted_packages", "combo_7.4.1.bin")
out_dir = os.path.join(root_dir, "firmware_store", "unpacked", "scarlet_w_7_4_1")
os.makedirs(out_dir, exist_ok=True)

unpacker_path = os.path.join(root_dir, "research", "dsmc2-unlocked", "tools", "fw-crypto", "unpack_combo.py")
print("Extracting SCARLET-W (0x16) to:", out_dir)
cmd = [sys.executable, unpacker_path, combo_bin_path, "--extract", "0x16", "--out", out_dir]
res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:\n", res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)
