"""
IOB / LSB-FPGA XAUI link model (the "left-side board" high-speed link bring-up).

Models the two register files the firmware polls to decide the IOB<->LSB-FPGA XAUI link is
UP, so the real ``weapon_left_side_board_init`` (@0x809B5358) bring-up sequence completes and
its async-group bit (0x10) sets, unblocking ``weapon_boards_init`` and the board-dependent
init-event flags (Boards | Fan | XAUI | Mailbox).

This is a *register-state* model, faithful to the reconstructed C and the sdk findings; it does
NOT execute the IOB Xtensa firmware. The firmware's own PHY/PCS bring-up sequence drives the
registers and then polls these status words, so presenting link-up values makes that sequence
succeed without faking any predicate.

Two transports carry the status (ground truth: sdk ``clean/lsb_fpga.c`` +
``clean/weapon_left_side_board.c``; ``findings/peripherals/LSB_FPGA_{CHARACTERIZED,NAMED}.md``;
memory ``omap-iob-transport`` / ``xaui-lane-sharing-sata-mon0``):

  1. IOB side -- an AHB aperture. ``FUN_80727028(addr)`` reads ``*((addr & 0x3FFFFFF) |
     0x1C000000)``: a 1:1 window onto the IOB register space, so a port base of 0x80020000
     (EXP1) or 0x80060000 (MON0) lands at window offset 0x20000 / 0x60000. The XAUI PCS/status
     block within each port (offsets relative to the port base):

        +0x010  IOB XAUI status   -- PHY-ready bit 0x20000000 set; RX-fault bit 0x40000 clear
        +0x02C  IOB PCS status    -- link-up constant 0x03FFC02F (``pcs != 0x3ffc02f`` => bad)
        +0x068  IOB-RX pkt-len err-- 0 when healthy
        +0x0BC  IOB-RX CRC err    -- 0 when healthy
        +0x248  PHY_CLK_CTRL      -- PLL-ready bit 0x00100000 set (``lsb_fpga_xaui_phy_initx``)

     ``report_xaui_status`` (@0x809BCF64) reads +0x2C/+0x10/+0x68/+0xBC; ``lsb_fpga_xaui_phy_initx``
     additionally polls +0x248 bit 0x100000 (PLL ready) and +0x10 bit 0x20000000 (PHY ready).

  2. FPGA side -- the LSB-FPGA register file over the McSPI1-ch2 / CS-mux-6 ``fpga_read``
     byte frame ([0x81][addr][data] write / [0x01][addr]+ACK 0x1F read; sdk COPROCESSOR_TRANSPORT,
     memory ``omap-iob-transport``, PR #66). ``report_xaui_status`` reads three FPGA regs via
     ``FUN_809ba680`` -> ``fpga_read(6, addr)``:

        0x40010008  FPGA PCS/link status -- (v>>3 & 0xff) must == 0xFC (LinkUp/Aligned/Sync)
        0xC2000010  FPGA XAUI status     -- RX-fault bit 0x40000 clear
        0xC20000BC  FPGA-RX CRC err      -- 0

     These are seeded on the ``ts_fpga`` SPI target (see ``coprocessors/c2c.py``).

Only the IOB AHB-window half lives here; the FPGA-side seed values are constants shared with the
SPI transport (``FPGA_LINK_UP_REGS``).
"""

from typing import Dict


# ---- IOB AHB-window XAUI port register block (offsets within a 0x40000 port) ----------------
# Each XAUI port (EXP1 @ window 0x20000, MON0 @ window 0x60000) exposes the same block.
IOB_PCS_LINK_UP = 0x03FFC02F        # +0x2C: PCS status when the link is up
IOB_XAUI_PHY_READY = 0x20000000     # +0x10: PHY-ready set, RX-fault (0x40000) clear
IOB_PHYCLK_PLL_READY = 0x00100000   # +0x248: PLL-ready bit polled during phy_init

