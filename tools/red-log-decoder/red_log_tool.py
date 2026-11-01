#!/usr/bin/env python3
"""
RED DSMC2 log parser / triage tool.

The raw decoder (decode_red_log.py) emits ONE line per 512-byte record, so a
single log message that crosses a record boundary gets a fake newline jammed
into it. The decoded file is also a circular dump containing many separate boot
sessions back-to-back, each of which resets its uptime clock to 0:00:00.

This tool cleans both problems and triages the result:

  1. REJOIN   - merge wrap artifacts back into whole log lines
  2. SPLIT    - cut the dump into individual boot sessions
  3. DENOISE  - drop high-volume routine chatter from the digest
  4. TRIAGE   - per session, report milestones reached + errors hit
  5. DIFF     - compare a working log against a broken one

Usage:
    python3 red_log_tool.py analyze <decoded.txt> [-o OUTDIR]   # do everything
    python3 red_log_tool.py sessions <decoded.txt>              # list sessions only
    python3 red_log_tool.py clean <decoded.txt> [-o file]       # rejoined, full
    python3 red_log_tool.py digest <decoded.txt> [--session N]  # denoised digest
    python3 red_log_tool.py diff <good.txt> <bad.txt>           # compare two logs

Notes:
  * The camera RTC is frequently wrong (logs show 2025 dates on a 2026 capture),
    so in-log wall-clock is shown but NOT trusted for ordering. Sessions are
    ordered as they appear in the dump; within a session, uptime is monotonic.
"""

import sys
import os
import re
import argparse
from collections import Counter, defaultdict

# A real log line begins with [D:HH:MM:SS:ms] (the leading bracket may be lost
# to a wrap, so we also accept a continuation that *starts* a timestamp).
TS_RE = re.compile(r'^\[(\d+):(\d+):(\d+):(\d+)\]')
# Severity marker:  ") E: "  ") W: "  ") I: "  or plain ") : "
SEV_RE = re.compile(r'\)\s*([EWI])?\s*:')
WALLCLOCK_RE = re.compile(r'(\d{1,2}:\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})')

# A bare row of '=' (no timestamp) is a boot-session delimiter. The token
# "BEGIN LOG" also precedes a fresh boot.
BOOT_MARKER_RE = re.compile(r'^\s*={5,}\s*$')

# ---------------------------------------------------------------------------
# Noise patterns: high-volume routine chatter excluded from the DIGEST only.
# (The full cleaned file always keeps everything.)
# ---------------------------------------------------------------------------
NOISE_PATTERNS = [
    re.compile(p) for p in [
        r'KEY_MAPPING_\d+ ',
        r'^A{8,}$',                       # AAAA... padding garbage
        r"Notification: 0x[0-9a-fA-F]+ '' 'LCD (Top|Bottom): Br",
        r'cal state machine state:',
        r'm_uiBlackLevel',
        r'input black level =',
        r'black level \d+, delta t',
        r'sensor_dac\.',
        r'Updating preset: Motion',
        r'Updated default key action',
        r'i2c_read i2c\.c',
        r'i2c_write i2c\.c',
        r'i2c_read_single .*timeout',
        r'i2c_probe .*device not found',
        r'ucd\d+_reg_write',
        r'mon\[\d+\]',
        r'EDID attempt \d+ for port',
        r'ISP\d+ clk_rslt for lane',
        r'Byte Pool|Block Pool|Water Mark',
        r'redpine_if: packet read failed',
        r'Power (In|Out)',
        r'module cap \d+ detected',
        r'Int_time = ',
        r'Bad pixel:|Total bad pixel|CalmapInterpolate',
        r'build_calfile_list',
        r'load display preset',
    ]
]

# ---------------------------------------------------------------------------
# Milestones & failure signatures we care about for triage.
# label -> regex.  Order matters for the "furthest reached" readout.
# ---------------------------------------------------------------------------
STATE_MILESTONES = [
    ('BOOT',              re.compile(r'initializing cpu usage')),
    ('NAND_FS',           re.compile(r'NAND File System|yaffs')),
    ('PLL_LOCK',          re.compile(r'PLL.*lock|pll.*lock', re.I)),
    ('LSB_INIT',          re.compile(r'\bLSB\b.*init|lsb.*init', re.I)),
    ('XAUI_UP',           re.compile(r'XAUI.*(up|sync|ok)', re.I)),
    ('PREVIEW_START',     re.compile(r'PREVIEW_START')),
    ('READY_TO_RECORD',   re.compile(r'READY_TO_RECORD')),
    ('RECORD_ACTIVE',     re.compile(r'RECORD_ACTIVE')),
    ('PLAYBACK_ACTIVE',   re.compile(r'PLAYBACK_ACTIVE')),
]

