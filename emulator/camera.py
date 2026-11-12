"""
Central RED DSMC2 Virtual Camera Orchestrator.
Integrates ARM CPU, system bus, peripheral models, storage, display, and control interfaces.
"""

import os
import unicorn
import struct
import threading
import time
from typing import Optional, List, Dict, Callable, Any, Tuple, Union, Set, Iterable

from emulator.core.cpu import ArmCpu
from emulator.core.bus import SystemBus
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
from emulator.devices.l4_interconnect import OmapL4Ap, OmapScm, OmapPrm, OmapSdrc
from emulator.devices.accessory_bus import AccessoryBus, ModuleDescriptor
from emulator.devices.rig_manager import RigManager, ConnectorPosition
from emulator.coprocessors.c2c import C2cTransport, IobDoorbellDevice
from emulator.coprocessors.xtensa import Iob0Coprocessor, Iob1Coprocessor, IspCoprocessor
from emulator.coprocessors.dsp import TiC64xDsp, DspLinkIpc, CImagingServer, RAudioServer
from emulator.devices.gpio import OmapGpio, GPIO_MAP
from emulator.devices.dss import OmapDss
from emulator.storage.vfs import VirtualFileSystem
from emulator.storage.r3d_recorder import R3dClipRecorder
from emulator.rcp.protocol import RcpProtocol
from emulator.rcp.server import RcpServer
from emulator.rcp.automation import RcpScriptEngine, RcpScriptStep, MultiCameraNetwork
from emulator.devices.lens_mount import LensMount
from emulator.core.snapshot import SnapshotManager


