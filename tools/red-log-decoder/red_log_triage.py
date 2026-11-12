#!/usr/bin/env python3
"""
RED DSMC / DSMC2 Log Decoder & Executive Triage Tool (Zero Dependencies)

Standalone Python reference tool that mirrors `dsmcdbg log`. Decodes encrypted `.enc`
logs using the hardware XOR pad, detects boot sessions, eliminates bloat lines,
decodes numeric error codes using the reverse-engineered firmware dictionary,
and prints a human-friendly executive triage report.

Usage:
    python red_log_triage.py triage <log.enc or log.txt> [--session N] [--json]
    python red_log_triage.py explain <code_or_query> (e.g. 0x01, 34, 103, LMH0340, fan)
    python red_log_triage.py decode <log.enc> [output.txt]
"""

import sys
import os
import re
import json
from collections import Counter, defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PAD_PATH = os.path.join(SCRIPT_DIR, "log_xor_table.bin")
DICT_PATH = os.path.join(SCRIPT_DIR, "..", "dsmc-core", "src", "error_dict.json")


def load_pad():
    if os.path.exists(PAD_PATH):
        with open(PAD_PATH, "rb") as f:
            return f.read()
    raise FileNotFoundError(f"Missing XOR pad at {PAD_PATH}")


def is_plaintext(data: bytes) -> bool:
    window = data[: min(len(data), 4096)]
    # Look for [digits:digits:digits:digits] timestamp
    if not re.search(rb"\[\d+:\d+:\d+:\d+\]", window):
        return False
    printable = sum(1 for b in window if b in (10, 13, 9) or (0x20 <= b <= 0x7E))
    return printable * 10 >= len(window) * 7


def decode_log(data: bytes) -> str:
    if is_plaintext(data):
        return data.decode("utf-8", errors="replace")
    pad = load_pad()
    pad_len = len(pad)
    decoded = bytes(b ^ pad[i % pad_len] for i, b in enumerate(data))
    return decoded.decode("utf-8", errors="replace")


def load_error_dict():
    if os.path.exists(DICT_PATH):
        with open(DICT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"states": {}, "entries": []}


def normalize_line(line: str) -> str:
    # Strip timestamp [0:00:00:000] and cpu usage ( 1%/1%)
    s = re.sub(r"^\[\d+:\d+:\d+:\d+\]\s*", "", line.strip())
    s = re.sub(r"^\(\s*\d+%\s*/\s*\d+%\)\s*", "", s)
    s = re.sub(r"^[EWID]:\s*", "", s)
    return s.strip()


def split_sessions(text: str):
    # Match boot session split boundaries (header lines or reset vectors)
    lines = text.splitlines()
    sessions = []
    current = []
    for line in lines:
        if "initializing cpu usage" in line.lower() or "BEGIN LOG" in line:
            if current:
                sessions.append(current)
                current = []
        current.append(line)
    if current:
        sessions.append(current)
    return sessions if sessions else [lines]


