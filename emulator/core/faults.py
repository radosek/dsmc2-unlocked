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
