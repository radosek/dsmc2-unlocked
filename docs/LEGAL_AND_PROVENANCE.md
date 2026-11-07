# Legal, Provenance, and Firmware Boundaries

## 1. Clean Distribution Boundaries

1. **No Proprietary Binary Redistribution**:
   - The repository contains **zero** proprietary RED Digital Cinema binaries (`dsmc_program.mem`, bootloader, ISP/IOB Xtensa images, DSP COFF objects, or FPGA bitstreams).
   - Firmware must be user-supplied from legitimate sources (e.g. public release builds downloaded directly by the user from RED's official portal, or extracted from user-owned cameras).
   - All local firmware packages, unpacked files, and derived binary dumps are stored in `firmware_store/` and `user_firmware/`, which are strictly ignored by `.gitignore`.

2. **Keys and Cryptographic Material**:
   - The RSA decryption private keys (`fw_v2_privkey.der`, `fw_v3_privkey.der`) and the preset universal key are documented research findings published in `radosek/dsmc2-unlocked` for interoperability and preservation.
   - Signing private keys are held exclusively by RED Digital Cinema and do not exist in this project or on the camera hardware.
   - The emulator validates unauthenticated modified firmware images because the physical DSMC2 bootloader does not check application image signatures.

3. **Attribution and Research Lineage**:
   - Primary research foundation: `radosek/dsmc2-unlocked` (MIT License).
   - Tools reused or adapted:
     - `tools/fw-crypto/unpack_combo.py`: container unpacker.
     - `tools/preset/red_preset.py`: wxSQLite3 preset codec.
     - `tools/red-log-decoder/`: log decryption and parsing tools.

4. **Synthetic Test Fixtures**:
   - The automated test suite uses non-proprietary synthetic ARM binary stubs and mocked peripheral responses.
   - Genuine firmware validation runs locally against imported user assets and outputs pass/fail reports without publishing proprietary code.
