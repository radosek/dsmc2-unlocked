import urllib.request
import json
import ssl

ctx = ssl._create_unverified_context()
cdx_url = "https://web.archive.org/cdx/search/cdx?url=downloads.red.com/*&output=json&filter=mimetype:application/zip&limit=100"
print("Querying CDX API for zip files on downloads.red.com...")
try:
    req = urllib.request.Request(cdx_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, context=ctx) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        print("Total results:", len(data) - 1)
        for row in data[1:]:
            print("  ", row[2]) # original URL
except Exception as e:
    print("Error:", e)