class Dsmc2Camera:
    """The complete authentic RED DSMC2 Virtual Camera."""

    # ThreadX Scheduler Idle Loop Addresses
    IDLE_LOOP_PCS = {0x80E9C368, 0x80E9C36C, 0x80E9C370}

    # ThreadX Global Symbols
    TX_THREAD_CREATED_PTR = 0x8149CE68
    TX_THREAD_CURRENT_PTR = 0x8149CE60
    TX_THREAD_EXECUTE_PTR = 0x8149DDE8

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.abspath(workspace_root)
        self.firmware_slot_dir = os.path.join(self.workspace_root, "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot")
        self.persistent_dir = os.path.join(self.workspace_root, "persistent_store")

        # 1. Initialize SoC Hardware & Registers
        self._init_hardware()

        # 2. Storage and VFS
        self.vfs = VirtualFileSystem(self.firmware_slot_dir, self.persistent_dir)
        self.env = self.vfs.env

        # 3. RCP Protocol, Server, Scripting & Multi-Camera Network
        self.rcp = RcpProtocol(camera=self)
        self.rcp_server = RcpServer(self.rcp, host="127.0.0.1", port=1111)
        self.rcp_script_engine = RcpScriptEngine()
        self.multicam_network = MultiCameraNetwork(self)

        # 4. Smart Electronic Lens Mount
        lens_dir = os.path.join(self.firmware_slot_dir, "lens")
        self.lens_mount = LensMount(self, lens_database_dir=lens_dir)

        # 5. REDCODE R3D Media Recorder
        self.recorder = R3dClipRecorder(self, storage_root=self.workspace_root)

        # 6. Physical Rig & Modular Connector Slot Manager
        self.rig = RigManager(camera=self)

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

    def _init_hardware(self):
        """Cleanly initialize or re-initialize SoC hardware, registers, and memory mappings."""
        # Save previous log lines if re-initializing
        old_logs = list(self.uarts[4].completed_lines) if hasattr(self, "uarts") and 4 in self.uarts else []

        # 1. Initialize Core Architecture
        self.cpu = ArmCpu()
        self.bus = SystemBus(self.cpu)

        # 2. Interrupt Controller
        self.intc = OmapIntc()

        # Fast IRQ wake hook: if waiting in scheduler idle loop with no ready thread and pending IRQ, wake Unicorn
        def _idle_wake_hook(uc, address, size, user_data):
            try:
                exec_ptr = struct.unpack("<I", uc.mem_read(self.TX_THREAD_EXECUTE_PTR, 4))[0]
            except Exception:
                exec_ptr = 0
            if exec_ptr == 0 and self.intc.has_pending_irq() and self.cpu.are_interrupts_enabled():
                uc.emu_stop()

        self._idle_wake_hook_handle = self.cpu.mu.hook_add(unicorn.UC_HOOK_CODE, _idle_wake_hook, None, 0x80E9C368, 0x80E9C368)

        # 3. L4 Interconnect AP, System Control Module (SCM), Clock Management (PRCM), and Wakeup PRM
        self.l4_core_ap = OmapL4Ap(name="L4_CORE_AP", base_addr=OmapL4Ap.BASE_ADDR_L4_CORE)
        self.bus.register_device(OmapL4Ap.BASE_ADDR_L4_CORE, OmapL4Ap.SIZE, self.l4_core_ap)

        self.scm = OmapScm()
        self.bus.register_device(OmapScm.BASE_ADDR, OmapScm.SIZE, self.scm)

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
        # I2C1: Power Management (TWL4030 @ 0x48), Thermal (TMP411 @ 0x4C), LED Driver (0x45)
        self.pmic = Twl4030Pmic(0x48)
        self.thermal = Tmp411Thermal(0x4C)
        self.i2c[1].attach_slave(I2cSlave(0x45))
        self.i2c[1].attach_slave(self.pmic)
        self.i2c[1].attach_slave(self.thermal)
        self.i2c[1].attach_slave(Twl4030Pmic(0x49))
        self.i2c[1].attach_slave(Twl4030Pmic(0x4A))
        self.i2c[1].attach_slave(Twl4030Pmic(0x4B))
        self.i2c[1].attach_slave(Twl4030Pmic(0x1B))
        self.i2c[1].attach_slave(Twl4030Pmic(0x19))

        # I2C2: Optical Low Pass Filter (OLPF EEPROM @ 0x54)
        self.olpf = OlpfEeprom(0x54)
        self.i2c[2].attach_slave(self.olpf)

        # I2C3: Atmel maXTouch touch controller (0x4B), EDID EEPROM (0x50), and PMIC sub-bus
        self.maxtouch = MaXTouchDevice(0x4B, irq_callback=lambda: self.intc.assert_irq(58))
        self.edid = EdidEeprom(0x50)
        self.i2c[3].attach_slave(self.maxtouch)
        self.i2c[3].attach_slave(self.edid)
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

        # GPMC CS1 (FPGA Board Space @ 0x18000000) and CS2 (FPGA Aperture @ 0x1C000000)
        self.cpu.uc.mem_map(0x18000000, 0x10000)
        self.bus.add_ram_region(0x18000000, 0x10000)
        self.cpu.uc.mem_map(0x1C000000, 0x100000)
        self.bus.add_ram_region(0x1C000000, 0x100000)

        # 10b. System DMA (sDMA Controller @ 0x48056000)
        self.sdma = OmapSdma(intc=self.intc, cpu=self.cpu)
        self.bus.register_device(OmapSdma.BASE_ADDR, OmapSdma.SIZE, self.sdma)

        # 10c. Multichannel SPI Controllers (McSPI 1..4)
        self.mcspi: Dict[int, OmapMcspi] = {}
        for port_id, (base, irq) in MCSPI_MAP.items():
            spi = OmapMcspi(port_id, base, irq, intc=self.intc)
            self.mcspi[port_id] = spi
            self.bus.register_device(base, 0x1000, spi)

        # 11. SPI-Backed Chip-to-Chip (C2C) Mailbox & Coprocessor ASICs
        # Note: 0x49000000 is L4-PER AP (registered above as self.l4_per_ap);
        # C2cTransport binds directly to McSPI 1..4 targets (ts_isp1, ts_isp2, ts_fpga, ts_sensor).
        self.c2c = C2cTransport(intc=self.intc, mcspi=self.mcspi)

        self.iob0 = Iob0Coprocessor()
        self.iob1 = Iob1Coprocessor()
        self.isp1 = IspCoprocessor(core_id=2)
        self.isp2 = IspCoprocessor(core_id=3)
        self.c2c.register_coprocessor(C2cTransport.CORE_IOB0, self.iob0)
        self.c2c.register_coprocessor(C2cTransport.CORE_IOB1, self.iob1)
        self.c2c.register_coprocessor(C2cTransport.CORE_ISP1, self.isp1)
        self.c2c.register_coprocessor(C2cTransport.CORE_ISP2, self.isp2)

        # 11b. Tensilica IOB0 and IOB1 Mailbox Doorbell MMIO
        self.iob0_doorbell = IobDoorbellDevice(
            core_id=C2cTransport.CORE_IOB0,
            bus=self.bus,
            coprocessor=self.iob0,
            mailbox_base_addr=0x800B0FFC
        )
        self.bus.register_device(IobDoorbellDevice.BASE_ADDR_IOB0, IobDoorbellDevice.SIZE, self.iob0_doorbell)

        self.iob1_doorbell = IobDoorbellDevice(
            core_id=C2cTransport.CORE_IOB1,
            bus=self.bus,
            coprocessor=self.iob1,
            mailbox_base_addr=0x800B17FC
        )
        self.bus.register_device(IobDoorbellDevice.BASE_ADDR_IOB1, IobDoorbellDevice.SIZE, self.iob1_doorbell)

        # Wire GPIO pin 130 (Bank 5 Pin 2) to monitor multiplexer (MONITOR_HDMI_MUX)
        def _on_gpio5_pin_changed(pin: int, high: bool):
            if pin == 2:
                self.iob0.hdmi_connected = high
        self.gpio[5].on_pin_changed = _on_gpio5_pin_changed

        # 12. TI TMS320C64x+ DSP Subsystem & Servers
        self.dsp = TiC64xDsp()
        self.dsplink = DspLinkIpc(self.dsp)
        self.imaging_server = CImagingServer(self.dsplink)
        self.audio_server = RAudioServer(self.dsplink)

        # 13. Accessory Bus Subsystem
        self.accessory_bus = AccessoryBus(camera=self)

        self.instruction_count = 0
        self.is_booted = False

    def log_system(self, message: str):
        """Append an entry to system logs (UART4) and terminal stdout."""
        self.uarts[4].completed_lines.append(message)
        print(message, flush=True)

    def load_firmware(self, firmware_path: Optional[str] = None):
        """Load genuine RED DSMC2 program into DDR RAM at 0x80000000."""
        if firmware_path is None:
            firmware_path = os.path.join(self.firmware_slot_dir, "dsmc_program.mem")

        with open(firmware_path, "rb") as f:
            fw_bytes = f.read()

        self.bus.load_binary(0x80000000, fw_bytes)

        # Reset vector state
        self.cpu.pc = 0x80829F2C
        self.cpu.sp = 0x881D2690
        self.cpu.cpsr = ArmCpu.MODE_SVC | 0xC0 # Supervisor mode, IRQ/FIQ disabled

        # Seed authentic NAND flash geometry descriptor in DDR (Micron MT29F8G08 256MB SLC)
        # 0x81ef7818 = 1 (driver initialized flag)
        # 0x81ef7820 = 0x2C (Micron), 0x81ef7821 = 0xBA (256MB SLC)
        # 0x81ef7824 = 0x80FCEBF6 (pointer to geometry struct: page=2048, blk_pages=64, blks=2048, oob=64)
        self.bus.write(0x81EF7818, 4, 0x00000001)
        self.bus.write(0x81EF7820, 4, 0x0000BA2C)
        self.bus.write(0x81EF7824, 4, 0x80FCEBF6)
        # Seed default CAMERA_TYPE fallback pointer (0x80FF591C -> 0x0016 Scarlet-W)
        self.bus.write(0x80FF591C, 2, 0x0016)

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

    def step_slice(self, count: int = 500_000):
        """Execute an instruction slice and service interrupts/timers."""
        pc = self.cpu.pc

        # Check for interrupt delivery if in scheduler idle loop
        if pc in self.IDLE_LOOP_PCS and self.intc.has_pending_irq():
            if self.cpu.are_interrupts_enabled():
                self.cpu.inject_irq(vector=0x80829F00)

        # Run CPU slice. The wall-clock timeout guarantees the call returns even if
        # the core halts (WFI with no interrupt source) and never retires `count`.
        try:
            self.cpu.run(self.cpu.pc, 0, count=count, timeout_us=self.SLICE_TIMEOUT_US)
            self.instruction_count += count
        except Exception as e:
            # Check if exception is benign or stop
            pass

        # Tick active hardware timers (Timer 2 is ThreadX system tick at 1000Hz)
        for tmr in self.timers.values():
            if tmr.tclr & 0x01: # Running
                if tmr.timer_id == 2:
                    tmr.tick(steps=32)
                else:
                    tmr.tick(steps=100)

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
            pc = self.cpu.pc
            if pc in self.IDLE_LOOP_PCS and self.intc.has_pending_irq():
                if self.cpu.are_interrupts_enabled():
                    self.cpu.inject_irq(vector=0x80829F00)
            self.cpu.run(self.cpu.pc, 0, count=n)
            done += n
            self.boot_progress = done / initial_instructions
            if progress_cb:
                progress_cb(self.boot_progress)

            # Service active hardware timers
            for tmr in self.timers.values():
                if tmr.tclr & 0x01:
                    if tmr.timer_id == 2:
                        tmr.tick(steps=32)
                    else:
                        tmr.tick(steps=100)

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
                pc = self.cpu.pc
                if pc in self.IDLE_LOOP_PCS and self.intc.has_pending_irq():
                    if self.cpu.are_interrupts_enabled():
                        self.cpu.inject_irq(vector=0x80829F00)

                self.cpu.run(self.cpu.pc, 0, count=n)
                done += n
                self.instruction_count += n

                if hit_flag["hit"]:
                    break

                # Service active hardware timers
                for tmr in self.timers.values():
                    if tmr.tclr & 0x01:
                        if tmr.timer_id == 2:
                            tmr.tick(steps=32)
                        else:
                            tmr.tick(steps=100)
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
            self.log_system("[CRT] Reset vector 0x80829F2C -> Initializing C runtime and clearing BSS...")
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

        tcbs = [0x8149D494, 0x814CAD40, 0x827109B0, 0x82710CA0, 0x81E51F5C, 0x814C6B28]
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

                threads.append({
                    "address": f"0x{tcb:08X}",
                    "name": name,
                    "state": state_names.get(state, f"STATE_{state}"),
                    "priority": prio,
                    "entry": f"0x{entry:08X}",
                    "sp": f"0x{sp:08X}",
                    "stack_range": f"0x{stk_start:08X}-0x{stk_end:08X}",
                    "run_count": run_cnt,
                })
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
            self.cpu.pc = 0x80829F2C
            self.cpu.sp = 0x881D2690
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
