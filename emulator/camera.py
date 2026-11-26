"""
Central RED DSMC2 Virtual Camera Orchestrator.
Integrates ARM CPU, system bus, peripheral models, storage, display, and control interfaces.
"""

import os
import unicorn
from unicorn import arm_const
import struct
import threading
import time
from typing import Optional, List, Dict, Callable, Any, Tuple, Union, Set, Iterable

from emulator.core.cpu import ArmCpu
from emulator.core.addrmap import AddrMap
from emulator.core.firmware import FirmwareManager
from emulator.core.bus import SystemBus
from emulator.core.trace_probe import TraceProbe
from emulator.devices.sidekick import SidekickMcu
from emulator.devices.intc import OmapIntc
from emulator.devices.prcm import OmapPrcm
from emulator.devices.gptimer import OmapGPTimer, TIMER_MAP
from emulator.devices.uart import OmapUart, UART_MAP, UART_ALIASES
from emulator.devices.i2c import OmapI2c, I2C_MAP, I2cSlave
from emulator.devices.i2c_maxtouch import MaXTouchDevice
from emulator.devices.i2c_eeprom import EdidEeprom
from emulator.devices.i2c_pmic import Twl4030Pmic
from emulator.devices.i2c_thermal import Tmp411Thermal
from emulator.devices.i2c_olpf import OlpfEeprom
from emulator.devices.gpmc import OmapGpmc
from emulator.devices.sdma import OmapSdma
from emulator.devices.mcspi import OmapMcspi, MCSPI_MAP
from emulator.devices.mcbsp import OmapMcBSP, MCBSP_MAP
from emulator.devices.cam_isp import OmapCamIsp
from emulator.devices.iob_xaui import IobXauiWindow
from emulator.devices.hdq_onewire import OmapHdq1Wire
from emulator.devices.i2c_ucd import (
    UcdPowerSequencer,
    make_iob_ucd9090,
    make_isp_ucd9090,
    make_sensor_ucd90160,
)
from emulator.devices.i2c_dsmc2_chips import (
    Si5346ClockSynth,
    Dac7578SensorDac,
    FocalTechTouch,
    FixedIdI2cDevice,
)
from emulator.devices.i2c_fan_controller import MaxFanController
from emulator.devices.l4_interconnect import OmapL4Ap, OmapScm, OmapScmId, OmapPrm, OmapSdrc
from emulator.devices.accessory_bus import AccessoryBus, ModuleDescriptor
from emulator.devices.rig_manager import RigManager, ConnectorPosition
from emulator.coprocessors.c2c import CoprocessorTransport, IobDoorbellDevice, IobMailboxDevice
from emulator.coprocessors.xtensa import Iob0Coprocessor, Iob1Coprocessor, IspCoprocessor
from emulator.coprocessors.dsp import (
    TiC64xDsp,
    DspLinkIpc,
    CImagingServer,
    RAudioServer,
    OmapMailbox,
    OmapIva2Mmu,
)
from emulator.devices.gpio import OmapGpio, GPIO_MAP
from emulator.devices.dss import OmapDss
from emulator.storage.vfs import VirtualFileSystem
from emulator.storage.r3d_recorder import R3dClipRecorder
from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.server import RcpServer
from emulator.rcp.rftp import RedpineRs9113Wifi, RftpServer
from emulator.rcp.automation import RcpScriptEngine, RcpScriptStep, MultiCameraNetwork
from emulator.devices.lens_mount import LensMount
from emulator.core.snapshot import SnapshotManager


