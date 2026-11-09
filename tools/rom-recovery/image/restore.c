/* RED block-0 restore, bare metal (OMAP3630 ROM UART3 peripheral boot image).
 * No DDR, no PLL, no U-Boot: SRAM only. The ROM leaves UART3 at 115200 8E1 and the
 * GPMC/NAND pins muxed; we set GPMC CS0 to the camera's live NAND timings, then
 * unlock/erase/program the embedded golden block-0 slice with on-die ECC OFF and
 * verbatim spare (ROM-Hamming bytes), and verify. TX-only status on UART3.
 *
 * Build selects the page slice via block0_slice.h (RED_B0_FIRST/LAST + red_b0_main/spare).
 * The slice containing page 0 erases the block; later slices program-only.
 * Target block = RR_BLK (default 0 = real block0; set to a scratch block to dry-run).
 *
 * Proven values + sequence come from the patched U-Boot SPL (sections 14-19 of
 * research/boards/pinout/UART3_ROM_BOOT_STATUS.md). This is a 1:1 bare-metal transcription.
 */

#include "block0_slice.h"	/* RED_B0_FIRST, RED_B0_LAST, red_b0_main[], red_b0_spare[] */
#include "red_pads.h"		/* red_pads[] = camera pad table (live dump), same as the U-Boot SPL replays */

#ifndef RR_BLK
#define RR_BLK 0
#endif

/* --- MMIO --- */
#define GPMC_BASE   0x6e000000u
#define GPMC_STATUS (*(volatile unsigned int *)0x6e000054u)   /* bit8 = NAND R/B ready */
#define NAND_CMD    (*(volatile unsigned char *)0x6e00007cu)
#define NAND_ADR    (*(volatile unsigned char *)0x6e000080u)
#define NAND_DAT    (*(volatile unsigned short *)0x6e000084u)  /* x16 */
#define UART3       ((volatile unsigned char *)0x49020000u)

static void uputc(char c)
{
	if (c == '\n') uputc('\r');
	while (!(UART3[0x14] & 0x20))	/* THR empty */
		;
	UART3[0x00] = (unsigned char)c;
}
static void uputs(const char *s) { while (*s) uputc(*s++); }
static void uhex2(unsigned v)
{
	const char *h = "0123456789abcdef";
	uputc(h[(v >> 4) & 0xf]); uputc(h[v & 0xf]);
}
static void udec(unsigned v)
{
	char b[10]; int n = 0;
	if (!v) { uputc('0'); return; }
	while (v) { b[n++] = '0' + v % 10; v /= 10; }
	while (n--) uputc(b[n]);
}

static void nwait_ready(void)
{
	unsigned tmo = 0x400000;
	while (!(GPMC_STATUS & 0x100))
		if (!--tmo) { uputs("RR: ready timeout\n"); break; }
}
static void nrow(unsigned r)
{
	NAND_ADR = r & 0xff; NAND_ADR = (r >> 8) & 0xff; NAND_ADR = (r >> 16) & 0xff;
}
static unsigned nstatus(void)
{
	unsigned s;
	NAND_CMD = 0x70; s = NAND_DAT & 0xff; NAND_CMD = 0x00;
	return s;
}

