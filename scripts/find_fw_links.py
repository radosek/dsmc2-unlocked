import urllib.request
import re

urls = [
    "https://www.reddigitalcinema.com/downloads",
    "https://support.red.com/hc/en-us/articles/360010998634-DSMC2-Firmware",
]

for url in urls:
    print("Fetching:", url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            print("  Length:", len(content))
            links = set(re.findall(r'href=[\'"]([^\'"]+?(?:zip|bin|downloads)[^\'"]*?)[\'"]', content, re.I))
            for l in sorted(links)[:20]:
                print("    ", l)
    except Exception as e:
        print("  Error:", e)