class Dsmc2Camera:
    """The complete authentic RED DSMC2 Virtual Camera.

    Every firmware address below is a stock 7.4.1 address. A relinked image with moved
    sections is run with its ``addr_map`` (``AddrMap``); all of them go through ``self.fw``.
    """

    # ThreadX Scheduler Idle Loop Addresses
    IDLE_LOOP_ENTRY = 0x80E9C368
    IDLE_LOOP_PCS = {0x80E9C368, 0x80E9C36C, 0x80E9C370}

    # Driver-Init Dispatch Harness Entry Points (FW 7.4.1)
    THREAD_DRIVER_ENTRY = 0x8066C92C
    INIT_PARALLEL_ADDR = 0x8066FE9C
    WAIT_FOR_INIT_FLAGS_ADDR = 0x8066C7D8

    # ThreadX Global Symbols
    TX_THREAD_CREATED_PTR = 0x8149CE68
    TX_THREAD_CURRENT_PTR = 0x8149CE60
    TX_THREAD_EXECUTE_PTR = 0x8149DDE8
    TX_SEMAPHORE_GET_INTERNAL = 0x80EA31D4
    TX_THREAD_SYSTEM_RETURN = 0x80EA1144
    SYNC_CALL_FALLBACK_TCB = 0x814CAD40

    # Fan tachometer speed-test (temp_hal_weapon.c). HAL_Temp_SpeedTest spins the BRAIN fan up at
    # full PWM, then calls tx_thread_sleep(0x1770 = 6000 ticks) to wait for mechanical spin-up
    # before sampling the tachometer. That 6000-ms wait is a real hardware spin-up delay: in the
    # emulator's compressed tick model (one GPTimer2 OVF per scheduler slice) 6000 ThreadX ticks
    # never accrue within a practical boot, so the fan worker's sleep never returns and the Fan
    # init-event bit 0x800 never sets. The sleep-compression hook below clamps the spin-up sleep
    # *only when it is issued from inside HAL_Temp_SpeedTest* to a few ticks, so the fan worker
    # proceeds to the tach read (which the MaxFanController model answers) and completes. The
    # firmware still runs the full start/sleep/read/classify sequence; only the spin-up duration
    # is time-compressed, exactly as the tick cadence already compresses every other timed wait.
    HAL_TEMP_SPEEDTEST_ENTRY = 0x809B061C   # push {..} true entry
    HAL_TEMP_SPEEDTEST_RET   = 0x809B08BC   # ldm sp,{..,pc} epilogue (speed test body end)
    TX_THREAD_SLEEP_ENTRY    = 0x80E9E32C   # tx_thread_sleep (r0 = tick count)
    FAN_SPINUP_SLEEP_TICKS   = 4            # compressed spin-up wait (ticks) in the emulator

    # ThreadX TCBs this build creates by 1G instructions (static .data/.bss objects)
    TCB_ADDRS = (0x8149D494, 0x814CAD40, 0x827109B0, 0x82710CA0, 0x81E51F5C, 0x814C6B28)

    # Seeded RAM cells: NAND driver state + CAMERA_TYPE fallback
    NAND_DRV_INIT_FLAG = 0x81EF7818
    NAND_DRV_ID = 0x81EF7820
    NAND_DRV_GEOMETRY_PTR = 0x81EF7824
    NAND_GEOMETRY_STRUCT = 0x80FCEBF6
    CAMERA_TYPE_FALLBACK = 0x80FF591C

    # IOB mailbox windows the doorbell models read
    IOB0_MAILBOX = 0x800B0FFC
    IOB1_MAILBOX = 0x800B17FC

    # Late driver-init bring-up (thread_DRIVER_entry @0x8066C92C). The Driver thread spawns
    # ThreadX ``init_parallel_thread`` children; each sets a bit in the primary init event-flag
    # group @0x81E54834 (+0x08 = current set flags) on success, and ``wait_for_init_flags``
    # @0x8066C7D8 blocks the Driver thread on ``_tx_event_flags_get`` until named bits set.
    # (sdk findings/boot/BOOT_FLOW_MAP.md.) Bits: RTC 0x1, FileX 0x2, CRYPT 0x4, NAND FS 0x8.
    INIT_EVENT_FLAGS_GROUP = 0x81E54834
    INIT_EVENT_FLAGS_SET_OFFSET = 0x08
    # Milestone 1 ("late driver init reached"): CRYPT+RTC+FileX parallel-init have completed and
    # the Driver thread is blocked in wait_for_init_flags on the NAND-FS barrier (the next
    # milestone). 0x7 = 0x1 | 0x2 | 0x4.
    LATE_INIT_FLAGS_TARGET = 0x7

    # Milestone 1 ("UI/driver bring-up"): after the NAND-FS mount (0x8) the Driver thread runs a
    # second init_parallel cascade and blocks on the board-bring-up barrier
    # ``wait_for_init_flags(0x03300FF7)``. Bits added past the FS mount (sdk
    # findings/boot/BOOT_FLOW_MAP.md): UART 0x40, Load System Config 0x80, HAL Power 0x100,
    # Power 0x200, Boards 0x400, Fan 0x800, ASIC Memory Map 0x100000, XAUI 0x200000,
    # Mailbox 0x1000000, HAL SYS_ID 0x2000000, HW Cap 0x40000000, Module Cap 0x80000000.
    # With peripheral-synchronised McSPI1-over-sDMA, GPIO-76/77 CS-mux routing, seeded LSB-FPGA
    # status/version registers on McSPI1 CH2, ``MaxFanController`` @ I2C1 0x4D + fan-tach spin-up
    # sleep compression, and the IOB/XAUI AHB window at 0x1C000000 (``IobXauiAhbDevice`` backed by
    # ``IobXauiWindow``), ``weapon_boards_init`` (@0x809B378C), ``weapon_left_side_board_init``
    # (@0x809B5354), and ``fan_init`` (@0x8067049C) all complete: all four UI_BRINGUP_BOARD_BITS
    # (Boards 0x400 | Fan 0x800 | XAUI 0x200000 | Mailbox 0x1000000) set, satisfying
    # ``UI_BRINGUP_FLAGS_BARRIER`` at 0xC3300FFF and populating ``hw_cap`` (@0x815811F4) to
    # 0x00041182.
    UI_BRINGUP_FLAGS_BARRIER = 0x03300FF7
    UI_BRINGUP_FLAGS_REACHABLE = 0xC3300FFF   # board barrier now fully satisfied (Fan 0x800 set)
    UI_BRINGUP_BOARD_BITS = 0x01200C00        # Boards | Fan | XAUI | Mailbox (board-dependent bits)

    # Storage-init stage constants (``boot_to_run_application`` probe).
    RUN_APP_FLAGS_BARRIER = 0x0C000000        # SATA 0x04000000 | Media 0x08000000
    RUN_APP_SATA_BIT = 0x04000000
    RUN_APP_MEDIA_BIT = 0x08000000
    DSS_DISPLAY_FLAGS = 0x000CE000            # MonitorPipeline|HDMI|HDSDI|DSP|Audio
    DSS_IOB_ISP_DOWNLOAD_BIT = 0x00001000     # IOB/ISP binary download (deps met, completes)

    # Milestone 2 ("application running"): with ``iob_status_handshake_enabled=True`` and finer
    # ThreadX timer cadence (``slice_size=12_000``), the Driver thread drives SATA (0x4000000),
    # Media (0x8000000), IOB/ISP Binary Download (0x1000), Monitor Pipeline (0x2000), HDMI
    # (0x4000), HDSDI (0x8000), Monitor Splash Screen, DSP (0x40000), Contiguous Media Space
    # (0x10000000), and Audio (0x80000) to satisfy ``wait_for_init_flags(0xCF3CF7FF)`` (@0x8066D360),
    # runs Cal Load (0x800000) -> 0xDFBCFFFF, and puts semaphore 0x81E53618 (@0x8066D3C8) to release
    # Starter Thread (``thread_0_entry`` @0x80008E24 -> ``run_application`` @0x80008CB4), which
    # creates ``APP_SEMAPHORE`` (@0x814C6D1C) and spawns ``Camera State Manager`` (@0x8048D534).
    APPLICATION_FLAGS_BARRIER = 0xCF3CF7FF
    APPLICATION_FLAGS_REACHABLE = 0xDFBCFFFF
    APP_SEMAPHORE_ADDR = 0x814C6D1C
    SEMAPHORE_MAGIC = 0x53454D41  # 'SEMA'

    # CDB2 parameter store addresses (stock 7.4.1)
    CDB2_INIT_ADDR = 0x8007FB58
    CDB2_GET_VALUE_ADDR = 0x80080C34
    CDB2_SET_VALUE_ADDR = 0x80082050
    CDB2_SET_UINT32_ADDR = 0x800820E8
    CDB2_READY_FLAG_ADDR = 0x814CD39C
    CDB2_ATTACH_STMT_ADDR = 0x814CD3A0
    CDB2_SET_STMT_ADDR = 0x814CD3D4
    CDB2_GET_STMT_ADDR = 0x814CD3D8
    CDB2_DELETE_STMT_ADDR = 0x814CD3C4     # "DELETE FROM user.parameters WHERE name = ?"
    CDB2_PARAM_RESET_ADDR = 0x80082700     # cdb2_parameter_reset_value(name)
    CDB2_FACTORY_RESET_ADDR = 0x80080974   # cdb2_reset_to_factory_defaults()
    CDB2_APPLY_PRESET_ADDR = 0x8008435C    # cdb2_apply_preset(preset_name, out_changed)
    CDB2_PRESET_HAS_PARAM_ADDR = 0x8008438C  # cdb2_preset_has_param(preset_name, param_name)
    CDB2_PRESET_KEY_PTR_ADDR = 0x8104A11C  # ptr to attach encryption key ("aes256:..." vs "")
    CDB2_EMPTY_KEY_STR_ADDR = 0x8104A14C   # "" for plain unencrypted SQLite3 preset files

    # SATA / media probes (stock 7.4.1)
    RED_MEDIA_INIT_ADDR = 0x800A04FC
    RED_MEDIA_GET_DEVICE_ADDR = 0x800A06F4  # red_media_get_device(hba, port)
    SATA_MEDIA_PRESENT_ADDR = 0x806A2ACC    # SATA_MediaPresent(dev, retries, log)
    SATA_HOST_INIT_ADDR = 0x806A14A4        # SATA_HostInit(hba, force)
    SATA_PORT_RESET_ADDR = 0x806A2298       # SATA_PortReset(dev)

    # Real-FW ASIC Xtensa binary upload functions (stock 7.4.1)
    ISP_LOAD_EMBEDDED_ADDR = 0x80664D18
    ISP_MEM_UPLOAD_ADDR = 0x80762798
    ISP_REG_WRITE_ADDR = 0x80762E3C
    IOB_LOAD_EMBEDDED_ADDR = 0x80664ECC
    IOB_WORD_WRITE_ADDR = 0x80726E7C
    IOB_RESET_CTL_ADDR = 0x80728678

    def __init__(self, workspace_root: str, addr_map: Optional[AddrMap] = None):
        self.workspace_root = os.path.abspath(workspace_root)
        self.addr_map = addr_map if addr_map is not None else AddrMap()
        self.firmware_path: Optional[str] = None   # None: the slot's dsmc_program.mem
        self.reset_pc = self.fw(FirmwareManager.DEFAULT_RESET_PC)
        self.reset_sp = FirmwareManager.DEFAULT_SP
        self.irq_vector = self.fw(FirmwareManager.DEFAULT_IRQ_VECTOR)
        self.firmware_slot_dir = os.path.join(self.workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot")
        self.persistent_dir = os.path.join(self.workspace_root, "persistent_store")

        # 1. Initialize SoC Hardware & Registers
        self._init_hardware()

        # 2. Storage and VFS
        self.vfs = VirtualFileSystem(self.firmware_slot_dir, self.persistent_dir)
        self.env = self.vfs.env

        # 3. RCP Protocol, Server, Scripting, Wi-Fi/RFTP & Multi-Camera Network
        self.rcp = RcpProtocol(camera=self)
        self.rcp_server = RcpServer(self.rcp, host="127.0.0.1", port=1111)
        self.wifi = RedpineRs9113Wifi()
        self.rftp = RftpServer(self)
        self.rcp_script_engine = RcpScriptEngine()
        self.multicam_network = MultiCameraNetwork(self)

        # 4. Smart Electronic Lens Mount
        lens_dir = os.path.join(self.firmware_slot_dir, "lens")
        self.lens_mount = LensMount(self, lens_database_dir=lens_dir)

        # 5. REDCODE R3D Media Recorder
        self.recorder = R3dClipRecorder(self, storage_root=self.workspace_root)

        # 6. Physical Rig & Modular Connector Slot Manager
        self.rig = RigManager(camera=self)

        # 7. Sidekick MCU + 220x176 Monochrome OLED & Rotary Controls
        self.sidekick = SidekickMcu()
        self.sidekick.attach_camera(self)
        self._active_iob_upload_core: Optional[int] = None
        self._asic_hook_handles: List[int] = []
        self.trace_probe: Optional[TraceProbe] = None

        # Execution & Power Control
        self.is_running = False
        self.instruction_count = 0
        self.is_booted = False

        # Power Lifecycle (STANDBY, BOOTING, ON)
        self.POWER_STANDBY = "STANDBY"
        self.POWER_BOOTING = "BOOTING"
        self.POWER_ON = "ON"
        self.power_state = self.POWER_STANDBY
        self.boot_progress = 0.0
        self.on_state_change: Optional[Callable[[str], None]] = None

    def fw(self, stock_addr: int) -> int:
        """Stock 7.4.1 firmware address -> address in the loaded image (identity without a map)."""
        return self.addr_map.to_fw(stock_addr)

    def to_stock(self, fw_addr: int) -> int:
        """Address in the loaded image -> stock 7.4.1 address."""
        return self.addr_map.to_stock(fw_addr)

    def is_idle_pc(self, pc: int) -> bool:
        return self.to_stock(pc) in self.IDLE_LOOP_PCS

    def set_addr_map(self, addr_map: Optional[AddrMap]):
        """Switch the address map; re-installs the address-bound hooks."""
        self.addr_map = addr_map if addr_map is not None else AddrMap()
        self.cpu.addr_map = self.addr_map
        self.cpu.irq_vector = self.irq_vector = self.fw(FirmwareManager.DEFAULT_IRQ_VECTOR)
        self.reset_pc = self.fw(FirmwareManager.DEFAULT_RESET_PC)
        self._install_idle_wake_hook()

    def _install_idle_wake_hook(self):
        """Fast IRQ wake: at the scheduler idle loop with no ready thread and a pending IRQ, deliver
        the interrupt IN PLACE (redirect PC to the IRQ vector) so the ISR runs within the current
        ``emu_start`` instead of stopping the core.

        Delivering in-place (rather than ``emu_stop`` + re-inject per slice) lets the dense stream of
        per-chunk NAND/sDMA completion interrupts that the YAFFS multi-partition mount waits on be
        serviced without thousands of costly ``emu_start`` round-trips -- the mount completes in a
        few seconds of wall time and ``init_filesystem`` reaches bit 0x8. ``inject_irq`` is a no-op
        when interrupts are masked, so this never disturbs a critical section.
        """
        if getattr(self, "_idle_wake_hook_handle", None) is not None:
            try:
                self.cpu.mu.hook_del(self._idle_wake_hook_handle)
            except Exception:
                pass
        exec_ptr_addr = self.fw(self.TX_THREAD_EXECUTE_PTR)
        idle = self.fw(self.IDLE_LOOP_ENTRY)

        intc = self.intc
        cpu = self.cpu

        def _idle_wake_hook(uc, address, size, user_data):
            # Cheap guards first (this fires on every idle-loop iteration): only touch memory /
            # deliver when an unmasked line is actually pending and IRQs are enabled.
            if not intc.has_pending_irq() or not cpu.are_interrupts_enabled():
                return
            try:
                exec_ptr = struct.unpack("<I", uc.mem_read(exec_ptr_addr, 4))[0]
            except Exception:
                exec_ptr = 0
            if exec_ptr == 0:
                cpu.inject_irq()

        self._idle_wake_hook_handle = self.cpu.mu.hook_add(unicorn.UC_HOOK_CODE, _idle_wake_hook, None, idle, idle)

    def _install_iob_xaui_hook(self):
        """Serve the IOB XAUI AHB aperture (0x1C000000) link-status words from IobXauiWindow.

        The aperture sits below the bus device-hook window (0x40000000..0x7FFFFFFF), so a bus
        Device would never be invoked for it. This dedicated MEM_READ hook answers the XAUI
        PCS/PHY status offsets the firmware polls (FUN_80727028), overwriting the backing RAM
        with the link-up value for the beat; all other reads keep the RAM contents. Writes into
        the window fall through to RAM.
        """
        win = self.iob_xaui

        def _xaui_read_hook(uc, access, address, size, value, user_data):
            off = address - 0x1C000000
            if not win.is_status_reg(off):
                return
            val = win.read(off, size)
            try:
                if size == 1:
                    uc.mem_write(address, bytes([val & 0xFF]))
                elif size == 2:
                    uc.mem_write(address, struct.pack("<H", val & 0xFFFF))
                else:
                    uc.mem_write(address, struct.pack("<I", val & 0xFFFFFFFF))
            except Exception:
                pass

        self._iob_xaui_hook_handle = self.cpu.mu.hook_add(
            unicorn.UC_HOOK_MEM_READ, _xaui_read_hook, None, 0x1C000000, 0x1C0FFFFF
        )

    def _install_fan_spinup_hook(self):
        """Compress the fan-tachometer spin-up sleep inside ``HAL_Temp_SpeedTest``.

        ``HAL_Temp_SpeedTest`` (@0x809B061C) starts the BRAIN fan at full PWM, then calls
        ``tx_thread_sleep(6000)`` (@0x80E9E32C) to wait ~6 s for the fan to reach speed before it
        samples the tachometer (``fan_tach_read`` @0x809B18B0 -> ``fan_tach_regread`` @0x809B750C,
        answered by ``MaxFanController`` @ I2C1 0x4D). In the emulator's compressed tick model a
        6000-tick ThreadX sleep never expires within a practical boot, so the fan worker strands and
        the Fan init-event bit 0x800 never sets.

        This hook tracks whether the CPU is executing inside the ``HAL_Temp_SpeedTest`` body and,
        when ``tx_thread_sleep`` is entered from there, clamps its tick argument (r0) to
        ``FAN_SPINUP_SLEEP_TICKS``. The firmware still performs the start -> sleep -> tach-read ->
        classify sequence unchanged; only the spin-up *duration* is compressed, which is the same
        modeling decision the one-OVF-per-slice tick cadence already makes for every timed wait.
        All addresses go through ``self.fw()`` so the hook is correct under a relinked
        (``--addr-map``) image as well as the stock layout.
        """
        for h in ("_fan_spinup_enter_h", "_fan_spinup_exit_h", "_fan_spinup_sleep_h"):
            handle = getattr(self, h, None)
            if handle is not None:
                try:
                    self.cpu.mu.hook_del(handle)
                except Exception:
                    pass
            setattr(self, h, None)

        st_entry = self.fw(self.HAL_TEMP_SPEEDTEST_ENTRY)
        st_ret = self.fw(self.HAL_TEMP_SPEEDTEST_RET)
        sleep_entry = self.fw(self.TX_THREAD_SLEEP_ENTRY)
        clamp = self.FAN_SPINUP_SLEEP_TICKS
        state = self._fan_spinup_active  # one-element list, survives across slices

        def _enter(uc, address, size, user_data):
            state[0] = True

        def _exit(uc, address, size, user_data):
            state[0] = False

        def _sleep(uc, address, size, user_data):
            if state[0]:
                r0 = uc.reg_read(unicorn.arm_const.UC_ARM_REG_R0)
                if r0 > clamp:
                    uc.reg_write(unicorn.arm_const.UC_ARM_REG_R0, clamp)

        self._fan_spinup_enter_h = self.cpu.mu.hook_add(
            unicorn.UC_HOOK_CODE, _enter, None, st_entry, st_entry)
        self._fan_spinup_exit_h = self.cpu.mu.hook_add(
            unicorn.UC_HOOK_CODE, _exit, None, st_ret, st_ret)
        self._fan_spinup_sleep_h = self.cpu.mu.hook_add(
            unicorn.UC_HOOK_CODE, _sleep, None, sleep_entry, sleep_entry)

    def _init_hardware(self):
        """Cleanly initialize or re-initialize SoC hardware, registers, and memory mappings."""
        # Save previous log lines if re-initializing
        old_logs = list(self.uarts[4].completed_lines) if hasattr(self, "uarts") and 4 in self.uarts else []

        # 1. Initialize Core Architecture
        self.cpu = ArmCpu()
        self.cpu.addr_map = self.addr_map
        self.cpu.irq_vector = self.irq_vector
        self.bus = SystemBus(self.cpu)

        # 2. Interrupt Controller
        self.intc = OmapIntc()

        self._idle_wake_hook_handle = None
        self._install_idle_wake_hook()

        # 3. L4 Interconnect AP, System Control Module (SCM), Clock Management (PRCM), and Wakeup PRM
        self.l4_core_ap = OmapL4Ap(name="L4_CORE_AP", base_addr=OmapL4Ap.BASE_ADDR_L4_CORE)
        self.bus.register_device(OmapL4Ap.BASE_ADDR_L4_CORE, OmapL4Ap.SIZE, self.l4_core_ap)

        self.scm = OmapScm()
        self.bus.register_device(OmapScm.BASE_ADDR, OmapScm.SIZE, self.scm)

        self.scm_id = OmapScmId()
        self.bus.register_device(OmapScmId.BASE_ADDR, OmapScmId.SIZE, self.scm_id)

        self.prcm = OmapPrcm(self.cpu)
        self.bus.register_device(OmapPrcm.BASE_ADDR, OmapPrcm.SIZE, self.prcm)

        self.prm = OmapPrm()
        self.bus.register_device(OmapPrm.BASE_ADDR, OmapPrm.SIZE, self.prm)

        self.l4_per_ap = OmapL4Ap(name="L4_PER_AP", base_addr=OmapL4Ap.BASE_ADDR_L4_PER)
        self.bus.register_device(OmapL4Ap.BASE_ADDR_L4_PER, OmapL4Ap.SIZE, self.l4_per_ap)

        # 4. INTC
        self.bus.register_device(OmapIntc.BASE_ADDR, OmapIntc.SIZE, self.intc)

        # 5. GPTimers (1..11)
        self.timers: Dict[int, OmapGPTimer] = {}
        for timer_id, (base, irq) in TIMER_MAP.items():
            tmr = OmapGPTimer(timer_id, irq, self.intc)
            self.timers[timer_id] = tmr
            self.bus.register_device(base, 0x1000, tmr)

        # 6. UARTs (1..4) and L4-Core UART3 compatibility alias
        self.uarts: Dict[int, OmapUart] = {}
        for uart_id, (base, irq) in UART_MAP.items():
            u = OmapUart(uart_id, irq, self.intc)
            self.uarts[uart_id] = u
            self.bus.register_device(base, 0x1000, u)
        for alias_base, target_uart_id in UART_ALIASES.items():
            if target_uart_id in self.uarts:
                self.bus.register_device(alias_base, 0x1000, self.uarts[target_uart_id])

        if old_logs:
            self.uarts[4].completed_lines.extend(old_logs)

        # 7. I2C Controllers & Slave Devices
        self.i2c: Dict[int, OmapI2c] = {}
        for bus_id, (base, irq) in I2C_MAP.items():
            ctrl = OmapI2c(bus_id, irq, self.intc)
            self.i2c[bus_id] = ctrl
            self.bus.register_device(base, 0x1000, ctrl)

        # Attach I2C Slaves:
        # IOB UCD9090: live single-head FW drives bus 2 (OMAP I2C3) @ 0x70; index table lists 0x7C.
        # Share rail dict so fault injection on self.ucd_iob is visible at both 0x70 and 0x7C.
        self.ucd_iob = make_iob_ucd9090(0x70)
        self.ucd_iob_bus2 = self.ucd_iob
        self.ucd_iob_idx = make_iob_ucd9090(0x7C)
        self.ucd_iob_idx.rails = self.ucd_iob.rails

        # I2C1: Power Management (TWL4030 @ 0x48), Thermal (TMP411 @ 0x4C), LED Driver (0x45),
        #       IOB PMBus UCD9090 index entry (0x7C), BRAIN Fan Controller (MAX6639-class @ 0x4D),
        #       RSB OLPF Expander (0x38)
        self.pmic = Twl4030Pmic(0x48)
        self.thermal = Tmp411Thermal(0x4C)
        # BRAIN fan controller (MAX6639-class dual-channel PWM/tach). The firmware's thermal/fan
        # HAL (temp_hal_weapon.c) drives it over I2C1 @ 0x4D: fan_init (@0x8067049C) ->
        # HAL_Temp_Fan_Control_Init (@0x809B09A8) -> detect_fan_type (@0x809B08C4) ->
        # HAL_Temp_SpeedTest (@0x809B061C), which spins the fan up and reads its tachometer. The
        # model answers the tach-count registers so the measured RPM lands in the firmware's valid
        # band and the Fan init-event bit 0x800 sets. (See MODEL_FIDELITY_AUDIT.md "Fan tach".)
        self.fan_controller = MaxFanController(0x4D)
        self.i2c[1].attach_slave(I2cSlave(0x45))
        self.i2c[1].attach_slave(self.pmic)
        self.i2c[1].attach_slave(self.thermal)
        self.i2c[1].attach_slave(self.ucd_iob_idx)
        self.i2c[1].attach_slave(self.fan_controller)
        self.i2c[1].attach_slave(FixedIdI2cDevice(0x38, "RSB_OLPF", 0x00))
        self.i2c[1].attach_slave(Twl4030Pmic(0x49))
        self.i2c[1].attach_slave(Twl4030Pmic(0x4A))
        self.i2c[1].attach_slave(Twl4030Pmic(0x4B))
        self.i2c[1].attach_slave(Twl4030Pmic(0x1B))
        self.i2c[1].attach_slave(Twl4030Pmic(0x19))

        # I2C2: Optical Low Pass Filter (OLPF EEPROM @ 0x54), ISP UCD9090 (0x70),
        #       Sensor UCD90160 (0x65), Si5346 Clock Synth (0x6C), Sensor DAC7578 (0x49/0x4B),
        #       FocalTech Touch 7.0 (0x3E), LSB FPGA Temp (0x4C), LSB Video Clk Gen (0x67)
        self.olpf = OlpfEeprom(0x54)
        self.ucd_isp = make_isp_ucd9090(0x70)
        self.ucd_sensor = make_sensor_ucd90160(0x65)
        self.si5346 = Si5346ClockSynth(0x6C)
        self.sensor_dac1 = Dac7578SensorDac(0x49)
        self.sensor_dac2 = Dac7578SensorDac(0x4B)
        self.focaltech = FocalTechTouch(0x3E)
        self.i2c[2].attach_slave(self.olpf)
        self.i2c[2].attach_slave(self.ucd_isp)
        self.i2c[2].attach_slave(self.ucd_sensor)
        self.i2c[2].attach_slave(self.si5346)
        self.i2c[2].attach_slave(self.sensor_dac1)
        self.i2c[2].attach_slave(self.sensor_dac2)
        self.i2c[2].attach_slave(self.focaltech)
        self.i2c[2].attach_slave(FixedIdI2cDevice(0x4C, "LSB_FPGA_TEMP", 0x55))
        self.i2c[2].attach_slave(FixedIdI2cDevice(0x67, "LSB_VID_CLK", 0xC0))
        self.i2c[2].attach_slave(EdidEeprom(0x50))

        # I2C3: Atmel maXTouch touch controller (0x4B), EDID EEPROM (0x50), PMIC sub-bus,
        #       and live single-head bus-2 scan targets (0x70 IOB UCD9090, 0x65 UCD90160,
        #       0x3E FocalTech, 0x3B Audio Codec, 0x57 SDI Serializer, 0x27 LCD7 GPIO Exp)
        self.maxtouch = MaXTouchDevice(0x4B, irq_callback=lambda: self.intc.assert_irq(58))
        self.edid = EdidEeprom(0x50)
        self.focaltech_rear = FocalTechTouch(0x3E)
        self.i2c[3].attach_slave(self.maxtouch)
        self.i2c[3].attach_slave(self.edid)
        self.i2c[3].attach_slave(self.ucd_iob)
        self.i2c[3].attach_slave(self.ucd_sensor)
        self.i2c[3].attach_slave(self.focaltech_rear)
        self.i2c[3].attach_slave(FixedIdI2cDevice(0x3B, "IOB_AUDIO_CODEC", 0x0C))
        self.i2c[3].attach_slave(FixedIdI2cDevice(0x57, "IOB_SDI_SER", 0x00))
        self.i2c[3].attach_slave(FixedIdI2cDevice(0x27, "LCD7_GPIO_EXP", 0x00))
        self.i2c[3].attach_slave(Twl4030Pmic(0x48))
        self.i2c[3].attach_slave(Twl4030Pmic(0x49))
        self.i2c[3].attach_slave(Twl4030Pmic(0x4A))
        self.i2c[3].attach_slave(Twl4030Pmic(0x1B))
        self.i2c[3].attach_slave(Twl4030Pmic(0x19))
        self.i2c[3].attach_slave(self.thermal)

        # 8. GPIO Controllers (1..6)
        self.gpio: Dict[int, OmapGpio] = {}
        for mod_id, (base, irq) in GPIO_MAP.items():
            g = OmapGpio(mod_id, irq, self.intc)
            self.gpio[mod_id] = g
            self.bus.register_device(base, 0x1000, g)

        # 9. Display Subsystem (DSS)
        self.dss = OmapDss(self.bus)
        self.bus.register_device(OmapDss.BASE_ADDR, OmapDss.SIZE, self.dss)

        # 10. SDRAM Controller (SDRC @ 0x6D000000) & General Purpose Memory Controller (GPMC @ 0x6E000000)
        self.sdrc = OmapSdrc()
        self.bus.register_device(OmapSdrc.BASE_ADDR, OmapSdrc.SIZE, self.sdrc)

        self.gpmc = OmapGpmc(intc=self.intc)
        self.bus.register_device(OmapGpmc.BASE_ADDR, OmapGpmc.SIZE, self.gpmc)

        # GPMC CS1 (FPGA Board Space @ 0x18000000) and CS2 (FPGA Aperture @ 0x1C000000..0x1FFFFFFF)
        self.cpu.uc.mem_map(0x18000000, 0x10000)
        self.bus.add_ram_region(0x18000000, 0x10000)
        self.cpu.uc.mem_map(0x1C000000, 0x04000000)
        # IobXauiWindow state tracker coupled to c2c.iob_ahb (0x1C000000..0x1FFFFFFF via SystemBus).
        self.iob_xaui = IobXauiWindow(link_up=True, media_present=False)

        # Fan tach spin-up sleep compression (HAL_Temp_SpeedTest). The one-element list tracks
        # whether the CPU is inside HAL_Temp_SpeedTest; it must exist before the hook installs.
        self._fan_spinup_active = [False]
        self._install_fan_spinup_hook()

        # 10c. Multichannel SPI Controllers (McSPI 1..4)
        self.mcspi: Dict[int, OmapMcspi] = {}
        for port_id, (base, irq) in MCSPI_MAP.items():
            spi = OmapMcspi(port_id, base, irq, intc=self.intc)
            self.mcspi[port_id] = spi
            self.bus.register_device(base, 0x1000, spi)

        # 10b. System DMA (sDMA Controller @ 0x48056000)
        self.sdma = OmapSdma(intc=self.intc, cpu=self.cpu, gpmc=self.gpmc, mcspi=self.mcspi)
        self.bus.register_device(OmapSdma.BASE_ADDR, OmapSdma.SIZE, self.sdma)
        self.sdma.bind_mcspi(self.mcspi)

        # 10d. Multi-Channel Buffered Serial Ports (McBSP 2..5), HDQ / 1-Wire & OMAP Camera ISP
        self.mcbsp: Dict[int, OmapMcBSP] = {}
        for mcbsp_id, (base, irq) in MCBSP_MAP.items():
            bsp = OmapMcBSP(mcbsp_id, irq, intc=self.intc)
            self.mcbsp[mcbsp_id] = bsp
            self.bus.register_device(base, OmapMcBSP.SIZE, bsp)

        self.hdq = OmapHdq1Wire(intc=self.intc)
        self.bus.register_device(OmapHdq1Wire.BASE_ADDR, OmapHdq1Wire.SIZE, self.hdq)

        self.cam_isp = OmapCamIsp()
        self.bus.register_device(OmapCamIsp.BASE_ADDR, OmapCamIsp.SIZE, self.cam_isp)

        # 11. Coprocessor transport (FW-proven). Config registers move over SPI as a byte
        # frame [0x81/0x01][addr u32][data u32] + ACK 0x1F (see coprocessors/c2c.py), bound
        # to the McSPI controllers (ts_isp1/ts_isp2/ts_iob0/ts_iob1/ts_fpga). The GPMC IOB
        # AHB mailbox @0xA5800000 and GPMC CS2 XAUI window @0x1C000000 are separate devices.
        # Note: 0x49000000 is L4-PER AP.
        self.c2c = CoprocessorTransport(intc=self.intc, mcspi=self.mcspi, gpio=self.gpio)
        self.c2c.iob_ahb.xaui_window = self.iob_xaui
        self.c2c.iob_ahb.sata_media_present = self.iob_xaui.media_present
        self.bus.register_device(IobMailboxDevice.BASE_ADDR, IobMailboxDevice.SIZE, self.c2c.mailbox)
        self.bus.register_device(self.c2c.iob_ahb.BASE_ADDR, self.c2c.iob_ahb.SIZE, self.c2c.iob_ahb)

        # Xtensa coprocessor cores (with local MMIO doorbell bridged to IobXauiWindow).
        self.iob0 = Iob0Coprocessor()
        self.iob1 = Iob1Coprocessor()
        self.isp1 = IspCoprocessor(core_id=2)
        self.isp2 = IspCoprocessor(core_id=3)
        self.iob0.on_mmio_write = self.iob_xaui.notify_xtensa_doorbell
        self.iob1.on_mmio_write = self.iob_xaui.notify_xtensa_doorbell

        # 11b. Tensilica IOB0/IOB1 local shared-memory doorbell MMIO (DDR descriptor kick,
        # distinct from the SPI register frame and the GPMC mailbox).
        self.iob0_doorbell = IobDoorbellDevice(
            core_id=0,
            bus=self.bus,
            coprocessor=self.iob0,
            mailbox_base_addr=self.fw(self.IOB0_MAILBOX)
        )
        self.bus.register_device(IobDoorbellDevice.BASE_ADDR_IOB0, IobDoorbellDevice.SIZE, self.iob0_doorbell)

        self.iob1_doorbell = IobDoorbellDevice(
            core_id=1,
            bus=self.bus,
            coprocessor=self.iob1,
            mailbox_base_addr=self.fw(self.IOB1_MAILBOX)
        )
        self.bus.register_device(IobDoorbellDevice.BASE_ADDR_IOB1, IobDoorbellDevice.SIZE, self.iob1_doorbell)

        # Wire GPIO pin 130 (Bank 5 Pin 2) to monitor multiplexer (MONITOR_HDMI_MUX)
        def _on_gpio5_pin_changed(pin: int, high: bool):
            if pin == 2:
                self.iob0.hdmi_connected = high
        self.gpio[5].on_pin_changed = _on_gpio5_pin_changed

        # 12. TI TMS320C64x+ DSP Subsystem, Mailbox, IVA2.2 MMU & Servers
        self.dsp = TiC64xDsp()
        self.dsplink = DspLinkIpc(self.dsp)
        self.imaging_server = CImagingServer(self.dsplink)
        self.audio_server = RAudioServer(self.dsplink)
        self.omap_mailbox = OmapMailbox(intc=self.intc)
        self.bus.register_device(OmapMailbox.BASE_ADDR, OmapMailbox.SIZE, self.omap_mailbox)
        self.iva2_mmu = OmapIva2Mmu()
        self.bus.register_device(OmapIva2Mmu.BASE_ADDR, OmapIva2Mmu.SIZE, self.iva2_mmu)

        # 13. Accessory Bus Subsystem
        self.accessory_bus = AccessoryBus(camera=self)

        self.instruction_count = 0
        self.is_booted = False

    def log_system(self, message: str):
        """Append an entry to system logs (UART4) and terminal stdout."""
        self.uarts[4].completed_lines.append(message)
        print(message, flush=True)

    def apply_entry(self, fw_bytes: bytes):
        """Reset PC / SP / IRQ handler from the image's vector header (stock map as fallback)."""
        vec = FirmwareManager.parse_vectors(fw_bytes)
        if vec is not None:
            self.reset_pc, self.reset_sp = vec["reset_pc"], vec["sp"]
            self.irq_vector = vec.get("irq_vector", self.fw(FirmwareManager.DEFAULT_IRQ_VECTOR))
        else:
            self.reset_pc = self.fw(FirmwareManager.DEFAULT_RESET_PC)
            self.reset_sp = FirmwareManager.DEFAULT_SP
            self.irq_vector = self.fw(FirmwareManager.DEFAULT_IRQ_VECTOR)
        self.entry_from_header = vec is not None
        self.cpu.irq_vector = self.irq_vector
        self.cpu.pc = self.reset_pc
        self.cpu.sp = self.reset_sp
        self.cpu.cpsr = ArmCpu.MODE_SVC | 0xC0 # Supervisor mode, IRQ/FIQ disabled

    def load_firmware(self, firmware_path: Optional[str] = None):
        """Load genuine RED DSMC2 program into DDR RAM at 0x80000000."""
        if firmware_path is None:
            firmware_path = self.firmware_path or os.path.join(self.firmware_slot_dir, "dsmc_program.mem")

        with open(firmware_path, "rb") as f:
            fw_bytes = f.read()

        self.bus.load_binary(0x80000000, fw_bytes)
        self.apply_entry(fw_bytes)

        # Seed authentic NAND flash geometry descriptor in DDR (Micron MT29F8G08 256MB SLC):
        # driver initialized flag = 1, ID = 0x2C (Micron) / 0xBA (256MB SLC), pointer to the
        # geometry struct (page=2048, blk_pages=64, blks=2048, oob=64)
        self.bus.write(self.fw(self.NAND_DRV_INIT_FLAG), 4, 0x00000001)
        self.bus.write(self.fw(self.NAND_DRV_ID), 4, 0x0000BA2C)
        self.bus.write(self.fw(self.NAND_DRV_GEOMETRY_PTR), 4, self.fw(self.NAND_GEOMETRY_STRUCT))
        # Seed default CAMERA_TYPE fallback (-> 0x0016 Scarlet-W)
        self.bus.write(self.fw(self.CAMERA_TYPE_FALLBACK), 2, 0x0016)

        # Stage synthesized YAFFS2 ``/env`` (/env/PARTITION_TABLE v6) and ``/image2``
        # (cdb2/factory.db plus isp/iob0/iob1 iram/dram.bin) into the emulated GPMC NAND
        # with sub-sector OOB tags (+4/+20/+36/+52) and per-block seqNumber tags, so the
        # firmware's init_filesystem mount (@0x80008310) registers real file objects and
        # compiles all SQLite CDB2 prepared statements cleanly without triggering the v0->v6
        # partition-table upgrade/reformat loop.
        from emulator.devices.nand_image import (
            PARTITIONS,
            write_env_image,
            write_image_partition,
        )
        write_env_image(self.gpmc, env_start_block=PARTITIONS[0][1])
        write_image_partition(
            self.gpmc,
            image_start_block=PARTITIONS[2][1],
            include_xtensa_blobs=True,
        )
        self._install_asic_upload_hooks()

        # Pre-stage authentic firmware splash screen into DDR LCD framebuffer (0x87400000)
        splash_file = os.path.join(self.firmware_slot_dir, "res", "splash_screen.bin")
        if not os.path.exists(splash_file):
            splash_file = os.path.join(self.workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "res", "splash_screen.bin")
        if os.path.exists(splash_file):
            try:
                import zlib
                from PIL import Image
                with open(splash_file, "rb") as sf:
                    sdata = sf.read()
                if sdata.startswith(b"REDZLIB0"):
                    decomp = zlib.decompress(sdata[12:])
                    rgb_pixels = decomp[8:8 + (1024 * 576 * 3)]
                    img = Image.frombytes("RGB", (1024, 576), rgb_pixels)
                    rgba_buf = img.convert("RGBA").tobytes()
                    self.bus.load_binary(0x87400000, rgba_buf)
                    self.bus.load_binary(0x8C000000, rgba_buf)
            except Exception:
                pass

    def _deliver_idle_irq(self):
        """If the core is parked in the scheduler idle loop with a deliverable IRQ, take it.

        ThreadX's ``_tx_thread_schedule`` idle loop (0x80E9C368) spins with IRQs enabled waiting
        for the next hardware interrupt to ready a thread. Unicorn has no hardware INTC, so the
        pending line is delivered as an ARM IRQ exception at the slice boundary. The in-place
        idle-wake hook (``_install_idle_wake_hook``) delivers interrupts that arrive *during* a
        slice, so the per-chunk NAND/sDMA completions of the YAFFS mount are serviced promptly
        inside one ``emu_start``; this boundary delivery covers the case where the slice started
        already parked at idle.
        """
        if self.is_idle_pc(self.cpu.pc) and self.intc.has_pending_irq() \
                and self.cpu.are_interrupts_enabled():
            self.cpu.inject_irq()

    def _tick_timers(self):
        """Advance running GPTimers one slice. Timer 2 is the ThreadX 1000 Hz system tick
        (TLDR 0xFFFFFFE0 -> 32-count period -> one OVF -> IRQ 38 per slice)."""
        for tmr in self.timers.values():
            if tmr.tclr & 0x01:  # Running
                tmr.tick(steps=32 if tmr.timer_id == 2 else 100)

    def step_slice(self, count: int = 500_000):
        """Execute an instruction slice and service interrupts/timers."""
        self._deliver_idle_irq()

        # Run CPU slice. The wall-clock timeout guarantees the call returns even if
        # the core halts (WFI with no interrupt source) and never retires `count`.
        try:
            self.cpu.run(self.cpu.pc, 0, count=count, timeout_us=self.SLICE_TIMEOUT_US)
            self.instruction_count += count
        except Exception as e:
            # Check if exception is benign or stop
            pass

        self._tick_timers()

    # Upper bound on wall-clock time for one interactive CPU slice (50ms max).
    SLICE_TIMEOUT_US = 50_000

    def boot(self, initial_instructions: int = 45_000_000, chunk: Optional[int] = None,
             progress_cb: Optional[Callable[[float], None]] = None):
        """Perform initial CRT and RTOS thread bringup.

        ``chunk`` splits execution into resumable slices (verified bit-identical to a
        single run) so callers can report progress via ``progress_cb(fraction)``.
        """
        step_size = chunk if (chunk and chunk < initial_instructions) else 1_000_000
        done = 0
        while done < initial_instructions:
            n = min(step_size, initial_instructions - done)
            self._deliver_idle_irq()
            self.cpu.run(self.cpu.pc, 0, count=n)
            done += n
            self.boot_progress = done / initial_instructions
            if progress_cb:
                progress_cb(self.boot_progress)
            self._tick_timers()

        self.instruction_count += initial_instructions
        self.is_booted = True
        self.power_state = self.POWER_ON
        self.boot_progress = 1.0

        # Stage live sensor feed into DDR primary LCD framebuffer (0x87400000)
        sensor_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "res", "sensor_feed_cinema.jpg")
        if not os.path.exists(sensor_path):
            sensor_path = os.path.join(self.workspace_root, "emulator", "res", "sensor_feed_cinema.jpg")
        if os.path.exists(sensor_path):
            try:
                from PIL import Image
                sim = Image.open(sensor_path).resize((1024, 576), Image.Resampling.LANCZOS)
                s_rgba = sim.convert("RGBA").tobytes()
                self.bus.load_binary(0x87400000, s_rgba)
                self.bus.load_binary(0x8C000000, s_rgba)
            except Exception:
                pass

    def init_event_flags(self) -> int:
        """Current set bits in the primary driver-init event-flag group (0 before kernel is up)."""
        try:
            return struct.unpack(
                "<I",
                self.bus.read_mem(
                    self.fw(self.INIT_EVENT_FLAGS_GROUP) + self.INIT_EVENT_FLAGS_SET_OFFSET, 4
                ),
            )[0]
        except Exception:
            return 0

    def boot_to_late_init(
        self,
        kernel_instructions: int = 45_000_000,
        max_instructions: int = 400_000_000,
        slice_size: int = 100_000,
        progress_cb: Optional[Callable[[float], None]] = None,
        _already_booted: bool = False,
    ) -> Dict[str, Any]:
        """Boot the RTOS kernel, then drive the scheduler past the idle park into late driver init.

        ``boot()`` retires a fixed instruction budget in coarse (1M) slices and delivers the
        GPTimer2 1000 Hz tick IRQ at most once per slice, so ThreadX only sees a few dozen ticks
        over the whole run -- far too few for its timer thread to expire the sleeps and post the
        semaphores that ready the next threads. Execution therefore parks in ``_tx_thread_schedule``
        (0x80E9C368) with ``SystemInitThread`` still SEMAPHORE-blocked: late driver init, UI, RCP
        and record/playback never run.

        This driver keeps the kernel's own cadence faithful but *fine-grained*: it runs short
        (~100k) slices and, every time the core returns to the scheduler idle loop with a pending
        unmasked IRQ, delivers it, so the timer tick stream is continuous and the scheduler advances
        normally. That carries boot from the bare idle park (``SystemInitThread`` blocked, 4 threads)
        to: ``SystemInitThread`` COMPLETED, the ``Driver thread`` (thread_DRIVER_entry @0x8066C92C)
        and ``Starter Thread`` spawned, and the CRYPT/RTC/FileX/NAND-FS children run with
        ``init_filesystem`` (@0x80008310) and ``cdb2_init`` (@0x8007FB58) complete (bit 0x8 set),
        stopping at ``LATE_INIT_FLAGS_TARGET`` (``0x001003BF``).

        Deterministic: progress is bounded purely by the instruction budget, with no wall-clock
        dependence, so stock and relinked (``--addr-map``) images advance identically.

        Returns a progress dict (threads, event flags, instructions retired, milestone reached).
        """
        if not _already_booted:
            self.boot(initial_instructions=kernel_instructions, chunk=3_000_000)

        target = self.LATE_INIT_FLAGS_TARGET
        done = 0
        # Milestone = every bit of the late-init group set, tested as a MASK not a magnitude: the
        # NAND-FS child (0x8) can complete before FileX (0x2), so a bare ``flags >= 0x7`` would stop
        # at 0xD (RTC|CRYPT|NAND, FileX still pending). Require ``flags & 0x7 == 0x7`` so RTC, FileX
        # and CRYPT have all run; NAND (0x8) coming too is a bonus, not a substitute.
        reached = (self.init_event_flags() & target) == target
        # Require a minimum of real post-kernel progress even if flags look set early.
        min_drive = 20_000_000
        # The NAND/YAFFS mount path (init_filesystem -> nand_media_open) reads NAND through sDMA and
        # blocks the mounting thread on a per-chunk DMA-completion IRQ (line 3 / IRQ 15). The idle
        # wake must deliver that IRQ promptly, so each slice boundary DRAINS the idle-IRQ backlog
        # (``_deliver_idle_irq(drain=...)``) rather than injecting once -- otherwise the
        # multi-partition mount crawls and the NAND-FS flag (0x8) never sets. The timer tick stays
        # one-per-slice as before, so the cadence remains deterministic and lockstep with relinked
        # (``--addr-map``) images.
        while done < max_instructions and not (reached and done >= min_drive):
            self._deliver_idle_irq()
            try:
                self.cpu.run(self.cpu.pc, 0, count=slice_size)
            except Exception:
                pass
            done += slice_size
            self.instruction_count += slice_size
            self._tick_timers()
            if progress_cb and (done % (slice_size * 50) == 0):
                progress_cb(min(1.0, done / max_instructions))
            reached = (self.init_event_flags() & target) == target

        self.is_booted = True
        self.power_state = self.POWER_ON
        flags = self.init_event_flags()
        threads = self.get_threads()
        driver = next((t for t in threads if t["name"] == "Driver thread"), None)
        reached_mask = (flags & target) == target
        return {
            "milestone": "late_driver_init" if reached_mask else "idle_park",
            "reached": reached_mask,
            "init_event_flags": flags,
            # Whether the NAND/YAFFS filesystem mount also completed (init_filesystem set bit 0x8).
            "nand_fs_mounted": bool(flags & 0x8),
            "late_init_instructions": done,
            "total_instructions": self.instruction_count,
            "pc": f"0x{self.to_stock(self.cpu.pc):08X}",
            "driver_thread_spawned": driver is not None,
            "threads": threads,
        }

    # weapon_boards_init async board-bring-up group: each of the six board workers
    # (IOB/ISP-pre/ISP/RSB/LSB/side-handle) sets one bit in a dynamically created ThreadX
    # event-flags group when it completes; ``weapon_boards_init`` AND-waits on all six (0x3F).
    # Bit 0x10 is the LSB (Left Side Board) worker ``weapon_left_side_board_init``.
    BOARD_GROUP_ALL_WORKERS = 0x3F
    BOARD_GROUP_LSB_BIT = 0x10

    def boot_to_ui_bringup(
        self,
        max_instructions: int = 300_000_000,
        slice_size: int = 200_000,
        _already_booted: bool = False,
    ) -> Dict[str, Any]:
        """Drive boot past the NAND-FS mount and clear the board-bring-up barrier.

        After ``boot_to_late_init`` reaches the filesystem mount (init event flags
        ``0xC21000FF``: RTC|FileX|CRYPT|NAND + the HW/Module-cap cascade), the Driver thread runs a
        second ``init_parallel`` cascade and blocks on the board-bring-up barrier
        ``wait_for_init_flags(0x03300FF7)`` (``UI_BRINGUP_FLAGS_BARRIER``).

        With peripheral-synchronised McSPI1-over-sDMA, GPIO-76/77 CS-mux routing, seeded LSB-FPGA
        status/version regs on McSPI1 CH2, ``MaxFanController`` @ I2C1 0x4D with fan spin-up
        sleep compression, and the IOB/XAUI AHB window at 0x1C000000, all four board-dependent bits
        (Boards 0x400, Fan 0x800, XAUI 0x200000, Mailbox 0x1000000) set, reaching ``0xC3300FFF``.
        """
        self.c2c.iob_ahb.iob_status_handshake_enabled = False
        self.c2c.iob_ahb.sata_shadow_sregs_enabled = False
        self.c2c.iob_ahb.sata_media_present = self.iob_xaui.media_present
        if not _already_booted:
            # boot_to_late_init already drives through the FS mount to ~0xC21000FF.
            self.boot_to_late_init()

        barrier = self.UI_BRINGUP_FLAGS_BARRIER
        done = 0
        flags = self.init_event_flags()
        while done < max_instructions and (flags & barrier) != barrier:
            self._deliver_idle_irq()
            try:
                self.cpu.run(self.cpu.pc, 0, count=slice_size)
            except Exception:
                pass
            done += slice_size
            self.instruction_count += slice_size
            self._tick_timers()
            flags = self.init_event_flags()

        self.is_booted = True
        self.power_state = self.POWER_ON
        flags = self.init_event_flags()
        barrier_passed = (flags & barrier) == barrier
        missing = barrier & ~flags
        blocked_boards = missing & self.UI_BRINGUP_BOARD_BITS
        # The IOB/LSB-FPGA XAUI link model is installed and presents an UP link on the status
        # words the firmware's ``lsb_fpga_report_xaui_status`` (@0x809BCF64) polls -- the IOB
        # AHB window (``IobXauiWindow`` @0x1C000000) answers the PCS/PHY status registers, and
        # the FPGA-side link regs are seeded on the ``ts_fpga`` SPI target. ``xaui_link_modeled``
        # reports that the model is present and (for the IOB-window half) was reached this boot.
        xaui_window_reached = self.iob_xaui.read_count > 0
        return {
            "milestone": "ui_bringup" if barrier_passed else "board_bringup_barrier",
            "barrier_passed": barrier_passed,
            "init_event_flags": flags,
            "ui_bringup_instructions": done,
            "total_instructions": self.instruction_count,
            "pc": f"0x{self.to_stock(self.cpu.pc):08X}",
            # The four board-dependent bits still clear at the barrier. Non-zero here identifies
            # the current blocker.
            "missing_flags": missing,
            "blocked_board_bits": blocked_boards,
            # The XAUI link-up register model is installed (IobXauiWindow + ts_fpga seeds).
            "xaui_link_modeled": True,
            "xaui_window_reached": xaui_window_reached,
            # The peripheral-synchronised McSPI1-over-sDMA coprocessor transport is modelled, so the
            # board workers run: Boards/XAUI/Mailbox now set (the LSB worker reaches and passes the
            # XAUI link check against the installed link-up model). Count of SPI frames clocked over
            # sDMA this boot (non-zero => the transport carried the board-init SPI reads).
            "spi_over_sdma_frames": getattr(self.sdma, "spi_dma_transfers", 0),
            # The fan controller + spin-up model is installed: the fan tach speed test now measures
            # a valid RPM and Fan 0x800 sets, so the whole board barrier passes (0xC3300FFF).
            "fan_tach_modeled": True,
            # Human-readable identification of the next blocker for the depth roadmap. The board
            # barrier (incl. Fan 0x800) now passes; the next blocker is the post-barrier SATA/Media
            # storage init, reported in full by ``boot_to_run_application``.
            "next_blocker": (
                "board bring-up now completes fully (Boards 0x400, Fan 0x800, XAUI 0x200000, "
                "Mailbox 0x1000000 all set; init event flags reach 0xC3300FFF). The Driver thread "
                "(@0x8066C92C) then dispatches the SATA/Media init_parallel stages and blocks on "
                "wait_for_init_flags(0x0C000000) (@0x8066D000) for the SATA (0x04000000) and Media "
                "(0x08000000) completion bits. Next milestone: SATA/AHCI + media storage bring-up "
                "(see boot_to_run_application)."
                if barrier_passed else
                "board bring-up incomplete: missing board bits 0x%X still clear at the barrier." % blocked_boards
            ),
            "threads": self.get_threads(),
        }

    def boot_to_run_application(
        self,
        max_instructions: int = 220_000_000,
        slice_size: int = 200_000,
    ) -> Dict[str, Any]:
        """Drive boot across the storage-init barrier toward ``run_application`` and pin the blocker."""
        # Reach the board barrier first (Fan included) via the existing depth probe.
        self.boot_to_ui_bringup()

        self.c2c.iob_ahb.iob_status_handshake_enabled = False
        self.c2c.iob_ahb.sata_shadow_sregs_enabled = False
        self.c2c.iob_ahb.sata_media_present = self.iob_xaui.media_present

        barrier = self.RUN_APP_FLAGS_BARRIER
        done = 0
        flags = self.init_event_flags()
        while done < max_instructions and (flags & barrier) != barrier:
            self._deliver_idle_irq()
            try:
                self.cpu.run(self.cpu.pc, 0, count=slice_size)
            except Exception:
                pass
            done += slice_size
            self.instruction_count += slice_size
            self._tick_timers()
            flags = self.init_event_flags()

        # Storage barrier crossed: keep driving so the IOB/ISP-download + DSS/display batch can
        # dispatch, and detect where it stalls. The loop stops once no new init bit has set for a
        # stall window (the display-batch dispatch gap) or the display batch is fully up.
        barrier_passed = (flags & barrier) == barrier
        post_target = self.DSS_DISPLAY_FLAGS | self.DSS_IOB_ISP_DOWNLOAD_BIT
        if barrier_passed:
            last_flags = flags
            stall = 0
            post_done = 0
            post_budget = min(60_000_000, max_instructions)
            while post_done < post_budget and (flags & post_target) != post_target and stall < 120:
                self._deliver_idle_irq()
                try:
                    self.cpu.run(self.cpu.pc, 0, count=slice_size)
                except Exception:
                    pass
                post_done += slice_size
                self.instruction_count += slice_size
                self._tick_timers()
                flags = self.init_event_flags()
                if flags != last_flags:
                    last_flags = flags
                    stall = 0
                else:
                    stall += 1

        self.is_booted = True
        self.power_state = self.POWER_ON
        flags = self.init_event_flags()
        missing = barrier & ~flags
        threads = self.get_threads()
        names = {t["name"]: t for t in threads}
        starter = names.get("Starter Thread")
        iob_isp_set = bool(flags & self.DSS_IOB_ISP_DOWNLOAD_BIT)
        display_missing = self.DSS_DISPLAY_FLAGS & ~flags
        return {
            "milestone": "run_application" if barrier_passed else "storage_init_barrier",
            "barrier_passed": barrier_passed,
            "init_event_flags": flags,
            # The board barrier (incl. Fan) is passed on entry; confirm it is retained.
            "board_barrier_passed": (flags & self.UI_BRINGUP_FLAGS_BARRIER) == self.UI_BRINGUP_FLAGS_BARRIER,
            "fan_bit_set": bool(flags & 0x800),
            "run_app_instructions": done,
            "total_instructions": self.instruction_count,
            "pc": f"0x{self.to_stock(self.cpu.pc):08X}",
            # Storage bits now set; this stays 0 once the barrier passes.
            "missing_flags": missing,
            "sata_bit_set": bool(flags & self.RUN_APP_SATA_BIT),
            "media_bit_set": bool(flags & self.RUN_APP_MEDIA_BIT),
            # The IOB/ISP binary download (post-storage, deps Mailbox|XAUI) also completes.
            "iob_isp_download_bit_set": iob_isp_set,
            # The DSS/display + DSP/audio init batch that gates the final 0xCF3CF7FF wait.
            "display_bits_missing": display_missing,
            # run_application (the Starter Thread) releases only when the Driver's final wait passes.
            "run_application_released": bool(starter is not None and starter["state"] != "SEMAPHORE"),
            "next_blocker": (
                "storage-init barrier crossed (SATA 0x04000000 + Media 0x08000000 set from the "
                "firmware's own sata_init @0x80670504 / media_init @0x8067060C code paths via the "
                "IOB-AHB SATA3 shadow-register model). The IOB/ISP binary download (0x1000) also "
                "completes. The Driver thread (@0x8066C92C) then dispatches the DSS/display + DSP/"
                "audio init_parallel batch -- Monitor Pipeline (0x2000 @0x8074C9E4), HDMI (0x4000), "
                "HDSDI (0x8000), DSP (0x40000 @0x80670FFC), Audio (0x80000) -- and blocks on its "
                "final wait_for_init_flags(0xCF3CF7FF). Under the current thread scheduler those "
                "display-batch init_parallel children are not resumed after the IOB/ISP-download "
                "bit sets, so boot stalls at 0x%08X (missing 0x%08X) with the Driver parked in the "
                "ThreadX scheduler (~0x80EA4A94) and run_application (Starter Thread @0x80008E24) "
                "still semaphore-blocked. Next milestone: DSS/DSP display-init batch dispatch."
                % (flags, display_missing)
                if barrier_passed else
                "board bring-up complete (0xC3300FFF, Fan 0x800 set) but the SATA/Media storage "
                "barrier 0x0C000000 did not cross (missing 0x%08X)." % missing
            ),
            "threads": threads,
        }

    def boot_to_application(
        self,
        max_instructions: int = 40_000_000,
        slice_size: int = 12_000,
        _already_at_ui_bringup: bool = False,
    ) -> Dict[str, Any]:
        """Drive boot past the full driver cascade (`0xCF3CF7FF`) into ``run_application``.

        With the IOB AHB status handshake (``0x1C0B0000..0x1C0B0FFF``), ``EdidEeprom(0x50)``
        on ``I2C2``, ``OmapMailbox`` (``0x48094000``), ``OmapIva2Mmu`` (``0x5D000000``) +
        ``IVA2_MEM`` (``0x5C000000``), and multi-chunk (>64B) Master TX in ``OmapI2c``,
        ``Driver thread`` completes the post-barrier cascade (SATA, Media, IOB/ISP Binary
        Download, Monitor Pipeline, HDMI, HDSDI, Monitor Splash Screen, DSP ``0x40000``,
        Contiguous Media Space ``0x10000000``, Audio ``0x80000``, and Cal Load ``0x800000`` ->
        ``0xDFBCFFFF``) and signals ``Starter Thread`` (``0x80008E24`` -> ``run_application``
        ``0x80008CB4``), which creates ``APP_SEMAPHORE`` (``0x814C6D1C``) and spawns
        ``Camera State Manager``.
        """
        if not _already_at_ui_bringup:
            self.boot_to_ui_bringup()

        self.c2c.iob_ahb.iob_status_handshake_enabled = True
        self.c2c.iob_ahb.sata_shadow_sregs_enabled = False
        self.c2c.iob_ahb.sata_media_present = self.iob_xaui.media_present

        barrier = self.APPLICATION_FLAGS_BARRIER
        app_sema_addr = self.fw(self.APP_SEMAPHORE_ADDR)
        done = 0

        def _is_ready() -> Tuple[bool, int, int, List[Dict[str, Any]]]:
            flags = self.init_event_flags()
            try:
                sema_magic = self.bus.read_u32(app_sema_addr)
            except Exception:
                sema_magic = 0
            threads = self.get_threads()
            csm = next((t for t in threads if t["name"] == "Camera State Manager"), None)
            ready = (
                (flags & barrier) == barrier
                and sema_magic == self.SEMAPHORE_MAGIC
                and csm is not None
            )
            return ready, flags, sema_magic, threads

        ready, flags, sema_magic, threads = _is_ready()
        while done < max_instructions and not ready:
            self._deliver_idle_irq()
            try:
                self.cpu.run(self.cpu.pc, 0, count=slice_size)
            except Exception:
                pass
            done += slice_size
            self.instruction_count += slice_size
            self._tick_timers()
            if (done % (slice_size * 50) == 0) or (
                (self.init_event_flags() & barrier) == barrier
                and self.bus.read_u32(app_sema_addr) == self.SEMAPHORE_MAGIC
            ):
                ready, flags, sema_magic, threads = _is_ready()

        if not ready:
            ready, flags, sema_magic, threads = _is_ready()

        self.c2c.iob_ahb.sata_shadow_sregs_enabled = True
        self.is_booted = True
        self.power_state = self.POWER_ON
        driver = next((t for t in threads if t["name"] == "Driver thread"), None)
        csm = next((t for t in threads if t["name"] == "Camera State Manager"), None)
        driver_completed = driver is not None and driver["state"] == "COMPLETED"
        app_sema_created = sema_magic == self.SEMAPHORE_MAGIC
        csm_spawned = csm is not None
        barrier_passed = (flags & barrier) == barrier and app_sema_created
        return {
            "milestone": "application_running" if barrier_passed else "driver_cascade_barrier",
            "barrier_passed": barrier_passed,
            "init_event_flags": flags,
            "driver_thread_completed": driver_completed,
            "app_semaphore_created": app_sema_created,
            "camera_state_manager_spawned": csm_spawned,
            "application_instructions": done,
            "total_instructions": self.instruction_count,
            "pc": f"0x{self.to_stock(self.cpu.pc):08X}",
            "threads": threads,
        }

    def boot_until(
        self,
        target_pc: Union[int, Set[int], Iterable[int]],
        max_instructions: int = 60_000_000,
        step_size: int = 250_000,
        on_hit: Optional[Callable[["Dsmc2Camera", int], None]] = None,
    ) -> bool:
        """Execute firmware slices (with IRQ and timer servicing) until PC reaches ``target_pc``.

        Allows behavioral tests to run directly to a named initialization or consumer site,
        inspect or poke registers/memory via ``on_hit(camera, pc)`` (or after return), and
        continue execution. Returns ``True`` if ``target_pc`` was hit within ``max_instructions``.
        """
        targets: Set[int] = {target_pc} if isinstance(target_pc, int) else set(target_pc)
        if not targets:
            return False

        hit_flag = {"hit": False, "pc": 0}

        def _bp_hook(uc, address, size, user_data):
            if address in targets:
                hit_flag["hit"] = True
                hit_flag["pc"] = address
                uc.emu_stop()

        min_pc = min(targets)
        max_pc = max(targets)
        hook_handle = self.cpu.mu.hook_add(unicorn.UC_HOOK_CODE, _bp_hook, None, min_pc, max_pc)

        done = 0
        try:
            while done < max_instructions and not hit_flag["hit"]:
                if self.cpu.pc in targets:
                    hit_flag["hit"] = True
                    hit_flag["pc"] = self.cpu.pc
                    break

                n = min(step_size, max_instructions - done)
                self._deliver_idle_irq()

                self.cpu.run(self.cpu.pc, 0, count=n)
                done += n
                self.instruction_count += n

                if hit_flag["hit"]:
                    break

                self._tick_timers()
        finally:
            try:
                self.cpu.mu.hook_del(hook_handle)
            except Exception:
                pass

        self.is_booted = True
        self.power_state = self.POWER_ON
        if hit_flag["hit"] and on_hit is not None:
            on_hit(self, hit_flag["pc"])
        return hit_flag["hit"]

    def run_dispatch_harness(
        self,
        entry_pc: int = 0x8066C92C,
        camera_type: Optional[int] = None,
        max_instructions: int = 100_000,
        extra_stubs: Optional[Dict[int, int]] = None,
    ) -> Dict[str, Any]:
        """Execute a thread/driver entry point directly with ThreadX primitives stubbed.

        Full-boot execution stops in `_tx_thread_schedule` (`0x80E9C368`) because timer/IRQ
        slices do not invoke `_tx_thread_resume` to ready blocked threads. This dispatch-path
        harness patches ThreadX create/get/put, `init_parallel`, `wait_for_init_flags`, and
        support helpers with ``mov r0, #ret; bx lr``, sets ``PC = entry_pc``, ``SP = 0x881D2000``,
        and ``LR = 0x80E9C368``, executes until return, records all ``init_parallel`` tasks
        and ``wait_for_init_flags`` barriers, and restores all patched code bytes afterward.
        ``entry_pc``, the stub addresses and the reported ``fn_ptr`` are stock 7.4.1 addresses
        (translated through the address map).
        """
        if camera_type is None:
            try:
                cam_type_val = int(str(self.vfs.env.get("CAMERA_TYPE", "0x16")), 0)
            except Exception:
                cam_type_val = 0x16
        else:
            cam_type_val = int(camera_type)

        stubs: Dict[int, int] = {
            # ThreadX mutex & semaphore create/get/put primitives
            0x80E9F9E4: 0,  # _txe_mutex_create
            0x80EA1DA8: 0,  # _tx_mutex_create
            0x80E9FA38: 0,  # _txe_semaphore_create
            0x80EA30F0: 0,  # _tx_semaphore_create
            0x80EA04A0: 0,  # _txe_semaphore_get
            0x80EA3194: 0,  # _tx_semaphore_get
            0x80EA056C: 0,  # _txe_semaphore_put
            0x80EA32C0: 0,  # _tx_semaphore_put
            # Driver-init dispatch & wait barriers
            self.INIT_PARALLEL_ADDR: 0,
            self.WAIT_FOR_INIT_FLAGS_ADDR: 0,
            # Support helpers in thread_DRIVER_entry
            0x80705C64: cam_type_val,
            0x8066C310: 0,
            0x8066C6B4: 0,
            0x808438C4: 0,
            0x8070E090: 0,
            0x80705DBC: 0,
            0x807044BC: 0,
            0x80080F20: 0,
            0x802576B4: 0,
            0x804D3814: 0,
            0x8008FEE0: 0,
            0x8076B414: 0,
            0x804960BC: 0,
            0x8066F374: 0,
            0x8066F4FC: 0,
            0x8066ED38: 0,
            0x8066ED5C: 0,
            0x8066E7F4: 0,
            0x8066FA8C: 0,
            0x8066E5D4: 0,
            0x8066AEE0: 0,
            0x8066B000: 0,
            0x8066F574: 0,
            0x8066AECC: 0,
            0x8066AEF4: 0,
            0x8066AF08: 0,
            0x8066EDCC: 0,
            0x8066F284: 0,
            0x8066ED10: 0,
        }
        if extra_stubs:
            stubs.update({int(k): int(v) for k, v in extra_stubs.items()})

        dispatched: List[Dict[str, Any]] = []
        waits: List[int] = []
        saved_code: Dict[int, bytes] = {}
        hook_handles: List[int] = []

        def _on_init_parallel(c: "Dsmc2Camera", _pc: int):
            name_ptr = c.cpu.get_r(0)
            fn_ptr = c.cpu.get_r(1)
            flag = c.cpu.get_r(2) | (c.cpu.get_r(3) << 32)
            try:
                dep_lo = c.bus.read_u32(c.cpu.sp)
                dep_hi = c.bus.read_u32(c.cpu.sp + 4)
                dep = dep_lo | (dep_hi << 32)
            except Exception:
                dep = 0
            name = ""
            if name_ptr:
                try:
                    raw = bytes(c.bus.read_mem(name_ptr, 48)).split(b"\x00", 1)[0]
                    name = raw.decode("ascii", errors="replace")
                except Exception:
                    name = f"0x{name_ptr:08X}"
            dispatched.append({
                "name": name,
                "fn_ptr": c.to_stock(fn_ptr),
                "flag": flag,
                "dep": dep,
            })

        def _on_wait_flags(c: "Dsmc2Camera", _pc: int):
            mask = c.cpu.get_r(0) | (c.cpu.get_r(1) << 32)
            waits.append(mask)

        try:
            for stock_addr, ret_val in stubs.items():
                addr = self.fw(stock_addr)
                saved_code[addr] = bytes(self.bus.read_mem(addr, 8))
                v = int(ret_val) & 0xFFFF
                if 0 <= v <= 0xFF:
                    instr0 = 0xE3A00000 | v  # mov r0, #v
                else:
                    instr0 = 0xE3000000 | ((v & 0xF000) << 4) | (v & 0x0FFF)  # movw r0, #v
                self.bus.write_mem(addr, struct.pack("<II", instr0, 0xE12FFF1E))

            hook_handles.append(self.add_pc_hook(self.fw(self.INIT_PARALLEL_ADDR), _on_init_parallel))
            hook_handles.append(self.add_pc_hook(self.fw(self.WAIT_FOR_INIT_FLAGS_ADDR), _on_wait_flags))

            sentinel_lr = self.fw(self.IDLE_LOOP_ENTRY)
            self.cpu.pc = self.fw(int(entry_pc))
            self.cpu.sp = 0x881D2000
            self.cpu.lr = sentinel_lr
            completed = self.boot_until(sentinel_lr, max_instructions=max_instructions, step_size=min(10_000, max_instructions))
        finally:
            for h in hook_handles:
                self.remove_hook(h)
            for addr, orig in saved_code.items():
                self.bus.write_mem(addr, bytes(orig))

        return {
            "completed": completed,
            "entry_pc": entry_pc,
            "dispatched": dispatched,
            "wait_barriers": waits,
        }

    def _ensure_sync_call_hooks(self) -> None:
        """Install ThreadX guard hooks active only during synchronous ``call_function()`` calls."""
        if getattr(self, "_sync_call_hooks_installed", False):
            return
        self._in_call_function = False
        self._sync_call_tcb = self.fw(self.SYNC_CALL_FALLBACK_TCB)
        cur_addr = self.fw(self.TX_THREAD_CURRENT_PTR)
        exec_addr = self.fw(self.TX_THREAD_EXECUTE_PTR)

        def _on_sem_get(cam: "Dsmc2Camera", _pc: int) -> None:
            if not getattr(cam, "_in_call_function", False):
                return
            sem = cam.cpu.get_r(0)
            if sem != 0 and cam.bus.read_u32(sem + 8) == 0:
                cam.bus.write_u32(sem + 8, 1)

        def _on_sleep(cam: "Dsmc2Camera", _pc: int) -> None:
            if not getattr(cam, "_in_call_function", False):
                return
            cam.cpu.set_r(0, 0)
            cam.cpu.pc = cam.cpu.lr

        def _on_sys_return(cam: "Dsmc2Camera", _pc: int) -> None:
            if not getattr(cam, "_in_call_function", False):
                return
            cam.bus.write_u32(cur_addr, cam._sync_call_tcb)
            cam.bus.write_u32(exec_addr, cam._sync_call_tcb)
            cam.cpu.pc = cam.cpu.lr

        self.add_pc_hook(self.fw(self.TX_SEMAPHORE_GET_INTERNAL), _on_sem_get)
        self.add_pc_hook(self.fw(self.TX_THREAD_SLEEP_ENTRY), _on_sleep)
        self.add_pc_hook(self.fw(self.TX_THREAD_SYSTEM_RETURN), _on_sys_return)
        self._sync_call_hooks_installed = True

    def call_function(
        self,
        entry_pc: int,
        args: Optional[List[int]] = None,
        scratch_sp: int = 0x881D0000,
        max_instructions: int = 5_000_000,
        step_size: int = 50_000,
    ) -> int:
        """Call a firmware function directly (AAPCS) and return r0.

        Sets r0..r3 from ``args`` (first four, AAPCS register args), sets ``sp`` and ``r12`` to
        ``scratch_sp`` (scratch DDR above the live app region), switches to IRQ/FIQ-masked
        Supervisor mode (``CPSR = 0xD3``), sets ``lr`` to the scratch DDR NOP sentinel
        ``0x881FF000``, executes until return, and restores ``(pc, sp, lr, cpsr, r12)``.
        Addresses are stock 7.4.1 (translated through the address map). Intended for synchronous
        leaf/short routines after boot; synchronous ThreadX primitives (mutex/semaphore/sleep)
        are kept non-blocking and non-preempting while the call runs.
        """
        self._ensure_sync_call_hooks()
        cur_addr = self.fw(self.TX_THREAD_CURRENT_PTR)
        exec_addr = self.fw(self.TX_THREAD_EXECUTE_PTR)
        orig_cur = self.bus.read_u32(cur_addr)
        orig_exec = self.bus.read_u32(exec_addr)
        self._sync_call_tcb = (
            orig_cur if (orig_cur != 0 and orig_cur == orig_exec) else self.fw(self.SYNC_CALL_FALLBACK_TCB)
        )
        self.bus.write_u32(cur_addr, self._sync_call_tcb)
        self.bus.write_u32(exec_addr, self._sync_call_tcb)

        args = args or []
        saved = (
            self.cpu.pc,
            self.cpu.sp,
            self.cpu.lr,
            self.cpu.cpsr,
            self.cpu.get_r(12),
        )
        for i, a in enumerate(args[:4]):
            self.cpu.set_r(i, a & 0xFFFFFFFF)
        sentinel = 0x881FF000
        self.bus.write_u32(sentinel, 0xE1A00000)  # nop return landing pad in scratch DDR
        self.cpu.cpsr = 0xD3  # SVC mode with IRQ & FIQ masked for synchronous leaf call
        self.cpu.sp = scratch_sp
        self.cpu.lr = sentinel
        self.cpu.set_r(12, scratch_sp)  # APCS +4 entry relies on ip == sp for ldm sp epilogue
        self.cpu.pc = self.fw(int(entry_pc))
        self._in_call_function = True
        try:
            self.cpu.run(self.cpu.pc, sentinel, count=max_instructions)
            return self.cpu.get_r(0)
        finally:
            self._in_call_function = False
            self.bus.write_u32(cur_addr, orig_cur)
            self.bus.write_u32(exec_addr, orig_exec)
            pc, sp, lr, cpsr, r12 = saved
            self.cpu.pc = pc
            self.cpu.sp = sp
            self.cpu.lr = lr
            self.cpu.cpsr = cpsr
            self.cpu.set_r(12, r12)

    def add_pc_hook(
        self,
        addr: int,
        callback: Callable[["Dsmc2Camera", int], None],
        one_shot: bool = False,
    ) -> int:
        """Register a PC code hook at ``addr`` invoking ``callback(camera, pc)``."""
        handle_box: List[Optional[int]] = [None]

        def _code_hook(uc, address, size, user_data):
            if address == addr:
                if one_shot and handle_box[0] is not None:
                    try:
                        uc.hook_del(handle_box[0])
                    except Exception:
                        pass
                    handle_box[0] = None
                callback(self, address)

        h = self.cpu.mu.hook_add(unicorn.UC_HOOK_CODE, _code_hook, None, addr, addr)
        handle_box[0] = h
        return h

    def add_mem_read_hook(
        self,
        addr: int,
        size: int,
        callback: Callable[["Dsmc2Camera", int, int], None],
    ) -> int:
        """Register a memory read hook on ``[addr, addr + size - 1]`` invoking ``callback(camera, address, access_size)``."""
        end_addr = addr + max(1, size) - 1

        def _read_hook(uc, access, address, access_size, value, user_data):
            callback(self, address, access_size)

        return self.cpu.mu.hook_add(unicorn.UC_HOOK_MEM_READ, _read_hook, None, addr, end_addr)

    def add_mem_write_hook(
        self,
        addr: int,
        size: int,
        callback: Callable[["Dsmc2Camera", int, int, int], None],
    ) -> int:
        """Register a memory write hook on ``[addr, addr + size - 1]`` invoking ``callback(camera, address, access_size, value)``."""
        end_addr = addr + max(1, size) - 1

        def _write_hook(uc, access, address, access_size, value, user_data):
            callback(self, address, access_size, value)

        return self.cpu.mu.hook_add(unicorn.UC_HOOK_MEM_WRITE, _write_hook, None, addr, end_addr)

    def remove_hook(self, handle: int):
        """Remove a previously registered Unicorn hook handle."""
        try:
            self.cpu.mu.hook_del(handle)
        except Exception:
            pass

    def power_on(self, progress_cb: Optional[Callable[[float], None]] = None):
        """Power on camera to operational state."""
        if not self.is_booted:
            self.power_state = self.POWER_BOOTING
            self.boot_progress = 0.0
            if progress_cb:
                progress_cb(0.0)
            self.log_system("[PWR] Powering on RED DSMC2 (Cortex-A8 @ 1GHz)...")
            self.log_system(f"[PWR] Loading firmware from {os.path.basename(self.firmware_slot_dir)} into DDR (0x80000000)...")
            self.load_firmware()
            self.log_system(f"[CRT] Reset vector 0x{self.reset_pc:08X} -> Initializing C runtime and clearing BSS...")
            self.boot(initial_instructions=45_000_000, chunk=3_000_000, progress_cb=progress_cb)
            self.log_system("[RTOS] ThreadX RTOS kernel initialized.")
            threads = self.get_threads()
            for t in threads:
                self.log_system(f"[RTOS] Thread [{t['name']}] state={t['state']} prio={t['priority']}")
            self.log_system("[DSS] OMAP3630 DISPC online: 1024x576 32bpp frame stream ready.")
            self.log_system("[UI] RED Touch 7.0 online (maXTouch @ 0x4B, EDID @ 0x50).")
            self.log_system(f"[PMIC] TI TWL4030 online (I2C1 @ 0x48): VDD1=1.35V, VDD2=1.15V, DC-IN {self.pmic.get_battery_voltage():.1f}V")
            self.log_system(f"[THERMAL] TI TMP411 online (I2C1 @ 0x4C): Sensor={self.thermal.sensor_temp_c:.0f}°C, BRAIN={self.thermal.brain_temp_c:.0f}°C (Cal: T/E OK)")
            self.log_system(f"[OLPF] DSMC2 OLPF EEPROM online (I2C2 @ 0x54): {self.olpf.get_info()['type_name']}")
            self.log_system("[GPMC] OMAP3630 GPMC Controller online @ 0x6E000000 (CS0 Micron NAND Flash, BCH ECC Active)")

            # Bring up Coprocessors from active firmware slot
            slot = self.firmware_slot_dir
            iob0_iram = os.path.join(slot, "iob0", "iram.bin")
            iob0_dram = os.path.join(slot, "iob0", "dram.bin")
            self.iob0.load_binaries(iob0_iram, iob0_dram)

            iob1_iram = os.path.join(slot, "iob1", "iram.bin")
            iob1_dram = os.path.join(slot, "iob1", "dram.bin")
            self.iob1.load_binaries(iob1_iram, iob1_dram)

            isp_iram = os.path.join(slot, "isp", "iram.bin")
            isp_dram = os.path.join(slot, "isp", "dram.bin")
            self.isp1.load_binaries(isp_iram, isp_dram)
            self.isp2.load_binaries(isp_iram, isp_dram)

            dsp_coff = os.path.join(slot, "dsp", "rdc_dsp_app.out")
            self.dsp.load_coff(dsp_coff)

            self.log_system("[L4-PER] OMAP3630 L4-Per Interconnect AP online @ 0x49000000")
            self.log_system("[C2C/SPI] McSPI Coprocessor mailbox online (ts_isp1, ts_isp2, ts_fpga, ts_sensor linked)")
            self.log_system("[IOB0] Tensilica Xtensa online: SATA 3.0 6Gbps HBA, HDMI 1080p, SPI Accelerometer")
            self.log_system(f"[IOB1] Tensilica Xtensa online: Dark-Level Calibration & Defect Map ({len(self.iob1.factory_defects)} factory defects)")
            self.log_system("[ISP] Dual ISP1 & ISP2 online: REDCODE Wavelet Engine, DDR Training PASS (Modified SCL V2)")
            self.log_system(f"[DSP] TI TMS320C64x+ DSP/BIOS online: Entry 0x{self.dsp.entry_point:08X}, CImagingServer & RAudioServer active")
            self.log_system(f"[ACCESSORY] Accessory Bus enumerated: {len(self.accessory_bus.attached_modules)} modules online")
            if self.lens_mount and self.lens_mount.attached_lens:
                self.log_system(f"[MOUNT] {self.lens_mount.mount_type} online: {self.lens_mount.attached_lens.model} ({self.lens_mount.attached_lens.serial})")
            if hasattr(self, "recorder") and self.recorder:
                self.log_system(f"[MEDIA] RED MINI-MAG 512GB online: Reel {self.recorder.current_reel_id} ({self.recorder.media_remaining_percent}% free)")
            self.log_system(f"[SYS] RED {self.vfs.env.get('CAMERA_NAME', 'SCARLET-W 5K')} is ONLINE and READY.")
        else:
            self.log_system("[PWR] Resuming camera from standby -> Display & Sensors active.")

        self.power_state = self.POWER_ON
        self.is_booted = True
        self.boot_progress = 1.0
        self.rcp_server.start()
        if self.on_state_change:
            self.on_state_change(self.power_state)

    def power_off(self):
        """Power down camera to standby state."""
        self.log_system("[PWR] Entering standby mode -> Display & Sensors sleeping...")
        self.power_state = self.POWER_STANDBY
        self.rcp_server.stop()
        if self.on_state_change:
            self.on_state_change(self.power_state)

    def toggle_power(self):
        """Toggle power between Standby and On."""
        if self.power_state == self.POWER_STANDBY:
            self.power_on()
        else:
            self.power_off()

    def start(self):
        """Start autonomous background execution."""
        if not self.is_booted:
            self.boot()

        self.power_state = self.POWER_ON
        self.is_running = True
        self.rcp_server.start()

    def stop(self):
        """Stop emulator execution."""
        self.is_running = False
        self.rcp_server.stop()

    # Input and Control API
    @property
    def brain_model(self) -> str:
        """Active DSMC2 Camera Model name."""
        if hasattr(self, "env") and self.env:
            return self.env.get("CAMERA_NAME", "SCARLET-W 5K")
        return "SCARLET-W 5K"

    def touch(self, x: int, y: int, pressed: bool):
        """Deliver touchscreen event to Atmel maXTouch controller."""
        self.maxtouch.inject_touch(x, y, pressed)

    def start_recording(self) -> bool:
        """Start active clip recording."""
        self.gpio[1].set_input_pin(12, True)
        self.gpio[1].set_input_pin(12, False)
        return self.recorder.start_recording()

    def stop_recording(self) -> bool:
        """Stop active clip recording."""
        self.gpio[1].set_input_pin(12, True)
        self.gpio[1].set_input_pin(12, False)
        return self.recorder.stop_recording()

    def press_record(self):
        """Toggle camera recording state."""
        self.gpio[1].set_input_pin(12, True)
        self.gpio[1].set_input_pin(12, False)
        self.recorder.toggle_recording()

    def get_frame(self) -> bytes:
        """Fetch current live pixels from Display Subsystem."""
        return self.dss.get_framebuffer_bytes()

    def get_serial_logs(self) -> List[str]:
        """Fetch system logs from UART4."""
        return list(self.uarts[4].completed_lines)

    def get_threads(self) -> List[Dict[str, Any]]:
        """Inspect and return all ThreadX RTOS threads from memory."""
        threads = []
        if not self.is_booted:
            return threads

        tcbs: List[int] = []
        seen_addrs: Set[int] = set()

        def _add_tcb(addr: int):
            if addr and addr not in seen_addrs:
                seen_addrs.add(addr)
                tcbs.append(addr)

        for a in self.TCB_ADDRS:
            _add_tcb(self.fw(a))

        # Also walk ThreadX circular created-thread list via tx_thread_created_next (+0x8C)
        # so dynamically created application threads (e.g., Camera State Manager) appear.
        walk_starts = [self.fw(self.TCB_ADDRS[0])]
        try:
            walk_starts.append(self.bus.read_u32(self.fw(self.TX_THREAD_CREATED_PTR)))
        except Exception:
            pass
        walk_seen: Set[int] = set()
        for start in walk_starts:
            cur = start
            while cur and cur not in walk_seen and len(walk_seen) < 64:
                walk_seen.add(cur)
                try:
                    if self.bus.read_u32(cur) != 0x54485244:  # 'THRD' magic
                        break
                    _add_tcb(cur)
                    cur = self.bus.read_u32(cur + 0x8C)  # tx_thread_created_next
                except Exception:
                    break

        mapped = not self.addr_map.is_identity
        state_names = {
            0: "READY", 1: "COMPLETED", 2: "TERMINATED", 3: "SUSPENDED",
            4: "SLEEP", 5: "QUEUE", 6: "SEMAPHORE", 7: "EVENT_FLAG",
            8: "BLOCK_MEMORY", 9: "BYTE_MEMORY", 10: "IO_DRIVER",
            11: "FILE", 12: "NETWORK", 13: "MUTEX"
        }

        for tcb in tcbs:
            try:
                chunk = self.bus.read_mem(tcb, 0x50)
                words = struct.unpack("<20I", chunk)
                if words[0] != 0x54485244: # 'THRD' magic
                    continue
                run_cnt = words[1]   # +0x04
                sp = words[2]        # +0x08
                stk_start = words[3] # +0x0C
                stk_end = words[4]   # +0x10
                name_ptr = words[10] # +0x28
                prio = words[11]     # +0x2C
                state = words[12]    # +0x30: tx_thread_state
                entry = words[17]    # +0x44: tx_thread_entry

                try:
                    raw_name = self.bus.read_mem(name_ptr, 48)
                    name = raw_name.split(b"\x00")[0].decode("latin1")
                except Exception:
                    name = "UNKNOWN"

                t = {
                    "address": f"0x{tcb:08X}",
                    "name": name,
                    "state": state_names.get(state, f"STATE_{state}"),
                    "priority": prio,
                    "entry": f"0x{entry:08X}",
                    "sp": f"0x{sp:08X}",
                    "stack_range": f"0x{stk_start:08X}-0x{stk_end:08X}",
                    "run_count": run_cnt,
                }
                if mapped:
                    st = self.to_stock
                    t["stock"] = {
                        "address": f"0x{st(tcb):08X}",
                        "entry": f"0x{st(entry):08X}",
                        "sp": f"0x{st(sp):08X}",
                        "stack_range": f"0x{st(stk_start):08X}-0x{st(stk_end):08X}",
                    }
                threads.append(t)
            except Exception:
                continue

        return threads

    def save_snapshot(self, filepath: str, description: str = ""):
        """Save emulator state to snapshot file."""
        SnapshotManager.save(self, filepath, description)

    def restore_snapshot(self, filepath: str) -> Dict[str, Any]:
        """Restore emulator state from snapshot file."""
        return SnapshotManager.restore(self, filepath)

    def inject_fault(self, fault_type: str, **kwargs):
        """Simulate hardware/system faults."""
        if fault_type == "monitor_disconnect":
            self.i2c[3].slaves.pop(0x4B, None)
            self.i2c[3].slaves.pop(0x50, None)
        elif fault_type == "monitor_connect":
            self.i2c[3].attach_slave(self.maxtouch)
            self.i2c[3].attach_slave(self.edid)
        elif fault_type == "i2c_nack":
            # Force next I2C transaction to NACK
            bus_id = kwargs.get("bus", 3)
            if bus_id in self.i2c:
                self.i2c[bus_id].force_nack = True
                self.i2c[bus_id].stat |= 0x02 # NACK flag
        elif fault_type == "corrupt_env":
            # Corrupt active environment and persistent storage backing file
            self.env.set("CAMERA_TYPE", "CORRUPTED_0xFF")
            if hasattr(self, "vfs") and self.vfs:
                env_file = self.vfs.mounts.get("/env")
                if env_file:
                    try:
                        with open(env_file, "wb") as f:
                            f.write(b"CORRUPT_ENV_DATA\xFF\xFF\xFF\xFF")
                    except Exception:
                        pass
        elif fault_type == "watchdog_reset":
            self.cpu.pc = self.reset_pc
            self.cpu.sp = self.reset_sp
            self.cpu.cpsr = ArmCpu.MODE_SVC | 0xC0
            self.instruction_count = 0
            self.is_booted = False

    def select_camera_model(self, model_id: str) -> bool:
        """Dynamically switch camera model personality, /env, slot assets, and active firmware binary."""
        if not self.env.apply_profile(model_id):
            return False

        profile = self.env.CAMERA_PROFILES.get(model_id) or next(
            (p for p in self.env.CAMERA_PROFILES.values() if p["CAMERA_NAME"].lower() == model_id.lower()), None
        )
        if not profile:
            return False

        # Update firmware slot directory and VFS mount target unconditionally
        new_slot_dir = os.path.join(self.workspace_root, profile["FIRMWARE_DIR"], "slot")
        self.firmware_slot_dir = new_slot_dir
        if hasattr(self, "vfs") and self.vfs:
            self.vfs.firmware_slot_dir = new_slot_dir

        fw_path = os.path.join(new_slot_dir, "dsmc_program.mem")
        fw_reloaded = False
        if os.path.exists(fw_path):
            # Cleanly re-initialize SoC hardware before booting new model's firmware
            self._init_hardware()
            self.load_firmware(fw_path)
            self.boot(initial_instructions=45_000_000)
            self.power_state = self.POWER_ON
            self.is_booted = True
            self.rcp_server.start()
            fw_reloaded = True

        # Update RCP state
        if hasattr(self, "rcp") and self.rcp:
            self.rcp.state[RcpProtocol.PARAM_CAMERA_NAME] = profile["CAMERA_NAME"]
            self.rcp.state[RcpProtocol.PARAM_FORMAT] = profile.get("DEFAULT_FORMAT", "5K 16:9")
            self.rcp.state["camera_type"] = profile["CAMERA_TYPE"]
            self.rcp.state["sensor_name"] = profile["SENSOR_NAME"]
            self.rcp.state["sensor_width"] = profile["SENSOR_WIDTH"]
            self.rcp.state["sensor_height"] = profile["SENSOR_HEIGHT"]
            self.rcp.state["max_fps"] = profile["MAX_FPS"]

        # Hardware Mount constraint: RED RAVEN has fixed integrated Canon EF mount
        if profile.get("CAMERA_TYPE") == "0x15" and hasattr(self, "lens_mount") and self.lens_mount:
            self.lens_mount.set_mount_type("Canon EF")

        # Update RedUi and Compositor
        comp = getattr(self, "compositor", None)
        if comp:
            if hasattr(comp, "_load_splash_screen"):
                comp.splash_image = comp._load_splash_screen()
            if hasattr(comp, "redui") and comp.redui:
                comp.redui.apply_camera_profile(profile)

        self.log_system(f"[CAMERA] Switched DSMC2 BRAIN Model to {profile['CAMERA_NAME']} ({profile['RELEASE_TAG']}, Type {profile['CAMERA_TYPE']})")
        self.log_system(f"[SENSOR] Active Sensor: {profile['SENSOR_NAME']} ({profile['SENSOR_WIDTH']}x{profile['SENSOR_HEIGHT']}, Max {profile['MAX_FPS']} FPS)")
        if fw_reloaded:
            self.log_system(f"[FIRMWARE] Active Firmware: v7.4.1 ({profile['CAMERA_NAME']}) from {profile['FIRMWARE_DIR']}")
        else:
            self.log_system(f"[FIRMWARE] Slot binary not staged at {profile['FIRMWARE_DIR']}/slot/dsmc_program.mem; profile metadata applied without firmware reload")
        return True

    def load_and_boot_custom_firmware(self, custom_path: str) -> Dict[str, Any]:
        """Validate, load, and execute custom firmware binary from RED MINI-MAG slot into DDR."""
        from emulator.core.firmware import FirmwareManager
        self.staged_firmware_path = custom_path
        return FirmwareManager.boot_custom(self, custom_path)

    def set_sensor_temperature(self, sensor_c: float, brain_c: float):
        """Set sensor die and brain temperatures in thermal sensor."""
        if hasattr(self, "thermal") and self.thermal:
            self.thermal.set_temperatures(sensor_c, brain_c)

    def set_battery_voltage(self, volts: float):
        """Set battery / DC input voltage in PMIC."""
        if hasattr(self, "pmic") and self.pmic:
            self.pmic.set_battery_voltage(volts)

    def set_olpf_type(self, olpf_name: str) -> bool:
        """Change active OLPF profile in EEPROM."""
        if hasattr(self, "olpf") and self.olpf:
            return self.olpf.set_olpf_type(olpf_name)
        return False

    def run_black_shading(self) -> Dict[str, Any]:
        """Trigger sensor black shading calibration on IOB1."""
        sensor_c = self.thermal.sensor_temp_c if hasattr(self, "thermal") and self.thermal else 39.0
        exposure = self.rcp.state.get(RcpProtocol.PARAM_SHUTTER, "1/48") if hasattr(self, "rcp") and self.rcp else "1/48"
        if hasattr(self, "iob1") and self.iob1:
            res = self.iob1.run_black_shading(sensor_c, exposure)
            self.log_system(f"[CALIBRATION] Black Shading complete on IOB1 ({res['defects_masked']} defects masked, target {sensor_c:.1f}°C {exposure})")
            return res
        return {"status": "ERROR"}

    def detect_faces(self) -> List[Dict[str, Any]]:
        """Run Haar-cascade face detection on DSP."""
        if hasattr(self, "imaging_server") and self.imaging_server:
            return self.imaging_server.detect_faces()
        return []

    def compute_focus_contrast(self, roi: Tuple[int, int, int, int] = (400, 200, 600, 400)) -> float:
        """Calculate focus contrast sharpness on DSP."""
        dist = self.lens_mount.current_focus_distance if hasattr(self, "lens_mount") and self.lens_mount else 2.5
        if hasattr(self, "imaging_server") and self.imaging_server:
            return self.imaging_server.compute_focus_contrast(roi, dist)
        return 0.0

    def attach_accessory(self, pin_or_name: str, serial: int = 100001, slot: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Attach DSMC2 expander, display, or rig module on accessory bus / slot."""
        if slot and hasattr(self, "rig") and self.rig:
            return self.rig.attach_module_to_slot(slot, pin_or_name, serial=serial)
        if hasattr(self, "accessory_bus") and self.accessory_bus:
            return self.accessory_bus.attach_module(pin_or_name, serial)
        return None

    def detach_accessory(self, pin_or_name: str, slot: Optional[str] = None) -> bool:
        """Detach DSMC2 expander, display, or rig module."""
        if slot and hasattr(self, "rig") and self.rig:
            return self.rig.detach_slot(slot)
        if hasattr(self, "accessory_bus") and self.accessory_bus:
            return self.accessory_bus.detach_module(pin_or_name)
        return False

    def toggle_module_position(self, from_slot: str, to_slot: str) -> bool:
        """Move or swap an accessory from one physical connector slot to another."""
        if hasattr(self, "rig") and self.rig:
            return self.rig.toggle_slot_position(from_slot, to_slot)
        return False

    def set_slot_orientation(self, slot: str, orientation: str) -> bool:
        """Set display or accessory orientation in a connector slot."""
        if hasattr(self, "rig") and self.rig:
            return self.rig.set_slot_orientation(slot, orientation)
        return False

    def execute_rcp_script(self, script_data: Any, script_name: str = "Custom Automation Script") -> Dict[str, Any]:
        """Execute an RCP script sequence (preset key, list of step dicts, or DSL text)."""
        if isinstance(script_data, str) and script_data.upper() in self.rcp_script_engine.PRESETS:
            preset = self.rcp_script_engine.PRESETS[script_data.upper()]
            script_name = preset["name"]
            steps = [RcpScriptStep(**s) for s in preset["steps"]]
        elif isinstance(script_data, list):
            if all(isinstance(s, str) for s in script_data):
                steps = self.rcp_script_engine.parse_script_lines(script_data)
            else:
                steps = [RcpScriptStep(**s) if isinstance(s, dict) else s for s in script_data]
        elif isinstance(script_data, str):
            steps = self.rcp_script_engine.parse_script_lines(script_data.splitlines())
        else:
            return {"status": "ERROR", "message": "Invalid script format"}

        return self.rcp_script_engine.execute(
            steps=steps,
            camera=self,
            rcp_protocol=self.rcp,
            multicam=self.multicam_network,
            script_name=script_name
        )

    def set_hdmi_mode(self, mode: str):
        """Set HDMI output broadcast mode (CLEAN, BROADCAST_TALLY, FRAME_GUIDES)."""
        if hasattr(self, "iob0") and self.iob0:
            self.iob0.set_hdmi_mode(mode)

    def get_audio_wav(self, duration_sec: float = 0.5) -> bytes:
        """Fetch 48kHz stereo WAV audio chunk from TI DSP audio server."""
        if hasattr(self, "audio_server") and self.audio_server:
            return self.audio_server.get_wav_bytes(duration_sec)
        import io, wave
        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(48000)
            wf.writeframes(b"")
        return out.getvalue()

    def fw_cdb2_get_uint32(
        self,
        param_name: str,
        param_type: str = "UINT32",
        max_instructions: int = 1_500_000,
    ) -> Tuple[int, int]:
        """Invoke stock ``_cdb2_parameter_get_value`` (@0x80080C34) on booted firmware."""
        arg_name = 0x881C0000
        arg_type = 0x881C0100
        out_buf = 0x881C0200
        self.bus.write_mem(self.fw(arg_name), param_name.encode("ascii") + b"\x00")
        self.bus.write_mem(self.fw(arg_type), param_type.encode("ascii") + b"\x00")
        self.bus.write_u32(self.fw(out_buf), 0xDEADBEEF)
        rc = self.call_function(
            self.CDB2_GET_VALUE_ADDR,
            [arg_name, arg_type, out_buf],
            max_instructions=max_instructions,
        )
        val = self.bus.read_u32(self.fw(out_buf))
        return rc, val

    def fw_cdb2_set_uint32(
        self,
        param_name: str,
        value: int,
        param_type: str = "UINT32",
        max_instructions: int = 2_000_000,
    ) -> int:
        """Invoke stock ``cdb2_parameter_set_uint32`` / ``_cdb2_parameter_set_value``."""
        arg_name = 0x881C0000
        self.bus.write_mem(self.fw(arg_name), param_name.encode("ascii") + b"\x00")
        if param_type == "UINT32":
            return self.call_function(
                self.CDB2_SET_UINT32_ADDR,
                [arg_name, value & 0xFFFFFFFF],
                max_instructions=max_instructions,
            )
        arg_type = 0x881C0100
        val_buf = 0x881C0210
        self.bus.write_mem(self.fw(arg_type), param_type.encode("ascii") + b"\x00")
        self.bus.write_u32(self.fw(val_buf), value & 0xFFFFFFFF)
        return self.call_function(
            self.CDB2_SET_VALUE_ADDR,
            [arg_name, arg_type, val_buf],
            max_instructions=max_instructions,
        )

    def fw_cdb2_reset_param(self, param_name: str, max_instructions: int = 1_500_000) -> int:
        """Invoke stock ``cdb2_parameter_reset_value`` (@0x80082700): drop the user override."""
        arg_name = 0x881C0000
        self.bus.write_mem(self.fw(arg_name), param_name.encode("ascii") + b"\x00")
        return self.call_function(
            self.CDB2_PARAM_RESET_ADDR, [arg_name], max_instructions=max_instructions
        )

    def fw_cdb2_reset_to_factory_defaults(self, max_instructions: int = 4_000_000) -> int:
        """Invoke stock ``cdb2_reset_to_factory_defaults`` (@0x80080974).

        Closes CDB2, unlinks ``/data/cdb2/user.db`` and re-runs ``cdb2_init``.
        """
        return self.call_function(
            self.CDB2_FACTORY_RESET_ADDR, [], max_instructions=max_instructions
        )

    def fw_cdb2_preset_has_param(
        self, preset_name: str, param_name: str, max_instructions: int = 6_000_000
    ) -> bool:
        """Invoke stock ``cdb2_preset_has_param`` (@0x8008438C) on a staged ``.preset`` SQLite DB."""
        self.bus.write_u32(self.fw(self.CDB2_PRESET_KEY_PTR_ADDR), self.fw(self.CDB2_EMPTY_KEY_STR_ADDR))
        arg_preset = 0x881C0000
        arg_param = 0x881C0100
        out_bool = 0x881C0200
        self.bus.write_mem(self.fw(arg_preset), preset_name.encode("ascii") + b"\x00")
        self.bus.write_mem(self.fw(arg_param), param_name.encode("ascii") + b"\x00")
        self.bus.write_u32(self.fw(out_bool), 0)
        rc = self.call_function(
            self.CDB2_PRESET_HAS_PARAM_ADDR,
            [arg_preset, arg_param, out_bool],
            max_instructions=max_instructions,
        )
        return rc == 0 and self.bus.read_mem(self.fw(out_bool), 1)[0] == 1

    def fw_cdb2_apply_preset(self, preset_name: str, max_instructions: int = 6_000_000) -> int:
        """Invoke stock ``cdb2_apply_preset`` (@0x8008435C) against ``/image2/cdb2/presets/<name>.preset``."""
        self.bus.write_u32(self.fw(self.CDB2_PRESET_KEY_PTR_ADDR), self.fw(self.CDB2_EMPTY_KEY_STR_ADDR))
        arg_preset = 0x881C0000
        out_flag = 0x881C0200
        self.bus.write_mem(self.fw(arg_preset), preset_name.encode("ascii") + b"\x00")
        self.bus.write_u32(self.fw(out_flag), 0)
        return self.call_function(
            self.CDB2_APPLY_PRESET_ADDR,
            [arg_preset, out_flag],
            max_instructions=max_instructions,
        )

    def fw_sata_media_present(
        self, media_present: Optional[bool] = None, max_instructions: int = 1_500_000
    ) -> int:
        """Ask the stock ``SATA_MediaPresent`` (@0x806A2ACC) whether HBA0/port0 has media.

        ``media_present`` (if given) first updates the IOB XAUI shadow PxSSTS the firmware reads.
        """
        if media_present is not None:
            self.iob_xaui.media_present = bool(media_present)
            self.c2c.iob_ahb.sata_media_present = bool(media_present)
        dev = self.call_function(
            self.RED_MEDIA_GET_DEVICE_ADDR, [0, 0], max_instructions=max_instructions
        )
        if dev == 0 or self.bus.read_mem(dev, 1)[0] == 0:
            self.call_function(self.RED_MEDIA_INIT_ADDR, [], max_instructions=3_000_000)
            dev = self.call_function(
                self.RED_MEDIA_GET_DEVICE_ADDR, [0, 0], max_instructions=max_instructions
            )
        if dev == 0:
            raise RuntimeError("red_media_get_device(0, 0) returned NULL (media layer not initialised)")
        return self.call_function(
            self.SATA_MEDIA_PRESENT_ADDR, [dev, 0, 0], max_instructions=max_instructions
        )

    def fw_sata_host_and_port_init(self, max_instructions: int = 3_000_000) -> Dict[str, int]:
        """Execute stock ``SATA_HostInit`` (@0x806A14A4) and ``SATA_PortReset`` (@0x806A2298) on HBA0."""
        self.iob_xaui.media_present = True
        self.iob_xaui.attach_engine_enabled = True
        self.c2c.iob_ahb.sata_media_present = True
        dev = self.call_function(
            self.RED_MEDIA_GET_DEVICE_ADDR, [0, 0], max_instructions=max_instructions
        )
        if dev == 0 or self.bus.read_mem(dev, 1)[0] == 0:
            self.call_function(self.RED_MEDIA_INIT_ADDR, [], max_instructions=3_000_000)
            dev = self.call_function(
                self.RED_MEDIA_GET_DEVICE_ADDR, [0, 0], max_instructions=max_instructions
            )
        hba = self.bus.read_u32(dev + 0x0C)
        rc_host = self.call_function(
            self.SATA_HOST_INIT_ADDR, [hba, 1], max_instructions=max_instructions
        )
        rc_port = self.call_function(
            self.SATA_PORT_RESET_ADDR, [dev], max_instructions=max_instructions
        )
        return {
            "host_init_rc": rc_host,
            "port_reset_rc": rc_port,
            "dev_ptr": dev,
            "hba_ptr": hba,
        }

    def install_trace_probe(
        self,
        points: Optional[Tuple[Tuple[int, str, str], ...]] = None,
        max_events: int = 4096,
    ) -> TraceProbe:
        """Attach a zero-overhead per-PC/IRQ ``TraceProbe`` to this camera's ARM CPU."""
        if self.trace_probe is not None:
            self.trace_probe.detach()
        probe = TraceProbe(points=points, max_events=max_events)
        probe.attach(self)
        self.trace_probe = probe
        return probe

    def _install_asic_upload_hooks(self) -> None:
        """Observe real-FW ISP/IOB binary download routines and feed ``XtensaCore`` IRAM/DRAM."""
        for h in getattr(self, "_asic_hook_handles", []):
            self.remove_hook(h)
        self._asic_hook_handles = []

        def _on_isp_upload(cam: "Dsmc2Camera", _pc: int):
            length = cam.cpu.get_r(1)
            dest_addr = cam.cpu.get_r(2)
            src_ptr = cam.cpu.get_r(3)
            if 0 < length <= 0x20000 and src_ptr != 0:
                blob = bytes(cam.bus.read_mem(src_ptr, length))
                for isp in (getattr(cam, "isp1", None), getattr(cam, "isp2", None)):
                    if isp is not None and hasattr(isp, "upload_segment"):
                        isp.upload_segment(dest_addr, blob)

        def _on_isp_reg_write(cam: "Dsmc2Camera", _pc: int):
            reg_addr = cam.cpu.get_r(1)
            val = cam.cpu.get_r(2)
            if reg_addr == 0x88900004 and val == 0x00029321:
                for isp in (getattr(cam, "isp1", None), getattr(cam, "isp2", None)):
                    if isp is not None and hasattr(isp, "release_reset"):
                        isp.release_reset()

        def _on_iob_load_entry(cam: "Dsmc2Camera", _pc: int):
            core_id = cam.cpu.get_r(0)
            cam._active_iob_upload_core = core_id if core_id in (0, 1) else None

        def _on_iob_word_write(cam: "Dsmc2Camera", _pc: int):
            core_id = cam._active_iob_upload_core
            if core_id not in (0, 1):
                return
            dest_addr = cam.cpu.get_r(0)
            word = cam.cpu.get_r(1)
            # Core 0 uses 0x3FFE0000 (DRAM) / 0x40000000 (IRAM);
            # Core 1 uses AHB aperture 0x4FFE0000 (DRAM) / 0x4FFF0000 (IRAM).
            norm_addr = dest_addr
            if 0x4FFE0000 <= dest_addr < 0x4FFF0000:
                norm_addr = 0x3FFE0000 + (dest_addr - 0x4FFE0000)
            elif 0x4FFF0000 <= dest_addr < 0x50000000:
                norm_addr = 0x40000000 + (dest_addr - 0x4FFF0000)
            target = getattr(cam, f"iob{core_id}", None)
            if target is not None and hasattr(target, "upload_segment"):
                target.upload_segment(norm_addr, struct.pack("<I", word & 0xFFFFFFFF))

        def _on_iob_reset_ctl(cam: "Dsmc2Camera", _pc: int):
            core_id = cam._active_iob_upload_core
            if core_id not in (0, 1):
                return
            reg = cam.cpu.get_r(0)
            val = cam.cpu.get_r(1)
            expected_release = 4 if core_id == 0 else 8
            if reg == 0x800A0008 and val == expected_release:
                target = getattr(cam, f"iob{core_id}", None)
                if target is not None and hasattr(target, "release_reset"):
                    target.release_reset()
                cam._active_iob_upload_core = None

        self._asic_hook_handles = [
            self.add_pc_hook(self.ISP_MEM_UPLOAD_ADDR, _on_isp_upload),
            self.add_pc_hook(self.ISP_REG_WRITE_ADDR, _on_isp_reg_write),
            self.add_pc_hook(self.IOB_LOAD_EMBEDDED_ADDR, _on_iob_load_entry),
            self.add_pc_hook(self.IOB_WORD_WRITE_ADDR, _on_iob_word_write),
            self.add_pc_hook(self.IOB_RESET_CTL_ADDR, _on_iob_reset_ctl),
        ]