FAILURE_SIGNATURES = [
    ('X12_MISALIGN',   re.compile(r'X12.*misalign', re.I)),
    ('XAUI_DMA_FAIL',  re.compile(r'xdma.*(retr|fail)', re.I)),
    ('RETRY_EXHAUST',  re.compile(r'Failure after \d+ retries', re.I)),
    ('C2C_PCS_LOST',   re.compile(r'XAUI_PCS_STATUS', re.I)),
    ('GUARD_BIT_FAIL', re.compile(r'isp_encode_extra_guard_bit_enable.*fail', re.I)),
    ('XSYS_FAIL',      re.compile(r'xsys_setup.*fail', re.I)),
    ('SYSTEM_ERROR',   re.compile(r'SYSTEM_ERROR')),
    ('SHUTDOWN',       re.compile(r'SHUTDOWN|Camera Shutdown')),
    ('ERROR_CODE',     re.compile(r'\bError:?\s*0x[0-9a-fA-F]+')),
]

# Interesting hardware/firmware identity lines worth pulling out per session.
IDENTITY_RE = re.compile(
    r'(ISP.*[Rr]ev|IOB.*[Rr]ev|firmware|build|RCP API|sensor\s*[: ]|serial)', re.I)


# A timestamp can appear anywhere a real log line begins, even mid-record.
TS_ANYWHERE_RE = re.compile(r'(?=\[\d+:\d+:\d+:\d+\])')


def rejoin_and_split(path):
    """Return list of sessions; each session is a list of whole log lines.

    The decoder inserts newlines at 512-byte record boundaries, which do NOT
    align to log-message boundaries. A single record line therefore often holds
    the tail of one message plus the head of the next. We fix this per session
    by concatenating all raw text and re-splitting on the timestamp pattern
    wherever it occurs.
    """
    with open(path, 'r', errors='replace') as f:
        raw = f.read().split('\n')

    raw_sessions = []
    current = []

    def new_session():
        nonlocal current
        if any(l.strip() for l in current):
            raw_sessions.append(current)
        current = []

    for line in raw:
        stripped = line.strip()
        if BOOT_MARKER_RE.match(line) or stripped == 'BEGIN LOG' \
                or line.startswith('DSMC Log File version'):
            new_session()
            continue
        current.append(line)
    new_session()

    sessions = []
    for chunk in raw_sessions:
        # Glue with '' so wrap artifacts vanish, then re-split on timestamps.
        blob = ''.join(chunk)
        parts = TS_ANYWHERE_RE.split(blob)
        lines = []
        for part in parts:
            part = part.rstrip('\r\n')
            if part.strip():
                lines.append(part)
        if lines:
            sessions.append(lines)
    return sessions


def session_meta(lines):
    """Extract triage metadata from one session's whole lines."""
    wall = None
    max_uptime = (0, 0, 0, 0)
    errors = warns = 0
    milestones = []
    failures = Counter()
    identity = []
    error_codes = Counter()

    for ln in lines:
        m = TS_RE.match(ln)
        if m:
            t = tuple(int(x) for x in m.groups())
            if t > max_uptime:
                max_uptime = t
        sev = SEV_RE.search(ln)
        if sev and sev.group(1) == 'E':
            errors += 1
        elif sev and sev.group(1) == 'W':
            warns += 1
        if wall is None:
            wm = WALLCLOCK_RE.search(ln)
            if wm:
                wall = f'{wm.group(2)} {wm.group(1)}'
        for label, rx in STATE_MILESTONES:
            if rx.search(ln) and label not in milestones:
                milestones.append(label)
        for label, rx in FAILURE_SIGNATURES:
            if rx.search(ln):
                failures[label] += 1
                if label == 'ERROR_CODE':
                    cm = re.search(r'0x[0-9a-fA-F]+', ln)
                    if cm:
                        error_codes[cm.group(0)] += 1
        if IDENTITY_RE.search(ln) and len(identity) < 12:
            identity.append(ln.strip())

    d, h, mn, s = max_uptime
    dur = f'{d}d {h:02d}:{mn:02d}:{s:02d}'
    return {
        'lines': len(lines),
        'wallclock': wall,
        'duration': dur,
        'errors': errors,
        'warns': warns,
        'milestones': milestones,
        'failures': dict(failures),
        'error_codes': dict(error_codes),
        'identity': identity,
    }


def furthest_state(milestones):
    order = [m[0] for m in STATE_MILESTONES]
    best = None
    for m in milestones:
        if m in order:
            if best is None or order.index(m) > order.index(best):
                best = m
    return best or '(none)'


