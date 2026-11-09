/* Bare-metal entry for the RED block-0 restore image. The OMAP3630 ROM loads this
 * to SRAM 0x40200000 and branches to the first instruction (ARM state, MMU/cache off,
 * UART3 already set up by the ROM at 115200 8E1). We set a stack and call rr_main().
 * SRAM top usable region: keep stack high in the 64 KB SRAM window, below the ROM
 * trace vector at 0x4020FFB0. */
	.arm
	.section .text.start, "ax"
	.global _start
_start:
	/* GP image header prepended by the build (size,dest) is stripped by the sender;
	 * ROM branches here directly for a peripheral boot. */
	cpsid	if			/* mask IRQ/FIQ */
	ldr	sp, =0x4020F000		/* stack in SRAM, below ROM trace area */
	bic	sp, sp, #7		/* 8-byte align */
	bl	rr_main
1:	b	1b			/* hang on return */
