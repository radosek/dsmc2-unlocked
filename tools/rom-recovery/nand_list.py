#!/usr/bin/env python3
"""List the yaffs2 files of the camera NAND from the SPL dump (spare tags + object-header pages) or from a raw programmer dump.
  nand_list.py PREFIX                      (PREFIX_spare.bin 64 B/page + PREFIX_hdr.bin from nand_dump_rx.py)
  nand_list.py --raw FILE [--stride 2160]  (raw image: 2048 data + spare per page)
Tag layout (verified on the DXL2 dump): spare +4 seq, +20 object id, +36 chunk id, +52 byte count. Header chunk: u32 type@0, u32 parent@4, name@0x0a."""
import sys, struct, collections

PARTS = [(0, 1, "block0"), (1, 45, "/env"), (45, 605, "/image1"), (605, 1165, "/image2"), (1165, 1445, "/data"),
         (1445, 1500, "journal?"), (1500, 1544, "/"), (1808, 2048, "/log"), (2048, 3248, "/rodata"), (3248, 8192, "/pdata")]


def part(page):
    blk = page // 64
    for a, b, n in PARTS:
        if a <= blk < b:
            return n
    return "?"


def load(argv):
    pages = {}   # idx -> (seq, objid, chid, bc)
    hdrs = {}    # idx -> 288 data bytes
    if argv[0] == "--raw":
        path = argv[1]
        stride = int(argv[argv.index("--stride") + 1]) if "--stride" in argv else 2160
        f = open(path, "rb").read()
        for p in range(len(f) // stride):
            b = p * stride
            sp = f[b + 2048:b + 2048 + 64]
            seq, objid, chid, bc = (struct.unpack_from("<I", sp, o)[0] for o in (4, 20, 36, 52))
            if objid in (0, 0xFFFFFFFF):
                continue
            pages[p] = (seq, objid, chid, bc)
            if (chid & 0x80000000) or (chid == 0 and (objid >> 28) != 0):
                hdrs[p] = f[b:b + 288]
        return pages, hdrs
    prefix = argv[0]
    sp = open(prefix + "_spare.bin", "rb").read()
    for p in range(len(sp) // 64):
        s = sp[p * 64:(p + 1) * 64]
        if s == b"\xff" * 64:
            continue
        seq, objid, chid, bc = (struct.unpack_from("<I", s, o)[0] for o in (4, 20, 36, 52))
        if objid in (0, 0xFFFFFFFF):
            continue
        pages[p] = (seq, objid, chid, bc)
    h = open(prefix + "_hdr.bin", "rb").read()
    for i in range(0, len(h) - 291, 292):
        idx = struct.unpack_from("<I", h, i)[0]
        hdrs[idx] = h[i + 4:i + 292]
    return pages, hdrs


pages, hdrs = load(sys.argv[1:])
info = {}   # obj -> (seq, type, parent, name, page)
for p, d in hdrs.items():
    if p not in pages:
        continue
    seq, objid, chid, bc = pages[p]
    obj = (part(p), objid & 0x0FFFFFFF)
    t, par = struct.unpack_from("<II", d, 0)
    raw = d[0x0a:0x0a + 255].split(b"\x00")[0]
    if t not in (1, 2, 3, 4, 5) or par > 0x00FFFFFF or obj[1] > 0x00FFFFFF or seq >= 0xF0000000:
        continue
    if not all(0x20 <= c < 0x7F for c in raw) or (obj[1] != 1 and len(raw) == 0):
        continue
    name = raw.decode("latin1")
    if obj not in info or seq > info[obj][0]:
        info[obj] = (seq, t, par, name, p)
size = collections.defaultdict(dict)   # obj -> chid -> (seq, bytecount)
for p, (seq, objid, chid, bc) in pages.items():
    if p in hdrs or chid & 0x80000000 or chid == 0:
        continue
    obj = (part(p), objid & 0x0FFFFFFF)
    if chid not in size[obj] or seq > size[obj][chid][0]:
        size[obj][chid] = (seq, bc)


def path(obj):
    parts, seen = [], set()
    pt = obj[0]
    while obj in info and obj not in seen and obj[1] != 1:
        seen.add(obj)
        _, _, par, nm, _ = info[obj]
        parts.append(nm)
        obj = (pt, par)
    return "/" + "/".join(reversed(parts))


rows = []
for obj, (seq, t, par, nm, p) in info.items():
    sz = sum(bc for _, bc in size[obj].values())
    rows.append((part(p), path(obj), {1: "file", 3: "dir", 2: "symlink", 4: "hardlink"}.get(t, str(t)), sz))
for r in sorted(rows):
    print(f"{r[0]:9s} {r[2]:8s} {r[3]:>10d}  {r[1]}")
print(f"\n{len(rows)} objects, {len(pages)} tagged pages, {len(hdrs)} header pages")