def cmd_explain(query: str):
    q = query.strip().lower()
    ed = load_error_dict()
    matches = []

    # Check numeric state code
    if q.isdigit():
        code = str(int(q))
        if code in ed.get("states", {}):
            st = ed["states"][code]
            matches.append({
                "id": f"STATE_{code}",
                "title": f"State Machine: {st['name']} (State {code})",
                "subsystem": "System State Machine",
                "severity": "Fatal" if code == "34" else "Info",
                "meaning": st["desc"],
                "action": "Camera entered fatal fault state. Check previous log lines for trigger event." if code == "34" else "Normal operational state machine transition."
            })

    # Check state descriptions
    for code, st in ed.get("states", {}).items():
        if q in st["name"].lower() or q in st["desc"].lower():
            mid = f"STATE_{code}"
            if not any(m["id"] == mid for m in matches):
                matches.append({
                    "id": mid,
                    "title": f"State Machine: {st['name']} (State {code})",
                    "subsystem": "System State Machine",
                    "severity": "Fatal" if code == "34" else "Info",
                    "meaning": st["desc"],
                    "action": "Camera entered fatal fault state. Check previous log lines for trigger event." if code == "34" else "Normal operational state machine transition."
                })

    # Check compiled entries
    for e in ed.get("entries", []):
        try:
            rx_matches = bool(re.search(e["regex"], query, re.IGNORECASE))
        except Exception:
            rx_matches = False

        text_matches = (
            q in e["id"].lower()
            or q in e["title"].lower()
            or q in e["subsystem"].lower()
            or q in e["meaning"].lower()
            or q in e["action"].lower()
            or rx_matches
        )
        if text_matches and not any(m["id"] == e["id"] for m in matches):
            matches.append(e)

    if not matches:
        print(f"No matching error codes or subsystems found for '{query}'.")
        print("Tip: Search by hex code (0x01, 0x1d, 0x20), state number (0..35), or component (sdi, fan, sata, media, sensor, x12, ddr).")
        return 1

    print(f"\nFound {len(matches)} match(es) for '{query}':")
    print("=" * 78)
    for m in matches:
        sev_tag = f"[{m['severity'].upper():<5}]"
        print(f"{sev_tag} {m['title']} — Subsystem: {m['subsystem']}")
        print(f"  Dictionary ID : {m['id']}")
        print(f"  Severity      : {m['severity']}")
        print(f"  Physical Cause: {m['meaning']}")
        print(f"  Action / Fix  : {m['action']}")
        print("-" * 78)
    print()
    return 0


