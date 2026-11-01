#!/usr/bin/env python3
"""Decrypt RED DSMC2 camera binary log files (txt/csv format).

Usage:
    python3 decode_red_log.py <input_file> [output_file]

If output_file is omitted, input_file.decoded is used.
"""

import sys
from collections import Counter

RECORD_SIZE = 512

def decode(infile, outfile=None):
    if outfile is None:
        outfile = infile + '.decoded'

    with open(infile, 'rb') as f:
        data = f.read()

    num_records = len(data) // RECORD_SIZE
    if num_records < 2:
        raise SystemExit(
            "file is too small to decode: need at least two %d-byte records, "
            "got %d bytes. The key is recovered statistically, so a real log "
            "(hundreds of records) is required." % (RECORD_SIZE, len(data)))

    k_even = bytearray(RECORD_SIZE)
    for pos in range(RECORD_SIZE):
        vals = [data[r * RECORD_SIZE + pos] for r in range(0, num_records, 2)]
        k_even[pos] = Counter(vals).most_common(1)[0][0] ^ 0x20

    k_odd = bytearray(RECORD_SIZE)
    for pos in range(RECORD_SIZE):
        vals = [data[r * RECORD_SIZE + pos] for r in range(1, num_records, 2)]
        k_odd[pos] = Counter(vals).most_common(1)[0][0] ^ 0x20

    lines = []
    for r in range(num_records):
        key = k_even if r % 2 == 0 else k_odd
        decoded = bytes(data[r * RECORD_SIZE + i] ^ key[i] for i in range(RECORD_SIZE))
        text = ''.join(chr(b) if 32 <= b < 127 else ('' if b == 0 else chr(b)) for b in decoded)
        lines.append(text)

    out = '\n'.join(lines)
    with open(outfile, 'w') as f:
        f.write(out)

    return outfile


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    infile = sys.argv[1]
    outfile = sys.argv[2] if len(sys.argv) > 2 else None

    result = decode(infile, outfile)
    print(f'Decoded: {result}')
