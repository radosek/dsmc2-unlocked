"""
Tests for Authentic RED Command Protocol v2 (RCP2) Wire Framing, Checksum Codec,
Stream Reassembly, DIY Serial-2 Handshake, and Live RcpServer TCP Dispatch.
"""

import socket

from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.server import RcpServer
from emulator.rcp.wire import (
    CMD_CURRENT,
    CMD_CURRENT_DEFAULT,
    CMD_CURRENT_LIST,
    CMD_GET,
    CMD_GET_DEFAULT,
    CMD_GET_LIST,
    CMD_SET,
    CMD_SET_RELATIVE,
    Rcp2StreamParser,
    build_packet,
    compute_checksum,
    parse_frame,
)


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_c_sdk_golden_vector_and_uppercase_hex():
    pkt = build_packet("S", "RFTPDATA", ["myuuid==", "0", "Zm9vYmFy"], source="API")
    assert pkt == b"#$API:S:RFTPDATA:myuuid==:0:Zm9vYmFy:*75\n"

    # Explicit lowercase vs uppercase checksum verification
    parsed = parse_frame(pkt)
    assert parsed is not None
    assert parsed.source == "API"
    assert parsed.cmd == "S"
    assert parsed.param == "RFTPDATA"
    assert parsed.args == ["myuuid==", "0", "Zm9vYmFy"]
    assert parsed.had_checksum is True


def test_escaping_specials_and_escaped_asterisk_arg_not_checksum():
    special = r"val#@$:*\end"
    frame = build_packet(CMD_SET, "TEST_PARAM", [special], source="HOST", target="CAM")

    # Must escape special chars inside token
    assert br"\#\@\$\:\*\\end" in frame
    # Must end with *CK\n uppercase hex
    ck_str = frame.rstrip(b"\n").split(b"*")[-1].decode("ascii")
    assert len(ck_str) == 2 and ck_str == ck_str.upper()

    pkt = parse_frame(frame)
    assert pkt is not None
    assert pkt.target == "CAM"
    assert pkt.source == "HOST"
    assert pkt.args == [special]

    # Arg literally equal to "*AA" is escaped as "\*AA" -> NOT mistaken for checksum trailer!
    uncksum_special = build_packet(
        CMD_CURRENT, "CAMERA_PIN", ["*AA"], source="CAM", target="API", include_checksum=False
    )
    assert br"\*AA:" in uncksum_special
    pkt2 = parse_frame(uncksum_special)
    assert pkt2 is not None
    assert pkt2.had_checksum is False
    assert pkt2.args == ["*AA"]


def test_optional_checksum_and_bad_checksum_drop():
    # Live DSMC2 reply quirk: valid unchecksummed frame is accepted
    no_ck = build_packet(CMD_CURRENT, "ISO", ["800"], source="CAM", target="API", include_checksum=False)
    pkt = parse_frame(no_ck)
    assert pkt is not None
    assert pkt.had_checksum is False
    assert pkt.cmd == CMD_CURRENT
    assert pkt.param == "ISO"
    assert pkt.args == ["800"]

    # Bad checksum must be dropped (return None)
    good = build_packet(CMD_GET, "ISO", source="API")
    bad = good[:-3] + b"FF\n"
    assert parse_frame(bad) is None


def test_stream_parser_chunked_reassembly_and_garbage_resync():
    p1 = build_packet(CMD_GET, "ISO", source="API")
    p2 = build_packet(CMD_SET, "FPS", ["24.000"], source="API")
    p_bad = b"#$API:G:ISO:*FF\n"
    stream = b"JUNK_BYTES\r\n" + p_bad + b"NOISE" + p1 + p2

    parser = Rcp2StreamParser()
    packets = []
    # Feed in uneven small chunks
    for i in range(0, len(stream), 5):
        packets.extend(parser.feed(stream[i : i + 5]))

    assert len(packets) == 2
    assert (packets[0].cmd, packets[0].param) == (CMD_GET, "ISO")
    assert (packets[1].cmd, packets[1].param, packets[1].args) == (CMD_SET, "FPS", ["24.000"])


def test_live_rcp_server_rcp2_and_legacy_backward_compat():
    proto = RcpProtocol()
    port = _free_tcp_port()
    server = RcpServer(proto, host="127.0.0.1", port=port)
    server.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3.0) as sock:
            sock.settimeout(3.0)
            f = sock.makefile("rb")
            banner = f.readline()
            assert banner.startswith(b"RED DSMC2 ONLINE")

            def rpc(raw: bytes):
                sock.sendall(raw)
                line = f.readline()
                pkt = parse_frame(line)
                assert pkt is not None, f"Invalid RCP2 reply line: {line!r}"
                assert pkt.had_checksum is True
                assert pkt.source == "CAM"
                assert pkt.target == "API"
                return pkt

            # GET -> C
            r = rpc(build_packet(CMD_GET, "ISO", source="API"))
            assert (r.cmd, r.param, r.args) == (CMD_CURRENT, "ISO", ["800"])

            # SET -> C
            r = rpc(build_packet(CMD_SET, "REDCODE", ["10:1"], source="API"))
            assert (r.cmd, r.param, r.args) == (CMD_CURRENT, "REDCODE", ["10:1"])
            assert proto.state["redcode"] == "10:1"

            # SET_RELATIVE -> C
            r = rpc(build_packet(CMD_SET_RELATIVE, "ISO", ["400"], source="API"))
            assert (r.cmd, r.param, r.args) == (CMD_CURRENT, "ISO", ["1200"])

            # GET_DEFAULT -> E
            r = rpc(build_packet(CMD_GET_DEFAULT, "ISO", source="API"))
            assert (r.cmd, r.param, r.args) == (CMD_CURRENT_DEFAULT, "ISO", ["800"])

            # GET_LIST -> D
            r = rpc(build_packet(CMD_GET_LIST, "REDCODE", source="API"))
            assert r.cmd == CMD_CURRENT_LIST
            assert "8:1" in r.args and "16:1" in r.args

            # DIY Serial-2 handshake verbs
            r_who = rpc(build_packet(CMD_GET, "WHO", source="API"))
            assert r_who.args == ["RED DSMC2"]

            r_ver = rpc(build_packet(CMD_GET, "VERSION", source="API"))
            assert r_ver.args == ["7.4.1"]

            r_info = rpc(build_packet(CMD_GET, "REDINFO", source="API"))
            assert len(r_info.args) == 1 and "SYNTH" in r_info.args[0]

            # Legacy plain-text GET/SET compatibility on the exact same connection
            sock.sendall(b"SET ISO 1600\n")
            legacy_set = f.readline()
            assert legacy_set == b"RED iso 1600\n"

            sock.sendall(b"GET ISO\n")
            legacy_get = f.readline()
            assert legacy_get == b"RED iso 1600\n"
    finally:
        server.stop()
