"""
Synthesized YAFFS2 NAND image builders for the DSMC2 ``/env`` and ``/image2`` partitions.

The firmware's ``init_filesystem`` (@0x80008310) mounts ``/env`` (block 1) and reads
``/env/PARTITION_TABLE`` via ``env_get_partition_table`` (@0x80706b84). If that file is
absent, the firmware falls back to a built-in **version-0** partition table
(``&DAT_8140898c``) and then ``env_upgrade_partition_table`` (@0x80707470) runs the
v0->v1->...->v6 upgrade path, which reformats/relocates partitions in an unbounded NAND
read/write loop that never completes under emulation.

To let mount and CDB2/Xtensa file loads complete cleanly, this module provides:

* ``write_env_image()``: Stages ``/env/PARTITION_TABLE`` (version 6) at block 1 with no serials,
  calibration, or unit-specific environment variables.
* ``write_image_partition()`` / ``build_yaffs_tree_chunks()``: Stages ``/image2`` (block 605)
  with ``cdb2/factory.db`` (from ``build_minimal_factory_db_blob()``) and compact Xtensa IRAM/DRAM
  images for ``isp``, ``iob0``, and ``iob1`` (``build_default_xtensa_blobs()``) using
  block-incrementing ``seqNumber`` tags so multi-block files register cleanly during ``yaffs_Scan``.

Formats are matched to the firmware's own readers (verified against the Ghidra decompile and
sdk ``clean/nand_utils.c`` / ``env_var.c``):

* **packed_tags2** (16-byte OOB tags), as unpacked by FUN_80a160a8:
  ``[u32 seqNumber, u32 objectId(+flags), u32 chunkId(+bit31 header), u32 byteCount]``.
  An unwritten chunk has ``seqNumber == 0xFFFFFFFF``.
* **yaffs_obj_hdr** (standard yaffs2 object header in the 2048-byte data area of chunk 0):
  ``u32 type; u32 parent_obj_id; u16 sum; char name[256]; ...`` — field offsets type@0,
  parent@4 confirmed from yaffs_verify_oh (@0x80a131d8).
* **PARTITION_TABLE on-disk layout**, from env_get_partition_table reads:
  ``u32 version; u32 count; count*(char name[16]; u32 startBlock; u32 numBlocks);
  u32 symVersion; u32 symCount; symCount*(u32 linkLen; char link[]; u32 tgtLen; char tgt[])``.

The image is written into ``OmapGpmc`` via ``program_page`` at the absolute pages of the
``/env`` partition, so the firmware's real GPMC NAND read path (on-die ECC enabled) serves it.
"""

import os
import sqlite3
import struct
import tempfile
from typing import Any, Dict, List, Optional, Tuple

PAGE_SIZE = 2048
SPARE_SIZE = 64
PAGES_PER_BLOCK = 64

# yaffs2 object types
YAFFS_OBJECT_TYPE_FILE = 1
YAFFS_OBJECT_TYPE_SYMLINK = 2
YAFFS_OBJECT_TYPE_DIRECTORY = 3

# yaffs2 well-known object ids
YAFFS_OBJECTID_ROOT = 1
YAFFS_OBJECTID_LOSTNFOUND = 2
YAFFS_OBJECTID_UNLINKED = 3
YAFFS_OBJECTID_DELETED = 4
YAFFS_FIRST_FREE_OBJECTID = 0x100

# The shipped DSMC2 partition table (block layout from the camera's own
# ``nand show-partition-table``, version 6). Generic: no per-unit data.
PARTITION_TABLE_VERSION = 6
PARTITIONS: List[Tuple[str, int, int]] = [
    ("/env", 1, 44),
    ("/image1", 45, 560),
    ("/image2", 605, 560),
    ("/data", 1165, 280),
    ("/", 1500, 44),
    ("/log", 1808, 240),
    ("/rodata", 2048, 1200),
    ("/pdata", 3248, 4944),
]
# Symlink table (version 13) exactly as the camera reports it. Pure path strings; generic.
SYMLINK_TABLE_VERSION = 13
SYMLINKS: List[Tuple[str, str]] = [
    ("/force_upgrade", "/pdata/force_upgrade"),
    ("/force_preset", "/pdata/force_preset"),
    ("/data/luts", "/pdata/data/luts"),
    ("/data/overlays", "/pdata/data/overlays"),
    ("/data/looks", "/pdata/data/looks"),
    ("/data/cdb2/presets", "/pdata/data/presets"),
    ("/cal2", "/pdata/cal2"),
    ("/cal", "/pdata/cal"),
    ("/cal/col_cal", "/rodata/cal/col_cal"),
    ("/cal/rts_cal", "/rodata/cal/rts_cal"),
    ("/cal2/factory_0", "/rodata/cal2/factory_0"),
    ("/cal/nand", "/rodata/cal/nand"),
    ("/data/cdls", "/pdata/data/cdls"),
    ("/data/licenses", "/rodata/licenses"),
]


