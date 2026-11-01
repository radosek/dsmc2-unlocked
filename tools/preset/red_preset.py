#!/usr/bin/env python3
"""red_preset.py — build and read RED DSMC2 .preset files. Portable, no RED app.

A .preset is a wxSQLite3 AES-256 encrypted SQLite database. The key is the
universal RED key. This tool reproduces the codec directly, so it runs on any OS
with Python and pycryptodome — no REDKeyMapper, no lldb, no macOS requirement.

Scheme (recovered from a known plaintext/ciphertext pair and verified by round-trip):
  - AES key   = the ASCII key bytes repeated to 32 bytes, used as AES-256 in ECB.
  - page size = 1024 bytes; the last 12 bytes of each page are reserved and hold a
                per-page nonce in the clear (SQLite "reserved bytes" = 12).
  - keystream = AES(counter_block) then each next block = AES(previous keystream
                block); counter_block = u32 page-number (1-based, little-endian)
                followed by the 12 nonce bytes. XORed over the first 1012 bytes.
  - page 1 only: bytes 0x10..0x18 are XORed with the keystream a second time
                (this is the wxSQLite3 header-area fixup).

deps: pip install pycryptodome
usage:
  python3 red_preset.py read  <file.preset>
  python3 red_preset.py make  <out.preset> <version> NAME=VALUE [NAME=VALUE ...]
"""
import ctypes
import ctypes.util
import os
import sqlite3
import sys
import tempfile

from Crypto.Cipher import AES

KEY_ASCII = "ABk530WAcrRbvaoKAjc3qoD9BGAhiotq"   # universal RED preset key
PS = 1024
RV = 12
DL = PS - RV


def _cipher():
    kb = KEY_ASCII.encode()
    key32 = bytes(kb[i % len(kb)] for i in range(32))
    return AES.new(key32, AES.MODE_ECB)


def _keystream(c, page_no, nonce):
    block = bytearray(16)
    block[0:4] = page_no.to_bytes(4, "little")
    block[4:16] = nonce[:12]
    ks = bytearray(c.encrypt(bytes(block)))
    while len(ks) < DL:
        ks += c.encrypt(bytes(ks[-16:]))
    return ks


def decrypt(ct):
    c = _cipher()
    out = bytearray(ct)
    for p in range(len(ct) // PS):
        off = p * PS
        nonce = ct[off + DL:off + PS]           # nonce stored in the clear
        ks = _keystream(c, p + 1, nonce)
        for j in range(DL):
            out[off + j] = ct[off + j] ^ ks[j]
        if p == 0:
            for j in range(0x10, 0x18):
                out[off + j] ^= ks[j]
    return bytes(out)


def encrypt(pt):
    c = _cipher()
    out = bytearray(pt)
    for p in range(len(pt) // PS):
        off = p * PS
        nonce = os.urandom(RV)
        page = bytearray(pt[off:off + PS])
        page[DL:PS] = nonce                     # reserved bytes carry the nonce
        ks = _keystream(c, p + 1, nonce)
        for j in range(DL):
            out[off + j] = page[j] ^ ks[j]
        if p == 0:
            for j in range(0x10, 0x18):
                out[off + j] ^= ks[j]
        out[off + DL:off + PS] = nonce          # store nonce in the clear
    return bytes(out)


def _build_plaintext_db(version, pairs):
    """Make a SQLite DB with page_size=1024 and reserved_bytes=12.

    Python's sqlite3 module cannot set the reserved-bytes count, so this calls
    the system libsqlite3 through ctypes to issue SQLITE_FCNTL_RESERVE_BYTES.
    libsqlite3 ships with every macOS and Linux, and on Windows the sqlite3.dll
    that Python itself bundles is used.
    """
    path = tempfile.mktemp(suffix=".sqlite")
    libname = (ctypes.util.find_library("sqlite3")
               or ctypes.util.find_library("libsqlite3")
               or "libsqlite3.dylib")
    sq = ctypes.CDLL(libname)
    db = ctypes.c_void_p()
    if sq.sqlite3_open(path.encode(), ctypes.byref(db)) != 0:
        raise SystemExit("could not open a temporary SQLite database")

    def ex(s):
        sq.sqlite3_exec(db, s.encode(), None, None, None)

    ex("PRAGMA page_size=1024")
    nbytes = ctypes.c_int(RV)
    SQLITE_FCNTL_RESERVE_BYTES = 38
    sq.sqlite3_file_control(db, b"main", SQLITE_FCNTL_RESERVE_BYTES,
                            ctypes.byref(nbytes))
    ex("CREATE TABLE info(version, delete_after_apply)")
    ex("INSERT INTO info VALUES(%d, 0)" % int(version))
    ex("CREATE TABLE parameters(name UNIQUE, value)")
    for name, value in pairs:
        n = name.replace("'", "''")
        if value.lstrip("-").isdigit():
            v = value
        else:
            v = "'%s'" % value.replace("'", "''")
        ex("INSERT INTO parameters VALUES('%s', %s)" % (n, v))
    ex("VACUUM")
    sq.sqlite3_close(db)

    data = bytearray(open(path, "rb").read())
    os.unlink(path)
    if data[20] != RV:
        raise SystemExit("libsqlite3 did not apply reserved_bytes=12 "
                         "(byte 20 = %d)" % data[20])
    if len(data) % PS:
        data += b"\x00" * (PS - len(data) % PS)
    return bytes(data)


def cmd_read(path):
    pt = decrypt(open(path, "rb").read())
    tmp = tempfile.mktemp(suffix=".sqlite")
    open(tmp, "wb").write(pt)
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute("SELECT name, value FROM parameters").fetchall()
        ver = con.execute("SELECT version FROM info").fetchone()
        con.close()
    finally:
        os.unlink(tmp)
    print("version:", ver[0] if ver else "?")
    for name, value in rows:
        print("%s = %s" % (name, value))


def cmd_make(out, version, pairs):
    parsed = []
    for p in pairs:
        if "=" not in p:
            raise SystemExit("bad pair (need NAME=VALUE): %r" % p)
        n, v = p.split("=", 1)
        parsed.append((n, v))
    pt = _build_plaintext_db(version, parsed)
    open(out, "wb").write(encrypt(pt))
    print("wrote %s (%d bytes)" % (out, os.path.getsize(out)))


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "read":
        cmd_read(a[1])
    elif len(a) >= 3 and a[0] == "make":
        cmd_make(a[1], a[2], a[3:])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