def cmd_triage(path: str, json_mode: bool = False):
    if not os.path.exists(path):
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 2

    with open(path, "rb") as f:
        raw_data = f.read()

    text = decode_log(raw_data)
    sessions = split_sessions(text)
    ed = load_error_dict()

    compiled_entries = []
    for e in ed.get("entries", []):
        try:
            compiled_entries.append((re.compile(e["regex"], re.IGNORECASE), e))
        except Exception:
            pass

    total_lines = 0
    total_errors = 0
    total_warns = 0
    err_counts = defaultdict(lambda: {"entry": None, "count": 0, "sessions": set(), "sample": ""})
    line_counts = Counter()
    session_summaries = []
    has_fatal = False

    for s_idx, sess in enumerate(sessions):
        total_lines += len(sess)
        sess_errors = 0
        reaches_ready = False
        saw_sys_err = False

        for line in sess:
            if ") E: " in line:
                total_errors += 1
                sess_errors += 1
            elif ") W: " in line:
                total_warns += 1

            if "READY_TO_RECORD" in line:
                reaches_ready = True
            if "SYSTEM_ERROR" in line:
                saw_sys_err = True

            # Match dictionary
            matched = False
            for rx, entry in compiled_entries:
                if rx.search(line):
                    eid = entry["id"]
                    err_counts[eid]["entry"] = entry
                    err_counts[eid]["count"] += 1
                    err_counts[eid]["sessions"].add(s_idx)
                    if not err_counts[eid]["sample"]:
                        err_counts[eid]["sample"] = line.strip()
                    matched = True
                    break

            norm = normalize_line(line)
            if norm:
                line_counts[norm] += 1

        passed = reaches_ready and not saw_sys_err
        if not passed:
            has_fatal = True

        session_summaries.append({
            "session": s_idx,
            "lines": len(sess),
            "errors": sess_errors,
            "passed": passed,
            "reaches_ready": reaches_ready
        })

    if json_mode:
        report = {
            "file": os.path.basename(path),
            "healthy": not has_fatal,
            "verdict": "FAIL (Fatal Fault Detected)" if has_fatal else "PASS (Healthy)",
            "total_sessions": len(sessions),
            "total_lines": total_lines,
            "total_errors": total_errors,
            "total_warns": total_warns,
            "detected_faults": [
                {
                    "id": k,
                    "title": v["entry"]["title"],
                    "severity": v["entry"]["severity"],
                    "subsystem": v["entry"]["subsystem"],
                    "count": v["count"],
                    "sessions": list(v["sessions"]),
                    "meaning": v["entry"]["meaning"],
                    "action": v["entry"]["action"],
                    "sample": v["sample"]
                }
                for k, v in err_counts.items() if v["entry"]
            ]
        }
        print(json.dumps(report, indent=2))
        return 1 if has_fatal else 0

    print("\n" + "=" * 80)
    print("                   RED CAMERA LOG TRIAGE EXECUTIVE REPORT                   ")
    print("=" * 80)
    print(f"Target File      : {os.path.basename(path)}")
    verdict = "[FAIL] FATAL HARDWARE OR SYSTEM FAULT DETECTED" if has_fatal else "[PASS] HEALTHY (Reached READY_TO_RECORD)"
    print(f"Overall Verdict  : {verdict}")
    print(f"Sessions Analyzed: {len(sessions):>2}   |   Total Lines: {total_lines:>7}   |   Errors: {total_errors:>4}   |   Warnings: {total_warns:>4}")
    print("-" * 80 + "\n")

    print("1. IDENTIFIED HARDWARE & FIRMWARE FAULTS (Ranked by Severity):")
    print("-" * 80)
    if not err_counts:
        print("  No fatal faults or known error signatures detected.\n")
    else:
        sorted_errs = sorted(err_counts.values(), key=lambda x: x["count"], reverse=True)
        for item in sorted_errs:
            e = item["entry"]
            if not e:
                continue
            sev = f"[{e['severity'].upper():<5}]"
            print(f"  {sev} {e['title']:<38} Count: {item['count']:>3} in {len(item['sessions'])}/{len(sessions)} session(s)")
            print(f"      Subsystem      : {e['subsystem']}")
            print(f"      Physical Cause : {e['meaning']}")
            print(f"      Actionable Fix : {e['action']}")
            print(f"      Sample Log Line: {item['sample']}")
            print()

    print("2. BOOT SESSIONS STATUS:")
    print("-" * 80)
    for s in session_summaries:
        status_tag = "[PASS]" if s["passed"] else "[FAIL]"
        ready_tag = "Reached READY_TO_RECORD" if s["reaches_ready"] else "Did NOT reach ready"
        print(f"  Session #{s['session']:<2} {status_tag}  Lines: {s['lines']:>5}  |  Errors: {s['errors']:>3}  |  {ready_tag}")
    print()

    print("3. TOP TELEMETRY NOISE & BLOAT LINES FILTERED:")
    print("-" * 80)
    top_bloat = [item for item in line_counts.most_common(5) if item[1] >= 2]
    if not top_bloat:
        print("  No repetitive chatter lines detected.")
    else:
        for text_line, count in top_bloat:
            truncated = text_line[:57] + "..." if len(text_line) > 60 else text_line
            print(f"    - {count:>5}x : {truncated}")
    print("=" * 80 + "\n")

    return 1 if has_fatal else 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    cmd = sys.argv[1].lower()

    if cmd == "explain":
        if len(sys.argv) < 3:
            print("Usage: python red_log_triage.py explain <code_or_query>")
            return 2
        return cmd_explain(sys.argv[2])

    elif cmd == "decode":
        if len(sys.argv) < 3:
            print("Usage: python red_log_triage.py decode <file.enc> [out.txt]")
            return 2
        infile = sys.argv[2]
        outfile = sys.argv[3] if len(sys.argv) > 3 else infile + ".decoded"
        with open(infile, "rb") as f:
            data = f.read()
        txt = decode_log(data)
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(txt)
        print(f"Decoded: {outfile}")
        return 0

    elif cmd == "triage":
        if len(sys.argv) < 3:
            print("Usage: python red_log_triage.py triage <file> [--json]")
            return 2
        json_mode = "--json" in sys.argv
        return cmd_triage(sys.argv[2], json_mode=json_mode)

    else:
        # Default: treat first argument as file to triage
        json_mode = "--json" in sys.argv
        return cmd_triage(sys.argv[1], json_mode=json_mode)


if __name__ == "__main__":
    sys.exit(main())