def build_partition_table_blob() -> bytes:
    """Serialize the PARTITION_TABLE file exactly as env_get_partition_table reads it."""
    out = bytearray()
    out += struct.pack("<I", PARTITION_TABLE_VERSION)
    out += struct.pack("<I", len(PARTITIONS))
    for name, start, numblk in PARTITIONS:
        nb = name.encode("ascii")[:16]
        nb = nb + b"\x00" * (16 - len(nb))
        out += nb
        out += struct.pack("<II", start, numblk)
    out += struct.pack("<I", SYMLINK_TABLE_VERSION)
    out += struct.pack("<I", len(SYMLINKS))
    for link, target in SYMLINKS:
        lb = link.encode("ascii")
        tb = target.encode("ascii")
        out += struct.pack("<I", len(lb)) + lb
        out += struct.pack("<I", len(tb)) + tb
    return bytes(out)


def _pack_tags2(seq: int, obj_id: int, chunk_id: int, byte_count: int) -> bytes:
    """Build the 16-byte packed_tags2 OOB tags FUN_80a160a8 unpacks (seq/obj/chunk/byteCount)."""
    return struct.pack("<IIII", seq & 0xFFFFFFFF, obj_id & 0xFFFFFFFF,
                       chunk_id & 0xFFFFFFFF, byte_count & 0xFFFFFFFF)


# The 2048-byte page is covered by four 512-byte on-die-ECC sub-sectors, each with its own
# 16-byte OOB sub-spare. The firmware's yaffs2 packed_tags2 are NOT contiguous at OOB byte 0:
# each 16-byte sub-spare keeps its first 4 bytes reserved (ECC/bad-block marker) and stores one
# 32-bit tag word at byte 4, so the four tag words land at OOB offsets 4, 20, 36, 52.
# yflash2_ReadChunkWithTagsFromNANDInternalECC (@0x80a1fdb0) reads the 64-byte OOB into a stack
# buffer (sp+0x48) then copies the words at sp+0x4c / sp+0x5c / sp+0x6c / sp+0x7c (OOB +4/+20/+36/
# +52) into a contiguous block before FUN_80a160a8 unpacks. A contiguous 0..15 layout (or a
# base-0 stride) shifts every tag word, the chunk decodes as erased (0xFFFFFFFF), and the whole
# YAFFS2 object is discarded during the scan.
TAG_WORD_BASE = 4
TAG_WORD_STRIDE = 16


def _make_spare(tags: bytes) -> bytes:
    """Lay the 4 packed_tags2 words into the 64-byte OOB at offsets 4/20/36/52 (per sub-sector)."""
    spare = bytearray(b"\xFF" * SPARE_SIZE)
    for i in range(4):
        off = TAG_WORD_BASE + i * TAG_WORD_STRIDE
        spare[off : off + 4] = tags[i * 4 : i * 4 + 4]
    return bytes(spare)


