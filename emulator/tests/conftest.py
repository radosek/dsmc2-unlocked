"""Shared test fixtures / gates for the emulator suite.

The boot-path tests load the genuine RED DSMC2 program image
(`firmware_store/unpacked/scarlet_w_7_4_1/slot/dsmc_program.mem`). That image is
copyrighted RED firmware and is NOT committed to this (public) repository — it is
staged locally by the owner. When it is absent, the FW-dependent test modules
skip instead of erroring, so a clean checkout still runs the FW-independent suite.
"""

import os

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FW_IMAGE = os.path.join(
    _REPO_ROOT, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "dsmc_program.mem"
)

FIRMWARE_PRESENT = os.path.exists(_FW_IMAGE)

requires_firmware = pytest.mark.skipif(
    not FIRMWARE_PRESENT,
    reason="requires the staged RED DSMC2 firmware image (not committed to the public repo)",
)
