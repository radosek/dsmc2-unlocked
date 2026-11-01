# The Accessory Bus — Module Enumeration and Identity

The DSMC2 brain talks to every attached module — expanders, power modules,
battery plates, side handles, lens mounts, I/O ports, the EVF — over a serial
accessory bus. When a module attaches, the brain **enumerates** it: it asks what
the module is, reads an identity descriptor, and optionally checks a signature.

This page documents that handshake, and the central finding: **no accessory is
cryptographically gated for use.** Every identity layer is soft. A module that
fails its signature is logged, not rejected. This matters if you want to build or
repair your own board (see the DIY note at the end).

Everything here was recovered from the camera firmware (the reference image, a
SCARLET-W on 7.4.1). The relevant routines, by name from the symbol map:

```
module_cap_if::handle_redinfo            0x804c5374
RCPShellSerial2::get_redinfo             0x801ccc68
onewire_verify_signature                 0x806903b4
HAL_SysID_UpdateOrVerifySecureBoards     0x807bf2.. (the "secure board" routine)
```

## The enumeration handshake

On attach, the brain runs a fixed sequence over the module's UART. The log lines
are literal firmware strings:

```
rear device %s: WHO response received
rear device %s: VERSION response hw:%d sw:%d
rear device %s: REDINFO response received
rear device %s: DEVID acknowledged (%s)
rear device %s: detected
KEY_MSG_REAR_DEVICE_ENUMERATION_COMPLETE
```

1. **WHO** — the module says what class of device it is.
2. **VERSION** — it reports hardware and software versions (`hw:%d sw:%d`). If the
   brain has a newer image for that device under
   `/image2/peripherals/reardevices/<name>.<n>.bin`, it pushes an upgrade (see
   [peripheral-firmware.md](peripheral-firmware.md)).
3. **REDINFO** — the module sends an identity blob. This is the important step.
4. **DEVID** — the brain acknowledges with a device id.

## REDINFO — the identity blob

REDINFO is a **base64-encoded `ModuleDescriptor`**. The brain base64-decodes it
and parses a small TLV structure:

```
REDINFO for module %d parsed successfully (Product Name: "%s", RED ID: %s)
```

The descriptor is a set of typed entries, each with a numeric entry id. The
firmware's parser knows these entry classes (from `ModuleDescriptor::*Entry`):

```
UINT8Entry  UINT16Entry  UINT32Entry  BoolEntry  StringEntry  EnumEntry  BlobEntry
```

and typed accessors (`GetUINT8Entry`, `GetStringEntry`, `GetHardwareCapabilities`,
`GetPowerIns`, `GetPowerOuts`, …). So a descriptor carries, among other fields:

- a **Product Name** (string),
- a **RED ID** — note this is a plain integer, not a key or a hash:
  ```
  Found augmented module descriptor with RED ID %d. Using that instead of
  the module descriptor parsed by the REDINFO blob.
  ```
  The brain keeps a registry of known RED IDs and will prefer a built-in
  ("augmented") descriptor for a recognised id — but an unknown id is not a
  rejection. The id is trusted as reported.
- **hardware capabilities** and **power in/out** descriptors (what the module can
  draw or supply).

### "Invalid" only means "did not parse"

The only REDINFO failure path is a parse failure, never a signature failure:

```
Unable to handle REDINFO blob for module %d. An error occurred base64 decoding "%s".
Unable to handle REDINFO blob for module %d. Parse error %d occurred. ...
Unable to handle REDINFO blob for module %d. NULL argument specified.
Unable to handle REDINFO blob. Module %d is invalid.
```

"Module %d is invalid" is emitted when the blob cannot be decoded or parsed —
bad base64, a malformed TLV, an allocation failure. A well-formed descriptor from
an unknown vendor parses fine.

You can send a REDINFO blob yourself from the service shell (`send_redinfo`): it
asks for a `module_interface_t` value and then the REDINFO payload. That is the
same path the brain uses internally.

## The two signatures (both soft)

### 1. ModuleDescriptor signature

The descriptor parser has a `ModuleDescriptor::ModuleDescriptorParser::VerifySignature`
method. It is checked when a signature entry is present and skipped when it is
absent. It is not required to enumerate or use the module.