def _build_obj_header(obj_type: int, parent_obj_id: int, name: str,
                      file_size: int = 0) -> bytes:
    """Build a 2048-byte yaffs2 object header (chunk 0 of an object).

    Standard yaffs2 ``yaffs_obj_hdr``: type@0, parent_obj_id@4, sum@8 (u16, unused -> 0xFFFF),
    name[256]@10, then POSIX-ish attributes; file size is stored as the low/high 32-bit split
    used by yaffs2 (``file_size_low`` / ``file_size_high``). Unused trailing bytes are 0xFF to
    match a NAND-written header.
    """
    hdr = bytearray(b"\x00" * PAGE_SIZE)
    struct.pack_into("<I", hdr, 0x00, obj_type)        # type: file/dir/symlink (yaffs_verify_oh @0)
    struct.pack_into("<I", hdr, 0x04, parent_obj_id)   # parent obj id (yaffs_verify_oh @4)
    struct.pack_into("<H", hdr, 0x08, 0xFFFF)          # name sum (recomputed from name on scan)
    # The object's name is the SHORT name at OH offset 0xA (NUL-terminated, <= 15 chars). The scan
    # applies it via FUN_80a179d8 -> FUN_80a1795c(obj, OH + 0xA): a non-empty byte there is
    # strcpy'd into the object (obj+0x38) and its 16-bit sum stored at obj+4, which yaffs_find_by_name
    # matches against. An empty 0xA makes the scan synthesize a fallback "obj<id>" name, so
    # red_open("/env/PARTITION_TABLE") never resolves. (The 0x12C field is the symlink ALIAS,
    # read only for symlink objects via FUN_80a19e7c(OH + 0x12C); not the file name.)
    nb = name.encode("ascii")[:0x0F]  # yaffs short-name limit: 15 chars + NUL (FUN_80a226f0 < 0x10)
    hdr[0x0A : 0x0A + len(nb)] = nb
    hdr[0x0A + len(nb)] = 0x00
    # yst_mode at OH+0x10C: the scan copies it to the object (obj[0xd] = OH[0x43]) and red_open
    # gates read access on bit 0x100 (S_IRUSR) -- a zero mode yields EACCES (-13) even though the
    # object is found by name. Use POSIX 0100644 for a file / 0040755 for a dir.
    struct.pack_into("<I", hdr, 0x10C,
                     0x000081A4 if obj_type == YAFFS_OBJECT_TYPE_FILE else 0x000041ED)
    # file size at OH+0x124 (FUN_80a1f530 returns *(OH + 0x124)); read by the scan to size the
    # file object. yaffs2's 64-bit split stores the high word separately; a <4GB table needs only
    # the low word here.
    struct.pack_into("<I", hdr, 0x124, file_size & 0xFFFFFFFF)
    return bytes(hdr)


def build_env_chunks(seq_base: int = 0x00001000) -> List[Tuple[int, bytes, bytes]]:
    """Build the (relative_page, data, spare) chunks for a minimal ``/env`` with PARTITION_TABLE.

    Relative page 0 is the first page of the ``/env`` partition. Chunk-per-page. Returns the
    object-header chunk for the PARTITION_TABLE file followed by its data chunks. The root
    directory (object id 1) is implicit in yaffs2 and needs no on-disk header.
    """
    chunks: List[Tuple[int, bytes, bytes]] = []
    blob = build_partition_table_blob()
    obj_id = YAFFS_FIRST_FREE_OBJECTID
    seq = seq_base

    rel_page = 0
    # Object-header chunk tags. A yaffs2 header chunk (unpacked by FUN_80a160a8) is NOT a plain
    # (seq,obj,chunk,bytes) tuple: the chunkId word has bit31 set, and the tag words carry the
    # "extra" object info the scan reads instead of a separate header read:
    #   objId word  : bits[27:0] = object id,  bits[31:28] = object type (1=file,3=dir,4=symlink)
    #   chunkId word: bit31 = 1 (header marker), bits[27:0] = parent object id
    #   byteCount   : extra file size (object types != symlink)
    hdr = _build_obj_header(YAFFS_OBJECT_TYPE_FILE, YAFFS_OBJECTID_ROOT,
                            "PARTITION_TABLE", file_size=len(blob))
    obj_word = (obj_id & 0x0FFFFFFF) | (YAFFS_OBJECT_TYPE_FILE << 28)
    chunk_word = 0x80000000 | (YAFFS_OBJECTID_ROOT & 0x0FFFFFFF)  # header marker + parent = root
    hdr_tags = struct.pack("<IIII", seq & 0xFFFFFFFF, obj_word, chunk_word, len(blob))
    chunks.append((rel_page, hdr, _make_spare(hdr_tags)))
    rel_page += 1

    # Data chunks (chunkId starts at 1). Last chunk's byteCount is the tail length.
    offset = 0
    chunk_id = 1
    while offset < len(blob):
        piece = blob[offset : offset + PAGE_SIZE]
        data = piece + b"\xFF" * (PAGE_SIZE - len(piece))
        tags = _pack_tags2(seq, obj_id, chunk_id, len(piece))
        chunks.append((rel_page, data, _make_spare(tags)))
        rel_page += 1
        chunk_id += 1
        offset += PAGE_SIZE

    return chunks


def write_env_image(gpmc, env_start_block: int = 1):
    """Program the synthesized ``/env`` YAFFS2 image into ``gpmc``'s backing NAND store.

    ``env_start_block`` is the absolute first block of ``/env`` (block 1 in the shipped
    layout; the firmware's yaffs_start_up hardcodes start=1, 44 blocks). Pages are written at
    their absolute page index so the firmware's partition-relative reads resolve correctly.
    """
    base_page = env_start_block * PAGES_PER_BLOCK
    for rel_page, data, spare in build_env_chunks():
        gpmc.program_page(base_page + rel_page, data, spare)


