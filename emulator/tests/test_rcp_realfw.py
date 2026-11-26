"""Real-firmware RCP parameter path (CDB2 param store) — boot-to-CSM depth probe.

The milestone-3/4 RCP tests exercise ``emulator.rcp.protocol.RcpProtocol``, a clean-room
Python model of the RED Command Protocol. This module instead drives the **real firmware's
own** RCP parameter code on the booted application image (past ``Camera State Manager``),
to measure how far the genuine param GET/SET path runs end-to-end and pin the next blocker.

Background (all addresses stock 7.4.1, from the canonical Ghidra project
``research/ghidra/ghidra_proj REDfw`` and ``research/SYMBOL_MAP.txt``):

* The RCP control plane maps every ``RCP_PARAM_*`` to a **CDB2** key. CDB2 is a
  SQLite-backed parameter store (``cdb2.cpp``). Two databases: a read-only shipped
  **factory** parameter DB (``<dir>/cdb2/factory.db``, column schema
  ``name,type,default_value,...,rcp_name``, ~2062 rows) opened as the primary connection,
  and a writable **user** DB (``/data/cdb2/user.db``) ATTACHed as ``user`` (overrides).

* ``cdb2_init`` (@0x8007FB58, called from ``init_filesystem`` @0x80008310 during the app
  filesystem bring-up) opens the factory DB into the handle ``DAT_814CD39C`` (the "cdb2
  ready" flag that every getter checks first), then pre-compiles a cascade of
  ``sqlite3_prepare_v2`` (FUN_80DA9688) statements — the ATTACH stmt into ``DAT_814CD3A0``,
  the GET stmt (``SELECT main.parameters.type, CASE WHEN user.parameters.value IS NULL THEN
  main.parameters.default_value ELSE user.parameters.value END ...``) into ``DAT_814CD3D8``,
  the SET stmt (``INSERT OR REPLACE INTO user.parameters ...``) into ``DAT_814CD3D4``, etc.

* ``_cdb2_parameter_get_value`` (@0x80080C34) is the leaf GET: it bails with rc=1 if the
  ready flag is 0, else runs the prepared GET statement on ``DAT_814CD3D8``; a failed
  prepare (null stmt) makes its ``sqlite3_prepare``/bind wrapper (FUN_80D7D7A8) return
  nonzero and the getter returns **rc=0xC (12)**.

Empirical result on the emulated boot (this test):

* ``write_image_partition()`` in ``devices/nand_image.py`` stages ``/image2/cdb2/factory.db`` into
  NAND with sub-sector OOB tags and block-incrementing ``seqNumber``, so the firmware's
  ``yaffs_Scan`` registers the file object cleanly.
* ``cdb2_init`` **runs once** during ``boot_to_application``, opens ``/image2/cdb2/factory.db``
  into ``DAT_814CD39C``, and compiles all prepared statements (``DAT_814CD3A0`` ATTACH,
  ``DAT_814CD3D8`` GET, ``DAT_814CD3D4`` SET are non-null).
* The firmware's own code calls ``_cdb2_parameter_get_value`` >100 times during CSM bring-up,
  and direct calls via ``fw_cdb2_get_uint32`` / ``fw_cdb2_set_uint32`` return **rc=0** and
  persist overrides through ``/data/cdb2/user.db``.
"""

import pytest

from emulator.camera import Dsmc2Camera
from conftest import requires_firmware

pytestmark = requires_firmware

# cdb2 globals + functions (stock 7.4.1)
CDB2_READY_FLAG = 0x814CD39C   # DAT_814cd39c: factory-DB handle; nonzero == cdb2 ready
CDB2_ATTACH_STMT = 0x814CD3A0  # DAT_814cd3a0: prepared "ATTACH DATABASE ? AS ? KEY ?"
CDB2_GET_STMT = 0x814CD3D8     # DAT_814cd3d8: prepared GET (type + value CASE)
CDB2_INIT = 0x8007FB58
CDB2_GET_VALUE = 0x80080C34    # _cdb2_parameter_get_value(rcpname, type_str, out)
CDB2_SET_VALUE = 0x80082050    # _cdb2_parameter_set_value

# _cdb2_parameter_get_value / _set_value return codes (from the decompile)
RC_OK = 0
RC_PREPARE_FAIL = 0xC          # FUN_80D7D7A8 / finalize error (null prepared stmt)
CDB2_SET_STMT = 0x814CD3D4     # DAT_814cd3d4: prepared SET (INSERT OR REPLACE INTO user.parameters)

# A real parameter name present in the shipped factory.db (verified: UINT32, default 0).
REAL_PARAM_NAME = "DEBUG_ENABLE_SHELL"
REAL_PARAM_TYPE = "UINT32"

# Scratch DDR (above the live app/semaphore region, below the heap top 0x881B2690+).
_ARG_RCPNAME = 0x881C0000
_ARG_TYPE = 0x881C0100
_OUT_BUF = 0x881C0200


