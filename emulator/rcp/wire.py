"""
Authentic RED Command Protocol v2 (RCP2) Wire Framing & Checksum Codec.

Reimplemented byte-for-byte from RED's C SDK `rcp_parser2` (`rcp_api.c`:
`RCP_buildHeader` / `RCP_addToken` / `RCP_addChecksum` / `RCP_finalizeMessage`,
`_RCP_get_and_parse_packet_ext`) and verified against `dsmc2-sdk/host/rftp-rs/src/rcp.rs`:

  `#[@TARGET]$SOURCE:CMD:PARAM:ARG0:ARG1:...:ARGn:*CK\n`

Rules:
- Start byte `#` (0x23)
- Escaping inside tokens: `# @ $ : * \\` are each prefixed with `\\`
- Every token (param and each arg) is followed by `:`
- Checksum `*CK`: XOR fold of every byte strictly AFTER `#` and strictly BEFORE `*`
  (therefore includes the final trailing `:` after the last token and any `\\` escape bytes),
  rendered as 2 uppercase hex digits
- Terminator `\\n` (0x0A)
- Live DSMC2 bodies sometimes omit `*CK` on replies; `parse_frame` verifies `*CK`
  whenever an unescaped final `*HH` trailer is present, and accepts unchecksummed
  replies cleanly.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


START_BYTE = ord("#")
TARGET_BYTE = ord("@")
SOURCE_BYTE = ord("$")
SEP_BYTE = ord(":")
CKSUM_BYTE = ord("*")
ESCAPE_BYTE = ord("\\")
END_BYTE = ord("\n")

SPECIAL_BYTES = frozenset((START_BYTE, TARGET_BYTE, SOURCE_BYTE, SEP_BYTE, CKSUM_BYTE, ESCAPE_BYTE))

DEFAULT_SOURCE_ID = "API"

# RCP2 command letters (`ghidra/structs/rcp_parser_structs.h` + `rftp-rs/src/rcp.rs`)
CMD_SET = "S"
CMD_GET = "G"
CMD_CURRENT = "C"
CMD_SET_LIST = "T"
CMD_GET_LIST = "H"
CMD_CURRENT_LIST = "D"
CMD_SET_RELATIVE = "U"
CMD_SET_LIST_RELATIVE = "V"
CMD_GET_PERIODIC = "I"
CMD_GET_DEFAULT = "J"
CMD_CURRENT_DEFAULT = "E"
CMD_FAIL = "F"


@dataclass
class Rcp2Packet:
    """Decoded RCP2 wire packet."""

    cmd: str
    param: str
    args: List[str] = field(default_factory=list)
    source: Optional[str] = None
    target: Optional[str] = None
    had_checksum: bool = True


def escape_token(token: bytes) -> bytes:
    """Escape RCP2 special characters (`# @ $ : * \\`) with backslash."""
    out = bytearray()
    for b in token:
        if b in SPECIAL_BYTES:
            out.append(ESCAPE_BYTE)
        out.append(b)
    return bytes(out)


def compute_checksum(body: bytes) -> int:
    """XOR fold across all bytes strictly after `#` and strictly before `*`."""
    ck = 0
    for b in body:
        ck ^= b
    return ck & 0xFF


def _ascii_hex2(a: int, b: int) -> Optional[int]:
    try:
        return int(bytes((a, b)).decode("ascii"), 16)
    except ValueError:
        return None


def build_packet(
    cmd: str,
    param: str,
    args: Sequence[str] = (),
    source: str = DEFAULT_SOURCE_ID,
    target: Optional[str] = None,
    include_checksum: bool = True,
) -> bytes:
    """
    Build one outgoing RCP2 wire frame:
      `#[@TARGET]$SOURCE:CMD:PARAM:[ARG0:...]:*CK\\n`
    """
    if len(cmd) != 1:
        raise ValueError(f"RCP2 cmd must be a single character, got {cmd!r}")

    buf = bytearray()
    buf.append(START_BYTE)
    if target:
        buf.append(TARGET_BYTE)
        buf.extend(escape_token(target.encode("utf-8")))
    buf.append(SOURCE_BYTE)
    buf.extend(escape_token(source.encode("utf-8")))
    buf.append(SEP_BYTE)
    buf.extend(cmd.encode("ascii"))
    buf.append(SEP_BYTE)

    buf.extend(escape_token(param.encode("utf-8")))
    buf.append(SEP_BYTE)
    for a in args:
        buf.extend(escape_token(str(a).encode("utf-8")))
        buf.append(SEP_BYTE)

    if include_checksum:
        ck = compute_checksum(buf[1:])
        buf.append(CKSUM_BYTE)
        buf.extend(f"{ck:02X}".encode("ascii"))

    buf.append(END_BYTE)
    return bytes(buf)


def _split_tokens_with_meta(body: bytes) -> Optional[List[Tuple[bytes, int, bool, bool]]]:
    """
    Split frame body (after `#`) on unescaped `:` separators.
    Returns list of `(unescaped_bytes, raw_start_offset, had_escape, ended_with_sep)`
    or None on invalid trailing bare escape.
    """
    tokens: List[Tuple[bytes, int, bool, bool]] = []
    cur = bytearray()
    tok_start = 0
    had_escape = False
    i = 0
    n = len(body)

    while i < n:
        b = body[i]
        if b == ESCAPE_BYTE:
            i += 1
            if i >= n:
                return None
            had_escape = True
            cur.append(body[i])
        elif b == SEP_BYTE:
            tokens.append((bytes(cur), tok_start, had_escape, True))
            cur.clear()
            tok_start = i + 1
            had_escape = False
        else:
            cur.append(b)
        i += 1

    if cur:
        tokens.append((bytes(cur), tok_start, had_escape, False))
    return tokens


def _parse_addr(tok: bytes) -> Tuple[Optional[str], Optional[str]]:
    target: Optional[str] = None
    source: Optional[str] = None
    rest = tok
    if rest.startswith(b"@"):
        idx = rest.find(b"$")
        if idx != -1:
            target = rest[1:idx].decode("utf-8", errors="replace")
            rest = rest[idx:]
        else:
            target = rest[1:].decode("utf-8", errors="replace")
            rest = b""
    if rest.startswith(b"$"):
        source = rest[1:].decode("utf-8", errors="replace")
    return target, source


def parse_frame(frame: bytes) -> Optional[Rcp2Packet]:
    """
    Parse one raw RCP2 wire frame (leading `#`, optional trailing `\\r\\n`).
    Validates `*CK` checksum when present; returns None on malformed input or bad checksum.
    """
    raw = frame.rstrip(b"\r\n")
    if not raw or raw[0] != START_BYTE:
        return None

    body = raw[1:]
    meta_tokens = _split_tokens_with_meta(body)
    if not meta_tokens:
        return None

    # Check if final token is an unescaped, unterminated `*HH` checksum trailer
    last_data, last_start, last_escaped, last_had_sep = meta_tokens[-1]
    has_cksum = (
        len(meta_tokens) >= 2
        and not last_had_sep
        and not last_escaped
        and len(last_data) == 3
        and last_data[0] == CKSUM_BYTE
        and _ascii_hex2(last_data[1], last_data[2]) is not None
    )

    if has_cksum:
        expected = _ascii_hex2(last_data[1], last_data[2])
        got = compute_checksum(body[:last_start])
        if got != expected:
            return None
        payload_tokens = [t[0] for t in meta_tokens[:-1]]
    else:
        payload_tokens = [t[0] for t in meta_tokens]

    if len(payload_tokens) < 3:
        return None

    target, source = _parse_addr(payload_tokens[0])
    cmd_tok = payload_tokens[1]
    if len(cmd_tok) != 1:
        return None
    cmd = chr(cmd_tok[0])
    param = payload_tokens[2].decode("utf-8", errors="replace")
    args = [t.decode("utf-8", errors="replace") for t in payload_tokens[3:]]

    return Rcp2Packet(
        cmd=cmd,
        param=param,
        args=args,
        source=source,
        target=target,
        had_checksum=has_cksum,
    )


class Rcp2StreamParser:
    """Streaming byte accumulator yielding validated `Rcp2Packet` objects."""

    def __init__(self, max_frame_bytes: int = 8192):
        self.buf = bytearray()
        self.max_frame_bytes = max_frame_bytes

    def feed(self, data: bytes) -> List[Rcp2Packet]:
        out: List[Rcp2Packet] = []
        for b in data:
            if b == START_BYTE:
                # Re-sync on '#' and discard preceding garbage/partial frame
                self.buf.clear()
                self.buf.append(b)
            elif not self.buf:
                continue
            elif b == END_BYTE:
                frame = bytes(self.buf)
                self.buf.clear()
                pkt = parse_frame(frame)
                if pkt is not None:
                    out.append(pkt)
            else:
                if len(self.buf) < self.max_frame_bytes:
                    self.buf.append(b)
                else:
                    # Overflow protection matching FSM -7 overflow guard
                    self.buf.clear()
        return out
