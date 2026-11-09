#!/usr/bin/env python3
"""Emit a C header with block-0 pages [FIRST,LAST) as uint16 LE arrays for the restore image.
Reads your block-0 dump from env: RED_GOLDEN_MAIN (64*2048 B) + RED_GOLDEN_SPARE (64*64 B).
Usage: gen_block0_slice.py FIRST LAST OUT.h"""
import sys, os
first, last, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
main = open(os.environ['RED_GOLDEN_MAIN'], 'rb').read()
spare = open(os.environ['RED_GOLDEN_SPARE'], 'rb').read()
def wl(b): return [b[i] | (b[i+1] << 8) for i in range(0, len(b), 2)]
mw, sw = [], []
for p in range(first, last):
    mw += wl(main[p*2048:(p+1)*2048])
    sw += wl(spare[p*64:(p+1)*64])
with open(out, 'w') as o:
    o.write(f"/* block0 pages {first}..{last-1} */\n")
    o.write(f"#define RED_B0_FIRST {first}\n#define RED_B0_LAST {last}\n")
    o.write(f"static const unsigned short red_b0_main[{len(mw)}] = {{\n")
    for i in range(0, len(mw), 12): o.write(",".join("0x%04x" % w for w in mw[i:i+12]) + ",\n")
    o.write("};\n")
    o.write(f"static const unsigned short red_b0_spare[{len(sw)}] = {{\n")
    for i in range(0, len(sw), 12): o.write(",".join("0x%04x" % w for w in sw[i:i+12]) + ",\n")
    o.write("};\n")
print(f"{out}: pages {first}..{last-1} ({len(mw)*2} B main, {len(sw)*2} B spare)")