# Per-port register offset -> value presented when the link is UP. Any offset not listed reads 0
# (the firmware only gates on these; other reads in the block are logged/ignored).
_PORT_LINK_UP_REGS: Dict[int, int] = {
    0x010: IOB_XAUI_PHY_READY,
    0x02C: IOB_PCS_LINK_UP,
    0x068: 0x00000000,
    0x0BC: 0x00000000,
    0x248: IOB_PHYCLK_PLL_READY,
}

# The two XAUI port blocks the firmware may select (``lsb_fpga_using_MON0``): EXP1 (non-0x18
# cameras with IOB board rev < 0x33) and MON0 (CAMERA_TYPE 0x18 or rev >= 0x33). Modelling both
# makes the link come up regardless of which base the running firmware picks.
WINDOW_BASE = 0x1C000000
WINDOW_SIZE = 0x00100000
PORT_EXP1_OFF = 0x20000            # 0x80020000 & 0x3FFFFFF (EXP1 port base in the AHB window)
PORT_MON0_OFF = 0x60000            # 0x80060000 & 0x3FFFFFF (MON0 port base in the AHB window)
# The XAUI register block sits in the low part of each port base; all polled regs are <= 0x248,
# so an offset belongs to a port when it is within PORT_BLOCK_SPAN of that base.
PORT_BLOCK_SPAN = 0x1000            # register block size within a port (regs up to 0x248)
_XAUI_PORT_BASES = (PORT_EXP1_OFF, PORT_MON0_OFF)


# ---- SATA3-over-FPGA register block (shadow SATA registers in the IOB AHB window) ----------
# The SATA3 driver (SATADriver.c) does NOT touch an OMAP AHCI controller: the DSMC2 main SATA
# path is a shadow-register set that the LSB-FPGA presents in the same IOB AHB aperture, read
# through ``FUN_80727028`` (@0x80727028). For an HBA whose pHBAInfo ``SATA3`` shadow flag
# (hba[8]) is set -- HBA0 on the DSMC2, set by ``pHBAInfo`` @0x8069AF58 writing FPGA reg
# 0xC2000074 then hba[8]=1 -- every register read is routed to a fixed shadow index:
#
#   SATA_ReadHBARegister(hba0, off) @0x8069A798  -> FUN_80727028(idx*4 + 0x800B0000)
#       off 0x00 -> idx 0x1A0  (controller/"FPGA running" register)
#   SATA_ReadPortRegister(dev, off) @0x8069AA38  -> FUN_80727028(idx*4 + 0x800B0000)
#       off 0x28 -> idx 0x1AE  (PxSSTS -- AHCI SATA Status, DET/SPD/IPM)
#
# ``0x800B0000 & 0x3FFFFFF == 0x0B0000``, so the shadow block lands at window offset 0x0B0000.
# Two reads gate the SATA/Media storage-init cascade (driverthread.c sata_init @0x80670504 /
# media_init @0x8067060C):
#   * SATA_WaitForFPGARunning @0x806ACD30 loops until SATA_ReadHBARegister(hba0,0) != 0
#     (FPGA kick-started / running).
#   * SATA_MediaPresent @0x806A2ACC (SATA3 branch, hba[8]!=0) returns "present" when
#     PxSSTS has (v & 0xF0) != 0 (speed negotiated) AND (v & 0xF) == 3 (AHCI DET=3:
#     device present + PHY communication established).  See the OMAP35x/AM/DM37xx TRM
#     "SATA PxSSTS" field layout (DET[3:0], SPD[7:4], IPM[11:8]) -- the shadow register
#     mirrors the standard AHCI Port x Serial ATA Status encoding.
SATA_SHADOW_BLOCK_OFF = 0x0B0000        # 0x800B0000 & 0x3FFFFFF (SATA shadow-register base)
SATA_SHADOW_BLOCK_SPAN = 0x0800         # covers idx 0x1A0..0x1B3 (0x680..0x6CC)
# AHCI PxSSTS value for a present, Gen2-negotiated device:
#   DET=0x3 (device present + PHY comm), SPD=0x2 (Gen2 3Gb/s), IPM=0x1 (active)  -> 0x00000123
SATA_PXSSTS_PRESENT = 0x00000123
# SATA_ReadHBARegister(hba0,0) != 0 == "FPGA running"; the FW writes 0x800B0680 to FPGA reg
# 0x150 as the run pattern (SATA_InitializeFPGA @0x8069AE30), so present the same non-zero word.
SATA_HBA_FPGA_RUNNING = 0x800B0680
# Shadow-register-index -> value presented once the SATA3 FPGA link is up and media is present.
# Index is (window_offset - 0x0B0000) >> 2.  Only the two gated indices are answered; any other
# read in the block returns 0 (the FW only gates on these).
_SATA_SHADOW_REGS: Dict[int, int] = {
    0x1A0: SATA_HBA_FPGA_RUNNING,   # HBA controller reg 0 -- FPGA running / HBA alive
    0x1AE: SATA_PXSSTS_PRESENT,     # PxSSTS -- DET=3 present, SPD=2 Gen2, IPM=1 active
}
# Additional AHCI shadow registers polled by SATA_HostInit (@0x806A14A4) & SATA_PortReset (@0x806A2298)
# when attach_engine_enabled is True: GHC=AE, PI=1, VS=1.3, PxCMD idle (CR/FR clear), PxTFD DRDY|DSC.
_SATA_ATTACH_ENGINE_REGS: Dict[int, int] = {
    0x1A1: 0x80000000,  # GHC (AE=1, HR=0)
    0x1A2: 0x00000000,  # IS
    0x1A3: 0x00000001,  # PI (Port 0 present)
    0x1A4: 0x00010300,  # VS (AHCI 1.3)
    0x1AA: 0x00000000,  # PxCMD (CR=0, FR=0)
    0x1AC: 0x00000050,  # PxTFD (DRDY|DSC, BSY=0, DRQ=0)
    0x1B0: 0x00000000,  # PxSERR
    0x1B1: 0x00000000,  # PxSACT
    0x1B2: 0x00000000,  # PxCI
}