_CACHED_FACTORY_DB_BLOB: Optional[bytes] = None

# Minimal subset of shipped factory.db rows required by firmware CSM / RCP CDB2 queries.
_DEFAULT_FACTORY_PARAMS: Tuple[Tuple[str, str, object, Optional[str]], ...] = (
    ("DEBUG_ENABLE_SHELL", "UINT32", 0, None),
    ("DEBUG_LOG_TO_SHELL", "BOOL", 0, None),
    ("DEBUG_LOAD_ASIC_BINS_FROM_HOST", "BOOL", 0, None),
    ("COMM_IP_ADDRESS", "UINT32", 168430090, "GEIPADDR"),
    ("COMM_NETMASK_ADDRESS", "UINT32", 4294967040, "GENETMSK"),
    ("COMM_GATEWAY_ADDRESS", "UINT32", 168430081, "GEGWADDR"),
    ("COMM_DHCP_ENABLE", "BOOL", 1, "GEDHCP"),
    ("CAMERA_ID", "STRING", "RED_SCARLET_W", "CAMID"),
    ("SENSOR_FRAME_RATE", "INT32", 24000, "FPS"),
    ("EXPOSURE_TIME", "INT32", 20833, "EXP"),
    ("ISO_SPEED", "UINT32", 800, "ISO"),
    ("COLOR_TEMPERATURE", "UINT32", 5600, "COLTEMP"),
)


def build_minimal_factory_db_blob() -> bytes:
    """Build a compact SQLite 3 database matching stock 7.4.1 ``cdb2/factory.db`` schemas.

    Uses legacy SQLite file format and 1024-byte pages so the firmware's embedded SQLite
    library executes ``cdb2_init`` prepared-statement compilation (ATTACH, GET, SET, etc.)
    with minimal NAND page reads during boot.
    """
    global _CACHED_FACTORY_DB_BLOB
    if _CACHED_FACTORY_DB_BLOB is not None:
        return _CACHED_FACTORY_DB_BLOB

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(tmp_path)
    try:
        db = sqlite3.connect(tmp_path)
        db.execute("PRAGMA legacy_file_format = ON;")
        db.execute("PRAGMA page_size = 1024;")
        db.execute("PRAGMA journal_mode = OFF;")
        db.execute(
            """CREATE TABLE parameters(
                name UNIQUE DEFAULT NULL,
                type DEFAULT NULL,
                msg_type DEFAULT NULL,
                default_value DEFAULT NULL,
                preset_group DEFAULT NULL,
                set_message UNIQUE DEFAULT NULL,
                get_message UNIQUE DEFAULT NULL,
                current_message UNIQUE DEFAULT NULL,
                set_list_message UNIQUE DEFAULT NULL,
                get_list_message UNIQUE DEFAULT NULL,
                current_list_message UNIQUE DEFAULT NULL,
                set_relative_message UNIQUE DEFAULT NULL,
                set_list_relative_message UNIQUE DEFAULT NULL,
                apply_order DEFAULT -1,
                rcp_name UNIQUE DEFAULT NULL,
                rcp_filter DEFAULT NULL,
                preset_name DEFAULT NULL,
                description DEFAULT NULL,
                multiplier DEFAULT 1,
                visibility DEFAULT 1,
                rcp_api_region DEFAULT NULL
            )"""
        )
        db.execute(
            "CREATE TABLE key_sources(val UNIQUE DEFAULT NULL, "
            "key_source DEFAULT NULL, hw_cap DEFAULT NULL)"
        )
        db.execute(
            "CREATE TABLE key_events(key_code UNIQUE DEFAULT NULL, "
            "key_event DEFAULT NULL, hw_cap DEFAULT NULL)"
        )
        db.execute(
            "CREATE TABLE key_actions(id UNIQUE DEFAULT NULL, key_action DEFAULT NULL, "
            "msg DEFAULT NULL, param DEFAULT NULL, msg_type DEFAULT NULL, "
            "hw_cap DEFAULT NULL, user_mappable DEFAULT 1)"
        )
        for idx, (name, ptype, val, rcp_name) in enumerate(_DEFAULT_FACTORY_PARAMS, start=1):
            db.execute(
                "INSERT INTO parameters(name, type, msg_type, default_value, apply_order, rcp_name) "
                "VALUES (?,?,?,?,?,?)",
                (name, ptype, ptype, val, idx, rcp_name),
            )
        db.commit()
        db.close()
        with open(tmp_path, "rb") as f:
            _CACHED_FACTORY_DB_BLOB = f.read()
        return _CACHED_FACTORY_DB_BLOB
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


