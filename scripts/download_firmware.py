import urllib.request
import os
import hashlib
import sys
import ssl

ctx = ssl._create_unverified_context()
url = "https://downloads.red.com/firmware/DSMC2Universal/7.4.1/Combo_Build_v7.4.1.zip"
out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "downloads")
os.makedirs(out_dir, exist_ok=True)
dest_path = os.path.join(out_dir, "Combo_Build_v7.4.1.zip")

expected_sha256 = "248b3501613a8f0bcdc0219b29661036fd79fc89c9b9e372ab0c95500ff074d0"

if os.path.exists(dest_path):
    print("File already exists. Checking SHA-256...")
    h = hashlib.sha256()
    with open(dest_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    digest = h.hexdigest()
    print("SHA-256:", digest)
    if digest == expected_sha256:
        print("Checksum matched!")
        sys.exit(0)
    else:
        print("Checksum mismatch, re-downloading...")

print(f"Downloading from {url} to {dest_path}...")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

with urllib.request.urlopen(req, context=ctx) as resp, open(dest_path, "wb") as f:
    total_size = int(resp.headers.get("Content-Length", 0))
    downloaded = 0
    h = hashlib.sha256()
    last_reported = 0
    while chunk := resp.read(1024 * 512):
        f.write(chunk)
        h.update(chunk)
        downloaded += len(chunk)
        percent = int(downloaded / total_size * 100) if total_size else 0
        if percent - last_reported >= 10:
            print(f"Downloaded {downloaded / 1024 / 1024:.1f} MB / {total_size / 1024 / 1024:.1f} MB ({percent}%)")
            last_reported = percent

digest = h.hexdigest()
print(f"Download complete. SHA-256: {digest}")
if digest == expected_sha256:
    print("Checksum MATCHED expected value!")
else:
    print("Warning: checksum did not match S3 metadata:", expected_sha256)