### 2. The 1-Wire signature

Physical modules carry a 1-Wire memory chip holding a board identity (part
number, assembly part number, board name, serial) and a signature. The verifier
is `onewire_verify_signature`. Its algorithm, read from the disassembly:

- It is a **standard MD5**. The init constants are the MD5 IV
  (`67452301 efcdab89 98badcfe 10325476`).
- The digest is computed over a **6-byte salt followed by the board identity
  fields** (board name, part numbers, serial, a type byte, …).
- The salt is a RED constant:
  ```
  27 A8 12 4F B3 EA
  ```
  (This is the accessory salt. It is a different constant from the media salt
  `82 3C 16 F5 4A 9C` in [../media/authentication.md](../media/authentication.md),
  though the primitive — MD5 — is the same.)
- The 16-byte digest is compared against the value stored in the 1-Wire chip.
  The routine returns **0** (no signature present / skipped), **1** (valid), or
  **2** (mismatch).

On a mismatch the firmware only logs — it does not disable the module:

```
1-Wire signature check failed for Module Part No. %s (Board Name "%s"), signature is:%s
1-Wire Signature Data did not match expected for Module Part No. %s ...
1-Wire data has an unknown Signature Version (%u) for Module Part No. %s ...
```

If the 1-Wire chip is missing or unreadable, the brain falls back to a default
device id rather than refusing the module:

```
Device ID not found in PORTX 1-wire.  Defaulting to PORTX as device ID.
Component part # not found in PORTX 1-wire.  Defaulting to PORTX as device ID.
```

### The "secure board" check is an env-var sync, not a gate

There is one more line that looks like a gate:

```
checking secure board %s: requires signature version >= %d; camera has signature version %d
```

It comes from `HAL_SysID_UpdateOrVerifySecureBoards`. Tracing that routine: it
compares each board's identity against a cached copy stored in the camera's `/env`
environment variables, and when they differ it **remounts `/env` read/write and
writes the correct value** — it self-heals the cache:

```
%s board info does not match; fixing it in env var
%s board info missing; adding ...
Error remounting /env as read/write.
```

Every path through the routine ends by continuing. It keeps an identity cache in
sync. It does not refuse an unsigned or mismatched board, and it is not part of
the attach/mount decision.

## The "unauthorized battery module" log line

You may see this in a boot log:

```
We are getting RVXL battery capacity info but no battery expander is attached.
Most likely unauthorized battery module is providing power.
```

This is **informational only**. The brain is reading battery telemetry over the
power path but did not enumerate an RVXL expander, so it guesses that an
unofficial power source is attached. Nothing is gated or shut down on the basis
of this line; the camera keeps running on that power.

## What this means for a DIY board

There is no cryptographic wall on the accessory bus. To make the camera recognise
and talk to a module you build, the module must:

1. Answer the serial handshake: **WHO → VERSION → REDINFO → DEVID**.
2. Send a **well-formed REDINFO blob** — a base64 `ModuleDescriptor` carrying a
   Product Name, a RED ID (a plain integer), and the power/capability entries the
   camera reads for that device class.
3. Optionally carry a 1-Wire chip. The signature on it is
   `MD5(27 A8 12 4F B3 EA ‖ board fields)` — reproducible offline with the salt
   above — but it is not required: a missing or mismatched 1-Wire signature only
   produces a log line.

The real difficulty is **electrical, not cryptographic**:

- Powering the brain from your own source is trivial — it is a regulated DC input.
  Hit the voltage and current spec with a clean rail and the camera runs. Dummy
  batteries and V-/Gold-mount plates are exactly this, with no chip at all.
- A module the camera must *enumerate* needs a small MCU to run the handshake
  above, plus whatever analog job it does (regulate power, buffer/level-shift
  slow I/O).
- A module carrying **fast lanes** (SATA3, C2C differential pairs) needs proper
  re-drivers/buffers and a controlled-impedance PCB. That is a board-design
  problem, not an authentication one.

The two still-unpublished pieces are the exact serial framing of the bus and the
precise byte layout of the `ModuleDescriptor` TLV. Both are recoverable: the TLV
layout from an accessory's own `peripherals/reardevices/*.bin` image, and the
framing from a single logic capture on a genuine module's connector.
