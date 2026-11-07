import zipfile
import os
import subprocess
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
zip_path = os.path.join(root_dir, "firmware_store", "downloads", "Combo_Build_v7.4.1.zip")
extracted_dir = os.path.join(root_dir, "firmware_store", "extracted_packages")
os.makedirs(extracted_dir, exist_ok=True)

combo_bin_path = os.path.join(extracted_dir, "combo_7.4.1.bin")

if not os.path.exists(combo_bin_path):
    print("Extracting combo_7.4.1.bin from zip...")
    with zipfile.ZipFile(zip_path, 'r') as z:
        with z.open("Combo_Build_v7.4.1/force_upgrade/combo_7.4.1.bin") as src, open(combo_bin_path, "wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
    print("Extracted to:", combo_bin_path)
else:
    print("combo_7.4.1.bin already extracted.")

unpacker_path = os.path.join(root_dir, "research", "dsmc2-unlocked", "tools", "fw-crypto", "unpack_combo.py")
print("Listing combo contents with unpack_combo.py:")
cmd = [sys.executable, unpacker_path, combo_bin_path, "--list"]
res = subprocess.run(cmd, capture_output=True, text=True)
print("STDOUT:\n", res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)
