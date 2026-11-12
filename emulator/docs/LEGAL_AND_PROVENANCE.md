# Legal, Provenance, and Firmware Boundaries

## 1. Distribution Boundaries

1. **No Proprietary Binary Redistribution**:
   - This repository contains zero proprietary RED Digital Cinema files (`dsmc_program.mem`, bootloader binaries, Xtensa coprocessor binaries, DSP COFF objects, or FPGA bitstreams).
   - You must supply your own firmware from a legitimate source, such as an official RED release archive or your own camera hardware.
   - The `.gitignore` file excludes `firmware_store/` and `user_firmware/` so unpacked binaries are never committed.

2. **Cryptographic Keys**:
   - The RSA decryption keys (`fw_v2_privkey.der`, `fw_v3_privkey.der`) and the preset AES key come from documented research in `radosek/dsmc2-unlocked`.
   - RED Digital Cinema holds the private package signing keys. Neither the camera hardware nor this repository contains signing keys.
   - The physical DSMC2 bootloader does not verify a signature on `dsmc_program.mem`. Therefore, the emulator boots modified firmware binaries without signature checks.

3. **Attribution**:
   - Hardware and protocol documentation builds on `radosek/dsmc2-unlocked` (MIT License).
   - The firmware importer calls `tools/fw-crypto/unpack_combo.py` to unpack combo archives.

4. **Automated Tests**:
   - The test suite in `emulator/tests/` uses synthetic ARM instruction stubs and mocked peripheral responses when user firmware is absent.
   - Tests that require user-supplied firmware or coprocessor binaries call `pytest.skip()` on a clean checkout.