_CACHED_DEFAULT_PRESET_BLOB: Optional[bytes] = None


def build_default_preset_db_blob(overrides: Optional[Dict[str, Any]] = None) -> bytes:
    """Build a compact SQLite 3 preset database for ``/image2/cdb2/presets/cinema.preset``.

    Schema matches ``_cdb2_process_preset`` (@0x80084404): ``parameters(name UNIQUE, value)``
    and ``info(version, delete_after_apply, has_pin_whitelist, has_version_whitelist,
    has_camera_type_whitelist)``.
    """
    global _CACHED_DEFAULT_PRESET_BLOB
    if overrides is None and _CACHED_DEFAULT_PRESET_BLOB is not None:
        return _CACHED_DEFAULT_PRESET_BLOB

    rows = (
        overrides
        if overrides is not None
        else {"ISO_SPEED": 1600, "COLOR_TEMPERATURE": 3200, "DEBUG_ENABLE_SHELL": 1}
    )
    fd, tmp_path = tempfile.mkstemp(suffix=".preset")
    os.close(fd)
    os.unlink(tmp_path)
    try:
        db = sqlite3.connect(tmp_path)
        db.execute("PRAGMA legacy_file_format = ON;")
        db.execute("PRAGMA page_size = 1024;")
        db.execute("PRAGMA journal_mode = OFF;")
        db.execute("CREATE TABLE parameters(name UNIQUE, value);")
        db.execute(
            "CREATE TABLE info(version, delete_after_apply, has_pin_whitelist, "
            "has_version_whitelist, has_camera_type_whitelist);"
        )
        db.execute("INSERT INTO info VALUES(17, 0, 0, 0, 0);")
        for pname, pval in rows.items():
            db.execute("INSERT INTO parameters(name, value) VALUES (?, ?)", (pname, pval))
        db.commit()
        db.close()
        with open(tmp_path, "rb") as f:
            blob = f.read()
        if overrides is None:
            _CACHED_DEFAULT_PRESET_BLOB = blob
        return blob
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def build_default_xtensa_blobs() -> Dict[str, Dict[str, bytes]]:
    """Build compact executable Xtensa IRAM/DRAM binary images for ``/image2/{isp,iob0,iob1}``.

    Produces valid 64-byte payloads whose DRAM descriptor table (words 3/4/7 matching the
    shipped binaries) points ``release_reset()`` to a real 16-byte Xtensa LX routine at
    ``IRAM + 0x10`` (``ENTRY a1, 32; L32R a2, 0x3FFE8000; MOVI.N a3, 1; S32I.N a3, a2, 0;
    MOVI.N a2, 0; RETW.N``) that writes a ready status word to C2C doorbell ``0x3FFE8000``.
    """
    # Little-endian Xtensa LX sequence placed at IRAM+0x10 (PC = 0x40000010):
    #   +0x10: 36 41 00   ENTRY  a1, 32
    #   +0x13: 21 FE FF   L32R   a2, [0x4000000C]   ; literal 0x3FFE8000 (-2 words from 0x40000014)
    #   +0x16: 0C 13      MOVI.N a3, 1              ; a3 = 1
    #   +0x18: 39 02      S32I.N a3, a2, 0          ; *(0x3FFE8000) = 1
    #   +0x1A: 0C 02      MOVI.N a2, 0              ; a2 = 0
    #   +0x1C: 1D F0      RETW.N                    ; windowed return
    _XTENSA_ENTRY_ROUTINE = bytes.fromhex("36410021feff0c1339020c021df0")

    def _make_pair(prefix: bytes) -> Dict[str, bytes]:
        dram = bytearray(64)
        dram[:12] = prefix[:12].ljust(12, b"\x00")
        struct.pack_into("<I", dram, 12, 0x40000010)  # dram[3]: IRAM entry address
        struct.pack_into("<I", dram, 16, 0x00040020)  # dram[4]: initial PS (WOE=1, UM=1)
        struct.pack_into("<I", dram, 28, 0x3FFE8000)  # dram[7]: C2C doorbell MMIO base

        iram = bytearray(64)
        iram[:12] = prefix.replace(b"DRAM", b"IRAM")[:12].ljust(12, b"\x00")
        struct.pack_into("<I", iram, 12, 0x3FFE8000)  # +0x0C: literal pool constant for L32R
        iram[16 : 16 + len(_XTENSA_ENTRY_ROUTINE)] = _XTENSA_ENTRY_ROUTINE
        return {"dram.bin": bytes(dram), "iram.bin": bytes(iram)}

    return {
        "isp": _make_pair(b"ISP_DRAM_741"),
        "iob0": _make_pair(b"IOB0_DRAM_74"),
        "iob1": _make_pair(b"IOB1_DRAM_74"),
    }


