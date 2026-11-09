#!/usr/bin/env python3
"""Receiver for the SPL's TX-only NAND dump. Waits for 'NANDDUMP: switching', tells the RP2040 to go to 500000 baud, then parses frames
  A5 5A idx(3 LE) flags len(2 LE) payload crc16(2 LE, CRC-16/XMODEM over idx..payload)
payload = 64-byte spare [+ 288 data bytes when flags&1 = yaffs object header]; blank pages are not sent. Writes PREFIX_spare.bin (64 B x pages, 0xFF = missing/blank)
and PREFIX_hdr.bin (idx u32 + 288 B per header page). Usage: nand_dump_rx.py PORT PREFIX"""
import sys, time, struct, serial

port, prefix = sys.argv[1], sys.argv[2]
PAGES = 524288
s = serial.Serial(port, 115200, timeout=0.2)
buf = bytearray()
t0 = time.time()
print("waiting for NANDDUMP (power-cycle the camera now)...", flush=True)
while True:
    d = s.read(512)
    if d:
        buf += d
        sys.stdout.write(d.decode(errors="replace")); sys.stdout.flush()
        if b"NANDDUMP: switching" in buf:
            time.sleep(0.2)
            s.write(b"\x1b#B500#\x1b\n")
            break
    if time.time() - t0 > 3600:
        sys.exit("no NANDDUMP message")
buf.clear()
spare = bytearray(b"\xff" * (64 * PAGES))
hdrs = {}
good = bad = 0
t0 = time.time()
started = False


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def save():
    open(prefix + "_spare.bin", "wb").write(spare)
    with open(prefix + "_hdr.bin", "wb") as f:
        for k in sorted(hdrs):
            f.write(struct.pack("<I", k) + hdrs[k])


last = time.time()
while True:
    d = s.read(4096)
    if d:
        buf += d
        last = time.time()
    elif time.time() - last > 60:
        print("\nno data for 60 s; saving and stopping")
        break
    while True:
        i = buf.find(b"\xa5\x5a")
        if i < 0 or len(buf) < i + 8:
            if i < 0 and len(buf) > 2:
                del buf[:-1]
            break
        idx = buf[i + 2] | (buf[i + 3] << 8) | (buf[i + 4] << 16)
        flags = buf[i + 5]
        ln = buf[i + 6] | (buf[i + 7] << 8)
        if idx == 0xFFFFFF and ln == 0:
            print(f"\nend marker. good={good} bad={bad}")
            save()
            sys.exit(0)
        if ln > 352:
            del buf[:i + 2]
            continue
        end = i + 8 + ln + 2
        if len(buf) < end:
            break
        body = bytes(buf[i + 2:i + 8 + ln])
        crc = buf[i + 8 + ln] | (buf[i + 9 + ln] << 8)
        if crc == crc16(body) and idx < PAGES and ln >= 64:
            spare[idx * 64:(idx + 1) * 64] = buf[i + 8:i + 8 + 64]
            if flags & 1 and ln >= 352:
                hdrs[idx] = bytes(buf[i + 8 + 64:i + 8 + 352])
            good += 1
            del buf[:end]
            if good % 5000 == 0:
                print(f"  {good} pages ({time.time() - t0:.0f}s), headers {len(hdrs)}, bad {bad}", flush=True)
                save()
        else:
            bad += 1
            del buf[:i + 2]
save()
print(f"saved. good={good} bad={bad}")