# ---- IOB command-response mailbox (xsys_iob_cmd_tx ack) ------------------------------------
# The IOB "cmd/response" mailbox the driver polls after ``xsys_iob_cmd_tx`` dispatches a command
# to an IOB Xtensa core. ``FUN_80727028(0x800B0018)`` reads the IOB0 response word (0x800B001C
# for IOB1); ``0x800B0018 & 0x3FFFFFF == 0x0B0018`` lands at this window offset, page 0x20.
#
# The Monitor-Pipeline init child (``monitor_pipeline_init`` @0x8074C9E8 -> ``FUN_807B45FC``,
# "iob_mon_init_black_frame") issues command 0x26 via ``xsys_iob_cmd_tx(0,0x26,...)`` then waits
# on this word for the done bit 0x20000:
#   * ``FUN_807B3044(0,0x20000,500)`` busy-waits (``FUN_80701EB0`` tick-spin) for bit 0x20000 SET
#   * ``FUN_807B30DC(0,0x20000,5000)`` then waits (``_tx_thread_sleep``) for bit 0x20000 to CLEAR
# On real hardware the IOB core asserts the done bit when the black-frame command completes, and
# the host sees it clear once consumed -- both polls pass on their first read. The emulator does
# not run the IOB Xtensa, so without a model this word stays 0: ``FUN_807B3044`` never sees the
# bit set and spins in ``FUN_80701EB0``, a tick-counter busy-wait that cannot advance (the CPU
# never returns to the scheduler idle loop where the compressed-tick model injects GPTimer2
# ticks), hanging the Monitor-Pipeline child so it never posts its init-event bit 0x2000. That
# strands the whole post-storage DSS/display + DSP/audio batch (0x000CE000), since the Driver
# blocks in ``wait_for_init_flags(0xE000)`` for Monitor Pipeline | HDMI | HDSDI before it
# dispatches DSP/Audio.  (sdk findings/subsystems/DSP_C64X_CHARACTERIZED.md, memory
# ``omap-iob-transport``: IOB mailbox @0xA5800000/GPMC + register-poke response path.)
#
# Model it as a read-to-clear done pulse: the response word reads 0x20000 (done bit set) on its
# first read -- satisfying ``FUN_807B3044`` on poll 1 so the tick-spin is never entered -- and
# reads 0 afterwards -- satisfying ``FUN_807B30DC``'s clear-wait on its first poll. Each read
# re-arms independently per IOB core, so a later command's poll pair sees the same set-then-clear.
IOB_CMDRESP_OFFS = (0x0B0018, 0x0B001C)   # 0x800B0018 (IOB0) / 0x800B001C (IOB1) & 0x3FFFFFF
IOB_CMD_DONE_BIT = 0x00020000             # command-done bit the FW polls (FUN_807B3044/30DC)


