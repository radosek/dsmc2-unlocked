import urllib.request
import ssl

ctx = ssl._create_unverified_context()
url = "https://downloads.red.com/firmware/DSMC2Universal/7.4.1/Combo_Build_v7.4.1.zip"
print("Checking URL:", url)
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
    with urllib.request.urlopen(req, context=ctx) as resp:
        print("Status:", resp.status)
        print("Headers:")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
except Exception as e:
    print("Direct error:", e)

# Also check wayback
wb_url = "https://web.archive.org/web/20210101000000id_/https://downloads.red.com/firmware/DSMC2Universal/7.4.1/Combo_Build_v7.4.1.zip"
print("Checking Wayback:", wb_url)
try:
    req = urllib.request.Request(wb_url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
    with urllib.request.urlopen(req, context=ctx) as resp:
        print("Status:", resp.status)
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
except Exception as e:
    print("Wayback error:", e)
