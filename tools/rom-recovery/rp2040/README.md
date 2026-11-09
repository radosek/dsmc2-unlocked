# RP2040 ROM-boot rig firmware

`red_romboot.ino` turns a Raspberry Pi RP2040 board (for example a Waveshare
RP2040-Zero) into the bridge between your computer and the camera UART3 pins. It
answers the camera boot ROM's ASIC-ID message by sending a recovery image, then
becomes a transparent serial bridge.

## You must generate `spl_data.h`

The sketch includes `spl_data.h`, which holds the recovery image as a C array
`SPL[]`. This file is **not** shipped (the image is built from your own block-0
dump). Generate it from a `restore.bin` (or a dump image) like this:

```sh
{ echo '#include <stdint.h>';
  xxd -i -n SPL restore.bin \
    | sed 's/unsigned char/const uint8_t/; s/unsigned int SPL_len/const unsigned SPL_LEN/';
} > spl_data.h
```

Put `spl_data.h` next to `red_romboot.ino`, then compile and upload with
`arduino-cli` for the `rp2040:rp2040:waveshare_rp2040_zero` board.

## Wiring and magics

See the [recovery procedure](../../../docs/access/rom-recovery.md) for the wiring and
for the arm command (`ESC # R S B # ESC LF`).
