"""
Hardware Fault Injection Subsystem for RED DSMC2 Virtual Camera.
Simulates hardware failures, bus faults, interrupt storms, memory ECC corruptions,
and environment data corruption to verify firmware resilience and error handlers.
"""

import os
from typing import Dict, Any, Optional


class HardwareFaultInjector:
    """Injects simulated hardware faults into the active DSMC2 camera instance."""

    def __init__(self, camera):
        self.camera = camera

    def inject_fault(self, fault_type: str, **kwargs) -> Dict[str, Any]:
        """Dispatch and apply a hardware or system fault."""
        norm_type = fault_type.strip().upper()

        if norm_type in ("INTC_IRQ_LOCKUP", "TOUCH_STORM"):
            # Unmask and assert IRQ 58 (touch controller / I2C3) to simulate touch lockup storm
            if hasattr(self.camera, "intc") and self.camera.intc:
                bank = 58 // 32
                bit = 1 << (58 % 32)
                self.camera.intc.mir[bank] &= ~bit
                self.camera.intc.assert_irq(58)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[FAULT] Injected INTC IRQ lockup: continuous IRQ 58 touch storm asserted.")
            return {
                "fault": "INTC_IRQ_LOCKUP",
                "status": "injected",
                "details": "IRQ 58 unmasked and asserted continuously on INTC to simulate touch controller lockup."
            }

        elif norm_type in ("DDR_ECC_CORRUPT", "DDR_BITFLIP"):
            # Corrupt single bit in DDR memory (0x80500000)
            corrupt_addr = kwargs.get("address", 0x80500000)
            try:
                curr_byte = self.camera.cpu.uc.mem_read(corrupt_addr, 1)[0]
                flipped_byte = curr_byte ^ 0x01
                self.camera.cpu.uc.mem_write(corrupt_addr, bytes([flipped_byte]))
                details = f"Flipped bit at 0x{corrupt_addr:08X} (0x{curr_byte:02X} -> 0x{flipped_byte:02X})."
            except Exception as e:
                details = f"DDR corruption attempt at 0x{corrupt_addr:08X}: {e}"

            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[FAULT] Injected DDR ECC memory corruption: {details}")
            return {
                "fault": "DDR_ECC_CORRUPT",
                "status": "injected",
                "details": details
            }

        elif norm_type in ("GPTIMER_DRIFT", "CLOCK_DRIFT"):
            # Induce +15% drift in GPTimer1/2
            if hasattr(self.camera, "gptimers") and self.camera.gptimers:
                t1 = self.camera.gptimers.get(1)
                if t1:
                    t1.tcrr = (t1.tcrr + 100000) & 0xFFFFFFFF
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[FAULT] Injected GPTimer system clock drift (+15% drift on GPTimer1).")
            return {
                "fault": "GPTIMER_DRIFT",
                "status": "injected",
                "details": "GPTimer1 counter adjusted by +100,000 ticks to induce timing skew."
            }

        elif norm_type in ("MONITOR_DISCONNECT",):
            self.camera.inject_fault("monitor_disconnect")
            return {
                "fault": "MONITOR_DISCONNECT",
                "status": "injected",
                "details": "RED Touch LCD removed from I2C3 bus (0x4B and 0x50 unmounted)."
            }

        elif norm_type in ("MONITOR_CONNECT",):
            self.camera.inject_fault("monitor_connect")
            return {
                "fault": "MONITOR_CONNECT",
                "status": "injected",
                "details": "RED Touch LCD reconnected to I2C3 bus."
            }

        elif norm_type in ("I2C_NACK",):
            bus_id = kwargs.get("bus", 3)
            self.camera.inject_fault("i2c_nack", bus=bus_id)
            return {
                "fault": "I2C_NACK",
                "status": "injected",
                "details": f"I2C bus {bus_id} transaction forced to return NACK (STAT bit 1 asserted)."
            }

        elif norm_type in ("CORRUPT_ENV",):
            self.camera.inject_fault("corrupt_env")
            return {
                "fault": "CORRUPT_ENV",
                "status": "injected",
                "details": "Persistent /env partition calibrated parameters set to corrupt payload."
            }

        elif norm_type in ("WATCHDOG_RESET",):
            self.camera.inject_fault("watchdog_reset")
            return {
                "fault": "WATCHDOG_RESET",
                "status": "injected",
                "details": "Watchdog reset triggered: CPU registers reset to boot vector 0x80829F2C."
            }

        elif norm_type in ("UCD_UV_FAULT",):
            board = str(kwargs.get("board", "isp")).lower()
            page = int(kwargs.get("page", 0))
            drop_volts = float(kwargs.get("drop_volts", 0.2))
            ucd_map = {
                "iob": getattr(self.camera, "ucd_iob", None),
                "isp": getattr(self.camera, "ucd_isp", None),
                "sensor": getattr(self.camera, "ucd_sensor", None),
            }
            seq = ucd_map.get(board)
            if seq is None:
                return {"fault": norm_type, "status": "error", "message": f"Unknown UCD board '{board}'"}
            seq.inject_uv_fault(page=page, drop_volts=drop_volts)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[FAULT] Injected UCD UV_FAULT on {board} page {page} (-{drop_volts:.3f}V).")
            return {
                "fault": "UCD_UV_FAULT",
                "status": "injected",
                "details": f"Under-voltage fault latched on {board.upper()} PMBus page {page}.",
            }

        elif norm_type in ("E49_ISP_POWER_FAULT",):
            i2c2 = self.camera.i2c.get(2)
            if i2c2:
                i2c2.slaves.pop(0x70, None)
                i2c2.slaves.pop(0x6C, None)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[FAULT] Injected E49 ISP power fault: I2C2 0x70 (UCD9090) & 0x6C (Si5346) offline.")
            return {
                "fault": "E49_ISP_POWER_FAULT",
                "status": "injected",
                "details": "ISP power sequencer (0x70) and Si5346 clock synth (0x6C) removed from I2C2.",
            }

        elif norm_type in ("E49_ISP_POWER_RESTORE",):
            i2c2 = self.camera.i2c.get(2)
            if i2c2:
                if getattr(self.camera, "ucd_isp", None) is not None:
                    i2c2.attach_slave(self.camera.ucd_isp)
                if getattr(self.camera, "si5346", None) is not None:
                    i2c2.attach_slave(self.camera.si5346)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[FAULT] Restored E49 ISP power domain: I2C2 0x70 & 0x6C online.")
            return {
                "fault": "E49_ISP_POWER_RESTORE",
                "status": "injected",
                "details": "ISP power sequencer (0x70) and Si5346 (0x6C) restored on I2C2.",
            }

        elif norm_type in ("ONEWIRE_BUS_FAULT",):
            if hasattr(self.camera, "hdq") and self.camera.hdq:
                self.camera.hdq.bus_fault = bool(kwargs.get("enable", True))
            if hasattr(self.camera, "log_system"):
                self.camera.log_system("[FAULT] Injected HDQ / 1-Wire bus fault (no presence detect).")
            return {
                "fault": "ONEWIRE_BUS_FAULT",
                "status": "injected",
                "details": "HDQ 1-Wire presence detect disabled (simulating bus short/open).",
            }

        elif norm_type in ("ONEWIRE_BOARD_MISMATCH",):
            board = str(kwargs.get("board", "ISP")).upper()
            bad_serial = str(kwargs.get("serial", "BAD-SERIAL-9999"))
            ok = hasattr(self.camera, "hdq") and self.camera.hdq.corrupt_board_serial(board, bad_serial)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[FAULT] Injected 1-Wire board serial mismatch on {board} -> {bad_serial} (0x03).")
            return {
                "fault": "ONEWIRE_BOARD_MISMATCH",
                "status": "injected" if ok else "error",
                "details": f"{board} 1-Wire EEPROM serial overwritten without re-signing.",
            }

        elif norm_type in ("ONEWIRE_BOARD_MISSING",):
            board = str(kwargs.get("board", "SENSOR")).upper()
            ok = hasattr(self.camera, "hdq") and self.camera.hdq.remove_board(board)
            if hasattr(self.camera, "log_system"):
                self.camera.log_system(f"[FAULT] Removed {board} from 1-Wire bus (0x04 / missing board).")
            return {
                "fault": "ONEWIRE_BOARD_MISSING",
                "status": "injected" if ok else "error",
                "details": f"{board} removed from HDQ 1-Wire board enumeration.",
            }

        else:
            # Fall back to camera.inject_fault if supported
            try:
                self.camera.inject_fault(fault_type.lower(), **kwargs)
                return {
                    "fault": fault_type,
                    "status": "injected",
                    "details": f"Dispatched generic fault '{fault_type}' to camera."
                }
            except Exception as e:
                return {
                    "fault": fault_type,
                    "status": "error",
                    "message": str(e)
                }
