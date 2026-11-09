/* Link the bare-metal restore image at SRAM 0x40200000 (OMAP3630 ROM peripheral-boot load addr). */
OUTPUT_FORMAT("elf32-littlearm")
OUTPUT_ARCH(arm)
ENTRY(_start)

MEMORY { SRAM : ORIGIN = 0x40200000, LENGTH = 0xDC00 }   /* ~55 KB, under the ROM download ceiling */

SECTIONS
{
	. = 0x40200000;
	.text : {
		*(.text.start)       /* _start first */
		*(.text*)
		*(.rodata*)          /* embedded block0 slice lives here */
	} > SRAM
	.data : { *(.data*) } > SRAM
	.bss : { *(.bss*) *(COMMON) } > SRAM
	. = ALIGN(8);
	_end = .;
}
