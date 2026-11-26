"""
DSMC2 Sidekick MCU + Peripherals Core Model (Priority 3, Tip #2B).

Models the RED DSMC2 Sidekick side-handle controller as a self-contained MCU target with:
  - Private 64 KB Flash (@0x08000000) and 16 KB SRAM (@0x20000000) memory space
  - Rotary dial + navigation / user buttons (MENU, BACK, ENTER, ROTARY_CW/CCW, USER_A..D)
  - 220x176 monochrome OLED status display framebuffer synchronized with camera parameters
  - Deterministic RCP/telemetry frame queue between Sidekick and Brain
"""

import io
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple
from PIL import Image

from emulator.rcp.wire import build_packet, CMD_SET


# Compact 5x7 uppercase/digit bitmap font for legible 220x176 monochrome OLED rendering.
_FONT_5X7: Dict[str, Tuple[int, ...]] = {
    " ": (0x00, 0x00, 0x00, 0x00, 0x00),
    "-": (0x08, 0x08, 0x08, 0x08, 0x08),
    ":": (0x00, 0x36, 0x36, 0x00, 0x00),
    "/": (0x20, 0x10, 0x08, 0x04, 0x02),
    ".": (0x00, 0x60, 0x60, 0x00, 0x00),
    "%": (0x23, 0x13, 0x08, 0x64, 0x62),
    "0": (0x3E, 0x51, 0x49, 0x45, 0x3E),
    "1": (0x00, 0x42, 0x7F, 0x40, 0x00),
    "2": (0x42, 0x61, 0x51, 0x49, 0x46),
    "3": (0x21, 0x41, 0x45, 0x4B, 0x31),
    "4": (0x18, 0x14, 0x12, 0x7F, 0x10),
    "5": (0x27, 0x45, 0x45, 0x45, 0x39),
    "6": (0x3C, 0x4A, 0x49, 0x49, 0x30),
    "7": (0x01, 0x71, 0x09, 0x05, 0x03),
    "8": (0x36, 0x49, 0x49, 0x49, 0x36),
    "9": (0x06, 0x49, 0x49, 0x29, 0x1E),
    "A": (0x7E, 0x11, 0x11, 0x11, 0x7E),
    "B": (0x7F, 0x49, 0x49, 0x49, 0x36),
    "C": (0x3E, 0x41, 0x41, 0x41, 0x22),
    "D": (0x7F, 0x41, 0x41, 0x22, 0x1C),
    "E": (0x7F, 0x49, 0x49, 0x49, 0x41),
    "F": (0x7F, 0x09, 0x09, 0x09, 0x01),
    "G": (0x3E, 0x41, 0x49, 0x49, 0x7A),
    "H": (0x7F, 0x08, 0x08, 0x08, 0x7F),
    "I": (0x00, 0x41, 0x7F, 0x41, 0x00),
    "K": (0x7F, 0x08, 0x14, 0x22, 0x41),
    "L": (0x7F, 0x40, 0x40, 0x40, 0x40),
    "M": (0x7F, 0x02, 0x0C, 0x02, 0x7F),
    "N": (0x7F, 0x04, 0x08, 0x10, 0x7F),
    "O": (0x3E, 0x41, 0x41, 0x41, 0x3E),
    "P": (0x7F, 0x09, 0x09, 0x09, 0x06),
    "R": (0x7F, 0x09, 0x19, 0x29, 0x46),
    "S": (0x46, 0x49, 0x49, 0x49, 0x31),
    "T": (0x01, 0x01, 0x7F, 0x01, 0x01),
    "U": (0x3F, 0x40, 0x40, 0x40, 0x3F),
    "V": (0x1F, 0x20, 0x40, 0x20, 0x1F),
    "W": (0x3F, 0x40, 0x38, 0x40, 0x3F),
    "X": (0x63, 0x14, 0x08, 0x14, 0x63),
    "Y": (0x07, 0x08, 0x70, 0x08, 0x07),
}


