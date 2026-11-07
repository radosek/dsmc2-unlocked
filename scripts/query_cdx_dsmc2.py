import urllib.request
import json
import ssl

ctx = ssl._create_unverified_context()
cdx_url = "https://web.archive.org/cdx/search/cdx?url=downloads.red.com/firmware/DSMC2*&output=json&limit=500"
print("Querying CDX API for DSMC2 firmware...")
try:
    req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("Total results:", len(data) - 1)
        urls = set()
        for row in data[1:]:
            urls.add(row[2])
        for u in sorted(urls):
            print("  ", u)
except Exception as e:
    print("Error:", e)
