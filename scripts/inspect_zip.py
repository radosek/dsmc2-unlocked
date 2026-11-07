import zipfile
import os

zip_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware_store", "downloads", "Combo_Build_v7.4.1.zip")
with zipfile.ZipFile(zip_path, 'r') as z:
    for info in z.infolist():
        print(f"{info.filename:40} {info.file_size:>12} bytes")