class SidekickMcu:
    """Self-contained RED Sidekick MCU core + 220x176 OLED + rotary/button peripherals."""

    FLASH_BASE = 0x08000000
    FLASH_SIZE = 64 * 1024
    SRAM_BASE = 0x20000000
    SRAM_SIZE = 16 * 1024

    OLED_WIDTH = 220
    OLED_HEIGHT = 176

    BUTTONS = (
        "MENU",
        "BACK",
        "ENTER",
        "ROTARY_CW",
        "ROTARY_CCW",
        "USER_A",
        "USER_B",
        "USER_C",
        "USER_D",
    )
    MENU_PAGES = ("MAIN", "ISO", "SHUTTER", "KELVIN")
    ISO_STEPS = (250, 320, 400, 500, 640, 800, 1000, 1280, 1600, 2000, 2500, 3200)

    def __init__(self):
        self.name = "DSMC2_SIDEKICK"
        self.mcu_arch = "ARM_CORTEX_M4"
        self.flash = bytearray(self.FLASH_SIZE)
        self.sram = bytearray(self.SRAM_SIZE)
        # Seed Cortex-M vector table SP and Reset_Handler at flash[0..8]
        self.flash[0:4] = (self.SRAM_BASE + self.SRAM_SIZE).to_bytes(4, "little")
        self.flash[4:8] = (self.FLASH_BASE + 0x41).to_bytes(4, "little")
        self.pc = self.FLASH_BASE + 0x40
        self.cycles = 0
        self.connected = True
        self.state = "RUNNING"

        self.framebuffer = bytearray(self.OLED_WIDTH * self.OLED_HEIGHT)
        self.button_history: List[str] = []
        self.tx_frames: Deque[str] = deque(maxlen=64)
        self.rx_frames: Deque[str] = deque(maxlen=64)
        self.last_rcp2_packet: Optional[str] = None
        self._camera = None

        self.menu_page_idx = 0
        self.telemetry: Dict[str, Any] = {
            "fps": "24.00",
            "shutter": "1/48",
            "iso": 800,
            "kelvin": 5600,
            "battery_pct": 92,
            "media_pct": 84,
            "recording": False,
        }
        self.render_oled_status()

    @property
    def active_page(self) -> str:
        return self.MENU_PAGES[self.menu_page_idx % len(self.MENU_PAGES)]

    def step(self, cycles: int = 100):
        """Advance Sidekick MCU execution cycles."""
        self.cycles += max(1, int(cycles))

    def attach_camera(self, cam) -> None:
        """Bind Sidekick serial/telemetry link to ``Dsmc2Camera`` and sync initial OLED state."""
        self._camera = cam
        self.sync_from_camera(cam)

    def press_button(self, button: str) -> Dict[str, Any]:
        """Inject a Sidekick physical button or rotary detent event."""
        btn = button.strip().upper()
        if btn not in self.BUTTONS:
            raise ValueError(f"Unknown Sidekick button: {button}")
        self.button_history.append(btn)
        self.step(250)

        cmd_emitted: Optional[str] = None
        rcp2_param: Optional[Tuple[str, str]] = None
        if btn == "MENU":
            self.menu_page_idx = (self.menu_page_idx + 1) % len(self.MENU_PAGES)
            cmd_emitted = f"PAGE:{self.active_page}"
        elif btn == "BACK":
            self.menu_page_idx = 0
            cmd_emitted = "PAGE:MAIN"
        elif btn in ("ROTARY_CW", "ROTARY_CCW"):
            delta = 1 if btn == "ROTARY_CW" else -1
            page = self.active_page
            if page in ("MAIN", "ISO"):
                cur_iso = int(self.telemetry["iso"])
                idx = min(
                    range(len(self.ISO_STEPS)),
                    key=lambda i: abs(self.ISO_STEPS[i] - cur_iso),
                )
                new_idx = max(0, min(len(self.ISO_STEPS) - 1, idx + delta))
                self.telemetry["iso"] = self.ISO_STEPS[new_idx]
                cmd_emitted = f"$S:ISO:{self.telemetry['iso']}"
                rcp2_param = ("ISO", str(self.telemetry["iso"]))
            elif page == "KELVIN":
                self.telemetry["kelvin"] = max(
                    1700, min(10000, int(self.telemetry["kelvin"]) + delta * 100)
                )
                cmd_emitted = f"$S:COLTEMP:{self.telemetry['kelvin']}"
                rcp2_param = ("COLTEMP", str(self.telemetry["kelvin"]))
        elif btn == "ENTER":
            cmd_emitted = f"CONFIRM:{self.active_page}"
        else:
            cmd_emitted = f"KEY:{btn}"

        if rcp2_param is not None:
            pname, pval = rcp2_param
            pkt_bytes = build_packet(CMD_SET, pname, [pval], source="SK")
            pkt_str = pkt_bytes.decode("ascii").strip()
            self.last_rcp2_packet = pkt_str
            self.tx_frames.append(pkt_str)
            if self._camera is not None:
                uarts = getattr(self._camera, "uarts", None)
                if isinstance(uarts, dict) and 3 in uarts:
                    uarts[3].write_rx(pkt_bytes)
                rcp = getattr(self._camera, "rcp", None)
                if rcp is not None:
                    resp = rcp.process_command(pkt_str)
                    if resp:
                        self.rx_frames.append(resp)
                    self.sync_from_camera(self._camera)
        elif cmd_emitted:
            self.tx_frames.append(cmd_emitted)

        self.render_oled_status()
        return {
            "button": btn,
            "active_page": self.active_page,
            "cmd": cmd_emitted,
            "rcp2_packet": self.last_rcp2_packet if rcp2_param else None,
        }

    def sync_from_camera(self, cam) -> None:
        """Pull camera UI / RCP state into Sidekick telemetry and refresh OLED."""
        rcp = getattr(cam, "rcp", None)
        state = getattr(rcp, "state", None) if rcp is not None else None
        if isinstance(state, dict):
            if "frame_rate" in state:
                self.telemetry["fps"] = state["frame_rate"]
            if "iso" in state:
                self.telemetry["iso"] = int(state["iso"])
            if "color_temperature" in state:
                self.telemetry["kelvin"] = int(state["color_temperature"])
            if "record_state" in state:
                self.telemetry["recording"] = str(state["record_state"]) != "0"
        self.render_oled_status()

    def _draw_text(self, x: int, y: int, text: str, fg: int = 0xFF, scale: int = 2):
        cursor_x = x
        for ch in text.upper():
            glyph = _FONT_5X7.get(ch, _FONT_5X7[" "])
            for gx, col_bits in enumerate(glyph):
                for gy in range(7):
                    if (col_bits >> gy) & 1:
                        for sy in range(scale):
                            py = y + gy * scale + sy
                            if not (0 <= py < self.OLED_HEIGHT):
                                continue
                            row_off = py * self.OLED_WIDTH
                            for sx in range(scale):
                                px = cursor_x + gx * scale + sx
                                if 0 <= px < self.OLED_WIDTH:
                                    self.framebuffer[row_off + px] = fg
            cursor_x += 6 * scale

    def render_oled_status(self) -> bytearray:
        """Render camera telemetry into the 220x176 8-bit monochrome OLED framebuffer."""
        w, h = self.OLED_WIDTH, self.OLED_HEIGHT
        self.framebuffer[:] = b"\x00" * (w * h)
        # 1px top/bottom/side frame border
        for x in range(w):
            self.framebuffer[x] = 0x80
            self.framebuffer[(h - 1) * w + x] = 0x80
        for y in range(h):
            self.framebuffer[y * w] = 0x80
            self.framebuffer[y * w + (w - 1)] = 0x80

        rec_tag = "REC" if self.telemetry["recording"] else "STBY"
        self._draw_text(10, 12, f"{rec_tag}  {self.active_page}", fg=0xFF, scale=2)
        self._draw_text(10, 44, f"FPS {self.telemetry['fps']}", fg=0xE0, scale=2)
        self._draw_text(10, 74, f"ISO {self.telemetry['iso']}", fg=0xFF, scale=2)
        self._draw_text(10, 104, f"WB  {self.telemetry['kelvin']}K", fg=0xE0, scale=2)
        self._draw_text(
            10,
            138,
            f"BAT:{self.telemetry['battery_pct']}% SSD:{self.telemetry['media_pct']}%",
            fg=0xC0,
            scale=1,
        )
        return self.framebuffer

    def render_oled_png_bytes(self) -> bytes:
        """Encode the 220x176 monochrome OLED framebuffer as PNG bytes."""
        img = Image.frombytes("L", (self.OLED_WIDTH, self.OLED_HEIGHT), bytes(self.framebuffer))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def get_status(self) -> Dict[str, Any]:
        lit_pixels = sum(1 for px in self.framebuffer if px > 0)
        return {
            "name": self.name,
            "arch": self.mcu_arch,
            "state": self.state,
            "connected": self.connected,
            "cycles": self.cycles,
            "active_page": self.active_page,
            "oled_resolution": f"{self.OLED_WIDTH}x{self.OLED_HEIGHT}",
            "oled_lit_pixels": lit_pixels,
            "button_count": len(self.button_history),
            "last_cmd": self.tx_frames[-1] if self.tx_frames else None,
            "last_rcp2_packet": self.last_rcp2_packet,
            "rx_count": len(self.rx_frames),
            "telemetry": dict(self.telemetry),
        }
