#!/usr/bin/env python3
"""unpack_combo.py — open RED v3 "combo" packages and v2 standalone packages.

Layout found 2026-11-01:

  v3 combo:  "DSMC" 03 | u32 toclen | 265B sig | 256B OAEP | RC4(TOC)
             TOC: u32 count, then count x { u16 camera_type, u32 file_offset, u32 size }
             At each file_offset: a COMPLETE, PLAINTEXT v2 package ("DSMC" 02 ...).
             Only the TOC is RC4-encrypted; the slices are not. Decrypting them again
             destroys them (that is what made them look "sealed").

  v2 package: sig[256] | OAEP[256] | RC4(header) | sections
             header: 0x25 bytes, then N x 265-byte entries {u8 type, u32 off, u32 len, sig[256]}
             type 2 = manifest, type 3 = bootloader (zlib), type 4 = file pack
             file pack: u8 fstype(0) | u16 count | per file: 264B {u32 clen, u32 ulen, name[256]} + zlib

Usage:
    python3 unpack_combo.py <file.bin> --list
    python3 unpack_combo.py <file.bin> --extract 0x16 --out DIR     # combo: pick a model
    python3 unpack_combo.py <file.bin> --extract --out DIR          # v2: whole package
"""
import argparse
import hashlib
import os
import struct
import zlib

from Crypto.Cipher import ARC4, PKCS1_OAEP
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA

HERE = os.path.dirname(os.path.abspath(__file__))
FW_V2 = os.path.join(HERE, "fw_v2_privkey.der")
FW_V3 = os.path.join(HERE, "fw_v3_privkey.der")


def oaep_key(path, blob):
    return PKCS1_OAEP.new(RSA.import_key(open(path, "rb").read()),
                          hashAlgo=SHA1, label=b"dsmc").decrypt(blob)


def parse_v3(buf):
    assert buf[:4] == b"DSMC" and buf[4] == 3, "not a v3 combo"
    key = oaep_key(FW_V3, buf[265:521])
    toc = ARC4.new(key).decrypt(buf[521:521 + 0x400])
    n = struct.unpack("<I", toc[:4])[0]
    return [struct.unpack("<HII", toc[4 + i * 10:14 + i * 10]) for i in range(n)]


def parse_v2(sl):
    assert sl[:4] == b"DSMC" and sl[4] == 2, "not a v2 package"
    key = oaep_key(FW_V2, sl[265:521])
    h = ARC4.new(key).decrypt(sl[521:521 + 0x1200])
    camtype = struct.unpack("<H", h[2:4])[0]
    secs = []
    for i in range(h[0x24]):
        e = h[0x25 + i * 0x109:0x25 + (i + 1) * 0x109]
        secs.append((e[0],) + struct.unpack("<II", e[1:9]))
    return camtype, key, secs


def read_pack(section):
    assert section[0] == 0, "unsupported fs type %d" % section[0]
    count = struct.unpack("<H", section[1:3])[0]
    pos = 3
    for _ in range(count):
        e = section[pos:pos + 264]
        clen, ulen = struct.unpack("<II", e[:8])
        name = e[8:].split(b"\0")[0].decode("latin1")
        blob = section[pos + 264:pos + 264 + clen]
        pos += 264 + clen
        yield name, ulen, blob


def extract_v2(sl, out):
    camtype, key, secs = parse_v2(sl)
    print("v2 package: camera type 0x%02x, sections %s" % (camtype, secs))
    os.makedirs(out, exist_ok=True)
    for st, so, sl_len in secs:
        if st == 3:
            d = zlib.decompress(ARC4.new(key).decrypt(sl[so:so + sl_len])[8:])
            p = os.path.join(out, "bootloader_0x%02x.bin" % camtype)
            open(p, "wb").write(d)
            print("  bootloader -> %s  %d B  sha256 %s" % (p, len(d), hashlib.sha256(d).hexdigest()[:16]))
        elif st == 4:
            pack = ARC4.new(key).decrypt(sl[so:so + sl_len])
            n = 0
            for name, ulen, blob in read_pack(pack):
                try:
                    data = zlib.decompress(blob)
                except zlib.error:
                    data = blob
                if len(data) != ulen:
                    print("  !! size mismatch %s %d != %d" % (name, len(data), ulen))
                # name comes from an untrusted package: keep the write inside out/slot.
                base = os.path.realpath(os.path.join(out, "slot"))
                dst = os.path.realpath(os.path.join(base, name.lstrip("/")))
                if dst != base and not dst.startswith(base + os.sep):
                    raise ValueError("path traversal in firmware entry: %r" % name)
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                open(dst, "wb").write(data)
                n += 1
            print("  slot: %d files -> %s/slot" % (n, out))
    return camtype


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--extract", nargs="?", const="", help="camera type hex for a combo; omit value for v2")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()

    buf = open(a.image, "rb").read()
    is_v2 = buf[:4] == b"DSMC" and buf[4] == 2
    if a.list or a.extract is None:
        if is_v2:
            camtype, _, secs = parse_v2(buf)
            print("v2 package, camera type 0x%02x" % camtype)
            for t, o, l in secs:
                print("  section type %d off %-10d len %-10d" % (t, o, l))
        else:
            for t, off, sz in parse_v3(buf):
                inner = buf[off:off + 8]
                print("type 0x%02x  off %-10d size %-10d  %s" % (
                    t, off, sz, "v2 pkg" if inner[:4] == b"DSMC" else inner.hex()))
        return

    if is_v2:
        extract_v2(buf, a.out)
        return

    want = int(a.extract, 0) if a.extract else None
    entries = parse_v3(buf)
    if want is None:
        raise SystemExit("combo: pass a camera type, e.g. --extract 0x16")
    hit = [(t, o, s) for t, o, s in entries if t == want]
    if not hit:
        raise SystemExit("camera type 0x%02x not in this combo" % want)
    t, off, sz = hit[0]
    extract_v2(buf[off:off + sz], a.out)


if __name__ == "__main__":
    main()