def is_noise(line):
    body = SEV_RE.split(line, maxsplit=1)
    text = body[-1].strip() if body else line
    for rx in NOISE_PATTERNS:
        if rx.search(line) or rx.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_sessions(args):
    sessions = rejoin_and_split(args.input)
    print(f'{len(sessions)} boot session(s) found in {os.path.basename(args.input)}\n')
    hdr = f'{"#":>3}  {"lines":>6}  {"dur":>12}  {"err":>5}  {"furthest state":<16}  failures'
    print(hdr)
    print('-' * len(hdr))
    for i, s in enumerate(sessions):
        m = session_meta(s)
        fail = ','.join(sorted(m['failures'])) or '-'
        print(f'{i:>3}  {m["lines"]:>6}  {m["duration"]:>12}  {m["errors"]:>5}  '
              f'{furthest_state(m["milestones"]):<16}  {fail}')
    return sessions


def cmd_clean(args):
    sessions = rejoin_and_split(args.input)
    out = args.output or (os.path.splitext(args.input)[0] + '-clean.txt')
    with open(out, 'w') as f:
        for i, s in enumerate(sessions):
            f.write(f'\n========== SESSION {i} ==========\n')
            for ln in s:
                f.write(ln + '\n')
    print(f'Wrote {len(sessions)} sessions, rejoined, to {out}')


def cmd_digest(args):
    sessions = rejoin_and_split(args.input)
    targets = [args.session] if args.session is not None else range(len(sessions))
    for i in targets:
        s = sessions[i]
        m = session_meta(s)
        print(f'\n===== SESSION {i}  (lines={m["lines"]}, dur={m["duration"]}, '
              f'err={m["errors"]}, wall={m["wallclock"]}) =====')
        print(f'  furthest state : {furthest_state(m["milestones"])}')
        print(f'  milestones     : {" > ".join(m["milestones"]) or "(none)"}')
        if m['failures']:
            print(f'  failures       : {m["failures"]}')
        if m['error_codes']:
            print(f'  error codes    : {m["error_codes"]}')
        if m['identity']:
            print('  identity:')
            for line in m['identity'][:8]:
                print(f'    {line}')
        print('  --- denoised event lines ---')
        for ln in s:
            if is_noise(ln):
                continue
            sev = SEV_RE.search(ln)
            interesting = (sev and sev.group(1) in ('E', 'W')) or \
                any(rx.search(ln) for _, rx in FAILURE_SIGNATURES) or \
                any(rx.search(ln) for _, rx in STATE_MILESTONES)
            if interesting:
                print(f'    {ln.strip()}')


def cmd_analyze(args):
    sessions = rejoin_and_split(args.input)
    outdir = args.output or (os.path.splitext(args.input)[0] + '-parsed')
    os.makedirs(outdir, exist_ok=True)

    # per-session clean files
    sess_dir = os.path.join(outdir, 'sessions')
    os.makedirs(sess_dir, exist_ok=True)
    index_lines = []
    for i, s in enumerate(sessions):
        m = session_meta(s)
        with open(os.path.join(sess_dir, f'session_{i:02d}.txt'), 'w') as f:
            f.write('\n'.join(s))
        fail = ','.join(sorted(m['failures'])) or '-'
        index_lines.append(
            f'{i:>3}  lines={m["lines"]:>6}  dur={m["duration"]:>12}  '
            f'err={m["errors"]:>5}  state={furthest_state(m["milestones"]):<16}  '
            f'fail={fail}  wall={m["wallclock"]}')

    # summary report
    report = os.path.join(outdir, 'SUMMARY.txt')
    with open(report, 'w') as f:
        f.write(f'RED log analysis: {os.path.basename(args.input)}\n')
        f.write(f'{len(sessions)} boot sessions\n')
        f.write('(camera RTC unreliable - wall-clock shown but not trusted)\n\n')
        f.write('\n'.join(index_lines) + '\n')
    print('\n'.join(index_lines))
    print(f'\nWrote per-session files to {sess_dir}/')
    print(f'Wrote summary to {report}')