@pytest.fixture(scope="module")
def booted():
    """Boot the real FW to Camera State Manager, counting cdb2 entry points reached."""
    cam = Dsmc2Camera(workspace_root=".")
    cam.load_firmware()
    counters = {"cdb2_init": 0, "get_value": 0}
    h_init = cam.add_pc_hook(cam.fw(CDB2_INIT),
                             lambda c, p: counters.__setitem__("cdb2_init", counters["cdb2_init"] + 1))
    h_get = cam.add_pc_hook(cam.fw(CDB2_GET_VALUE),
                            lambda c, p: counters.__setitem__("get_value", counters["get_value"] + 1))
    res = cam.boot_to_application(max_instructions=200_000_000)
    cam.remove_hook(h_init)
    cam.remove_hook(h_get)
    return cam, res, counters


def _wstr(cam, addr, s):
    cam.bus.write_mem(cam.fw(addr), s.encode("ascii") + b"\x00")


def test_boot_reaches_csm(booted):
    """Sanity: the real FW booted past run_application into Camera State Manager."""
    _cam, res, _counters = booted
    assert res["camera_state_manager_spawned"] is True
    assert res["app_semaphore_created"] is True


def test_cdb2_init_runs_during_boot(booted):
    """cdb2_init (@0x8007FB58) is dispatched by init_filesystem during the real boot-to-CSM,
    and the factory-DB open succeeds (ready flag DAT_814CD39C becomes non-null)."""
    cam, _res, counters = booted
    assert counters["cdb2_init"] == 1, "cdb2_init must run exactly once via init_filesystem"
    ready = cam.bus.read_u32(cam.fw(CDB2_READY_FLAG))
    assert ready != 0, "cdb2 factory-DB handle / ready flag must be set after cdb2_init"


def test_firmware_itself_drives_the_get_path(booted):
    """The firmware's OWN code exercises _cdb2_parameter_get_value during CSM bring-up —
    i.e. the real RCP param GET path runs end-to-end, not just our probe."""
    _cam, _res, counters = booted
    assert counters["get_value"] > 0, "firmware should query params via _cdb2_parameter_get_value"


def test_real_fw_get_value_executes_sqlite_query(booted):
    """Drive _cdb2_parameter_get_value directly on the booted FW with real params.

    With /image2/cdb2/factory.db staged in NAND via write_image_partition, cdb2_init
    compiles all prepared statements, so SQLite lookup succeeds and returns rc=0 with the
    parameter value written to out_buf.
    """
    cam, _res, _counters = booted
    _wstr(cam, _ARG_RCPNAME, REAL_PARAM_NAME)
    _wstr(cam, _ARG_TYPE, REAL_PARAM_TYPE)
    cam.bus.write_mem(cam.fw(_OUT_BUF), b"\xEF\xBE\xAD\xDE" + b"\x00" * 28)

    rc = cam.call_function(CDB2_GET_VALUE, [_ARG_RCPNAME, _ARG_TYPE, _OUT_BUF])
    assert rc == RC_OK, f"expected RC_OK (0), got 0x{rc:X}"
    assert cam.bus.read_u32(cam.fw(_OUT_BUF)) == 0

    rc_ip, ip_val = cam.fw_cdb2_get_uint32("COMM_IP_ADDRESS")
    assert rc_ip == RC_OK
    assert ip_val == 168430090


def test_prepared_statements_compiled(booted):
    """Verify cdb2_init compiled the ATTACH, GET, and SET SQLite statements from factory.db."""
    cam, _res, _counters = booted
    attach_stmt = cam.bus.read_u32(cam.fw(CDB2_ATTACH_STMT))
    get_stmt = cam.bus.read_u32(cam.fw(CDB2_GET_STMT))
    set_stmt = cam.bus.read_u32(cam.fw(CDB2_SET_STMT))
    assert attach_stmt != 0, "ATTACH prepared statement must be non-null"
    assert get_stmt != 0, "GET prepared statement must be non-null"
    assert set_stmt != 0, "SET prepared statement must be non-null"


def test_get_and_set_value_roundtrip_through_user_db(booted):
    """Verify real-FW CDB2 SET persists an override into /data/cdb2/user.db and GET reads it back."""
    cam, _res, _counters = booted
    rc_set = cam.fw_cdb2_set_uint32(REAL_PARAM_NAME, 1)
    assert rc_set == RC_OK
    rc_get, val = cam.fw_cdb2_get_uint32(REAL_PARAM_NAME)
    assert rc_get == RC_OK
    assert val == 1
    # Restore default value 0 for clean repeatability
    assert cam.fw_cdb2_set_uint32(REAL_PARAM_NAME, 0) == RC_OK
    rc_get2, val2 = cam.fw_cdb2_get_uint32(REAL_PARAM_NAME)
    assert rc_get2 == RC_OK
    assert val2 == 0
