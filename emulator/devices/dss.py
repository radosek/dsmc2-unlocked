"""
OMAP3630 Display Subsystem (DSS / DISPC) Model for RED DSMC2.
Captures genuine RedUi framebuffer pointers, resolution, and pixel streams directly from DDR.
"""

from typing import Optional, Tuple
from emulator.core.bus import Device


class OmapDss(Device):
    """
    OMAP3630 Display Subsystem (DSS) and Display Controller (DISPC).
    Located at 0x48050000 - 0x48060000.
    """

    BASE_ADDR = 0x48050000
    SIZE = 0x1000

    # Authentic DSMC2 Firmware Pipeline Framebuffer Addresses
    FB_PIPELINE_LCD_PRIMARY = 0x87400000
    FB_PIPELINE_LCD_OVERLAY = 0x8E200000
    FB_PIPELINE_HDMI = 0x87000000
    FB_PIPELINE_HDMI_OVERLAY = 0x8E000000
    FB_PIPELINE_HDSDI = 0x87200000
    FB_PIPELINE_HDSDI_OVERLAY = 0x8E100000

    def __init__(self, bus):
        self.bus = bus

        # DISPC Registers (offset 0x400)
        self.dispc_control = 0
        self.dispc_config = 0
        self.dispc_size_lcd = (575 << 16) | 1023 # Default 1024x576 native DSMC2
        self.dispc_gfx_ba0 = 0x8C000000         # Default framebuffer in high DDR
        self.dispc_gfx_ba1 = 0x8C000000
        self.dispc_gfx_size = (575 << 16) | 1023
        self.dispc_gfx_attributes = 0x00000009   # Format: RGB24 / ARGB32
        self.dispc_gfx_row_inc = 1
        self.dispc_gfx_pixel_inc = 1
        self.dispc_irqstatus = 0
        self.dispc_irqenable = 0

        self.registers = {}

    @property
    def width(self) -> int:
        hsize = (self.dispc_size_lcd & 0x07FF) + 1
        return hsize if hsize > 0 else 1024

    @property
    def height(self) -> int:
        vsize = ((self.dispc_size_lcd >> 16) & 0x07FF) + 1
        return vsize if vsize > 0 else 576

    @property
    def framebuffer_address(self) -> int:
        return self.dispc_gfx_ba0

    def get_framebuffer_bytes(self) -> bytes:
        """Read live framebuffer pixels directly from simulated DDR memory."""
        w = self.width
        h = self.height
        # Determine bytes per pixel: attribute bits [4:1]
        fmt = (self.dispc_gfx_attributes >> 1) & 0x0F
        if fmt in (0x08, 0x09, 0x0D): # RGB24 / ARGB32
            bpp = 4
        elif fmt in (0x06, 0x07): # RGB16 / RGB565
            bpp = 2
        else:
            bpp = 4 # Default 32bpp

        size = w * h * bpp
        for fb_addr in (self.FB_PIPELINE_LCD_PRIMARY, self.framebuffer_address):
            try:
                buf = self.bus.read_mem(fb_addr, size)
                if any(buf):
                    return buf
            except Exception:
                pass
        return b"\x00" * size

    def read(self, offset: int, size: int) -> int:
        if offset == 0x00: # DSS_SYSSTATUS
            return 0x01 # RESETDONE
        elif offset == 0x400: # DISPC_REVISION
            return 0x30
        elif offset == 0x414: # DISPC_SYSSTATUS
            return 0x01 # RESETDONE
        elif offset == 0x418: # DISPC_IRQSTATUS
            return self.dispc_irqstatus
        elif offset == 0x41C: # DISPC_IRQENABLE
            return self.dispc_irqenable
        elif offset == 0x440: # DISPC_CONTROL
            return self.dispc_control
        elif offset == 0x444: # DISPC_CONFIG
            return self.dispc_config
        elif offset == 0x47C: # DISPC_SIZE_LCD
            return self.dispc_size_lcd
        elif offset == 0x480: # DISPC_GFX_BA0
            return self.dispc_gfx_ba0
        elif offset == 0x484: # DISPC_GFX_BA1
            return self.dispc_gfx_ba1
        elif offset == 0x48C: # DISPC_GFX_SIZE
            return self.dispc_gfx_size
        elif offset == 0x4A0: # DISPC_GFX_ATTRIBUTES
            return self.dispc_gfx_attributes
        return self.registers.get(offset, 0)

    def write(self, offset: int, size: int, value: int):
        self.registers[offset] = value
        if offset == 0x418:
            self.dispc_irqstatus &= ~value
        elif offset == 0x41C:
            self.dispc_irqenable = value
        elif offset == 0x440:
            self.dispc_control = value
        elif offset == 0x444:
            self.dispc_config = value
        elif offset == 0x47C:
            self.dispc_size_lcd = value
        elif offset == 0x480:
            self.dispc_gfx_ba0 = value
        elif offset == 0x484:
            self.dispc_gfx_ba1 = value
        elif offset == 0x48C:
            self.dispc_gfx_size = value
        elif offset == 0x4A0:
            self.dispc_gfx_attributes = value