void rr_main(void)
{
	unsigned blk = RR_BLK, rowb, p, w, idx, st, mism = 0;

	uputs("\nRR: bare-metal block-0 restore. block ");
	udec(blk); uputs(" slice "); udec(RED_B0_FIRST); uputs(".."); udec(RED_B0_LAST - 1); uputc('\n');

	/* replay the camera pad table (same as the proven U-Boot SPL s_init). Writes only, never reads
	 * 0x480025F8..FC (the power-off trap). This sets any NAND/write-strobe pad the ROM left unset. */
	{
		unsigned k;
		for (k = 0; k < sizeof(red_pads) / sizeof(red_pads[0]); k++)
			*(volatile unsigned int *)(unsigned long)red_pads[k].addr = red_pads[k].val;
	}

	/* GPMC CS0 = camera live NAND timings (same as the proven SPL) */
	*(volatile unsigned int *)0x6e000060 = 0;            /* CONFIG7: CS off while programming */
	*(volatile unsigned int *)0x6e000060 = 0x00001800;
	*(volatile unsigned int *)0x6e000064 = 0x00080900;
	*(volatile unsigned int *)0x6e000068 = 0x00080000;
	*(volatile unsigned int *)0x6e00006c = 0x05000500;
	*(volatile unsigned int *)0x6e000070 = 0x00050809;
	*(volatile unsigned int *)0x6e000074 = 0x00000000;
	*(volatile unsigned int *)0x6e000078 = 0x00000f50;   /* CONFIG7: CS0 enable */

	/* Mirror the PROVEN U-Boot NANDPROBE order EXACTLY (sections 14-19): reset, SET FEATURES
	 * 0x90=0x0008 (ECC ON), GET FEATURES, READ ID. The chip appears to need this full probe to
	 * accept the subsequent block-unlock. We flip ECC OFF only just before programming block 0. */
	{
		unsigned short f[4], id[6]; unsigned i;
		/* RSB-side GPIO state (the passing U-Boot scratch build drove these before unlock; one of them
	 * is in the NAND lock/nWP path). Enable PER GPIO clocks, drive 62/98/115/163 high, 66/86/87 low.
	 * Banks: 62=G2.30, 98=G4.2, 115=G4.19, 163=G6.3, 66/86/87=G3.2/22/23. SET=0x94 CLR=0x90 OE=0x34. */
	{
		volatile unsigned int *g2 = (volatile unsigned int *)0x49050000;
		volatile unsigned int *g3 = (volatile unsigned int *)0x49052000;
		volatile unsigned int *g4 = (volatile unsigned int *)0x49054000;
		volatile unsigned int *g6 = (volatile unsigned int *)0x49058000;
		*(volatile unsigned int *)0x48005000 |= (0x1fu << 13);  /* CM_FCLKEN_PER EN_GPIO2..6 */
		*(volatile unsigned int *)0x48005010 |= (0x1fu << 13);  /* CM_ICLKEN_PER EN_GPIO2..6 */
		g2[0x094/4] = (1u<<30); g2[0x034/4] &= ~(1u<<30);
		g4[0x094/4] = (1u<<2)|(1u<<19); g4[0x034/4] &= ~((1u<<2)|(1u<<19));
		g6[0x094/4] = (1u<<3); g6[0x034/4] &= ~(1u<<3);
		g3[0x090/4] = (1u<<2)|(1u<<22)|(1u<<23); g3[0x034/4] &= ~((1u<<2)|(1u<<22)|(1u<<23));
	}

	NAND_CMD = 0xff; nwait_ready();                              /* reset */
		NAND_CMD = 0xef; NAND_ADR = 0x90;                            /* SET FEATURES ECC ON */
		NAND_DAT = 0x0008; NAND_DAT = 0; NAND_DAT = 0; NAND_DAT = 0;
		nwait_ready();
		NAND_CMD = 0xee; NAND_ADR = 0x90; nwait_ready();            /* GET FEATURES */
		f[0] = NAND_DAT; f[1] = NAND_DAT; f[2] = NAND_DAT; f[3] = NAND_DAT;
		uputs("RR: feature90 "); uhex2(f[0] & 0xff); uputc('\n');
		NAND_CMD = 0x00; NAND_CMD = 0x90; NAND_ADR = 0x00;         /* READ ID */
		for (i = 0; i < 6; i++) id[i] = NAND_DAT;
		uputs("RR: id "); uhex2(id[0] & 0xff); uhex2(id[1] & 0xff); uputc('\n');
		NAND_CMD = 0x00;
	}

	rowb = blk * 64;
	NAND_CMD = 0x23; nrow(rowb); NAND_CMD = 0x24; nrow(rowb); nwait_ready();   /* block unlock */
	NAND_CMD = 0x7a; nrow(rowb);                        /* block-lock read status */
	st = NAND_DAT & 0xff;
	uputs("RR: lock-status "); uhex2(st); uputc('\n');
	NAND_CMD = 0x00;

	if (RED_B0_FIRST == 0) {                             /* erase once (first slice) */
		NAND_CMD = 0x60; nrow(rowb); NAND_CMD = 0xd0; nwait_ready();
		st = nstatus();
		uputs("RR: erase status "); uhex2(st); uputc('\n');
	}

	/* now ECC OFF for the block-0 raw/Hamming write */
	NAND_CMD = 0xef; NAND_ADR = 0x90; NAND_DAT = 0; NAND_DAT = 0; NAND_DAT = 0; NAND_DAT = 0;
	nwait_ready();
	NAND_CMD = 0x00;

	for (p = RED_B0_FIRST; p < RED_B0_LAST; p++) {
		idx = p - RED_B0_FIRST;
		rowb = blk * 64 + p;
		NAND_CMD = 0x80; NAND_ADR = 0; NAND_ADR = 0; nrow(rowb);
		for (w = 0; w < 1024; w++) NAND_DAT = red_b0_main[idx * 1024 + w];   /* 2048 main */
		for (w = 0; w < 32; w++)   NAND_DAT = red_b0_spare[idx * 32 + w];    /* 64 spare verbatim */
		NAND_CMD = 0x10; nwait_ready();
		st = nstatus();
		if (st & 1) { uputs("RR: page "); udec(p); uputs(" PROGRAM FAIL\n"); mism++; }
	}

	for (p = RED_B0_FIRST; p < RED_B0_LAST; p++) {       /* verify vs golden */
		unsigned bad = 0;
		idx = p - RED_B0_FIRST;
		rowb = blk * 64 + p;
		NAND_CMD = 0x00; NAND_ADR = 0; NAND_ADR = 0; nrow(rowb); NAND_CMD = 0x30; nwait_ready();
		for (w = 0; w < 1024; w++) if (NAND_DAT != red_b0_main[idx * 1024 + w]) bad = 1;
		for (w = 0; w < 32; w++)   if (NAND_DAT != red_b0_spare[idx * 32 + w]) bad = 1;
		if (bad) { uputs("RR: page "); udec(p); uputs(" VERIFY MISMATCH\n"); mism++; }
	}

	NAND_CMD = 0x2a;                                     /* re-lock */
	uputs("RR: SLICE DONE. RESULT ");
	uputs(mism == 0 ? "PASS" : "FAIL");
	uputs(" ("); udec(mism); uputs(" errors) pages ");
	udec(RED_B0_FIRST); uputs(".."); udec(RED_B0_LAST - 1);
	uputs(" block "); udec(blk); uputc('\n');
}
