#!/usr/bin/env python3
"""Receive RED_RAWREAD frames (2112 B/page, main+spare, on-die ECC OFF). Like nand_dump_rx but full pages.
Frame: A5 5A pg(3 LE) flags len(2 LE)=2112 payload[2112] crc16/xmodem(2 LE over pg..payload).
Sends ESC#B500#ESC to the RP2040 bridge (NOT host baud). Usage: PORT OUTPREFIX"""
import sys, time, serial

def crc16(d):
    c = 0
    for b in d:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xffff if c & 0x8000 else (c << 1) & 0xffff
    return c

port, pref = sys.argv[1], sys.argv[2]
s = serial.Serial(port, 115200, timeout=2)
log = open(pref + "_rx.log", "w")
def L(m):
    print(m, flush=True); log.write(m + "\n"); log.flush()

L("waiting for RAWREAD (cycle camera)...")
buf = bytearray()
t0 = time.time()
while time.time() - t0 < 600:
    d = s.read(512)
    if d:
        buf += d
        if b"RAWREAD: switching" in buf:
            time.sleep(0.2)
            s.write(b"\x1b#B500#\x1b\n")   # tell RP2040 bridge to go 500000
            L(">> sent B500 to RP2040")
            break
else:
    L("no RAWREAD message"); sys.exit(1)
buf = bytearray()
pages = {}
last = time.time()
while time.time() - last < 25:
    d = s.read(8192)
    if not d: continue
    last = time.time(); buf += d
    while True:
        i = buf.find(b"\xa5\x5a")
        if i < 0 or len(buf) - i < 8:
            if i > 0: del buf[:i]
            break
        hdr = bytes(buf[i:i+8])
        pg = hdr[2] | (hdr[3]<<8) | (hdr[4]<<16)
        ln = hdr[6] | (hdr[7]<<8)
        if pg == 0xffffff: L("END marker"); last = 0; break
        if ln != 2112 or len(buf) - i < 8 + ln + 2:
            if ln != 2112: del buf[:i+2]; continue
            break
        payload = bytes(buf[i+8:i+8+ln])
        rc = buf[i+8+ln] | (buf[i+8+ln+1]<<8)
        if crc16(hdr[2:8] + payload) == rc:
            pages[pg] = payload
        del buf[:i+8+ln+2]
    if last == 0: break
if pages:
    mx = max(pages)
    with open(pref + "_raw.bin", "wb") as o:
        for p in range(mx+1):
            o.write(pages.get(p, b"\xff"*2112))
    L(f"got {len(pages)} pages (0..{mx}), wrote {pref}_raw.bin ({(mx+1)*2112} B)")
else:
    L("no pages received")