def cmd_health(args):
    """Quick PASS/FAIL on the IOB/FPGA<->ISP link for each boot session.

    Designed for after-repair checks: point it at a fresh log and it tells you
    whether the ISP XAUI link came up, without reading anything by hand.
    """
    sessions = rejoin_and_split(args.input)
    pcs_re = re.compile(r'ISP[12]_XAUI_PCS_STATUS\(0x[0-9a-f]+\)\s*=\s*0x([0-9a-f]+)', re.I)
    rev_re = re.compile(r'ISP Revision (\d+)')
    cmdfail_re = re.compile(r'failed to send XCOMMAND|xsys_isp_stats_setup failed')
    mism_re = re.compile(r'(\w+) board info does not match')
    prbs_re = re.compile(r'X12: ISP[12] PRBS test passed')

    print(f'ISP-link health: {os.path.basename(args.input)}  ({len(sessions)} sessions)\n')
    any_pass = False
    for i, s in enumerate(sessions):
        pcs_bad = pcs_re_cnt = 0
        revs = set()
        cmdfails = 0
        mism = set()
        prbs_ok = 0
        m = session_meta(s)
        for ln in s:
            for mt in pcs_re.finditer(ln):
                pcs_re_cnt += 1
                if mt.group(1) == 'f':
                    pcs_bad += 1
            rm = rev_re.search(ln)
            if rm:
                revs.add(int(rm.group(1)))
            if cmdfail_re.search(ln):
                cmdfails += 1
            mm = mism_re.search(ln)
            if mm:
                mism.add(mm.group(1))
            if prbs_re.search(ln):
                prbs_ok += 1
        reached = furthest_state(m['milestones'])
        order = [x[0] for x in STATE_MILESTONES]
        link_ok = (pcs_bad == 0 and cmdfails == 0
                   and order.index(reached) >= order.index('READY_TO_RECORD'))
        rev_str = ('0 (CANNOT READ ISP)' if revs == {0}
                   else (','.join(map(str, sorted(revs))) or 'n/a'))
        verdict = 'PASS' if link_ok else 'FAIL'
        any_pass = any_pass or link_ok
        if reached in ('NAND_FS', 'BOOT'):
            verdict = 'incomplete-boot'
        print(f'  session {i:>2}: {verdict:<16} reached={reached:<16} '
              f'XAUI_PCS=0xf x{pcs_bad}  ISPrev={rev_str}  '
              f'XCMDfail x{cmdfails}  X12-PRBS-ok x{prbs_ok}'
              + (f'  MISMATCH:{",".join(sorted(mism))}' if mism else ''))
    print(f'\nOVERALL: {"at least one boot brought the ISP link up - PROGRESS" if any_pass else "ISP link never came up - no change"}')


def cmd_diff(args):
    good = rejoin_and_split(args.good)
    bad = rejoin_and_split(args.bad)

    def best_session(sessions):
        # pick the session that reached the furthest state / most lines
        order = [m[0] for m in STATE_MILESTONES]
        best_i, best_key = 0, (-1, -1)
        for i, s in enumerate(sessions):
            m = session_meta(s)
            fs = furthest_state(m['milestones'])
            key = (order.index(fs) if fs in order else -1, m['lines'])
            if key > best_key:
                best_key, best_i = key, i
        return best_i, sessions[best_i]

    gi, gs = best_session(good)
    bi, bs = best_session(bad)
    gm, bm = session_meta(gs), session_meta(bs)

    print(f'GOOD: {os.path.basename(args.good)} session {gi}')
    print(f'BAD : {os.path.basename(args.bad)} session {bi}\n')
    order = [m[0] for m in STATE_MILESTONES]
    print(f'{"milestone":<18}{"GOOD":>6}{"BAD":>6}')
    for label in order:
        print(f'{label:<18}{("yes" if label in gm["milestones"] else "-"):>6}'
              f'{("yes" if label in bm["milestones"] else "-"):>6}')
    print(f'\nfurthest GOOD: {furthest_state(gm["milestones"])}')
    print(f'furthest BAD : {furthest_state(bm["milestones"])}')
    print(f'\nGOOD failures: {gm["failures"]}')
    print(f'BAD  failures: {bm["failures"]}')
    print(f'GOOD error codes: {gm["error_codes"]}')
    print(f'BAD  error codes: {bm["error_codes"]}')


def main():
    p = argparse.ArgumentParser(description='RED DSMC2 log parser / triage tool')
    sub = p.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('analyze', help='split + clean + summary report (default workflow)')
    a.add_argument('input'); a.add_argument('-o', '--output')
    a.set_defaults(func=cmd_analyze)

    s = sub.add_parser('sessions', help='list boot sessions with triage one-liners')
    s.add_argument('input')
    s.set_defaults(func=cmd_sessions)

    c = sub.add_parser('clean', help='rejoin wrap artifacts, one file, sessions marked')
    c.add_argument('input'); c.add_argument('-o', '--output')
    c.set_defaults(func=cmd_clean)

    d = sub.add_parser('digest', help='denoised event digest per session')
    d.add_argument('input'); d.add_argument('--session', type=int)
    d.set_defaults(func=cmd_digest)

    h = sub.add_parser('health', help='PASS/FAIL on the ISP XAUI link per boot (after-repair check)')
    h.add_argument('input')
    h.set_defaults(func=cmd_health)

    f = sub.add_parser('diff', help='compare working vs broken log')
    f.add_argument('good'); f.add_argument('bad')
    f.set_defaults(func=cmd_diff)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