# ---- FPGA-side (McSPI ch6) link-up register seeds, shared with the SPI transport -----------
# 0x40010008: (v>>3 & 0xff) must == 0xFC  ->  0x7E0 gives (0x7E0>>3)&0xff = 0xFC
FPGA_PCS_LINK_UP = 0x000007E0
FPGA_LINK_UP_REGS: Dict[int, int] = {
    0x40010008: FPGA_PCS_LINK_UP,   # LinkUp=1 Aligned=1 Sync=1111 RxFault=0 TxFault=0
    0xC2000010: 0x00000000,         # FPGA XAUI status: RX-fault bit 0x40000 clear
    0xC20000BC: 0x00000000,         # FPGA-RX CRC errors = 0
}


class IobXauiWindow:
    """IOB AHB XAUI aperture @0x1C000000 (0x100000), presenting an UP link on both port blocks.

    Installed as a Unicorn MEM_READ hook (the window is below the bus device-hook range), it
    answers the exact status words ``FUN_80727028`` reads so the firmware's XAUI PHY/PCS
    bring-up and ``lsb_fpga_report_xaui_status`` see the link come up. Writes into the window
    (PHY config / latch-clear) are left to RAM: the model reports ready/good independently of
    them, exactly as a brought-up link would.
    """

    def __init__(
        self,
        link_up: bool = True,
        media_present: bool = True,
        attach_engine_enabled: bool = False,
    ):
        self.link_up = link_up
        # When True the SATA3 shadow block reports an attached, present SSD on HBA0/port0 so the
        # SATA/Media storage-init cascade completes. False models an empty main media bay (the
        # FW's "No media is present" branch -- a valid boot that still releases run_application).
        self.media_present = media_present
        self.attach_engine_enabled = bool(attach_engine_enabled)
        self.read_count = 0
        self.xtensa_ack_count = 0
        self.status_reads: Dict[int, int] = {}
        # IOB command-response mailbox: per-core "done bit armed" latch (read-to-clear). Armed so
        # the first poll after a command sees the done bit set; the read clears it so the paired
        # clear-wait passes too. Keyed by window offset (0x0B0018 IOB0 / 0x0B001C IOB1).
        self._iob_cmd_done_armed: Dict[int, bool] = {off: True for off in IOB_CMDRESP_OFFS}

    def notify_xtensa_doorbell(self, core_id: int, addr: int, val: int) -> None:
        """Bridge Xtensa core local MMIO doorbell writes (``0x3FFE8000``) to IOB cmd-response."""
        if addr == 0x3FFE8000 and val != 0 and core_id in (0, 1):
            off = IOB_CMDRESP_OFFS[core_id]
            self._iob_cmd_done_armed[off] = True
            self.xtensa_ack_count += 1

    def _reg_off(self, window_offset: int):
        """Map a window offset to (port_base, reg_off) if it lands on a modelled XAUI port
        block's status area, else (None, None)."""
        for base in _XAUI_PORT_BASES:
            if base <= window_offset < base + PORT_BLOCK_SPAN:
                return base, window_offset - base
        return None, None

    def _sata_idx(self, window_offset: int):
        """Map a window offset to a SATA3 shadow-register index if it lands in the shadow block
        (base 0x0B0000), else None. Index = (offset - base) >> 2."""
        if SATA_SHADOW_BLOCK_OFF <= window_offset < SATA_SHADOW_BLOCK_OFF + SATA_SHADOW_BLOCK_SPAN:
            return (window_offset - SATA_SHADOW_BLOCK_OFF) >> 2
        return None

    def value_for(self, window_offset: int) -> int:
        """Return the link-up register value for an offset within the 0x1C000000 window.

        Answers the two modelled XAUI port blocks (EXP1/MON0), the SATA3 shadow-register block,
        and the IOB command-response mailbox (done bit); anything else reads 0 (handled as RAM by
        the caller via ``is_status_reg``). Pure read for the cmd-response word -- the read-to-clear
        state transition happens in ``read``; here it reflects the current armed latch."""
        if window_offset in IOB_CMDRESP_OFFS:
            return IOB_CMD_DONE_BIT if self._iob_cmd_done_armed.get(window_offset) else 0x00000000
        sata_idx = self._sata_idx(window_offset)
        if sata_idx is not None:
            if not self.link_up:
                return 0x00000000
            if sata_idx in _SATA_SHADOW_REGS:
                val = _SATA_SHADOW_REGS[sata_idx]
            elif self.attach_engine_enabled and sata_idx in _SATA_ATTACH_ENGINE_REGS:
                val = _SATA_ATTACH_ENGINE_REGS[sata_idx]
            else:
                return 0x00000000
            # PxSSTS reports "no device" (DET=0) when the main media bay is modelled empty; the
            # HBA/FPGA-running register stays non-zero (controller is up regardless of media).
            if sata_idx == 0x1AE and not self.media_present:
                return 0x00000000
            return val
        port_base, reg_off = self._reg_off(window_offset)
        if port_base is None or not self.link_up:
            return 0x00000000
        return _PORT_LINK_UP_REGS.get(reg_off, 0x00000000)

    def is_status_reg(self, window_offset: int) -> bool:
        if window_offset in IOB_CMDRESP_OFFS:
            return True
        sata_idx = self._sata_idx(window_offset)
        if sata_idx is not None:
            if sata_idx in _SATA_SHADOW_REGS:
                return True
            return self.attach_engine_enabled and sata_idx in _SATA_ATTACH_ENGINE_REGS
        port_base, reg_off = self._reg_off(window_offset)
        return port_base is not None and reg_off in _PORT_LINK_UP_REGS

    def read(self, window_offset: int, size: int) -> int:
        self.read_count += 1
        if window_offset in IOB_CMDRESP_OFFS:
            # Read-to-clear done-bit pulse: the done bit reads set once (satisfies the SET-wait
            # FUN_807B3044 on poll 1, so the FUN_80701EB0 tick-spin is never entered), then reads
            # clear (satisfies the CLEAR-wait FUN_807B30DC on its first poll). Re-arms so a later
            # command's poll pair sees the same set-then-clear sequence.
            armed = self._iob_cmd_done_armed.get(window_offset, False)
            self.status_reads[window_offset] = self.status_reads.get(window_offset, 0) + 1
            if armed:
                self._iob_cmd_done_armed[window_offset] = False
                return IOB_CMD_DONE_BIT
            # Clear read observed -- re-arm for the next command's SET-wait.
            self._iob_cmd_done_armed[window_offset] = True
            return 0x00000000
        _, reg_off = self._reg_off(window_offset)
        if reg_off is not None:
            self.status_reads[reg_off] = self.status_reads.get(reg_off, 0) + 1
        return self.value_for(window_offset)