def build_yaffs_tree_chunks(
    tree: Dict[str, Any],
    seq_base: int = 0x00001000,
    first_obj_id: int = YAFFS_FIRST_FREE_OBJECTID + 1,
) -> List[Tuple[int, bytes, bytes]]:
    """Serialize a nested directory/file tree into YAFFS2 ``(rel_page, data, spare)`` chunks.

    Supports arbitrary subdirectory nesting (dict -> directory, bytes -> file). Each block
    advances ``seq = seq_base + (rel_page // PAGES_PER_BLOCK)`` so multi-block files pass
    ``queryNANDBlock`` and scan into full-length YAFFS2 file objects.
    """
    chunks: List[Tuple[int, bytes, bytes]] = []
    state = {"rel_page": 0, "next_obj_id": first_obj_id}

    def _emit_entries(parent_id: int, entries: Dict[str, Any]) -> None:
        for name, val in entries.items():
            obj_id = state["next_obj_id"]
            state["next_obj_id"] += 1
            rel_page = state["rel_page"]
            seq = seq_base + (rel_page // PAGES_PER_BLOCK)

            if isinstance(val, dict):
                hdr_d = _build_obj_header(YAFFS_OBJECT_TYPE_DIRECTORY, parent_id, name, 0)
                tags_d = _pack_tags2(
                    seq,
                    (obj_id & 0x0FFFFFFF) | (YAFFS_OBJECT_TYPE_DIRECTORY << 28),
                    0x80000000 | (parent_id & 0x0FFFFFFF),
                    0,
                )
                chunks.append((rel_page, hdr_d, _make_spare(tags_d)))
                state["rel_page"] += 1
                _emit_entries(obj_id, val)
            else:
                blob = val
                hdr_f = _build_obj_header(YAFFS_OBJECT_TYPE_FILE, parent_id, name, len(blob))
                tags_f = _pack_tags2(
                    seq,
                    (obj_id & 0x0FFFFFFF) | (YAFFS_OBJECT_TYPE_FILE << 28),
                    0x80000000 | (parent_id & 0x0FFFFFFF),
                    len(blob),
                )
                chunks.append((rel_page, hdr_f, _make_spare(tags_f)))
                state["rel_page"] += 1

                offset = 0
                chunk_id = 1
                while offset < len(blob):
                    piece = blob[offset : offset + PAGE_SIZE]
                    data = piece + b"\xFF" * (PAGE_SIZE - len(piece))
                    rp = state["rel_page"]
                    seq = seq_base + (rp // PAGES_PER_BLOCK)
                    tags = _pack_tags2(seq, obj_id, chunk_id, len(piece))
                    chunks.append((rp, data, _make_spare(tags)))
                    state["rel_page"] += 1
                    chunk_id += 1
                    offset += PAGE_SIZE

    _emit_entries(YAFFS_OBJECTID_ROOT, tree)
    return chunks


def write_image_partition(
    gpmc,
    image_start_block: int = 605,
    factory_db_bytes: Optional[bytes] = None,
    include_xtensa_blobs: bool = False,
) -> Dict[str, int]:
    """Program ``/image2`` (active slot 0) with ``cdb2/factory.db``, presets & Xtensa blobs."""
    tree: Dict[str, Any] = {
        "cdb2": {
            "factory.db": (
                factory_db_bytes if factory_db_bytes is not None else build_minimal_factory_db_blob()
            ),
            "presets": {
                "cinema.preset": build_default_preset_db_blob(),
            },
        }
    }
    if include_xtensa_blobs:
        tree.update(build_default_xtensa_blobs())

    chunks = build_yaffs_tree_chunks(tree)
    base_page = image_start_block * PAGES_PER_BLOCK
    for rel_page, data, spare in chunks:
        gpmc.program_page(base_page + rel_page, data, spare)

    return {"blocks_written": (len(chunks) + PAGES_PER_BLOCK - 1) // PAGES_PER_BLOCK, "pages": len(chunks)}
