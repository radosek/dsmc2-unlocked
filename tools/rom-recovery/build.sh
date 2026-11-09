#!/bin/sh
# Build the bare-metal RED block-0 restore image for OMAP3630 ROM UART3 peripheral boot.
# Usage: build.sh FIRST LAST [BLK]
#   FIRST LAST = page range of block 0 to write this run (e.g. 0 21, 21 42, 42 61)
#   BLK        = target block (default 0 = real block 0; use a scratch block to dry-run)
# Requires: arm-none-eabi-gcc/ld/objcopy, python3, and a block-0 golden dump (see README).
set -e
FIRST=${1:-0}; LAST=${2:-21}; BLK=${3:-0}
cd "$(dirname "$0")"
: "${RED_GOLDEN_MAIN:?set RED_GOLDEN_MAIN to your block0 main-only dump (64*2048 B)}"
: "${RED_GOLDEN_SPARE:?set RED_GOLDEN_SPARE to your block0 spare-only dump (64*64 B)}"
cc -O2 -o gen_block0_slice gen_block0_slice.c
./gen_block0_slice "$FIRST" "$LAST" block0_slice.h
CC=arm-none-eabi-gcc
CFLAGS="-mcpu=cortex-a8 -marm -ffreestanding -nostdlib -Os -fno-pic -fno-builtin -Wall"
LIBGCC=$($CC $CFLAGS -print-libgcc-file-name)
$CC $CFLAGS -DRR_BLK=$BLK -c start.S -o start.o
$CC $CFLAGS -DRR_BLK=$BLK -c restore.c -o restore.o
arm-none-eabi-ld -T restore.lds start.o restore.o "$LIBGCC" -o restore.elf
arm-none-eabi-objcopy -O binary restore.elf restore.bin
rm -f start.o restore.o
echo "restore.bin: $(wc -c < restore.bin) bytes (block $BLK, pages $FIRST..$((LAST-1)))"
