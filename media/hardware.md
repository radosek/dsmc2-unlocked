# Media Adapter Hardware

Only one physical task remains to use a bare SATA SSD as a magazine. You need a
**connector/adapter board**. The board seats the drive in the mag bay. The board
routes SATA plus power to the camera's mag connector.

- A genuine MINI-MAG is an **mSATA** module. An **M.2-SATA** module works too
  (M.2-SATA, not M.2 NVMe). An adapter can host either.
- The electrical interface is plain SATA III plus power. Nothing on the wire is
  proprietary.
- Approved third-party mags (for example KipperTie's M.2-SATA unit) prove the
  mechanical and electrical approach scales. It scales to capacities past RED's
  own 960 GB.

## The mag connector (TE Connectivity)

The MINI-MAG electrical interface uses TE Connectivity parts. The part numbers
come from a public teardown:

| Side | TE part number |
|---|---|
| Card reader (male, camera/reader side) | `2129261-1` or `21229276-1` |
| MINI-MAG (female, on the mag) | `2129260-2` |

An adapter board recreates the mag-side footprint (female `2129260-2`). The board
wires it to a bare mSATA or M.2-SATA SSD. These are standard orderable TE
connectors.

Board design files and photos will be added here as the hardware is built.

> Source for the part numbers: a public YouTube comment by `@我是02老公` on a RED
> MINI-MAG teardown video. The comment also confirms the OEM device titles in
> [media-table.md](media-table.md) (for example 120 GB = `KINGSTON RBU-SMS100S3120GD1`,
> 240 GB = `M500IT_MTFDDAT240MBD`).
