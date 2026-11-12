"""
DSMC2 Virtual Brain Web Studio.
Provides a modern, freeze-proof browser interface running on a dedicated local port (default: 8765).
Includes:
- Authentic 1024x576 RED Touch 7.0 LCD frame streaming (MJPEG)
- Direct touch coordinate mapping to Atmel maXTouch controller & RedUi menu system
- Physical tactile controls (Record, Power, Menu, 1:1 Mag, User keys, D-Pad)
- Real-time Developer Workbench (UART4 console, RCP inspector, ThreadX RTOS monitor, Snapshots, Faults)
"""

import os
import io
import json
import time
import socket
import zlib
import urllib.parse
import re
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional, Tuple, Dict, Any, List
from PIL import Image, ImageDraw, ImageFont

from emulator.camera import Dsmc2Camera
from emulator.ui.redui import RedUiEngine
from emulator.rcp.protocol import RcpProtocol

try:
    HUD_FONT_LG = ImageFont.truetype("arialbd.ttf", 16)
    HUD_FONT_MED = ImageFont.truetype("arialbd.ttf", 13)
    HUD_FONT_SM = ImageFont.truetype("arial.ttf", 10)
    HUD_FONT_BOLD_SM = ImageFont.truetype("arialbd.ttf", 10)
except Exception:
    HUD_FONT_LG = ImageFont.load_default()
    HUD_FONT_MED = ImageFont.load_default()
    HUD_FONT_SM = ImageFont.load_default()
    HUD_FONT_BOLD_SM = ImageFont.load_default()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP server allowing concurrent MJPEG streaming and API requests."""
    daemon_threads = True
    allow_reuse_address = True


class ScreenCompositor:
    """
    Decoupled graphics compositor for RED DSMC2.
    Produces authentic 1024x576 LCD frames with genuine HUD overlays, splash screen, and RedUi system.
    """

    NATIVE_WIDTH = 1024
    NATIVE_HEIGHT = 576

    def __init__(self, camera: Dsmc2Camera):
        self.camera = camera
        self.redui = RedUiEngine(camera)
        self.splash_image: Optional[Image.Image] = self._load_splash_screen()
        self.sensor_feed_image: Optional[Image.Image] = self._load_sensor_feed_image()
        self._zero_fb_buf = b"\x00" * (self.NATIVE_WIDTH * self.NATIVE_HEIGHT * 4)

    def _load_splash_screen(self) -> Optional[Image.Image]:
        splash_path = os.path.join(self.camera.firmware_slot_dir, "res", "splash_screen.bin")
        if not os.path.exists(splash_path):
            splash_path = os.path.join(
                self.camera.workspace_root,
                "firmware_store", "unpacked", "scarlet_w_7_4_1", "slot", "res", "splash_screen.bin"
            )
        if not os.path.exists(splash_path):
            return None
        try:
            with open(splash_path, "rb") as f:
                data = f.read()
            if data.startswith(b"REDZLIB0"):
                decomp = zlib.decompress(data[12:])
                pixels = decomp[8:8 + (1024 * 576 * 3)]
                return Image.frombytes("RGB", (1024, 576), pixels)
        except Exception as e:
            print(f"[Compositor] Failed to load splash screen: {e}")
            return None
        return None

    def _load_sensor_feed_image(self) -> Optional[Image.Image]:
        """Load authentic cinema sensor background in place of the gaussian swirl."""
        sensor_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res", "sensor_feed_cinema.jpg")
        if not os.path.exists(sensor_path):
            sensor_path = os.path.join(self.camera.workspace_root, "emulator", "res", "sensor_feed_cinema.jpg")
        if not os.path.exists(sensor_path):
            return None
        try:
            im = Image.open(sensor_path)
            if im.size != (self.NATIVE_WIDTH, self.NATIVE_HEIGHT):
                im = im.resize((self.NATIVE_WIDTH, self.NATIVE_HEIGHT), Image.Resampling.LANCZOS)
            return im.convert("RGB")
        except Exception as e:
            print(f"[Compositor] Failed to load cinema sensor feed: {e}")
            return None

    def compose_frame(self) -> Image.Image:
        """Compose raw LCD frame with overlays."""
        state = self.camera.power_state

        if state == self.camera.POWER_STANDBY:
            img = self._render_standby_screen()
        elif state == self.camera.POWER_BOOTING:
            img = self._render_booting_screen()
        else: # POWER_ON
            fb_bytes = self.camera.get_frame()
            is_blank = (fb_bytes == self._zero_fb_buf)

            if not is_blank and len(fb_bytes) >= self.NATIVE_WIDTH * self.NATIVE_HEIGHT * 4:
                img = Image.frombytes("RGBA", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), fb_bytes)
            elif self.sensor_feed_image:
                img = self.sensor_feed_image.copy()
            elif self.splash_image:
                img = self.splash_image.copy()
            else:
                img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))

            # Draw RED HUD
            try:
                self._draw_hud(img)
            except Exception as e:
                print(f"[Compositor] Error drawing HUD: {e}")

            # Draw RedUi layer (Dialogs, Menu, Tools, Reticle)
            try:
                img = self.redui.render(img)
            except Exception as e:
                print(f"[Compositor] Error drawing RedUi: {e}")

        return img

    def get_jpeg_bytes(self, quality: int = 85) -> bytes:
        """Render current frame to JPEG byte buffer."""
        img = self.compose_frame()
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def compose_hdmi_frame(self, mode: Optional[str] = None) -> Image.Image:
        """
        Compose dedicated clean or broadcast HDMI output frame.
        Independent from the RED Touch LCD display (no touch menus or HUD).
        Modes:
          - CLEAN: Pristine sensor video feed.
          - BROADCAST_TALLY: Video feed with tally indicator when recording and SMPTE timecode.
          - FRAME_GUIDES: Video feed with 2.39:1 aspect ratio safe action frame lines.
        """
        if hasattr(self.camera, "iob0") and self.camera.iob0:
            if mode:
                self.camera.iob0.set_hdmi_mode(mode)
            effective_mode = self.camera.iob0.hdmi_mode
            self.camera.iob0.hdmi_frames_rendered += 1
        else:
            effective_mode = mode or "CLEAN"

        state = self.camera.power_state
        if state == self.camera.POWER_STANDBY:
            img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.text((self.NATIVE_WIDTH // 2 - 140, self.NATIVE_HEIGHT // 2 - 10), "HDMI OUT: NO SIGNAL (STANDBY)", fill=(80, 80, 80), font=HUD_FONT_MED)
            return img
        elif state == self.camera.POWER_BOOTING:
            if self.splash_image:
                img = self.splash_image.copy()
            else:
                img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))
            return img

        # Live sensor feed for clean HDMI
        fb_bytes = self.camera.get_frame()
        is_blank = (fb_bytes == self._zero_fb_buf)
        if not is_blank and len(fb_bytes) >= self.NATIVE_WIDTH * self.NATIVE_HEIGHT * 4:
            img = Image.frombytes("RGBA", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), fb_bytes)
        elif self.sensor_feed_image:
            img = self.sensor_feed_image.copy()
        elif self.splash_image:
            img = self.splash_image.copy()
        else:
            img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))

        if img.mode != "RGB":
            img = img.convert("RGB")

        draw = ImageDraw.Draw(img)

        # Apply Broadcast Overlays according to mode
        if effective_mode == "BROADCAST_TALLY":
            is_rec = (self.camera.recorder.record_state == 2)
            if is_rec:
                draw.rectangle([(0, 0), (self.NATIVE_WIDTH - 1, self.NATIVE_HEIGHT - 1)], outline=(220, 20, 20), width=4)
                draw.rectangle([(self.NATIVE_WIDTH - 110, 16), (self.NATIVE_WIDTH - 20, 46)], fill=(200, 20, 20))
                draw.text((self.NATIVE_WIDTH - 98, 22), "● REC", fill=(255, 255, 255), font=HUD_FONT_MED)

            tc = self.camera.recorder.current_timecode if hasattr(self.camera.recorder, "current_timecode") else "01:23:45:12"
            tc_w = 140
            tc_x = (self.NATIVE_WIDTH - tc_w) // 2
            draw.rectangle([(tc_x, self.NATIVE_HEIGHT - 36), (tc_x + tc_w, self.NATIVE_HEIGHT - 14)], fill=(0, 0, 0))
            draw.text((tc_x + 12, self.NATIVE_HEIGHT - 32), f"TC {tc}", fill=(255, 255, 255), font=HUD_FONT_MED)

        elif effective_mode == "FRAME_GUIDES":
            target_h = int(self.NATIVE_WIDTH / 2.39)
            bar_h = (self.NATIVE_HEIGHT - target_h) // 2
            draw.rectangle([(0, 0), (self.NATIVE_WIDTH, bar_h)], fill=(0, 0, 0))
            draw.rectangle([(0, self.NATIVE_HEIGHT - bar_h), (self.NATIVE_WIDTH, self.NATIVE_HEIGHT)], fill=(0, 0, 0))
            draw.line([(0, bar_h), (self.NATIVE_WIDTH, bar_h)], fill=(255, 255, 255), width=1)
            draw.line([(0, self.NATIVE_HEIGHT - bar_h), (self.NATIVE_WIDTH, self.NATIVE_HEIGHT - bar_h)], fill=(255, 255, 255), width=1)
            cx, cy = self.NATIVE_WIDTH // 2, self.NATIVE_HEIGHT // 2
            draw.line([(cx - 15, cy), (cx + 15, cy)], fill=(200, 200, 200), width=1)
            draw.line([(cx, cy - 15), (cx, cy + 15)], fill=(200, 200, 200), width=1)

        return img

    def get_hdmi_jpeg_bytes(self, quality: int = 85, mode: Optional[str] = None) -> bytes:
        """Render HDMI output frame to JPEG byte buffer."""
        img = self.compose_hdmi_frame(mode)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def _render_standby_screen(self) -> Image.Image:
        img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (6, 6, 6))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(10, 10), (self.NATIVE_WIDTH - 10, self.NATIVE_HEIGHT - 10)], outline=(30, 30, 30), width=2)
        cx, cy = self.NATIVE_WIDTH // 2, self.NATIVE_HEIGHT // 2

        card_w, card_h = 560, 200
        x1, y1 = cx - card_w // 2, cy - card_h // 2
        x2, y2 = cx + card_w // 2, cy + card_h // 2

        draw.rectangle([(x1, y1), (x2, y2)], fill=(16, 16, 16), outline=(48, 48, 48), width=2)
        draw.rectangle([(x1, y1), (x1 + 6, y2)], fill=(200, 20, 20)) # Red DSMC2 accent bar

        model_name = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K")
        draw.text((x1 + 30, y1 + 22), "RED DIGITAL CINEMA", fill=(170, 170, 170), font=HUD_FONT_SM)
        draw.text((x1 + 30, y1 + 42), f"DSMC2 BRAIN: {model_name}", fill=(240, 240, 240), font=HUD_FONT_LG)
        draw.text((x1 + 30, y1 + 75), "[ SYSTEM IN STANDBY ]", fill=(255, 170, 0), font=HUD_FONT_MED)
        draw.text((x1 + 30, y1 + 105), "DC IN 14.8V  •  Sensors & Display Sleeping  •  Hardware Ready", fill=(130, 130, 130), font=HUD_FONT_SM)

        draw.rectangle([(x1 + 25, y1 + 140), (x2 - 25, y1 + 175)], fill=(20, 35, 20), outline=(0, 180, 80), width=1)
        draw.text((x1 + 55, y1 + 150), ">>> TAP MONITOR OR CLICK [POWER ON] BELOW TO WAKE <<<", fill=(0, 255, 120), font=HUD_FONT_BOLD_SM)
        return img

    def _render_booting_screen(self) -> Image.Image:
        if self.splash_image:
            img = self.splash_image.copy()
        else:
            img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))
        draw = ImageDraw.Draw(img)
        cx, cy = 512, 288
        draw.rectangle([(cx - 240, cy - 50), (cx + 240, cy + 50)], fill=(0, 0, 0), outline=(0, 200, 100), width=2)
        pct = int(self.camera.boot_progress * 100)
        draw.text((cx - 120, cy - 35), f"BOOTING RED DSMC2... {pct}%", fill=(255, 255, 255))
        bar_x1, bar_y1 = cx - 200, cy - 5
        bar_x2, bar_y2 = cx + 200, cy + 15
        draw.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], outline=(80, 80, 80), width=1)
        fill_width = int(400 * max(0.0, min(1.0, self.camera.boot_progress)))
        if fill_width > 0:
            draw.rectangle([(bar_x1 + 1, bar_y1 + 1), (bar_x1 + fill_width, bar_y2 - 1)], fill=(0, 220, 100))
        draw.text((cx - 140, cy + 25), "Bringing up Cortex-A8, ThreadX & OMAP3...", fill=(160, 160, 160))
        return img

    def _draw_hud(self, img: Image.Image):
        draw = ImageDraw.Draw(img)
        rcp = self.camera.rcp
        fps = rcp.state.get(rcp.PARAM_FPS, "23.98")
        shutter = rcp.state.get(rcp.PARAM_SHUTTER, "1/48")
        iso = rcp.state.get(rcp.PARAM_ISO, "800")
        format_name = rcp.state.get(rcp.PARAM_FORMAT, "5K 16:9")
        record_state = rcp.state.get(rcp.PARAM_RECORD_STATE, "0")
        is_recording = (record_state == "2")
        lm = getattr(self.camera, "lens_mount", None)
        iris_str = f"f/{lm.current_aperture:.1f}" if (lm and lm.attached_lens) else rcp.state.get("aperture", "f/2.8")

        # 1. Top HUD Bar (Only drawn when full DSMC2 menu is not active)
        if not self.redui.is_menu_open:
            draw.rectangle([(0, 0), (self.NATIVE_WIDTH, 42)], fill=(0, 0, 0, 210))
            draw.line([(0, 42), (self.NATIVE_WIDTH, 42)], fill=(40, 40, 40), width=1)

            # Left STBY / REC / Model Badge (x: 12..82)
            if is_recording:
                draw.rectangle([(12, 6), (82, 34)], fill=(200, 20, 20), outline=(255, 60, 60), width=1)
                draw.text((22, 11), "• REC", fill=(255, 255, 255), font=HUD_FONT_MED)
            else:
                draw.rectangle([(12, 6), (82, 34)], fill=(28, 28, 28), outline=(60, 60, 60), width=1)
                draw.text((24, 11), "STBY", fill=(180, 180, 180), font=HUD_FONT_MED)

            # Model Menu header (x: 88..245)
            draw.rectangle([(88, 6), (245, 34)], fill=(28, 28, 28), outline=(60, 60, 60), width=1)
            model_name = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K")
            draw.text((96, 11), f"RED {model_name} [MENU]", fill=(220, 220, 220), font=HUD_FONT_SM)

            # FPS (x: 255..365)
            fps_active = (self.redui.active_dialog == "FPS")
            draw.rectangle([(255, 6), (365, 34)], fill=(28, 28, 28), outline=(220, 20, 20) if fps_active else (60, 60, 60), width=1)
            draw.text((265, 11), f"FPS: {fps}", fill=(255, 255, 255), font=HUD_FONT_MED)
            if fps_active:
                draw.line([(255, 35), (365, 35)], fill=(255, 30, 30), width=2)

            # SHUTTER (x: 375..495)
            shutter_active = (self.redui.active_dialog == "SHUTTER")
            draw.rectangle([(375, 6), (495, 34)], fill=(28, 28, 28), outline=(220, 20, 20) if shutter_active else (60, 60, 60), width=1)
            draw.text((385, 11), f"SHTR: {shutter}", fill=(255, 255, 255), font=HUD_FONT_MED)
            if shutter_active:
                draw.line([(375, 35), (495, 35)], fill=(255, 30, 30), width=2)

            # IRIS (x: 505..615)
            iris_active = (self.redui.active_dialog == "IRIS")
            draw.rectangle([(505, 6), (615, 34)], fill=(28, 28, 28), outline=(220, 20, 20) if iris_active else (60, 60, 60), width=1)
            draw.text((515, 11), f"IRIS: {iris_str}", fill=(255, 255, 255), font=HUD_FONT_MED)
            if iris_active:
                draw.line([(505, 35), (615, 35)], fill=(255, 30, 30), width=2)

            # ISO (x: 625..735)
            iso_active = (self.redui.active_dialog == "ISO")
            draw.rectangle([(625, 6), (735, 34)], fill=(28, 28, 28), outline=(220, 20, 20) if iso_active else (60, 60, 60), width=1)
            draw.text((635, 11), f"ISO: {iso}", fill=(255, 255, 255), font=HUD_FONT_MED)
            if iso_active:
                draw.line([(625, 35), (735, 35)], fill=(255, 30, 30), width=2)

            # FORMAT (x: 745..895)
            fmt_active = (self.redui.active_dialog == "FORMAT")
            draw.rectangle([(745, 6), (895, 34)], fill=(28, 28, 28), outline=(220, 20, 20) if fmt_active else (60, 60, 60), width=1)
            draw.text((755, 11), f"FORMAT: {format_name}", fill=(255, 255, 255), font=HUD_FONT_MED)
            if fmt_active:
                draw.line([(745, 35), (895, 35)], fill=(255, 30, 30), width=2)

            # Authentic Right-side Menu Button (x: 905..1014)
            draw.rectangle([(905, 6), (1014, 34)], fill=(32, 32, 32), outline=(220, 30, 30), width=1)
            draw.text((936, 11), "Menu", fill=(255, 255, 255), font=HUD_FONT_MED)

            # 2. Inside Frame Metadata
            rec = getattr(self.camera, "recorder", None)
            clip_name = rec.current_clip_name if (rec and rec.current_clip_name) else f"{rec.current_reel_id if rec else 'A001'}_C{rec.clip_number if rec else 1:03d}"
            draw.text((24, 492), f"{clip_name}", fill=(240, 240, 240), font=HUD_FONT_MED)

            timecode = "01:00:00:00" if not is_recording else f"01:00:{int(self.camera.instruction_count/1000000)%60:02d}:12"
            tc_color = (255, 50, 50) if is_recording else (220, 220, 220)
            draw.text((865, 492), timecode, fill=tc_color, font=HUD_FONT_MED)

            # Subtle frame lines
            draw.line([(20, 48), (20, 512)], fill=(80, 20, 20), width=1)
            draw.line([(1004, 48), (1004, 512)], fill=(80, 20, 20), width=1)

        # 3. Authentic Bottom Status Bar (Always visible at y: 520..576)
        draw.rectangle([(0, 520), (self.NATIVE_WIDTH, 576)], fill=(10, 10, 10))
        draw.line([(0, 520), (self.NATIVE_WIDTH, 520)], fill=(45, 45, 45), width=1)

        # Camera Icon Outline & FPS below
        cam_fill = (220, 20, 20) if is_recording else (30, 30, 30)
        draw.rectangle([(12, 528), (38, 548)], fill=cam_fill, outline=(220, 220, 220) if not is_recording else (255, 60, 60), width=1)
        draw.polygon([(38, 532), (46, 528), (46, 548), (38, 544)], fill=cam_fill, outline=(220, 220, 220) if not is_recording else (255, 60, 60))
        draw.text((10, 554), f"{fps}FPS", fill=(220, 220, 220), font=HUD_FONT_BOLD_SM)

        # Mini RGB Histogram Box (x: 55..98, y: 526..568)
        draw.rectangle([(55, 526), (98, 568)], fill=(18, 18, 18), outline=(50, 50, 50), width=1)
        # Exposure Curves
        draw.line([(57, 566), (65, 555), (75, 540), (85, 548), (96, 566)], fill=(240, 50, 50), width=1)
        draw.line([(57, 566), (67, 548), (77, 535), (87, 552), (96, 566)], fill=(50, 220, 50), width=1)
        draw.line([(57, 566), (63, 560), (73, 542), (83, 538), (96, 566)], fill=(60, 120, 255), width=1)

        # 3 Calibration Dots (x: 108)
        draw.ellipse([(108, 529), (114, 535)], fill=(0, 220, 80)) # Temp
        draw.ellipse([(108, 541), (114, 547)], fill=(0, 220, 80)) # Black Shading T/E
        draw.ellipse([(108, 553), (114, 559)], fill=(0, 220, 80)) # Fan/Electronics

        # Status text (x: 122)
        thermal = getattr(self.camera, "thermal", None)
        temp_str = thermal.get_status_str() if thermal else "39°/63°"
        cal_ok = thermal.is_calibrated_temperature() if thermal else True
        cal_fill = (0, 230, 90) if cal_ok else (240, 200, 20)

        draw.text((122, 526), temp_str, fill=(220, 220, 220), font=HUD_FONT_BOLD_SM)
        draw.text((122, 540), "Cal: ", fill=(180, 180, 180), font=HUD_FONT_BOLD_SM)
        draw.text((148, 540), "T/E", fill=cal_fill, font=HUD_FONT_BOLD_SM)
        draw.text((122, 554), "Drop: 0", fill=(180, 180, 180), font=HUD_FONT_BOLD_SM)

        # Badges cluster (x: 195..340)
        draw.text((195, 526), "HDRx", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)
        draw.text((195, 540), "OFF", fill=(160, 160, 160), font=HUD_FONT_BOLD_SM)
        draw.text((195, 554), "1:1", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)
        draw.text((215, 554), "ON" if self.redui.is_magnify_on else "OFF", fill=(0, 230, 90) if self.redui.is_magnify_on else (160, 160, 160), font=HUD_FONT_BOLD_SM)

        draw.text((250, 526), "TC", fill=(0, 230, 90), font=HUD_FONT_BOLD_SM)
        draw.text((275, 526), "GEN", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)
        draw.text((305, 526), "RIG", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)
        draw.text((250, 544), "SYNC", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)
        draw.text((285, 544), "WIFI", fill=(120, 120, 120), font=HUD_FONT_BOLD_SM)

        # Media Status (x: 355..470)
        rec = getattr(self.camera, "recorder", None)
        rem_pct = rec.media_remaining_percent if rec else 100
        media_active = (self.redui.active_dialog == "MEDIA")
        draw.rectangle([(355, 524), (470, 570)], fill=(20, 20, 20), outline=(220, 20, 20) if media_active else (45, 45, 45))
        draw.text((365, 528), "S-SSD", fill=(180, 180, 180), font=HUD_FONT_BOLD_SM)
        draw.text((365, 540), f"{rem_pct}%", fill=(0, 230, 90) if rem_pct > 15 else (240, 50, 50), font=HUD_FONT_MED)
        draw.rectangle([(425, 532), (462, 548)], fill=(40, 40, 40), outline=(70, 70, 70))
        draw.text((430, 535), "R3D", fill=(255, 255, 255), font=HUD_FONT_BOLD_SM)

        # Power Status (x: 480..575)
        pmic = getattr(self.camera, "pmic", None)
        pwr_source = "DC" if (pmic and pmic.is_dc_in_connected) else "BAT"
        pwr_volts = pmic.get_battery_voltage() if pmic else 14.8
        v_fill = (80, 240, 80) if pwr_volts >= 12.0 else (240, 50, 50)
        draw.rectangle([(480, 524), (575, 570)], fill=(20, 20, 20), outline=(45, 45, 45))
        draw.text((490, 528), pwr_source, fill=(180, 180, 180), font=HUD_FONT_BOLD_SM)
        draw.text((490, 542), f"{pwr_volts:.1f}V", fill=v_fill, font=HUD_FONT_MED)

        # 4-Channel Audio Peak Meters (x: 585..770)
        audio_active = (self.redui.active_dialog == "AUDIO")
        draw.rectangle([(585, 524), (770, 570)], fill=(18, 18, 18), outline=(220, 20, 20) if audio_active else (45, 45, 45))
        # Ch 1
        draw.text((592, 527), "Ch1", fill=(0, 220, 80), font=HUD_FONT_BOLD_SM)
        draw.rectangle([(620, 529), (755, 535)], outline=(50, 50, 50))
        draw.rectangle([(621, 530), (715, 534)], fill=(0, 220, 80)) # -18 dBFS level
        # Ch 2
        draw.text((592, 538), "Ch2", fill=(0, 220, 80), font=HUD_FONT_BOLD_SM)
        draw.rectangle([(620, 540), (755, 546)], outline=(50, 50, 50))
        draw.rectangle([(621, 541), (710, 545)], fill=(0, 220, 80))
        # Ch 3 & 4
        draw.text((592, 549), "Ch3", fill=(100, 100, 100), font=HUD_FONT_BOLD_SM)
        draw.rectangle([(620, 551), (755, 557)], outline=(40, 40, 40))
        draw.text((592, 559), "Ch4", fill=(100, 100, 100), font=HUD_FONT_BOLD_SM)
        draw.rectangle([(620, 561), (755, 567)], outline=(40, 40, 40))

        # Virtual CPU Instructions (x: 870..1014)
        instr_m = self.camera.instruction_count / 1_000_000
        draw.rectangle([(870, 544), (1014, 572)], fill=(22, 22, 22), outline=(50, 50, 50), width=1)
        draw.text((880, 550), f"INSTR: {instr_m:.1f}M", fill=(140, 140, 140), font=HUD_FONT_BOLD_SM)


class WebStudio:
    """Manages virtual camera execution, HTTP server, and client dispatch."""

    def __init__(self, workspace_root: str, host: str = "127.0.0.1", port: int = 8765, camera: Optional[Dsmc2Camera] = None):
        self.workspace_root = os.path.abspath(workspace_root)
        self.host = host
        self.port = port
        self.camera = camera if camera is not None else Dsmc2Camera(self.workspace_root)
        self.compositor = ScreenCompositor(self.camera)
        self.camera.compositor = self.compositor

        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.http_server: Optional[ThreadedHTTPServer] = None

        # Lock for thread-safe camera dispatch
        self.lock = threading.Lock()

        # Firmware Staging & Baseline Configuration
        self.confirmed_baseline_name = "SCARLET-W 5K (v7.4.1)"
        self.confirmed_baseline_file = "dsmc_program.mem"
        self.active_firmware_name = "SCARLET-W 5K (v7.4.1)"
        self.active_firmware_file = "dsmc_program.mem"
        self.active_firmware_size = 18972672
        self.active_firmware_is_custom = False
        self.custom_firmware_path: Optional[str] = None

    def start_camera(self):
        """Boot camera and launch CPU stepping thread."""
        if not self.camera.is_booted:
            self.camera.power_on()
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="Dsmc2CpuWorker")
        self.worker_thread.start()

    def _worker_loop(self):
        """Continuously steps CPU instructions when powered on."""
        while self.running:
            if self.camera.power_state == self.camera.POWER_ON and self.camera.is_booted:
                with self.lock:
                    self.camera.step_slice(25_000)
            time.sleep(0.015)

    def handle_touch(self, x: int, y: int, pressed: bool, action: str = "down"):
        with self.lock:
            if self.camera.power_state == self.camera.POWER_STANDBY:
                if action == "down":
                    self.camera.log_system("[PWR] Touch event received in standby -> Resuming RED DSMC2...")
                    self.camera.power_on()
                return

            self.camera.touch(x, y, pressed=pressed)
            self.compositor.redui.handle_touch(x, y, pressed=pressed, action=action)
            if action == "down":
                self.camera.log_system(f"[TOUCH] Touch down at ({x}, {y}) -> maXTouch (0x4B)")
            elif action == "up":
                self.camera.log_system(f"[TOUCH] Touch release at ({x}, {y}) -> maXTouch (0x4B)")

    def handle_button(self, btn_name: str):
        with self.lock:
            if self.camera.power_state == self.camera.POWER_STANDBY:
                if btn_name in ("MENU", "REC", "1:1 MAG", "USER 1", "USER 2"):
                    self.camera.log_system(f"[PWR] Physical [{btn_name}] pressed in standby -> Resuming RED DSMC2...")
                    self.camera.power_on()
                return

            pin_map = {
                "MENU": 10, "1:1 MAG": 11, "USER 1": 14, "USER 2": 15,
                "NAV UP": 20, "NAV LEFT": 21, "NAV ENTER": 22, "NAV RIGHT": 23, "NAV DOWN": 24
            }
            pin = pin_map.get(btn_name)
            if pin is not None:
                self.camera.log_system(f"[KEY] Physical button [{btn_name}] pressed (GPIO pin {pin})")
                if 1 in self.camera.gpio:
                    self.camera.gpio[1].set_input_pin(pin, True)
                    self.camera.gpio[1].set_input_pin(pin, False)

            self.compositor.redui.handle_button_press(btn_name)

    def handle_record(self):
        with self.lock:
            self.camera.press_record()
            is_rec = (self.camera.rcp.state.get(RcpProtocol.PARAM_RECORD_STATE) == "2")
            if is_rec:
                self.camera.log_system("[REC] Recording STARTED -> RED MINI-MAG (R3D 5K 24fps)")
            else:
                self.camera.log_system("[REC] Recording STOPPED -> File saved safely")

    def handle_power(self):
        with self.lock:
            self.camera.toggle_power()

    def get_hdmi_jpeg_bytes(self, quality: int = 85, mode: Optional[str] = None) -> bytes:
        return self.compositor.get_hdmi_jpeg_bytes(quality=quality, mode=mode)

    def stop(self):
        self.running = False
        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass
        self.camera.stop()


def create_handler(studio: WebStudio):
    """Factory creating HTTP request handler bound to the studio instance."""

    class StudioHttpHandler(BaseHTTPRequestHandler):

        def log_message(self, format, *args):
            # Suppress normal HTTP logging to keep terminal output clean for camera logs
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/" or path == "/index.html":
                self._serve_studio_html()
            elif path == "/api/frame":
                self._serve_single_frame()
            elif path == "/api/stream":
                self._serve_mjpeg_stream()
            elif path == "/api/status":
                self._serve_status_json()
            elif path == "/api/logs":
                self._serve_logs_json(parsed.query)
            elif path == "/api/lens":
                with studio.lock:
                    lm = studio.camera.lens_mount
                    catalog = [l.to_dict() for l in lm.lens_database]
                    self._send_json({"status": lm.get_status(), "catalog": catalog})
            elif path == "/api/media/clips":
                with studio.lock:
                    clips = studio.camera.recorder.list_clips()
                    self._send_json({"clips": clips})
            elif path == "/api/firmware/status":
                with studio.lock:
                    info = {
                        "status": "ok",
                        "active_name": studio.active_firmware_name,
                        "active_file": studio.active_firmware_file,
                        "active_size": studio.active_firmware_size,
                        "is_custom": studio.active_firmware_is_custom,
                        "baseline_name": studio.confirmed_baseline_name,
                        "slot_mounted": studio.camera.recorder.is_media_mounted if hasattr(studio.camera, "recorder") else True
                    }
                self._send_json(info)
            elif path == "/api/camera/models":
                with studio.lock:
                    models = studio.camera.env.list_profiles()
                    current = studio.camera.env.get("CAMERA_TYPE", "0x16")
                    self._send_json({"status": "ok", "current": current, "models": models})
            elif path == "/api/video/hdmi":
                with studio.lock:
                    q = urllib.parse.parse_qs(parsed.query)
                    mode = q.get("mode", [None])[0]
                    jpeg_bytes = studio.get_hdmi_jpeg_bytes(mode=mode)
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg_bytes)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.end_headers()
                self.wfile.write(jpeg_bytes)
            elif path == "/api/video/hdmi/mode":
                with studio.lock:
                    mode = studio.camera.iob0.hdmi_mode if hasattr(studio.camera, "iob0") and studio.camera.iob0 else "CLEAN"
                self._send_json({"status": "ok", "mode": mode})
            elif path == "/api/audio/wav":
                with studio.lock:
                    dur = 0.5
                    wav_bytes = studio.camera.get_audio_wav(dur)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_bytes)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(wav_bytes)
            elif path == "/api/audio/status":
                with studio.lock:
                    stat = studio.camera.audio_server.get_status() if hasattr(studio.camera, "audio_server") and studio.camera.audio_server else {}
                self._send_json({"status": "ok", "audio": stat})
            elif path == "/api/rcp/automation/presets":
                with studio.lock:
                    presets = studio.camera.rcp_script_engine.PRESETS
                self._send_json({"status": "ok", "presets": presets})
            elif path == "/api/rcp/multicam/status":
                with studio.lock:
                    stat = studio.camera.multicam_network.get_status()
                self._send_json(stat)

            elif path == "/api/rig/status":
                with studio.lock:
                    rig_stat = studio.camera.rig.get_status() if hasattr(studio.camera, "rig") and studio.camera.rig else {}
                self._send_json(rig_stat)
            else:
                self.send_error(404, "Not Found")

        def do_POST(self):
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("application/json"):
                self.send_error(415, "Unsupported Media Type: application/json required")
                return

            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(length) if length > 0 else b"{}"

            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                data = {}

            if path == "/api/touch":
                x = int(data.get("x", 0))
                y = int(data.get("y", 0))
                pressed = bool(data.get("pressed", True))
                action = str(data.get("action", "down" if pressed else "up"))
                studio.handle_touch(x, y, pressed, action=action)
                self._send_json({"status": "ok", "x": x, "y": y, "pressed": pressed, "action": action})

            elif path == "/api/camera/select":
                model_id = str(data.get("model", "0x16"))
                with studio.lock:
                    success = studio.camera.select_camera_model(model_id)
                    current_name = studio.camera.env.get("CAMERA_NAME", "SCARLET-W 5K")
                    studio.active_firmware_name = f"{current_name} (v7.4.1)"
                    studio.confirmed_baseline_name = f"{current_name} (v7.4.1)"
                self._send_json({"status": "ok" if success else "error", "model": model_id, "camera_name": current_name})

            elif path == "/api/button":
                btn = str(data.get("button", ""))
                if btn == "REC":
                    studio.handle_record()
                elif btn == "POWER":
                    studio.handle_power()
                else:
                    studio.handle_button(btn)
                self._send_json({"status": "ok", "button": btn})

            elif path == "/api/rcp":
                cmd = str(data.get("command", "")).strip()
                if cmd:
                    with studio.lock:
                        resp = studio.camera.rcp.process_command(cmd)
                else:
                    resp = "ERROR"
                self._send_json({"status": "ok", "command": cmd, "response": resp})

            elif path == "/api/power":
                studio.handle_power()
                self._send_json({"status": "ok", "power_state": studio.camera.power_state})

            elif path == "/api/snapshot/save":
                name = str(data.get("name", f"snapshot_{int(time.time())}.dsmc2"))
                if not re.match(r"^[A-Za-z0-9_.-]+$", name):
                    self._send_json({"status": "error", "message": "Invalid snapshot filename"}, status=400)
                    return
                snap_dir = os.path.join(studio.workspace_root, "snapshots")
                os.makedirs(snap_dir, exist_ok=True)
                snap_path = os.path.join(snap_dir, name)
                real_snap = os.path.realpath(snap_path)
                real_snap_dir = os.path.realpath(snap_dir)
                if not (real_snap == real_snap_dir or real_snap.startswith(real_snap_dir + os.sep)):
                    self._send_json({"status": "error", "message": "Path traversal detected"}, status=400)
                    return
                with studio.lock:
                    from emulator.core.snapshot import SnapshotManager
                    SnapshotManager.save(studio.camera, snap_path, description=f"Web snapshot {name}")
                self._send_json({"status": "ok", "file": snap_path})

            elif path == "/api/snapshot/restore":
                file_name = str(data.get("name", ""))
                if not re.match(r"^[A-Za-z0-9_.-]+$", file_name):
                    self._send_json({"status": "error", "message": "Invalid snapshot filename"}, status=400)
                    return
                snap_dir = os.path.join(studio.workspace_root, "snapshots")
                snap_path = os.path.join(snap_dir, file_name)
                real_snap = os.path.realpath(snap_path)
                real_snap_dir = os.path.realpath(snap_dir)
                if not (real_snap == real_snap_dir or real_snap.startswith(real_snap_dir + os.sep)):
                    self._send_json({"status": "error", "message": "Path traversal detected"}, status=400)
                    return
                success = False
                if os.path.exists(snap_path):
                    with studio.lock:
                        from emulator.core.snapshot import SnapshotManager
                        success = SnapshotManager.restore(studio.camera, snap_path)
                self._send_json({"status": "ok" if success else "error", "restored": success})

            elif path == "/api/fault":
                fault_type = str(data.get("type", "INTC_IRQ_LOCKUP"))
                with studio.lock:
                    from emulator.core.faults import HardwareFaultInjector
                    inj = HardwareFaultInjector(studio.camera)
                    res = inj.inject_fault(fault_type)
                self._send_json({"status": "ok", "result": res})

            elif path == "/api/lens/attach":
                name = str(data.get("name", ""))
                idx = data.get("index")
                with studio.lock:
                    lm = studio.camera.lens_mount
                    target = None
                    if idx is not None and 0 <= int(idx) < len(lm.lens_database):
                        target = lm.lens_database[int(idx)]
                    elif name:
                        target = next((l for l in lm.lens_database if l.model.lower() == name.lower()), None)
                    if target:
                        lm.attach_lens(target)
                self._send_json({"status": "ok", "attached": target.model if target else None})

            elif path == "/api/lens/mount":
                mount_name = str(data.get("mount", "Canon EF"))
                with studio.lock:
                    studio.camera.lens_mount.set_mount_type(mount_name)
                self._send_json({"status": "ok", "mount": mount_name})

            elif path == "/api/lens/aperture":
                val = data.get("aperture")
                step = data.get("step")
                with studio.lock:
                    lm = studio.camera.lens_mount
                    if step is not None:
                        lm.step_aperture(int(step))
                    elif val is not None:
                        lm.set_aperture(float(val))
                self._send_json({"status": "ok", "aperture": studio.camera.lens_mount.current_aperture})

            elif path == "/api/lens/focal":
                f_mm = float(data.get("focal_length", 50.0))
                with studio.lock:
                    studio.camera.lens_mount.set_focal_length(f_mm)
                self._send_json({"status": "ok", "focal_length": studio.camera.lens_mount.current_focal_length})

            elif path == "/api/lens/focus":
                dist = float(data.get("distance", 2.5))
                with studio.lock:
                    studio.camera.lens_mount.set_focus_distance(dist)
                self._send_json({"status": "ok", "focus_distance": studio.camera.lens_mount.current_focus_distance})

            elif path == "/api/lens/af":
                with studio.lock:
                    res = studio.camera.lens_mount.trigger_autofocus()
                self._send_json({"status": "ok", "result": res, "distance": studio.camera.lens_mount.current_focus_distance})

            elif path == "/api/hardware/thermal":
                sensor_c = float(data.get("sensor_c", 39.0))
                brain_c = float(data.get("brain_c", 63.0))
                with studio.lock:
                    studio.camera.set_sensor_temperature(sensor_c, brain_c)
                    studio.camera.log_system(f"[THERMAL] Sensor temp set to {sensor_c:.1f}°C, BRAIN temp to {brain_c:.1f}°C")
                self._send_json({"status": "ok", "sensor_c": sensor_c, "brain_c": brain_c})

            elif path == "/api/hardware/power":
                volts = float(data.get("voltage", 14.8))
                dc_in = bool(data.get("dc_in", True)) if "dc_in" in data else None
                with studio.lock:
                    studio.camera.set_battery_voltage(volts)
                    if dc_in is not None and hasattr(studio.camera, "pmic") and studio.camera.pmic:
                        studio.camera.pmic.set_dc_in(dc_in)
                    dc_stat = studio.camera.pmic.is_dc_in_connected if hasattr(studio.camera, "pmic") and studio.camera.pmic else True
                    studio.camera.log_system(f"[PMIC] Supply updated: {volts:.1f}V (DC-IN: {dc_stat})")
                self._send_json({"status": "ok", "voltage": volts, "dc_in": dc_stat})

            elif path == "/api/hardware/olpf":
                olpf_type = str(data.get("type", "Standard"))
                with studio.lock:
                    success = studio.camera.set_olpf_type(olpf_type)
                    info = studio.camera.olpf.get_info() if hasattr(studio.camera, "olpf") and studio.camera.olpf else None
                    studio.camera.log_system(f"[OLPF] Swapped OLPF filter module to {olpf_type}")
                self._send_json({"status": "ok" if success else "error", "olpf": info})

            elif path == "/api/hardware/calibrate":
                with studio.lock:
                    res = studio.camera.run_black_shading()
                self._send_json(res)

            elif path == "/api/hardware/accessory/attach":
                pin = str(data.get("pin", "720-0033"))
                serial = int(data.get("serial", 100001))
                slot = data.get("slot")
                with studio.lock:
                    res = studio.camera.attach_accessory(pin, serial, slot=slot)
                    if res:
                        res = {k: v for k, v in res.items() if not k.endswith("_obj")}
                self._send_json({"status": "ok" if res else "error", "module": res})

            elif path == "/api/hardware/accessory/detach":
                pin = str(data.get("pin", ""))
                slot = data.get("slot")
                with studio.lock:
                    res = studio.camera.detach_accessory(pin, slot=slot)
                self._send_json({"status": "ok", "detached": res})

            elif path == "/api/rig/toggle":
                from_slot = str(data.get("from_slot", ""))
                to_slot = str(data.get("to_slot", ""))
                with studio.lock:
                    res = studio.camera.toggle_module_position(from_slot, to_slot)
                self._send_json({"status": "ok" if res else "error", "toggled": res})

            elif path == "/api/rig/orientation":
                slot = str(data.get("slot", ""))
                orientation = str(data.get("orientation", "normal"))
                with studio.lock:
                    res = studio.camera.set_slot_orientation(slot, orientation)
                self._send_json({"status": "ok" if res else "error", "updated": res})

            elif path == "/api/rig/preset":
                preset_name = str(data.get("preset", "cinema_production"))
                with studio.lock:
                    res = studio.camera.rig.apply_preset(preset_name) if hasattr(studio.camera, "rig") and studio.camera.rig else False
                self._send_json({"status": "ok" if res else "error", "applied": res})

            elif path == "/api/hardware/face_detect":
                with studio.lock:
                    faces = studio.camera.detect_faces()
                self._send_json({"status": "ok", "faces": faces})

            elif path == "/api/media/format":
                with studio.lock:
                    res = studio.camera.recorder.format_media()
                self._send_json({"status": "ok", "formatted": res})

            elif path == "/api/media/eject":
                with studio.lock:
                    res = studio.camera.recorder.eject_media()
                self._send_json({"status": "ok", "ejected": res})

            elif path == "/api/media/mount":
                with studio.lock:
                    res = studio.camera.recorder.mount_media()
                self._send_json({"status": "ok", "mounted": res})

            elif path == "/api/firmware/upload":
                import base64
                from emulator.core.firmware import FirmwareManager
                filename = str(data.get("filename", "custom_firmware.bin"))
                filename = os.path.basename(filename)
                b64_data = data.get("data", "")
                if "," in b64_data:
                    b64_data = b64_data.split(",", 1)[1]
                file_bytes = base64.b64decode(b64_data)

                custom_dir = os.path.join(studio.workspace_root, "firmware_store", "custom")
                os.makedirs(custom_dir, exist_ok=True)
                dest_path = os.path.join(custom_dir, filename)
                with open(dest_path, "wb") as f:
                    f.write(file_bytes)

                meta = FirmwareManager.inspect(dest_path, filename=filename)

                with studio.lock:
                    studio.active_firmware_name = f"Custom: {filename}"
                    studio.active_firmware_file = filename
                    studio.active_firmware_size = len(file_bytes)
                    studio.active_firmware_is_custom = True
                    studio.custom_firmware_path = dest_path
                    studio.camera.staged_firmware_path = dest_path
                    studio.camera.log_system(f"[MEDIA-BAY] RED MINI-MAG: Custom firmware image staged: {filename} ({meta.size_mb:.2f} MB)")
                    studio.camera.log_system(f"[FIRMWARE-LOADER] Format: {meta.format_name} | SP: 0x{meta.sp:08X} | Reset PC: 0x{meta.reset_pc:08X}")
                    studio.camera.log_system("[FIRMWARE-LOADER] Ready for flash & execution into DDR RAM (0x80000000).")

                self._send_json({
                    "status": "ok",
                    "active_name": studio.active_firmware_name,
                    "filename": filename,
                    "size": len(file_bytes),
                    "metadata": meta.to_dict()
                })

            elif path == "/api/firmware/boot":
                if not studio.custom_firmware_path or not os.path.exists(studio.custom_firmware_path):
                    self._send_json({"status": "error", "message": "No custom firmware staged in RED MINI-MAG slot"}, status=400)
                    return

                with studio.lock:
                    res = studio.camera.load_and_boot_custom_firmware(studio.custom_firmware_path)
                    if res.get("status") == "ok":
                        studio.active_firmware_name = f"Custom: {os.path.basename(studio.custom_firmware_path)} (Running)"
                        studio.active_firmware_is_custom = True
                    else:
                        studio.active_firmware_name = f"Custom: {os.path.basename(studio.custom_firmware_path)} (Crashed)"
                self._send_json(res)

            elif path == "/api/firmware/reset":
                with studio.lock:
                    current_model = studio.camera.env.get("CAMERA_TYPE", "0x16")
                    studio.camera.select_camera_model(current_model)
                    current_name = studio.camera.env.get("CAMERA_NAME", "SCARLET-W 5K")
                    studio.active_firmware_name = f"{current_name} (v7.4.1)"
                    studio.active_firmware_file = "dsmc_program.mem"
                    studio.active_firmware_size = 21614152
                    studio.active_firmware_is_custom = False
                    studio.custom_firmware_path = None
                    studio.camera.staged_firmware_path = None
                    studio.camera.log_system(f"[MEDIA-BAY] RED MINI-MAG slot reset to confirmed working baseline: {studio.active_firmware_name}")
                self._send_json({
                    "status": "ok",
                    "active_name": studio.active_firmware_name,
                    "baseline_name": studio.confirmed_baseline_name
                })

            elif path == "/api/video/hdmi/mode":
                mode = str(data.get("mode", "CLEAN"))
                with studio.lock:
                    studio.camera.set_hdmi_mode(mode)
                    curr = studio.camera.iob0.hdmi_mode if hasattr(studio.camera, "iob0") and studio.camera.iob0 else mode
                self._send_json({"status": "ok", "mode": curr})

            elif path == "/api/audio/control":
                with studio.lock:
                    srv = studio.camera.audio_server if hasattr(studio.camera, "audio_server") else None
                    if srv:
                        if "preamp_ch" in data and "gain_db" in data:
                            srv.set_preamp_gain(int(data["preamp_ch"]) - 1, float(data["gain_db"]))
                        if "headphone_vol" in data:
                            srv.headphone_volume_pct = max(0, min(100, int(data["headphone_vol"])))
                        if "test_tone" in data:
                            srv.set_test_tone(bool(data["test_tone"]), float(data.get("freq_hz", 1000.0)))
                        stat = srv.get_status()
                    else:
                        stat = {}
                self._send_json({"status": "ok", "audio": stat})

            elif path == "/api/rcp/automation/run":
                script_data = data.get("script") or data.get("preset") or "RACK_FOCUS"
                script_name = str(data.get("name", "Web Studio Script"))
                with studio.lock:
                    res = studio.camera.execute_rcp_script(script_data, script_name=script_name)
                self._send_json(res)

            elif path == "/api/rcp/multicam/sync":
                tc = str(data.get("timecode", "01:00:00:00"))
                with studio.lock:
                    res = studio.camera.multicam_network.sync_genlock(timecode=tc)
                self._send_json({"status": "ok", "sync": res})

            elif path == "/api/rcp/multicam/broadcast":
                param = str(data.get("param", "iso"))
                val = str(data.get("value", "800"))
                with studio.lock:
                    res = studio.camera.multicam_network.broadcast_parameter(param, val)
                self._send_json({"status": "ok", "broadcast": res})

            elif path == "/api/rcp/multicam/record":
                action = str(data.get("action", "START"))
                with studio.lock:
                    res = studio.camera.multicam_network.synchronized_record_trigger(action)
                self._send_json({"status": "ok", "record": res})

            else:
                self.send_error(404, "Unknown API Route")

        def _send_json(self, payload: dict, status: int = 200):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_single_frame(self):
            with studio.lock:
                jpeg_data = studio.compositor.get_jpeg_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(jpeg_data)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(jpeg_data)

        def _serve_mjpeg_stream(self):
            """Stream multipart MJPEG video directly to browser at ~25 FPS."""
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--frame")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()

            try:
                while studio.running:
                    with studio.lock:
                        frame_bytes = studio.compositor.get_jpeg_bytes(quality=80)
                    self.wfile.write(b"----frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame_bytes)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame_bytes)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.04) # ~25 FPS
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass

        def _serve_status_json(self):
            with studio.lock:
                cam = studio.camera
                is_rec = (cam.rcp.state.get(RcpProtocol.PARAM_RECORD_STATE) == "2")
                lm_status = cam.lens_mount.get_status() if hasattr(cam, "lens_mount") else None
                rec_status = {
                    "is_recording": cam.recorder.is_recording,
                    "is_mounted": cam.recorder.is_media_mounted,
                    "reel_id": cam.recorder.current_reel_id,
                    "clip_number": cam.recorder.clip_number,
                    "capacity_gb": cam.recorder.MEDIA_CAPACITY_GB,
                    "used_mb": round(cam.recorder.used_space_mb, 1),
                    "free_mb": round(cam.recorder.free_space_mb, 1),
                    "remaining_percent": cam.recorder.media_remaining_percent,
                    "current_clip": cam.recorder.current_clip_name,
                    "clips_count": len(cam.recorder.list_clips())
                } if hasattr(cam, "recorder") else None

                status = {
                    "power_state": cam.power_state,
                    "boot_progress": cam.boot_progress,
                    "instruction_count": cam.instruction_count,
                    "camera_name": cam.env.get("CAMERA_NAME", "SCARLET-W 5K"),
                    "camera_type": cam.env.get("CAMERA_TYPE", "0x16"),
                    "is_recording": is_rec,
                    "rcp_clients_count": cam.rcp_server.get_client_count() if hasattr(cam, "rcp_server") else 0,
                    "lens": lm_status,
                    "media": rec_status,
                    "active_dialog": studio.compositor.redui.active_dialog,
                    "is_menu_open": studio.compositor.redui.is_menu_open,
                    "tools": {
                        "magnify": studio.compositor.redui.is_magnify_on,
                        "false_color": studio.compositor.redui.is_false_color_on,
                        "zebras": studio.compositor.redui.is_zebras_on,
                        "guide": studio.compositor.redui.guide_mode
                    },
                    "rcp": dict(cam.rcp.state),
                    "firmware": {
                        "active_name": studio.active_firmware_name,
                        "active_file": studio.active_firmware_file,
                        "active_size": studio.active_firmware_size,
                        "is_custom": studio.active_firmware_is_custom,
                        "baseline_name": studio.confirmed_baseline_name
                    },
                    "hardware": {
                        "pmic": cam.pmic.get_status() if hasattr(cam, "pmic") and cam.pmic else None,
                        "thermal": {
                            "sensor_c": cam.thermal.sensor_temp_c,
                            "brain_c": cam.thermal.brain_temp_c,
                            "is_calibrated": cam.thermal.is_calibrated_temperature(),
                            "status_str": cam.thermal.get_status_str()
                        } if hasattr(cam, "thermal") and cam.thermal else None,
                        "olpf": cam.olpf.get_info() if hasattr(cam, "olpf") and cam.olpf else None,
                        "gpmc": {
                            "sysstatus": cam.gpmc.sysstatus,
                            "cs0_nand_valid": bool(cam.gpmc.cs_configs.get(0x78, 0) & 0x40)
                        } if hasattr(cam, "gpmc") and cam.gpmc else None,
                    },
                    "coprocessors": {
                        "c2c": cam.c2c.get_status() if hasattr(cam, "c2c") and cam.c2c else None,
                        "iob0": cam.iob0.get_status() if hasattr(cam, "iob0") and cam.iob0 else None,
                        "iob1": cam.iob1.get_status() if hasattr(cam, "iob1") and cam.iob1 else None,
                        "isp1": cam.isp1.get_status() if hasattr(cam, "isp1") and cam.isp1 else None,
                        "isp2": cam.isp2.get_status() if hasattr(cam, "isp2") and cam.isp2 else None,
                        "dsp": cam.dsp.get_status() if hasattr(cam, "dsp") and cam.dsp else None,
                        "imaging_server": cam.imaging_server.get_status() if hasattr(cam, "imaging_server") and cam.imaging_server else None,
                        "audio_server": cam.audio_server.get_status() if hasattr(cam, "audio_server") and cam.audio_server else None,
                    },
                    "accessories": cam.accessory_bus.get_status() if hasattr(cam, "accessory_bus") and cam.accessory_bus else None,
                    "rig": cam.rig.get_status() if hasattr(cam, "rig") and cam.rig else None,
                    "multicam": cam.multicam_network.get_status() if hasattr(cam, "multicam_network") and cam.multicam_network else None,
                    "threads": cam.get_threads(),
                    "unknown_mmio_count": len(cam.bus.unknown_mmio)
                }
            self._send_json(status)

        def _serve_logs_json(self, query_str: str):
            since = 0
            if query_str:
                params = urllib.parse.parse_qs(query_str)
                since = int(params.get("since", [0])[0])

            with studio.lock:
                all_logs = studio.camera.get_serial_logs()
                new_logs = all_logs[since:]

            self._send_json({"logs": new_logs, "total": len(all_logs)})

        def _serve_studio_html(self):
            html = STUDIO_HTML.replace("{{HOST}}", studio.host).replace("{{PORT}}", str(studio.port))
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return StudioHttpHandler


# ---------------------------------------------------------------------------
# Authentic DSMC2 Virtual Brain Web Studio Frontend
# Single-page application with zero external dependencies (pure HTML5/CSS3/JS)
# ---------------------------------------------------------------------------
STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DSMC2 Virtual Brain — Scarlet-W 5K</title>
<style>
  :root {
    --bg-main: #121212;
    --bg-panel: #1b1b1b;
    --bg-card: #222222;
    --border: #333333;
    --red-brand: #d11212;
    --red-bright: #ff2222;
    --green-led: #00e676;
    --amber-led: #ffb300;
    --text-primary: #f0f0f0;
    --text-muted: #888888;
    --accent: #007acc;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
  body {
    background: var(--bg-main);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
  }

  /* Header */
  header {
    background: #0a0a0a;
    border-bottom: 1px solid var(--border);
    padding: 10px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .red-logo {
    background: var(--red-brand);
    color: #fff;
    font-weight: 900;
    letter-spacing: 2px;
    padding: 3px 10px;
    border-radius: 2px;
    font-size: 14px;
  }
  .brand-title {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    color: #ddd;
  }
  .brand-sub {
    font-size: 11px;
    color: var(--text-muted);
    font-family: monospace;
  }
  .status-cluster {
    display: flex;
    align-items: center;
    gap: 16px;
    font-family: monospace;
    font-size: 12px;
  }
  .led-badge {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 4px;
    background: #181818;
    border: 1px solid #333;
  }
  .led-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--amber-led);
    box-shadow: 0 0 6px var(--amber-led);
  }
  .led-dot.online { background: var(--green-led); box-shadow: 0 0 8px var(--green-led); }
  .led-dot.recording { background: var(--red-bright); box-shadow: 0 0 10px var(--red-bright); animation: pulse 1s infinite; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

  /* Main Studio Layout */
  .studio-grid {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
    padding: 14px 20px 40px 20px;
    flex: 1;
    max-width: 1350px;
    margin: 0 auto;
    width: 100%;
    box-sizing: border-box;
  }

  /* Camera Unit Column */
  .camera-unit {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    width: 100%;
  }

  /* Authentic RED Touch 7.0 Aluminum Bezel */
  .monitor-bezel {
    background: linear-gradient(145deg, #242424, #151515);
    border: 3px solid #383838;
    border-radius: 12px;
    padding: 12px 16px 14px 16px;
    box-shadow: 0 16px 40px rgba(0,0,0,0.85), inset 0 1px 0 rgba(255,255,255,0.1);
    position: relative;
    width: 100%;
    box-sizing: border-box;
  }
  .bezel-screws {
    display: flex;
    justify-content: space-between;
    margin-bottom: 6px;
    padding: 0 4px;
  }
  .screw {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: #2a2a2a;
    border: 1px solid #444;
    box-shadow: inset 0 1px 1px #000;
  }
  .bezel-header {
    display: flex;
    justify-content: space-between;
    font-family: monospace;
    font-size: 11px;
    color: #888;
    margin-bottom: 6px;
    letter-spacing: 1px;
  }

  /* Screen & MINI-MAG Flex Container */
  .screen-and-mag-container {
    display: flex;
    flex-direction: row;
    gap: 14px;
    width: 100%;
    align-items: stretch;
    justify-content: center;
  }

  /* RED MINI-MAG Vertical Slot Bay */
  .minimag-slot-bay {
    width: 175px;
    min-width: 175px;
    flex-shrink: 0;
    background: linear-gradient(180deg, #1c1c1c 0%, #121212 100%);
    border: 2px solid #333333;
    border-radius: 6px;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.8), 0 4px 10px rgba(0,0,0,0.5);
    box-sizing: border-box;
  }
  .mag-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #2a2a2a;
    padding-bottom: 6px;
  }
  .mag-brand {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .mag-logo-red {
    background: var(--red-brand);
    color: #fff;
    font-weight: 900;
    font-size: 10px;
    padding: 1px 4px;
    border-radius: 2px;
    letter-spacing: 1px;
  }
  .mag-label {
    font-size: 10px;
    font-weight: 700;
    color: #ddd;
    letter-spacing: 0.5px;
  }
  .mag-slot-tag {
    font-family: monospace;
    font-size: 9px;
    color: #777;
  }

  /* Physical Cartridge Visual */
  .mag-cartridge {
    background: linear-gradient(135deg, #a81010 0%, #680000 100%);
    border: 1px solid #ff3333;
    border-radius: 4px;
    padding: 8px 10px;
    box-shadow: inset 0 1px 2px rgba(255,255,255,0.3), 0 4px 8px rgba(0,0,0,0.6);
    position: relative;
    overflow: hidden;
  }
  .mag-grip {
    position: absolute;
    right: 4px;
    top: 4px;
    bottom: 4px;
    width: 6px;
    background: repeating-linear-gradient(180deg, #440000, #440000 2px, #881111 2px, #881111 4px);
    border-radius: 1px;
  }
  .mag-cartridge-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .mag-cartridge-title {
    font-size: 11px;
    font-weight: 900;
    color: #ffffff;
    letter-spacing: 1px;
  }
  .mag-cartridge-cap {
    font-size: 15px;
    font-weight: 900;
    color: #ffffff;
    font-family: monospace;
  }
  .mag-cartridge-sub {
    font-size: 8.5px;
    color: #ffcccc;
    font-family: monospace;
    letter-spacing: 0.5px;
  }
  .mag-led-row {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 6px;
    padding-top: 4px;
    border-top: 1px solid rgba(255,255,255,0.15);
  }
  .mag-led {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--green-led);
    box-shadow: 0 0 6px var(--green-led);
  }
  .mag-led.custom {
    background: #00b0ff;
    box-shadow: 0 0 8px #00b0ff;
  }
  .mag-led.ejected {
    background: #555;
    box-shadow: none;
  }
  .mag-led-text {
    font-family: monospace;
    font-size: 9.5px;
    font-weight: bold;
    color: #eee;
  }

  /* Firmware Card */
  .mag-fw-card {
    background: #181818;
    border: 1px solid #2e2e2e;
    border-radius: 4px;
    padding: 6px 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .fw-card-label {
    font-size: 9px;
    font-weight: 700;
    color: #777;
    letter-spacing: 0.5px;
  }
  .fw-card-name {
    font-size: 10.5px;
    font-weight: bold;
    color: #00e676;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .fw-card-status {
    font-size: 9.5px;
    color: #aaa;
  }
  .fw-card-details {
    font-family: monospace;
    font-size: 9px;
    color: #666;
  }

  /* Dropzone */
  .mag-dropzone {
    border: 1.5px dashed #444;
    border-radius: 4px;
    padding: 10px 6px;
    text-align: center;
    cursor: pointer;
    background: #141414;
    transition: all 0.15s ease;
  }
  .mag-dropzone:hover, .mag-dropzone.dragover {
    border-color: var(--red-brand);
    background: #1e1414;
  }
  .dropzone-icon {
    font-size: 16px;
    color: #888;
    margin-bottom: 2px;
  }
  .dropzone-text {
    font-size: 10px;
    color: #ccc;
    line-height: 1.3;
  }
  .dropzone-hint {
    font-size: 8.5px;
    color: #777;
    margin-top: 3px;
  }

  /* Controls */
  .mag-controls {
    display: flex;
    gap: 6px;
    margin-top: auto;
  }
  .mag-btn-reset {
    padding: 5px 8px;
    font-size: 10px;
    flex: 1;
    background: #252525;
    border: 1px solid #444;
    color: #aaa;
  }
  .mag-btn-reset:hover {
    color: #fff;
    border-color: #777;
  }

  @media (max-width: 860px) {
    .screen-and-mag-container {
      flex-direction: column;
    }
    .minimag-slot-bay {
      width: 100%;
      min-width: 0;
    }
  }

  /* Screen Frame Stream Canvas */
  .screen-viewport {
    position: relative;
    width: 100%;
    flex: 1;
    min-width: 0;
    aspect-ratio: 16 / 9;
    max-height: 62vh;
    background: #000;
    border-radius: 4px;
    overflow: hidden;
    cursor: crosshair;
    box-shadow: inset 0 0 16px rgba(0,0,0,0.95);
  }
  .screen-viewport img {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    object-fit: fill;
    display: block;
    pointer-events: none;
  }
  /* Overlay canvas for responsive touch feedback */
  .touch-overlay {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: auto;
  }

  /* Physical Button Control Deck */
  .tactile-deck {
    background: #1a1a1a;
    border: 2px solid #2f2f2f;
    border-radius: 8px;
    padding: 12px 18px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 6px 20px rgba(0,0,0,0.5);
    width: 100%;
    box-sizing: border-box;
    justify-content: space-between;
    flex-wrap: wrap;
  }
  .btn-group {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* Authentic Buttons */
  button.cam-btn {
    background: linear-gradient(180deg, #333333, #222222);
    color: #e0e0e0;
    border: 1px solid #444;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    padding: 8px 14px;
    cursor: pointer;
    box-shadow: 0 2px 4px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.1);
    transition: all 0.08s ease;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  button.cam-btn:hover {
    background: linear-gradient(180deg, #3e3e3e, #2a2a2a);
    border-color: #666;
  }
  button.cam-btn:active {
    background: #181818;
    transform: translateY(1px);
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.8);
  }

  /* Primary RED Record Button */
  button.rec-btn {
    background: linear-gradient(180deg, #b01010, #7a0000);
    color: #ffffff;
    border: 2px solid #ff4444;
    border-radius: 50%;
    width: 58px;
    height: 58px;
    font-size: 11px;
    font-weight: 900;
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(180, 0, 0, 0.4), inset 0 2px 2px rgba(255,255,255,0.3);
    transition: all 0.1s;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
  }
  button.rec-btn:hover {
    background: linear-gradient(180deg, #cf1515, #940505);
    transform: scale(1.04);
  }
  button.rec-btn.recording {
    background: #ff1111;
    border-color: #ffffff;
    box-shadow: 0 0 16px rgba(255, 30, 30, 0.9);
    animation: recPulse 1.2s infinite;
  }
  @keyframes recPulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.03); } }

  /* Power Button */
  button.power-btn {
    background: linear-gradient(180deg, #242424, #181818);
    color: #ccc;
    border: 1px solid #444;
    font-family: monospace;
    font-weight: bold;
    transition: all 0.15s ease;
  }
  button.power-btn:hover {
    background: #2e2e2e;
    color: #ff5555;
    border-color: #773333;
  }
  button.power-btn.standby {
    background: linear-gradient(180deg, #16361a, #0e2010);
    color: #00ff77;
    border: 1px solid #00bb55;
    box-shadow: 0 0 10px rgba(0, 255, 119, 0.25);
  }
  button.power-btn.standby:hover {
    background: linear-gradient(180deg, #1f4a24, #142e17);
    color: #ffffff;
    box-shadow: 0 0 14px rgba(0, 255, 119, 0.45);
  }

  /* D-Pad Container */
  .dpad {
    display: grid;
    grid-template-columns: repeat(3, 28px);
    grid-template-rows: repeat(3, 28px);
    gap: 3px;
  }
  .dpad button {
    background: #2a2a2a;
    border: 1px solid #444;
    color: #ccc;
    border-radius: 3px;
    cursor: pointer;
    font-size: 10px;
    font-weight: bold;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  .dpad button:hover { background: #383838; }
  .dpad button:active { background: #111; }

  /* Engineering Workbench: Full Width Below Screen */
  .workbench {
    background: var(--bg-panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    width: 100%;
    min-height: 480px;
    max-height: 650px;
    box-sizing: border-box;
  }
  .tab-bar {
    display: flex;
    background: #141414;
    border-bottom: 1px solid var(--border);
    overflow-x: auto;
  }
  .tab-btn {
    padding: 10px 18px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.15s;
  }
  .tab-btn:hover { color: #fff; }
  .tab-btn.active {
    color: #fff;
    border-bottom: 2px solid var(--red-brand);
    background: #1d1d1d;
  }
  .tab-content {
    flex: 1;
    overflow: auto;
    padding: 14px;
    display: none;
  }
  .tab-content.active { display: flex; flex-direction: column; }

  /* Terminal Console */
  .console-box {
    background: #080808;
    border: 1px solid #2a2a2a;
    border-radius: 4px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11.5px;
    color: #00ff66;
    padding: 12px;
    flex: 1;
    overflow-y: auto;
    white-space: pre-wrap;
    line-height: 1.5;
  }
  .console-tools {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    align-items: center;
    font-size: 12px;
  }

  /* RCP Parameters Grid */
  table.data-table {
    width: 100%;
    border-collapse: collapse;
    font-family: monospace;
    font-size: 12px;
  }
  table.data-table th, table.data-table td {
    padding: 8px 10px;
    border-bottom: 1px solid #2c2c2c;
    text-align: left;
  }
  table.data-table th { background: #181818; color: #888; font-weight: 600; }
  table.data-table tr:hover { background: #222; }

  /* Command Prompt Bar */
  .cmd-bar {
    display: flex;
    gap: 8px;
    margin-top: 10px;
  }
  .cmd-input {
    flex: 1;
    background: #0d0d0d;
    border: 1px solid #444;
    color: #fff;
    padding: 8px 12px;
    border-radius: 4px;
    font-family: monospace;
    font-size: 13px;
  }
  .cmd-input:focus { outline: none; border-color: var(--accent); }

  /* Tip / Hotkeys */
  .hotkey-badge {
    background: #252525;
    border: 1px solid #444;
    padding: 2px 5px;
    border-radius: 3px;
    font-size: 10px;
    color: #aaa;
    font-family: monospace;
  }

  /* Camera Model Modal */
  .modal-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.88);
    backdrop-filter: blur(6px);
    z-index: 10000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .modal-box {
    background: #181818;
    border: 2px solid #383838;
    border-radius: 10px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.9), inset 0 1px 0 rgba(255,255,255,0.1);
    max-width: 920px;
    width: 100%;
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }
  .modal-top {
    background: #111;
    border-bottom: 1px solid #2e2e2e;
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .dsmc2-badge {
    background: var(--red-brand);
    color: #fff;
    font-size: 11px;
    font-weight: 800;
    padding: 2px 8px;
    border-radius: 2px;
    letter-spacing: 1px;
    margin-right: 10px;
  }
  .modal-x-btn {
    background: transparent;
    border: none;
    color: #aaa;
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
  }
  .modal-x-btn:hover { color: #fff; }
  .modal-intro {
    padding: 14px 20px 4px 20px;
    font-size: 13px;
    color: #aaa;
    line-height: 1.4;
  }
  .camera-model-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 14px;
    padding: 16px 20px;
    max-height: 65vh;
    overflow-y: auto;
  }
  .cam-card {
    background: #202020;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 14px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 10px;
    cursor: pointer;
    transition: all 0.2s ease;
  }
  .cam-card:hover {
    border-color: #ff3333;
    background: #262626;
    transform: translateY(-2px);
  }
  .cam-card.active {
    border-color: var(--red-bright);
    background: #2a1515;
    box-shadow: 0 0 12px rgba(220, 20, 20, 0.4);
  }
  .cam-card-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .cam-card-name {
    font-size: 15px;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: #fff;
  }
  .cam-card-id {
    font-size: 11px;
    font-family: monospace;
    background: #111;
    padding: 2px 6px;
    border-radius: 3px;
    color: #888;
  }
  .cam-card-sensor {
    font-size: 12px;
    color: #00e676;
    font-family: monospace;
    margin-top: 4px;
  }
  .cam-card-desc {
    font-size: 12px;
    color: #bbb;
    line-height: 1.35;
  }
  .cam-card-specs {
    display: flex;
    gap: 6px;
    font-size: 10px;
    font-family: monospace;
    flex-wrap: wrap;
  }
  .spec-pill {
    background: #151515;
    padding: 3px 6px;
    border-radius: 3px;
    color: #ddd;
    border: 1px solid #333;
  }
  .cam-card-btn {
    background: #333;
    color: #fff;
    border: 1px solid #555;
    padding: 7px 12px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    cursor: pointer;
    text-align: center;
    transition: background 0.15s;
    margin-top: 8px;
  }
  .cam-card.active .cam-card-btn {
    background: var(--red-brand);
    border-color: #ff4444;
  }
  .cam-card:hover .cam-card-btn {
    background: var(--red-brand);
  }
  .modal-bottom {
    background: #111;
    border-top: 1px solid #2e2e2e;
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-foot-note {
    font-size: 11px;
    color: #777;
    font-family: monospace;
  }
  .model-select-btn {
    background: #242424;
    border: 1px solid #444;
    color: #fff;
    font-size: 12px;
    padding: 5px 12px;
    border-radius: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
  }
  .model-select-btn:hover {
    border-color: #ff3333;
    background: #2c1a1a;
  }
  .model-select-btn .bolt { color: #ffb300; font-size: 13px; }
  .model-select-btn .caret { font-size: 10px; color: #888; }
</style>
</head>
<body>

<header>
  <div class="brand">
    <div class="red-logo">RED</div>
    <div>
      <div class="brand-title">DSMC2 VIRTUAL BRAIN</div>
      <div class="brand-sub"><span id="hdr-sub-name">SCARLET-W 5K</span> • FIRMWARE v7.4.1 • CORTEX-A8 @ 1.0 GHz</div>
    </div>
  </div>
  <div class="status-cluster">
    <button class="model-select-btn" onclick="openModelModal()" id="hdr-model-btn" title="Choose DSMC2 Camera Model">
      <span class="bolt">⚡</span> BRAIN: <strong id="hdr-model-name">SCARLET-W 5K</strong> <span class="caret">▾</span>
    </button>
    <div class="led-badge">
      <div id="led-dot" class="led-dot"></div>
      <span id="pwr-text">STANDBY</span>
    </div>
    <div class="led-badge">
      <span>RCP: <strong id="rcp-clients">0 clients</strong> (Port 1111)</span>
    </div>
    <div class="led-badge">
      <span>HOST: <strong>{{HOST}}:{{PORT}}</strong></span>
    </div>
    <div class="led-badge">
      <span id="instr-text">0.0M INSTR</span>
    </div>
  </div>
</header>

<div class="studio-grid">

  <!-- Left: Virtual Camera Zone -->
  <div class="camera-unit">
    <div class="monitor-bezel">
      <div class="bezel-screws">
        <div class="screw"></div><div class="screw"></div>
      </div>
      <div class="bezel-header">
        <span>RED TOUCH 7.0 LCD MONITOR</span>
        <span>1024 x 576 NATIVE (16:9)</span>
      </div>

      <!-- Container: Vertical RED MINI-MAG Slot (Left) + Screen Viewport (Right) -->
      <div class="screen-and-mag-container">
        <!-- RED MINI-MAG Slot Bay -->
        <div class="minimag-slot-bay" id="minimag-bay">
          <div class="mag-header">
            <div class="mag-brand">
              <span class="mag-logo-red">RED</span>
              <span class="mag-label">MINI-MAG&reg;</span>
            </div>
            <div class="mag-slot-tag">SLOT 1 &bull; SATA0</div>
          </div>

          <!-- Physical Cartridge Graphic / Insert Slot -->
          <div class="mag-cartridge" id="mag-cartridge">
            <div class="mag-grip"></div>
            <div class="mag-cartridge-body">
              <div class="mag-cartridge-title">RED MINI-MAG</div>
              <div class="mag-cartridge-cap" id="mag-cartridge-cap">512 GB</div>
              <div class="mag-cartridge-sub">TURBO / R3D RAW</div>
            </div>
            <div class="mag-led-row">
              <div class="mag-led" id="mag-led"></div>
              <span class="mag-led-text" id="mag-led-text">MEDIA READY</span>
            </div>
          </div>

          <!-- Active Firmware Status Box -->
          <div class="mag-fw-card">
            <div class="fw-card-label">ACTIVE FIRMWARE</div>
            <div class="fw-card-name" id="fw-active-name">SCARLET-W 5K (v7.4.1)</div>
            <div class="fw-card-status" id="fw-active-status">Confirmed Working Baseline</div>
            <div class="fw-card-details" id="fw-active-details">dsmc_program.mem &bull; 18.1 MB</div>
          </div>

          <!-- Firmware Upload / Drag-and-Drop Area -->
          <div class="mag-dropzone" id="mag-dropzone" onclick="document.getElementById('fw-file-input').click()" title="Drag &amp; drop custom firmware file (.bin / .mem / .pkg) or click to browse">
            <input type="file" id="fw-file-input" style="display: none;" accept=".bin,.mem,.pkg,.zip,.tar,.gz,.dsmc2" onchange="handleFwFileSelect(this.files)" />
            <div class="dropzone-icon">&uArr;</div>
            <div class="dropzone-text"><strong>Drop Custom Firmware</strong><br>or click to load (.bin, .mem, .pkg)</div>
            <div class="dropzone-hint">Test custom firmware mods</div>
          </div>

          <!-- Slot Action Controls -->
          <div class="mag-controls" style="flex-direction: column; gap: 5px;">
            <button class="cam-btn" id="btn-boot-custom" onclick="bootCustomFirmware()" style="display: none; background: linear-gradient(180deg, #0088cc, #005588); color: #fff; font-weight: bold; border-color: #00b0ff; width: 100%; padding: 6px;" title="Flash staged custom firmware directly into DDR RAM (0x80000000)">
              ⚡ Flash &amp; Boot Mod
            </button>
            <div style="display: flex; gap: 4px; width: 100%;">
              <button class="cam-btn mag-btn-reset" id="btn-revert-fw" onclick="revertFirmwareBaseline()" title="Reset to confirmed working baseline firmware">
                &circlearrowleft; Revert Baseline
              </button>
              <button class="cam-btn" style="padding: 5px 8px; font-size: 10px; flex: 1;" onclick="document.getElementById('fw-file-input').click()">
                Load Image...
              </button>
            </div>
          </div>
        </div>

        <!-- Screen Viewport (Right of Media Slot) -->
        <div class="screen-viewport" id="viewport">
          <!-- Live Video Stream -->
          <img id="stream-img" src="/api/stream" alt="RED DSMC2 LCD Stream" />
          <!-- Interactive Touch Layer -->
          <canvas class="touch-overlay" id="touchCanvas" width="1024" height="576"></canvas>
        </div>
      </div>

      <div class="bezel-screws" style="margin-top: 8px;">
        <div class="screw"></div><div class="screw"></div>
      </div>
    </div>

    <!-- Tactile Deck: Physical Camera Hardware Buttons -->
    <div class="tactile-deck">
      <!-- REC & POWER -->
      <div class="btn-group">
        <button id="rec-btn" class="rec-btn" title="Toggle Recording [R]">
          <span>●</span>
          <span>REC</span>
        </button>
        <button id="pwr-btn" class="cam-btn power-btn" title="Toggle Power / Standby">
          POWER ON
        </button>
      </div>

      <!-- FUNCTION KEYS -->
      <div class="btn-group">
        <button class="cam-btn" onclick="sendBtn('MENU')" title="Toggle Menu [M]">
          MENU <span class="hotkey-badge">M</span>
        </button>
        <button class="cam-btn" onclick="sendBtn('1:1 MAG')" title="Toggle 1:1 Magnify [1]">
          1:1 MAG <span class="hotkey-badge">1</span>
        </button>
        <button class="cam-btn" onclick="sendBtn('USER 1')" title="Toggle False Color [U]">
          USER 1 (FC) <span class="hotkey-badge">U</span>
        </button>
        <button class="cam-btn" onclick="sendBtn('USER 2')" title="Toggle Zebras [Z]">
          USER 2 (ZB) <span class="hotkey-badge">Z</span>
        </button>
      </div>

      <!-- D-PAD -->
      <div class="dpad">
        <div></div>
        <button onclick="sendBtn('NAV UP')">▲</button>
        <div></div>
        <button onclick="sendBtn('NAV LEFT')">◀</button>
        <button onclick="sendBtn('NAV ENTER')">●</button>
        <button onclick="sendBtn('NAV RIGHT')">▶</button>
        <div></div>
        <button onclick="sendBtn('NAV DOWN')">▼</button>
        <div></div>
      </div>

      <!-- BROADCAST HDMI & AUDIO MONITORING -->
      <div class="btn-group" style="flex-direction: column; gap: 4px; justify-content: center;">
        <button class="cam-btn" style="padding: 5px 8px; font-size: 10px; background: #222;" onclick="openHdmiModal()" title="View external 1080p clean/broadcast feed">
          🖥️ HDMI Broadcast Monitor
        </button>
        <button id="audio-mon-btn" class="cam-btn" style="padding: 5px 8px; font-size: 10px; background: #222;" onclick="toggleAudioMonitor()" title="Monitor 48kHz camera audio via Web Audio API">
          🎧 Headphone Monitor: OFF
        </button>
      </div>
    </div>
  </div>

  <!-- Right: Engineering Workbench -->
  <div class="workbench">
    <div class="tab-bar">
      <button class="tab-btn active" onclick="switchTab('serial', this)">Console / Serial</button>
      <button class="tab-btn" onclick="switchTab('rig', this)">Rig &amp; Positions</button>
      <button class="tab-btn" onclick="switchTab('rcp', this)">RCP &amp; Automation</button>
      <button class="tab-btn" onclick="switchTab('hardware', this)">Hardware I/O & Audio</button>
      <button class="tab-btn" onclick="switchTab('lens', this)">Lens & Optics</button>
      <button class="tab-btn" onclick="switchTab('media', this)">Media & Clips</button>
      <button class="tab-btn" onclick="switchTab('threads', this)">ThreadX RTOS</button>
      <button class="tab-btn" onclick="switchTab('snapshots', this)">Snapshots</button>
      <button class="tab-btn" onclick="switchTab('faults', this)">Fault Injection</button>
    </div>

    <!-- Tab 1: Serial Console -->
    <div id="tab-serial" class="tab-content active">
      <div class="console-tools">
        <div>
          <span>UART4 Serial Stream</span>
          <span id="log-count" style="color: #666; margin-left: 8px;">(0 lines)</span>
        </div>
        <div style="display: flex; gap: 12px; align-items: center;">
          <label style="cursor: pointer;">
            <input type="checkbox" id="auto-scroll" checked /> Auto-scroll
          </label>
          <button class="cam-btn" style="padding: 4px 10px;" onclick="clearConsole()">Clear Log</button>
        </div>
      </div>
      <div id="console" class="console-box"></div>
    </div>

    <!-- Tab: Modular Rig & Physical Positions -->
    <div id="tab-rig" class="tab-content">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
        <div>
          <span style="font-size: 14px; font-weight: bold; color: #ff3333;">Modular Camera Rig &amp; Connector Positions</span>
          <div style="font-size: 11px; color: #888;">Configure physical mounting slots, hot-swap modules, toggle display locations, and test hardware presence detection.</div>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <span style="font-size: 11px; color: #aaa;">Presets:</span>
          <select id="rig-preset-select" style="background: #242424; color: #fff; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; font-size: 11px;">
            <option value="cinema_production">Cinema Production Rig</option>
            <option value="handheld_operator">Operator Handheld Rig</option>
            <option value="broadcast_studio">Broadcast &amp; Live Studio</option>
            <option value="bare_brain">Bare Brain (Minimal)</option>
          </select>
          <button class="cam-btn" style="padding: 4px 10px; font-size: 11px;" onclick="applyRigPreset()">Apply Rig</button>
        </div>
      </div>

      <!-- Quick Slot Grid Cards -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 14px;" id="rig-slots-grid">
        <!-- Rendered dynamically by renderRigSlots() -->
      </div>

      <!-- Rig Control & Hot-Swap Panel -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 14px;">
        <div>
          <div style="font-size: 12px; font-weight: bold; color: #00e676; margin-bottom: 6px;">Hot-Swap / Attach to Slot</div>
          <div style="display: flex; gap: 8px; margin-bottom: 8px;">
            <select id="rig-slot-target-select" style="flex: 1; background: #222; color: #fff; border: 1px solid #444; padding: 4px 6px; border-radius: 3px; font-size: 11px;">
              <option value="top_pogo">Top Pogo (LCD/EVF)</option>
              <option value="side_pogo">Side Pogo (EVF/Sidekick)</option>
              <option value="rear_module">Rear Expander Bus (26-pin)</option>
              <option value="lens_mount">Front Lens Mount</option>
              <option value="media_bay">Media Bay (Mini-Mag)</option>
            </select>
            <select id="rig-module-catalog-select" style="flex: 1; background: #222; color: #fff; border: 1px solid #444; padding: 4px 6px; border-radius: 3px; font-size: 11px;">
              <option value="730-0024">RED Touch 7.0 LCD</option>
              <option value="730-0025">RED Touch 4.7 LCD</option>
              <option value="730-0026">DSMC2 OLED EVF</option>
              <option value="720-0043">DSMC2 Sidekick</option>
              <option value="720-0033">DSMC2 Base Expander</option>
              <option value="720-0034">DSMC2 REDVOLT Expander</option>
              <option value="720-0035">DSMC2 Jetpack-SDI</option>
              <option value="720-0045">DSMC2 V-Lock I/O Expander</option>
              <option value="725-0026">Canon EF Mount</option>
              <option value="725-0022">PL Intelligent Mount</option>
              <option value="750-0075">RED MINI-MAG 512GB</option>
              <option value="750-0082">RED MINI-MAG 960GB</option>
            </select>
            <button class="cam-btn" style="padding: 4px 10px; font-size: 11px;" onclick="attachRigModule()">Mount</button>
          </div>
        </div>

        <div>
          <div style="font-size: 12px; font-weight: bold; color: #ffaa00; margin-bottom: 6px;">Position Toggle &amp; Spatial Swap</div>
          <div style="display: flex; gap: 8px; margin-bottom: 8px;">
            <select id="rig-toggle-from" style="flex: 1; background: #222; color: #fff; border: 1px solid #444; padding: 4px 6px; border-radius: 3px; font-size: 11px;">
              <option value="top_pogo">From: Top Pogo</option>
              <option value="side_pogo">From: Side Pogo</option>
            </select>
            <select id="rig-toggle-to" style="flex: 1; background: #222; color: #fff; border: 1px solid #444; padding: 4px 6px; border-radius: 3px; font-size: 11px;">
              <option value="side_pogo">To: Side Pogo</option>
              <option value="top_pogo">To: Top Pogo</option>
            </select>
            <button class="cam-btn" style="padding: 4px 10px; font-size: 11px; background: #333;" onclick="toggleRigPosition()">Move / Swap</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 2: RCP & Automation -->
    <div id="tab-rcp" class="tab-content">
      <!-- Top Grid: Automation & Multi-Cam Studio -->
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
        
        <!-- Script Runner Box -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: bold; font-size: 12px; color: #ff3333;">RCP Automation Sequence Runner</span>
            <span id="script-status-badge" style="font-size: 10px; padding: 2px 6px; border-radius: 3px; background: #2a2a2a; color: #aaa;">IDLE</span>
          </div>
          <div style="display: flex; gap: 6px; margin-bottom: 8px;">
            <select id="rcp-preset-select" style="flex: 1; background: #242424; color: #fff; border: 1px solid #444; padding: 4px 6px; border-radius: 3px; font-size: 11px;">
              <option value="RACK_FOCUS">Rack Focus & Depth Sweep (f/2.8 -> f/8)</option>
              <option value="RECORD_CYCLE">Production Slate & Record Cycle (ISO 800)</option>
              <option value="EXPOSURE_BRACKET">Exposure Bracket Sweep (ISO/Shutter)</option>
              <option value="MULTICAM_SYNC">Multi-Camera Master Broadcast Sync</option>
            </select>
            <button class="cam-btn" style="padding: 4px 10px; font-size: 11px; background: #c00;" onclick="runRcpPreset()">Execute</button>
          </div>
          <div id="script-summary-text" style="font-size: 11px; color: #888; font-family: monospace; min-height: 20px;">
            Ready to execute automation script sequence.
          </div>
        </div>

        <!-- Multi-Camera Network Box -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: bold; font-size: 12px; color: #00b0ff;">Multi-Camera Studio Network</span>
            <span id="genlock-badge" style="font-size: 10px; padding: 2px 6px; border-radius: 3px; background: #1a3320; color: #00e676;">GENLOCK: LOCKED</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; font-size: 10.5px; font-family: monospace; margin-bottom: 8px;">
            <div style="background: #121212; padding: 4px 6px; border-radius: 3px; border-left: 2px solid #ff3333;">
              <div style="color: #fff; font-weight: bold;">A-CAM (Master)</div>
              <div id="multicam-acam-state" style="color: #aaa;">Standby</div>
            </div>
            <div style="background: #121212; padding: 4px 6px; border-radius: 3px; border-left: 2px solid #00b0ff;">
              <div style="color: #fff; font-weight: bold;">B-CAM (Slave)</div>
              <div id="multicam-bcam-state" style="color: #aaa;">Standby</div>
            </div>
            <div style="background: #121212; padding: 4px 6px; border-radius: 3px; border-left: 2px solid #00b0ff;">
              <div style="color: #fff; font-weight: bold;">C-CAM (Slave)</div>
              <div id="multicam-ccam-state" style="color: #aaa;">Standby</div>
            </div>
          </div>
          <div style="display: flex; gap: 6px;">
            <button class="cam-btn" style="flex: 1; padding: 3px 6px; font-size: 10px;" onclick="syncMulticamGenlock()">Sync Genlock & TC</button>
            <button class="cam-btn" style="flex: 1; padding: 3px 6px; font-size: 10px; background: #7a1111;" onclick="triggerMulticamRecord()">Broadcast Rec Trigger</button>
          </div>
        </div>

      </div>

      <!-- Execution Trace Log Container (collapsible/visible on run) -->
      <div id="script-trace-box" style="display: none; background: #111; border: 1px solid #444; border-radius: 4px; padding: 8px; margin-bottom: 10px; max-height: 120px; overflow-y: auto; font-family: monospace; font-size: 10.5px;">
        <div style="color: #00e676; font-weight: bold; margin-bottom: 4px;">Script Execution Audit Trail:</div>
        <div id="script-trace-content"></div>
      </div>

      <!-- Live Parameter Cache Table -->
      <div style="margin-bottom: 6px; font-size: 12px; color: #aaa;">
        Live RED Command Protocol (RCP) Parameter Cache
      </div>
      <div style="flex: 1; overflow-y: auto;">
        <table class="data-table">
          <thead>
            <tr><th>Parameter</th><th>Value</th><th>Action</th></tr>
          </thead>
          <tbody id="rcp-table-body"></tbody>
        </table>
      </div>
      <div class="cmd-bar">
        <input id="rcp-cmd-input" class="cmd-input" type="text" placeholder="Send RCP command (e.g. GET iso, SET iso 1600)..." onkeydown="if(event.key==='Enter') sendRcp()" />
        <button class="cam-btn" onclick="sendRcp()">Send</button>
      </div>
    </div>

    <!-- Tab: Hardware I/O & Peripherals -->
    <div id="tab-hardware" class="tab-content">
      <div style="margin-bottom: 12px; font-size: 12px; color: #aaa;">
        OMAP3630 Multi-Bus I2C Subsystem (I2C1/I2C2/I2C3) &amp; General Purpose Memory Controller (GPMC)
      </div>

      <!-- I2C Bus Topology Overview -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 10px 14px; margin-bottom: 12px; font-family: monospace; font-size: 11px; color: #bbb; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;">
        <div style="background: #121212; padding: 8px; border-radius: 3px; border-left: 3px solid #00e676;">
          <div style="color: #888; font-size: 10px;">I2C1 (0x48070000, IRQ 56)</div>
          <div style="color: #fff; font-weight: bold; margin-top: 3px;">TWL4030 PMIC (0x48)</div>
          <div style="color: #aaa; margin-top: 2px;">TMP411 Thermal (0x4C)</div>
        </div>
        <div style="background: #121212; padding: 8px; border-radius: 3px; border-left: 3px solid #00b0ff;">
          <div style="color: #888; font-size: 10px;">I2C2 (0x48072000, IRQ 57)</div>
          <div style="color: #fff; font-weight: bold; margin-top: 3px;">OLPF EEPROM (0x54)</div>
          <div style="color: #aaa; margin-top: 2px;">Smart Lens Mount</div>
        </div>
        <div style="background: #121212; padding: 8px; border-radius: 3px; border-left: 3px solid #ffaa00;">
          <div style="color: #888; font-size: 10px;">I2C3 (0x48060000, IRQ 61)</div>
          <div style="color: #fff; font-weight: bold; margin-top: 3px;">maXTouch (0x4B)</div>
          <div style="color: #aaa; margin-top: 2px;">EDID EEPROM (0x50)</div>
        </div>
        <div style="background: #121212; padding: 8px; border-radius: 3px; border-left: 3px solid #d11212;">
          <div style="color: #888; font-size: 10px;">GPMC (0x6E000000)</div>
          <div style="color: #fff; font-weight: bold; margin-top: 3px;">Micron NAND (CS0)</div>
          <div style="color: #aaa; margin-top: 2px;">Hardware BCH ECC</div>
        </div>
      </div>

      <!-- Device Cards Grid -->
      <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">

        <!-- Card 1: PMIC TWL4030 -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #00e676;">TI TWL4030 / TPS65950 PMIC</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">I2C1 @ 0x48</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11.5px; font-family: monospace; margin-bottom: 10px;">
            <div>Power Source: <strong id="hw-pmic-source" style="color: #00e676;">DC IN (15V)</strong></div>
            <div>ADC Voltage: <strong id="hw-pmic-volts" style="color: #00e676;">14.8V</strong></div>
            <div>VDD1 (MPU 1GHz): <strong id="hw-pmic-vdd1" style="color: #fff;">1.35V</strong></div>
            <div>VDD2 (Core/L3): <strong id="hw-pmic-vdd2" style="color: #fff;">1.15V</strong></div>
          </div>
          <div style="margin-bottom: 8px;">
            <div style="display: flex; justify-content: space-between; font-size: 11px; color: #888; margin-bottom: 4px;">
              <span>Simulate Battery Drain / Supply Voltage:</span>
              <span id="hw-pmic-slider-val" style="font-family: monospace; color: #fff;">14.8V</span>
            </div>
            <input id="hw-pmic-slider" type="range" min="10.0" max="16.8" step="0.1" value="14.8" style="width: 100%;" oninput="document.getElementById('hw-pmic-slider-val').textContent = parseFloat(this.value).toFixed(1)+'V'; setPmicVoltage(this.value);" />
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setPmicVoltage(15.2); document.getElementById('hw-pmic-slider').value=15.2; document.getElementById('hw-pmic-slider-val').textContent='15.2V';">15.2V (AC In)</button>
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setPmicVoltage(14.8); document.getElementById('hw-pmic-slider').value=14.8; document.getElementById('hw-pmic-slider-val').textContent='14.8V';">14.8V (RED BRICK)</button>
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setPmicVoltage(11.5); document.getElementById('hw-pmic-slider').value=11.5; document.getElementById('hw-pmic-slider-val').textContent='11.5V';">11.5V (Low Batt)</button>
            <button id="hw-pmic-dc-toggle" class="cam-btn" style="padding: 4px 8px; font-size: 10px; background: #222;" onclick="toggleDcIn()">Toggle DC-IN / Battery</button>
          </div>
        </div>

        <!-- Card 2: Thermal TMP411 -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #ffaa00;">TI TMP411 Dual-Channel Thermal</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">I2C1 @ 0x4C</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11.5px; font-family: monospace; margin-bottom: 10px;">
            <div>Remote Sensor Die: <strong id="hw-temp-sensor" style="color: #00e676;">39°C</strong></div>
            <div>BRAIN Core Ambient: <strong id="hw-temp-brain" style="color: #ffaa00;">63°C</strong></div>
          </div>
          <div id="hw-temp-cal" style="font-size: 11px; font-family: monospace; margin-bottom: 8px;">
            <span style="color: #00e676;">● T/E Calibrated (Within &plusmn;2.5°C)</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 8px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 11px; color: #888; width: 80px;">Sensor Temp:</span>
              <input id="hw-temp-sensor-slider" type="range" min="20" max="80" step="1" value="39" style="flex: 1;" oninput="onSensorTempSlider(this.value);" />
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="font-size: 11px; color: #888; width: 80px;">BRAIN Core:</span>
              <input id="hw-temp-brain-slider" type="range" min="30" max="95" step="1" value="63" style="flex: 1;" oninput="onBrainTempSlider(this.value);" />
            </div>
          </div>
          <div style="display: flex; gap: 6px;">
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setThermalTemps(39, 63);">Reset Nominal (39°/63°)</button>
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setThermalTemps(46, 75);">Trigger T/E Drift (46°/75°)</button>
          </div>
        </div>

        <!-- Card 3: OLPF EEPROM -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #00b0ff;">DSMC2 OLPF EEPROM (24C02)</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">I2C2 @ 0x54</span>
          </div>
          <div style="font-size: 12px; margin-bottom: 6px;">
            Active Filter: <strong id="hw-olpf-name" style="color: #fff;">Standard OLPF</strong>
            <span style="font-family: monospace; color: #888; font-size: 11px; margin-left: 6px;" id="hw-olpf-id">(0x01)</span>
          </div>
          <div id="hw-olpf-desc" style="font-size: 11px; color: #aaa; margin-bottom: 10px; line-height: 1.4;">
            Balanced color reproduction, optimal sharpness and highlight retention.
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px;">
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setOlpfProfile('Standard')">Standard</button>
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setOlpfProfile('Skin Tone-Highlight')">Skin Tone-Highlight</button>
            <button class="cam-btn" style="padding: 4px 8px; font-size: 10px;" onclick="setOlpfProfile('Low Light Optimized')">Low Light Optimized</button>
          </div>
          <div style="background: #111; padding: 6px; border-radius: 3px; font-family: monospace; font-size: 10px; color: #666;">
            EEPROM Header Magic: <strong>REDOLPF\x01</strong> &bull; Size: 256 bytes &bull; 9-float Color Matrix
          </div>
        </div>

        <!-- Card 4: GPMC Memory Controller -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #d11212;">OMAP3630 GPMC Controller</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">MMIO @ 0x6E000000</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 11.5px; font-family: monospace; margin-bottom: 10px;">
            <div>Controller Status: <strong id="hw-gpmc-status" style="color: #00e676;">READY (0x01)</strong></div>
            <div>BCH Hardware ECC: <strong style="color: #00e676;">ACTIVE</strong></div>
            <div>CS0 Base Window: <strong style="color: #fff;">0x08000000</strong></div>
            <div>Flash Device: <strong style="color: #fff;">Micron 256MB SLC</strong></div>
          </div>
          <div style="background: #111; padding: 8px; border-radius: 3px; font-family: monospace; font-size: 10.5px; color: #aaa; margin-bottom: 8px;">
            <div>&bull; NAND_CMD: <span style="color: #00e676;">0x6E00007C</span> | ONFI Command Bus</div>
            <div>&bull; NAND_ADDRESS: <span style="color: #00e676;">0x6E000080</span> | 5-cycle Flash Addressing</div>
            <div>&bull; NAND_DATA: <span style="color: #00e676;">0x6E000084</span> | 32-bit DMA / FIFO Window</div>
            <div>&bull; ECC_RESULT: <span style="color: #00e676;">0x6E000200</span> | Hardware BCH8 Engine</div>
          </div>
        </div>

        <!-- Card 5: Tensilica Xtensa Coprocessors (IOB0, IOB1, Dual ISP) -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #ff5555;">Tensilica Xtensa ASICs (IOB0, IOB1, ISP1/2)</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">McSPI / C2C Mailbox</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px; font-family: monospace; font-size: 11px;">
            <!-- IOB0 -->
            <div style="background: #111; padding: 6px 8px; border-radius: 3px; border-left: 2px solid #00e676;">
              <div style="color: #00e676; font-weight: bold;">IOB0: Storage, HDMI &amp; SPI Motion</div>
              <div style="color: #bbb; margin-top: 2px;">
                SATA 3.0: <span id="hw-iob0-sata" style="color: #fff;">6.0 Gbps (0 frames)</span> &bull; HDMI: <span style="color: #fff;">1080p60</span>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Tilt Angle: <span id="hw-iob0-tilt" style="color: #ffaa00;">Roll 0.0°, Pitch 0.0° [LEVEL]</span>
              </div>
            </div>
            <!-- IOB1 -->
            <div style="background: #111; padding: 6px 8px; border-radius: 3px; border-left: 2px solid #00b0ff;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #00b0ff; font-weight: bold;">IOB1: Sensor Dark-Level Calibration</span>
                <button class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="runBlackShading()">Run Black Shading</button>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Status: <span id="hw-iob1-status" style="color: #00e676;">CALIBRATED (39°C 1/48)</span>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Defect Tables: <span id="hw-iob1-defects" style="color: #fff;">3 Factory, 2 User Masked</span>
              </div>
            </div>
            <!-- Dual ISP -->
            <div style="background: #111; padding: 6px 8px; border-radius: 3px; border-left: 2px solid #ffaa00;">
              <div style="color: #ffaa00; font-weight: bold;">ISP1 &amp; ISP2: REDCODE Wavelet Compression</div>
              <div style="color: #bbb; margin-top: 2px;">
                Engine: <span style="color: #fff;">3-Level DWT (G1/B/R/G2 slices)</span> &bull; DDR: <span style="color: #00e676;">PASS (SCL V2)</span>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Active Ratio: <span id="hw-isp-ratio" style="color: #fff;">8:1</span> &bull; Frames: <span id="hw-isp-frames" style="color: #00e676;">0</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Card 6: TI TMS320C64x+ DSP & Vision Servers -->
        <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #b388ff;">TI TMS320C64x+ DSP (DSP/BIOS)</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">Entry @ 0x8FA00000</span>
          </div>
          <div style="display: flex; flex-direction: column; gap: 8px; font-family: monospace; font-size: 11px;">
            <div style="background: #111; padding: 6px 8px; border-radius: 3px; border-left: 2px solid #b388ff;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #b388ff; font-weight: bold;">CImagingServer: Vision &amp; Autofocus</span>
                <button class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="triggerFaceDetection()">Detect Faces</button>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Focus Sharpness Score: <span id="hw-dsp-af" style="color: #00e676;">98.5 / 100.0</span>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Haar Face Detection: <span id="hw-dsp-faces" style="color: #fff;">1 Detected (TI VLIB HW)</span>
              </div>
            </div>
            <div style="background: #111; padding: 6px 8px; border-radius: 3px; border-left: 2px solid #00e676;">
              <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: #00e676; font-weight: bold;">RAudioServer: 4-Channel 24-Bit Audio</span>
                <button id="hw-audio-tone-btn" class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="toggleTestTone()">1kHz Cal Tone</button>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Ch1: <span id="hw-audio-ch1" style="color: #00e676;">-18.5 dBFS</span> &bull; Ch2: <span id="hw-audio-ch2" style="color: #00e676;">-19.2 dBFS</span>
              </div>
              <div style="color: #bbb; margin-top: 2px;">
                Pre-Amps: <span id="hw-audio-preamp" style="color: #fff;">+18.0 dB (Ch1/2)</span> &bull; Headphone: <span id="hw-audio-hp" style="color: #fff;">75%</span>
              </div>
              <canvas id="audio-scope-canvas" width="280" height="36" style="width: 100%; height: 36px; background: #080808; border: 1px solid #2a2a2a; border-radius: 2px; margin-top: 4px; display: block;"></canvas>
            </div>
          </div>
        </div>

        <!-- Card 7: Accessory Bus & Module Hot-Plug -->
        <div style="grid-column: span 2; background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 13px; font-weight: bold; color: #ffb300;">DSMC2 Accessory Bus &amp; Expander Enumeration (1-Wire / UART)</span>
            <span style="font-family: monospace; font-size: 11px; color: #888;">Protocol: WHO &bull; VERSION &bull; REDINFO (TLV)</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 11.5px;">
            <div style="display: flex; gap: 8px; align-items: center;">
              <span>Hot-Plug Attach:</span>
              <select id="hw-acc-select" style="background: #242424; color: #fff; border: 1px solid #444; padding: 3px 8px; border-radius: 3px; font-size: 11px;">
                <option value="720-0033">DSMC2 Base Expander (720-0033)</option>
                <option value="720-0034">DSMC2 REDVOLT Expander (720-0034)</option>
                <option value="720-0035">DSMC2 Jetpack-SDI Expander (720-0035)</option>
              </select>
              <button class="cam-btn" style="padding: 3px 8px; font-size: 11px;" onclick="attachAccessoryModule()">Attach Module</button>
            </div>
            <div style="font-family: monospace; font-size: 11px; color: #aaa;">
              Total Accessory Power: <strong id="hw-acc-power" style="color: #00e676;">25W</strong>
            </div>
          </div>
          <div style="overflow-x: auto;">
            <table class="data-table" style="font-size: 11px;">
              <thead>
                <tr><th>PIN</th><th>Module Name</th><th>Category</th><th>Serial</th><th>Power</th><th>Ports</th><th>Action</th></tr>
              </thead>
              <tbody id="hw-acc-table-body"></tbody>
            </table>
          </div>
        </div>

      </div>
    </div>

    <!-- Tab: Lens & Optics -->
    <div id="tab-lens" class="tab-content">
      <div style="margin-bottom: 12px; font-size: 12px; color: #aaa;">
        Electronic Lens Mount Interface & Authentic Firmware Lens Database
      </div>
      
      <!-- Attached Lens Card -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px; margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span style="font-size: 14px; font-weight: bold; color: #00e676;" id="lens-model-txt">Canon EF 24-70mm f/2.8L II USM</span>
          <span style="font-family: monospace; font-size: 11px; color: #888;" id="lens-mount-txt">Canon EF</span>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; font-size: 12px; font-family: monospace; color: #bbb;">
          <div>Brand: <strong id="lens-brand-txt" style="color: #fff;">Canon</strong></div>
          <div>Serial: <strong id="lens-serial-txt" style="color: #fff;">CN-748921</strong></div>
          <div>Focal Range: <strong id="lens-range-txt" style="color: #fff;">24-70mm</strong></div>
          <div>Current Focal: <strong id="lens-focal-txt" style="color: #ffaa00;">50mm</strong></div>
          <div>Current Iris: <strong id="lens-iris-txt" style="color: #00ff66;">f/2.8</strong></div>
          <div>Focus Dist: <strong id="lens-dist-txt" style="color: #66b3ff;">2.50m</strong></div>
        </div>
      </div>

      <!-- Controls -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px; margin-bottom: 14px;">
        <div style="font-weight: 600; font-size: 12px; color: #ddd; margin-bottom: 8px;">Electronic Iris / Aperture Stepping (1/3 EV)</div>
        <div id="lens-stops-container" style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px;"></div>
        <div style="display: flex; gap: 8px;">
          <button class="cam-btn" onclick="stepAperture(-1)">◄ Open Up (-1/3 Stop)</button>
          <button class="cam-btn" onclick="stepAperture(1)">Close Down (+1/3 Stop) ►</button>
        </div>
      </div>

      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px; margin-bottom: 14px;">
        <div style="font-weight: 600; font-size: 12px; color: #ddd; margin-bottom: 8px;">Zoom & Focus Motors</div>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div style="display: flex; align-items: center; gap: 10px;">
            <label style="font-size: 12px; width: 90px; color: #aaa;">Focal Length:</label>
            <input id="focal-slider" type="range" min="24" max="70" value="50" style="flex: 1;" oninput="onFocalSlider(this.value)" />
            <span id="focal-val-lbl" style="font-family: monospace; font-size: 12px; width: 50px;">50mm</span>
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <label style="font-size: 12px; width: 90px; color: #aaa;">Focus Dist:</label>
            <input id="focus-slider" type="range" min="0.3" max="50.0" step="0.1" value="2.5" style="flex: 1;" oninput="onFocusSlider(this.value)" />
            <span id="focus-val-lbl" style="font-family: monospace; font-size: 12px; width: 50px;">2.5m</span>
            <button class="cam-btn" style="padding: 4px 10px;" onclick="triggerAf()">Trigger AF</button>
          </div>
        </div>
      </div>

      <!-- Mount Swapper & Catalog -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px;">
        <div style="font-weight: 600; font-size: 12px; color: #ddd; margin-bottom: 8px;">Mount Hardware & Authentic Lens Catalog (230+ Models)</div>
        <div style="display: flex; gap: 8px; margin-bottom: 10px;">
          <select id="mount-select" class="cmd-input" style="flex: 1;" onchange="onMountChange(this.value)">
            <option value="Canon EF">Canon EF Smart Mount</option>
            <option value="Nikon F">Nikon F Electronic Mount</option>
            <option value="PL Mount (/i)">PL Intelligent Mount (/i)</option>
          </select>
        </div>
        <div style="display: flex; gap: 8px;">
          <select id="catalog-select" class="cmd-input" style="flex: 1;"></select>
          <button class="cam-btn" onclick="attachSelectedLens()">Attach Lens</button>
        </div>
      </div>
    </div>

    <!-- Tab: Media & Clips -->
    <div id="tab-media" class="tab-content">
      <div style="margin-bottom: 12px; font-size: 12px; color: #aaa;">
        RED MINI-MAG High-Speed Solid State Media & Authentic .R3D / .RMD Clips
      </div>

      <!-- Media Card -->
      <div style="background: #181818; border: 1px solid #333; border-radius: 4px; padding: 12px; margin-bottom: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
          <span style="font-size: 14px; font-weight: bold; color: #fff;">RED MINI-MAG 512GB (Port SATA0)</span>
          <span id="media-status-badge" style="font-family: monospace; font-size: 11px; padding: 2px 6px; border-radius: 3px; background: #1b3d1b; color: #00ff66;">MOUNTED</span>
        </div>
        <div style="font-size: 12px; font-family: monospace; color: #bbb; margin-bottom: 8px;">
          Reel: <strong id="media-reel-txt" style="color: #fff;">A001</strong> | Filesystem: <strong style="color: #fff;">FAT32 / RED UDF v2.50</strong>
        </div>
        <!-- Progress bar -->
        <div style="height: 14px; background: #252525; border-radius: 3px; overflow: hidden; margin-bottom: 6px; border: 1px solid #444;">
          <div id="media-used-bar" style="height: 100%; width: 22%; background: #00b0ff; transition: width 0.3s;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 11px; font-family: monospace; color: #888;">
          <span id="media-used-txt">Used: 112.0 GB</span>
          <span id="media-free-txt" style="color: #00e676;">Free: 400.0 GB (78%)</span>
        </div>
        <div style="display: flex; gap: 8px; margin-top: 10px;">
          <button class="cam-btn" onclick="formatMedia()" style="background: #4a1515; border-color: #aa2222; color: #fff;">Format Media</button>
          <button id="media-eject-btn" class="cam-btn" onclick="toggleMediaMount()">Eject Media</button>
        </div>
      </div>

      <!-- Clips Table -->
      <div style="flex: 1; overflow-y: auto; background: #141414; border: 1px solid #2a2a2a; border-radius: 4px;">
        <table class="data-table">
          <thead>
            <tr><th>Clip Container (.RDC)</th><th>Size</th><th>R3D Format</th><th>Action</th></tr>
          </thead>
          <tbody id="clips-table-body"></tbody>
        </table>
      </div>

      <!-- RMD Viewer Box -->
      <div id="rmd-viewer-container" style="display: none; margin-top: 10px; background: #0a0a0a; border: 1px solid #444; border-radius: 4px; padding: 10px; max-height: 180px; overflow-y: auto;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
          <span style="font-size: 11px; color: #aaa; font-weight: bold;">RED Metadata XML Sidecar (.RMD)</span>
          <button class="cam-btn" style="padding: 1px 6px; font-size: 10px;" onclick="closeRmdViewer()">Close</button>
        </div>
        <pre id="rmd-viewer-content" style="font-family: monospace; font-size: 11px; color: #ffaa00; white-space: pre-wrap; margin: 0;"></pre>
      </div>
    </div>

    <!-- Tab 3: ThreadX RTOS Inspector -->
    <div id="tab-threads" class="tab-content">
      <div style="margin-bottom: 8px; font-size: 12px; color: #aaa;">
        Detected ThreadX RTOS Threads & Schedular State
      </div>
      <div style="flex: 1; overflow-y: auto;">
        <table class="data-table">
          <thead>
            <tr><th>Address</th><th>Thread Name</th><th>State</th><th>Priority</th><th>SP</th><th>Stack Range</th></tr>
          </thead>
          <tbody id="threads-table-body"></tbody>
        </table>
      </div>
    </div>

    <!-- Tab 4: Snapshots -->
    <div id="tab-snapshots" class="tab-content">
      <div style="margin-bottom: 12px; font-size: 12px; color: #aaa;">
        Full-system state snapshot save and instantaneous restoration.
      </div>
      <div style="display: flex; gap: 10px; margin-bottom: 16px;">
        <input id="snap-name-input" class="cmd-input" type="text" placeholder="snapshot_01.dsmc2" />
        <button class="cam-btn" onclick="saveSnapshot()">Save Snapshot</button>
      </div>
      <div id="snap-result" style="font-family: monospace; font-size: 12px; color: #00ff66;"></div>
    </div>

    <!-- Tab 5: Hardware Faults -->
    <div id="tab-faults" class="tab-content">
      <div style="margin-bottom: 12px; font-size: 12px; color: #aaa;">
        Inject hardware faults to verify firmware resilience and exception handlers.
      </div>
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <button class="cam-btn" onclick="injectFault('INTC_IRQ_LOCKUP')">Inject INTC IRQ Lockup (IRQ 58 Touch Storm)</button>
        <button class="cam-btn" onclick="injectFault('DDR_ECC_CORRUPT')">Inject DDR ECC Single-Bit Memory Corruption</button>
        <button class="cam-btn" onclick="injectFault('GPTIMER_DRIFT')">Inject GPTimer System Clock Drift (+15%)</button>
      </div>
      <div id="fault-result" style="font-family: monospace; font-size: 12px; color: #ffaa00; margin-top: 14px;"></div>
    </div>

  </div>

</div>

<script>
  let lastLogIndex = 0;
  let isTouching = false;
  const canvas = document.getElementById('touchCanvas');
  const ctx = canvas.getContext('2d');
  const viewport = document.getElementById('viewport');

  // Map mouse/touch pointer to native 1024x576 coordinates
  function getNativeCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches ? e.touches[0].clientY : e.clientY;
    const x = Math.round((clientX - rect.left) * (1024 / rect.width));
    const y = Math.round((clientY - rect.top) * (576 / rect.height));
    return {
      x: Math.max(0, Math.min(1023, x)),
      y: Math.max(0, Math.min(575, y))
    };
  }

  // Draw local high-responsiveness touch reticle
  function drawReticle(x, y) {
    ctx.clearRect(0, 0, 1024, 576);
    ctx.strokeStyle = '#ff3333';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 22, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(x, y, 14, 0, Math.PI * 2);
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.arc(x, y, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  function clearReticle() {
    ctx.clearRect(0, 0, 1024, 576);
  }

  // Touch Event Listeners
  canvas.addEventListener('mousedown', (e) => {
    isTouching = true;
    const {x, y} = getNativeCoords(e);
    drawReticle(x, y);
    sendTouch(x, y, true, 'down');
  });

  window.addEventListener('mousemove', (e) => {
    if (!isTouching) return;
    const {x, y} = getNativeCoords(e);
    drawReticle(x, y);
    sendTouch(x, y, true, 'move');
  });

  window.addEventListener('mouseup', (e) => {
    if (!isTouching) return;
    isTouching = false;
    const {x, y} = getNativeCoords(e);
    sendTouch(x, y, false, 'up');
    setTimeout(clearReticle, 200);
  });

  // Mobile / Touchscreen Support
  canvas.addEventListener('touchstart', (e) => {
    e.preventDefault();
    isTouching = true;
    const {x, y} = getNativeCoords(e);
    drawReticle(x, y);
    sendTouch(x, y, true, 'down');
  }, {passive: false});

  canvas.addEventListener('touchmove', (e) => {
    e.preventDefault();
    if (!isTouching) return;
    const {x, y} = getNativeCoords(e);
    drawReticle(x, y);
    sendTouch(x, y, true, 'move');
  }, {passive: false});

  canvas.addEventListener('touchend', (e) => {
    e.preventDefault();
    isTouching = false;
    sendTouch(0, 0, false, 'up');
    setTimeout(clearReticle, 200);
  });

  // API Dispatchers
  function sendTouch(x, y, pressed, action = 'down') {
    fetch('/api/touch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({x, y, pressed, action})
    }).catch(() => {});
  }

  function sendBtn(name) {
    fetch('/api/button', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({button: name})
    }).catch(() => {});
  }

  document.getElementById('rec-btn').addEventListener('click', () => sendBtn('REC'));
  document.getElementById('pwr-btn').addEventListener('click', async () => {
    const btn = document.getElementById('pwr-btn');
    btn.disabled = true;
    try {
      const res = await fetch('/api/power', {method: 'POST'});
      const data = await res.json();
      await pollStatus();
    } catch (e) {
      console.error('Power toggle failed:', e);
    } finally {
      btn.disabled = false;
    }
  });

  // Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;
    const key = e.key.toUpperCase();
    if (key === 'M') sendBtn('MENU');
    else if (key === 'R') sendBtn('REC');
    else if (key === '1') sendBtn('1:1 MAG');
    else if (key === 'U') sendBtn('USER 1');
    else if (key === 'Z') sendBtn('USER 2');
    else if (e.key === 'ArrowUp') sendBtn('NAV UP');
    else if (e.key === 'ArrowDown') sendBtn('NAV DOWN');
    else if (e.key === 'ArrowLeft') sendBtn('NAV LEFT');
    else if (e.key === 'ArrowRight') sendBtn('NAV RIGHT');
    else if (e.key === 'Enter') sendBtn('NAV ENTER');
  });

  // Tab switching
  function switchTab(name, btn) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${name}`).classList.add('active');
  }

  function clearConsole() {
    document.getElementById('console').textContent = '';
  }

  // Periodic Polling Loop for Logs & Camera Telemetry
  async function pollStatus() {
    try {
      // 1. Status telemetry
      const res = await fetch('/api/status');
      const data = await res.json();

      // Power state
      const pwrText = document.getElementById('pwr-text');
      const pwrBtn = document.getElementById('pwr-btn');
      const ledDot = document.getElementById('led-dot');
      const recBtn = document.getElementById('rec-btn');

      if (data.power_state === 'STANDBY') {
        pwrText.textContent = 'STANDBY';
        pwrText.style.color = '#ffaa00';
        pwrBtn.textContent = 'POWER ON';
        pwrBtn.classList.add('standby');
        ledDot.className = 'led-dot';
      } else if (data.power_state === 'BOOTING') {
        const pct = Math.round(data.boot_progress * 100);
        pwrText.textContent = `BOOTING ${pct}%`;
        pwrText.style.color = '#ffaa00';
        pwrBtn.textContent = 'BOOTING...';
        pwrBtn.classList.remove('standby');
        ledDot.className = 'led-dot';
      } else {
        pwrText.textContent = 'ONLINE';
        pwrText.style.color = '#00ff77';
        pwrBtn.textContent = 'POWER OFF';
        pwrBtn.classList.remove('standby');
        ledDot.className = 'led-dot online';
      }

      // Camera Model Name update
      if (data.camera_name) {
        const hdrName = document.getElementById('hdr-model-name');
        if (hdrName) hdrName.textContent = data.camera_name;
        const subName = document.getElementById('hdr-sub-name');
        if (subName) subName.textContent = data.camera_name;
      }

      // Recording badge & button state
      if (data.is_recording) {
        recBtn.classList.add('recording');
        recBtn.innerHTML = '<span>■</span><span>STOP</span>';
        ledDot.className = 'led-dot recording';
      } else {
        recBtn.classList.remove('recording');
        recBtn.innerHTML = '<span>●</span><span>REC</span>';
      }

      // Instruction counter
      const instrM = (data.instruction_count / 1000000).toFixed(1);
      document.getElementById('instr-text').textContent = `${instrM}M INSTR`;

      // RCP Connected Clients
      if (document.getElementById('rcp-clients')) {
        const cCount = data.rcp_clients_count || 0;
        document.getElementById('rcp-clients').textContent = `${cCount} client${cCount === 1 ? '' : 's'}`;
      }

      // Render RCP table
      renderRcp(data.rcp);

      // Render Threads table
      renderThreads(data.threads);

      // Render Lens Telemetry
      if (data.lens) {
        renderLens(data.lens);
      }

      // Render Media Telemetry
      if (data.media) {
        renderMedia(data.media);
      }

      // Render Firmware Telemetry
      if (data.firmware) {
        updateFirmwareDisplay(data.firmware);
      }

      // Render Hardware Telemetry
      if (data.hardware) {
        renderHardware(data.hardware);
      }

      // Render Coprocessors Telemetry
      if (data.coprocessors) {
        renderCoprocessors(data.coprocessors);
      }

      // Render Accessories Telemetry
      if (data.accessories) {
        renderAccessories(data.accessories);
      }

      // Render Rig & Positions Telemetry
      if (data.rig) {
        renderRigSlots(data.rig);
      }

      // Render Multi-Camera Studio Telemetry
      if (data.multicam) {
        renderMulticam(data.multicam);
      }

      // Render Audio Server Telemetry
      if (data.coprocessors && data.coprocessors.audio_server) {
        updateAudioTelemetry(data.coprocessors.audio_server);
      }

    } catch (e) {}

    // 2. Serial logs
    try {
      const res = await fetch(`/api/logs?since=${lastLogIndex}`);
      const data = await res.json();
      if (data.logs && data.logs.length > 0) {
        const box = document.getElementById('console');
        box.textContent += data.logs.join('\n') + '\n';
        lastLogIndex = data.total;
        document.getElementById('log-count').textContent = `(${data.total} lines)`;
        if (document.getElementById('auto-scroll').checked) {
          box.scrollTop = box.scrollHeight;
        }
      }
    } catch (e) {}

    setTimeout(pollStatus, 250);
  }

  function renderRcp(rcp) {
    const tbody = document.getElementById('rcp-table-body');
    if (!tbody || !rcp) return;
    let html = '';
    for (const [key, val] of Object.entries(rcp)) {
      html += `<tr>
        <td style="color: #66b3ff;">${key}</td>
        <td style="color: #fff; font-weight: bold;">${val}</td>
        <td><button class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="promptSetRcp('${key}', '${val}')">Edit</button></td>
      </tr>`;
    }
    tbody.innerHTML = html;
  }

  function promptSetRcp(param, curr) {
    const newVal = prompt(`Enter new value for ${param}:`, curr);
    if (newVal !== null) {
      fetch('/api/rcp', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command: `SET ${param} ${newVal}`})
      });
    }
  }

  function renderThreads(threads) {
    const tbody = document.getElementById('threads-table-body');
    if (!tbody || !threads) return;
    let html = '';
    for (const t of threads) {
      const stateColor = (t.state === 'READY') ? '#00e676' : '#ffb300';
      html += `<tr>
        <td>${t.address}</td>
        <td style="color: #fff; font-weight: bold;">${t.name}</td>
        <td style="color: ${stateColor}; font-weight: bold;">${t.state}</td>
        <td>${t.priority}</td>
        <td>${t.sp}</td>
        <td style="color: #888;">${t.stack_range}</td>
      </tr>`;
    }
    tbody.innerHTML = html;
  }

  function renderHardware(hw) {
    if (!hw) return;

    // PMIC (TWL4030)
    if (hw.pmic) {
      const vEl = document.getElementById('hw-pmic-volts');
      const srcEl = document.getElementById('hw-pmic-source');
      const vdd1El = document.getElementById('hw-pmic-vdd1');
      const vdd2El = document.getElementById('hw-pmic-vdd2');
      const slider = document.getElementById('hw-pmic-slider');
      const sliderVal = document.getElementById('hw-pmic-slider-val');
      const toggleBtn = document.getElementById('hw-pmic-dc-toggle');

      const v = hw.pmic.battery_voltage_v;
      if (vEl) {
        vEl.textContent = `${v.toFixed(1)}V`;
        vEl.style.color = v >= 12.0 ? '#00e676' : '#ff4444';
      }
      if (srcEl) {
        srcEl.textContent = hw.pmic.dc_in_connected ? 'DC IN (15V)' : 'BATTERY (V-Mount)';
        srcEl.style.color = hw.pmic.dc_in_connected ? '#00e676' : '#ffb300';
      }
      if (vdd1El) vdd1El.textContent = `${hw.pmic.vdd1_v.toFixed(2)}V`;
      if (vdd2El) vdd2El.textContent = `${hw.pmic.vdd2_v.toFixed(2)}V`;
      if (slider && document.activeElement !== slider) {
        slider.value = v;
      }
      if (sliderVal && document.activeElement !== slider) {
        sliderVal.textContent = `${v.toFixed(1)}V`;
      }
      if (toggleBtn) {
        toggleBtn.textContent = hw.pmic.dc_in_connected ? 'Disconnect DC-IN (Run on Battery)' : 'Connect DC-IN (External 15V)';
      }
    }

    // Thermal (TMP411)
    if (hw.thermal) {
      const sTemp = document.getElementById('hw-temp-sensor');
      const bTemp = document.getElementById('hw-temp-brain');
      const calEl = document.getElementById('hw-temp-cal');
      const sSlider = document.getElementById('hw-temp-sensor-slider');
      const bSlider = document.getElementById('hw-temp-brain-slider');

      if (sTemp) sTemp.textContent = `${Math.round(hw.thermal.sensor_c)}°C`;
      if (bTemp) bTemp.textContent = `${Math.round(hw.thermal.brain_c)}°C`;
      if (sSlider && document.activeElement !== sSlider) sSlider.value = hw.thermal.sensor_c;
      if (bSlider && document.activeElement !== bSlider) bSlider.value = hw.thermal.brain_c;

      if (calEl) {
        if (hw.thermal.is_calibrated) {
          calEl.innerHTML = '<span style="color: #00e676;">● T/E Calibrated (Within ±2.5°C)</span>';
        } else {
          calEl.innerHTML = '<span style="color: #ffaa00;">▲ Temperature Drift (Black Shading Recommended)</span>';
        }
      }
    }

    // OLPF EEPROM
    if (hw.olpf) {
      const nameEl = document.getElementById('hw-olpf-name');
      const descEl = document.getElementById('hw-olpf-desc');
      const idEl = document.getElementById('hw-olpf-id');
      if (nameEl) nameEl.textContent = hw.olpf.type_name;
      if (descEl) descEl.textContent = hw.olpf.description;
      if (idEl) idEl.textContent = `(0x0${hw.olpf.type_id})`;
    }

    // GPMC
    if (hw.gpmc) {
      const gStat = document.getElementById('hw-gpmc-status');
      if (gStat) gStat.textContent = hw.gpmc.sysstatus === 1 ? 'READY (0x01)' : 'RESETTING';
    }
  }

  function setPmicVoltage(volts) {
    fetch('/api/hardware/power', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({voltage: parseFloat(volts)})
    });
  }

  function toggleDcIn() {
    const srcEl = document.getElementById('hw-pmic-source');
    const isDc = srcEl && srcEl.textContent.includes('DC IN');
    fetch('/api/hardware/power', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({dc_in: !isDc, voltage: !isDc ? 15.2 : 14.4})
    });
  }

  function setThermalTemps(s_c, b_c) {
    fetch('/api/hardware/thermal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sensor_c: parseFloat(s_c), brain_c: parseFloat(b_c)})
    });
  }

  function onSensorTempSlider(val) {
    const bSlider = document.getElementById('hw-temp-brain-slider');
    const b_c = bSlider ? bSlider.value : 63.0;
    document.getElementById('hw-temp-sensor').textContent = `${Math.round(val)}°C`;
    setThermalTemps(val, b_c);
  }

  function onBrainTempSlider(val) {
    const sSlider = document.getElementById('hw-temp-sensor-slider');
    const s_c = sSlider ? sSlider.value : 39.0;
    document.getElementById('hw-temp-brain').textContent = `${Math.round(val)}°C`;
    setThermalTemps(s_c, val);
  }

  function setOlpfProfile(typeStr) {
    fetch('/api/hardware/olpf', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({type: typeStr})
    });
  }

  function renderCoprocessors(c) {
    if (!c) return;
    if (c.iob0 && c.iob0.sata) {
      const s = c.iob0.sata;
      const sataEl = document.getElementById('hw-iob0-sata');
      if (sataEl) sataEl.textContent = `${s.speed_gbps.toFixed(1)} Gbps (${s.frames_written} frames, ${s.mb_transferred} MB)`;
    }
    if (c.iob0 && c.iob0.accelerometer) {
      const a = c.iob0.accelerometer;
      const tiltEl = document.getElementById('hw-iob0-tilt');
      if (tiltEl) {
        tiltEl.textContent = `Roll ${a.roll_deg >= 0 ? '+' : ''}${a.roll_deg.toFixed(1)}°, Pitch ${a.pitch_deg >= 0 ? '+' : ''}${a.pitch_deg.toFixed(1)}° ${a.is_level ? '[LEVEL]' : ''}`;
        tiltEl.style.color = a.is_level ? '#00e676' : '#ffaa00';
      }
    }
    if (c.iob1 && c.iob1.black_shading) {
      const bs = c.iob1.black_shading;
      const stEl = document.getElementById('hw-iob1-status');
      if (stEl) {
        stEl.textContent = bs.calibrated ? `CALIBRATED (${Math.round(bs.target_temp_c)}°C ${bs.target_exposure})` : 'CALIBRATING...';
        stEl.style.color = bs.calibrated ? '#00e676' : '#ffaa00';
      }
    }
    if (c.iob1 && c.iob1.defect_tables) {
      const dt = c.iob1.defect_tables;
      const defEl = document.getElementById('hw-iob1-defects');
      if (defEl) defEl.textContent = `${dt.factory_defects} Factory, ${dt.user_defects} User Masked (${dt.pixels_corrected} corrected)`;
    }
    if (c.isp1) {
      const ispRatio = document.getElementById('hw-isp-ratio');
      const ispFrm = document.getElementById('hw-isp-frames');
      if (ispRatio) ispRatio.textContent = c.isp1.compression_ratio || '8:1';
      if (ispFrm) ispFrm.textContent = (c.isp1.frames_compressed || 0).toLocaleString();
    }
    if (c.imaging_server) {
      const afEl = document.getElementById('hw-dsp-af');
      const fcEl = document.getElementById('hw-dsp-faces');
      if (afEl) afEl.textContent = `${c.imaging_server.autofocus_sharpness.toFixed(1)} / 100.0`;
      if (fcEl) fcEl.textContent = `${c.imaging_server.detected_faces ? c.imaging_server.detected_faces.length : 0} Detected (TI VLIB HW)`;
    }
    if (c.audio_server && c.audio_server.channels) {
      const ch1 = document.getElementById('hw-audio-ch1');
      const ch2 = document.getElementById('hw-audio-ch2');
      if (ch1 && c.audio_server.channels[0]) ch1.textContent = `${c.audio_server.channels[0].peak_dbfs.toFixed(1)} dBFS`;
      if (ch2 && c.audio_server.channels[1]) ch2.textContent = `${c.audio_server.channels[1].peak_dbfs.toFixed(1)} dBFS`;
    }
  }

  function renderAccessories(acc) {
    if (!acc || !acc.modules) return;
    const pwrEl = document.getElementById('hw-acc-power');
    if (pwrEl) pwrEl.textContent = `${acc.total_accessory_power_w}W`;
    const tbody = document.getElementById('hw-acc-table-body');
    if (!tbody) return;

    let html = '';
    for (const m of acc.modules) {
      const isBase = m.pin === '720-0033' || m.pin === '730-0024' || m.pin === '750-0075';
      const detachBtn = isBase ?
        '<span style="color: #666;">Primary</span>' :
        `<button class="cam-btn" style="padding: 2px 6px; font-size: 10px; background: #662222;" onclick="detachAccessoryModule('${m.pin}')">Eject</button>`;

      html += `<tr>
        <td style="color: #66b3ff;">${m.pin}</td>
        <td style="color: #fff; font-weight: bold;">${m.name}</td>
        <td style="color: #aaa;">${m.category}</td>
        <td>${m.serial}</td>
        <td style="color: #ffaa00;">${m.power_w}W</td>
        <td style="color: #888;">${m.ports.join(', ')}</td>
        <td>${detachBtn}</td>
      </tr>`;
    }
    tbody.innerHTML = html;
  }

  function runBlackShading() {
    fetch('/api/hardware/calibrate', {method: 'POST'})
      .then(r => r.json())
      .then(res => {
        alert(`Sensor Black Shading Complete!\n\nTarget Temp: ${res.target_temp_c}°C\nTarget Shutter: ${res.target_exposure}\nDefects Masked: ${res.defects_masked}\nMap File: ${res.cal_map}`);
        pollStatus();
      });
  }

  function triggerFaceDetection() {
    fetch('/api/hardware/face_detect', {method: 'POST'})
      .then(r => r.json())
      .then(res => {
        const count = res.faces ? res.faces.length : 0;
        alert(`TI VLIB Face Detection Executed on DSP!\n\nDetected ${count} face(s) in frame.\nConfidence: 94%\nAutofocus ROI tracking updated.`);
        pollStatus();
      });
  }

  function attachAccessoryModule() {
    const sel = document.getElementById('hw-acc-select');
    if (!sel) return;
    const pin = sel.value;
    fetch('/api/hardware/accessory/attach', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function detachAccessoryModule(pin) {
    fetch('/api/hardware/accessory/detach', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pin})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function renderRigSlots(rig) {
    const grid = document.getElementById('rig-slots-grid');
    if (!grid || !rig || !rig.slots) return;

    let html = '';
    const slotOrder = ['top_pogo', 'side_pogo', 'rear_module', 'lens_mount', 'media_bay'];
    for (const sid of slotOrder) {
      const slot = rig.slots[sid];
      if (!slot) continue;

      const isOcc = slot.is_occupied;
      const mod = slot.module;
      const borderCol = isOcc ? '#00e676' : '#444';
      const statusBadge = isOcc
        ? `<span style="background: #113311; color: #00e676; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: bold;">OCCUPIED (GPIO${slot.gpio_bank}:${slot.gpio_pin} HIGH)</span>`
        : `<span style="background: #222; color: #777; padding: 2px 6px; border-radius: 3px; font-size: 10px;">EMPTY (GPIO${slot.gpio_bank}:${slot.gpio_pin} LOW)</span>`;

      let modDetails = '<div style="color: #666; font-style: italic; margin-top: 6px;">No module connected</div>';
      let actions = '';

      if (isOcc && mod) {
        modDetails = `
          <div style="font-size: 13px; font-weight: bold; color: #fff; margin-top: 4px;">${mod.name}</div>
          <div style="font-size: 11px; color: #aaa; font-family: monospace;">PIN: ${mod.pin} &bull; ${mod.serial}</div>
          <div style="font-size: 11px; color: #ffaa00; margin-top: 2px;">Power Draw: ${mod.power_w}W &bull; Orientation: ${slot.orientation}</div>
        `;

        const canRotate = (sid === 'top_pogo' || sid === 'side_pogo');
        actions = `
          <div style="display: flex; gap: 6px; margin-top: 8px;">
            ${canRotate ? `<button class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="rotateSlotOrientation('${sid}', '${slot.orientation === 'normal' ? 'flipped' : 'normal'}')">Flip 180°</button>` : ''}
            <button class="cam-btn" style="padding: 2px 6px; font-size: 10px; background: #662222;" onclick="detachRigSlot('${sid}')">Detach</button>
          </div>
        `;
      }

      html += `
        <div style="background: #1e1e1e; border: 1px solid ${borderCol}; border-radius: 6px; padding: 10px; display: flex; flex-direction: column; justify-content: space-between;">
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
              <span style="font-weight: bold; font-size: 12px; color: #ddd;">${slot.name}</span>
              ${statusBadge}
            </div>
            ${modDetails}
          </div>
          ${actions}
        </div>
      `;
    }
    grid.innerHTML = html;
  }

  function applyRigPreset() {
    const sel = document.getElementById('rig-preset-select');
    if (!sel) return;
    fetch('/api/rig/preset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({preset: sel.value})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function attachRigModule() {
    const slotSel = document.getElementById('rig-slot-target-select');
    const modSel = document.getElementById('rig-module-catalog-select');
    if (!slotSel || !modSel) return;
    fetch('/api/hardware/accessory/attach', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slot: slotSel.value, pin: modSel.value})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function detachRigSlot(slotId) {
    fetch('/api/hardware/accessory/detach', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slot: slotId})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function toggleRigPosition() {
    const fromSel = document.getElementById('rig-toggle-from');
    const toSel = document.getElementById('rig-toggle-to');
    if (!fromSel || !toSel) return;
    fetch('/api/rig/toggle', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({from_slot: fromSel.value, to_slot: toSel.value})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function rotateSlotOrientation(slotId, orientation) {
    fetch('/api/rig/orientation', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slot: slotId, orientation})
    }).then(r => r.json()).then(() => pollStatus());
  }

  function sendRcp() {
    const input = document.getElementById('rcp-cmd-input');
    const cmd = input.value.trim();
    if (!cmd) return;
    fetch('/api/rcp', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({command: cmd})
    }).then(r => r.json()).then(res => {
      input.value = '';
    });
  }

  function saveSnapshot() {
    const name = document.getElementById('snap-name-input').value.trim() || undefined;
    fetch('/api/snapshot/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name})
    }).then(r => r.json()).then(res => {
      document.getElementById('snap-result').textContent = `Snapshot saved: ${res.file}`;
    });
  }

  function injectFault(type) {
    fetch('/api/fault', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({type})
    }).then(r => r.json()).then(res => {
      document.getElementById('fault-result').textContent = `Fault injected [${type}]: ${JSON.stringify(res.result)}`;
    });
  }

  function renderLens(lens) {
    if (!document.getElementById('lens-model-txt')) return;
    document.getElementById('lens-model-txt').textContent = lens.attached ? lens.lens.model : 'NO LENS DETECTED';
    document.getElementById('lens-mount-txt').textContent = lens.mount_type;
    document.getElementById('lens-brand-txt').textContent = lens.attached ? lens.lens.brand : 'None';
    document.getElementById('lens-serial-txt').textContent = lens.attached ? lens.lens.serial : 'N/A';
    document.getElementById('lens-range-txt').textContent = lens.attached ? lens.lens.focal_display : '--';
    document.getElementById('lens-focal-txt').textContent = lens.focal_display;
    document.getElementById('lens-iris-txt').textContent = lens.aperture_display;
    document.getElementById('lens-dist-txt').textContent = lens.focus_display;

    // Render aperture stops buttons if changed
    const stopsBox = document.getElementById('lens-stops-container');
    if (stopsBox && lens.available_stops && stopsBox.dataset.lastCount != lens.available_stops.length) {
      stopsBox.dataset.lastCount = lens.available_stops.length;
      let html = '';
      for (const s of lens.available_stops) {
        const isCur = Math.abs(s - lens.current_aperture) < 0.05;
        const bg = isCur ? '#b01010' : '#2a2a2a';
        const col = isCur ? '#fff' : '#ccc';
        html += `<button class="cam-btn" style="padding: 3px 8px; font-size: 11px; background: ${bg}; color: ${col};" onclick="setAperture(${s})">f/${s.toFixed(1)}</button>`;
      }
      stopsBox.innerHTML = html;
    }

    // Sync sliders if not focused
    const fSlider = document.getElementById('focal-slider');
    if (fSlider && document.activeElement !== fSlider && lens.attached) {
      fSlider.min = lens.lens.focal_min;
      fSlider.max = lens.lens.focal_max;
      fSlider.value = lens.current_focal_length;
      document.getElementById('focal-val-lbl').textContent = `${Math.round(lens.current_focal_length)}mm`;
    }
  }

  function renderMedia(media) {
    if (!document.getElementById('media-reel-txt')) return;
    document.getElementById('media-reel-txt').textContent = media.reel_id;
    document.getElementById('media-used-bar').style.width = `${100 - media.remaining_percent}%`;
    document.getElementById('media-used-txt').textContent = `Used: ${(media.used_mb / 1024).toFixed(1)} GB`;
    document.getElementById('media-free-txt').textContent = `Free: ${(media.free_mb / 1024).toFixed(1)} GB (${media.remaining_percent}%)`;
    
    const badge = document.getElementById('media-status-badge');
    const ejectBtn = document.getElementById('media-eject-btn');
    if (media.is_mounted) {
      badge.textContent = 'MOUNTED';
      badge.style.background = '#1b3d1b';
      badge.style.color = '#00ff66';
      ejectBtn.textContent = 'Eject Media';
    } else {
      badge.textContent = 'EJECTED';
      badge.style.background = '#4a1515';
      badge.style.color = '#ff6666';
      ejectBtn.textContent = 'Mount Media';
    }
  }

  function setAperture(val) {
    fetch('/api/lens/aperture', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({aperture: val})
    });
  }

  function stepAperture(step) {
    fetch('/api/lens/aperture', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({step})
    });
  }

  function onFocalSlider(val) {
    document.getElementById('focal-val-lbl').textContent = `${val}mm`;
    fetch('/api/lens/focal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({focal_length: parseFloat(val)})
    });
  }

  function onFocusSlider(val) {
    document.getElementById('focus-val-lbl').textContent = `${parseFloat(val).toFixed(1)}m`;
    fetch('/api/lens/focus', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({distance: parseFloat(val)})
    });
  }

  function triggerAf() {
    fetch('/api/lens/af', {method: 'POST'});
  }

  function onMountChange(mount) {
    fetch('/api/lens/mount', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mount})
    }).then(() => loadLensCatalog());
  }

  function attachSelectedLens() {
    const sel = document.getElementById('catalog-select');
    if (!sel || sel.selectedIndex < 0) return;
    const name = sel.value;
    fetch('/api/lens/attach', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name})
    });
  }

  let catalogLoaded = false;
  function loadLensCatalog() {
    fetch('/api/lens').then(r => r.json()).then(res => {
      const sel = document.getElementById('catalog-select');
      if (!sel || !res.catalog) return;
      sel.innerHTML = '';
      const currMount = document.getElementById('mount-select').value;
      const filtered = res.catalog.filter(l => l.mount === currMount || currMount === 'All');
      filtered.forEach((l, idx) => {
        const opt = document.createElement('option');
        opt.value = l.model;
        opt.textContent = `${l.model} (${l.brand})`;
        sel.appendChild(opt);
      });
      catalogLoaded = true;
    });
  }

  function formatMedia() {
    if (!confirm('Format RED MINI-MAG 512GB? All clips on the current reel will be cleared.')) return;
    fetch('/api/media/format', {method: 'POST'}).then(() => loadClips());
  }

  function toggleMediaMount() {
    const badge = document.getElementById('media-status-badge');
    const isMounted = badge.textContent === 'MOUNTED';
    fetch(isMounted ? '/api/media/eject' : '/api/media/mount', {method: 'POST'}).then(() => loadClips());
  }

  function loadClips() {
    fetch('/api/media/clips').then(r => r.json()).then(res => {
      const tbody = document.getElementById('clips-table-body');
      if (!tbody || !res.clips) return;
      if (res.clips.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="color: #666; text-align: center; padding: 20px;">No R3D clips recorded on current reel.</td></tr>';
        return;
      }
      let html = '';
      window._cachedClips = res.clips;
      res.clips.forEach((c, idx) => {
        html += `<tr>
          <td style="color: #fff; font-weight: bold;">${c.clip_name}.RDC</td>
          <td style="color: #ffaa00;">${c.size_mb} MB</td>
          <td style="color: #66b3ff;">REDCODE RAW 5K</td>
          <td><button class="cam-btn" style="padding: 2px 6px; font-size: 10px;" onclick="viewRmd(${idx})">View RMD</button></td>
        </tr>`;
      });
      tbody.innerHTML = html;
    });
  }

  function viewRmd(idx) {
    if (!window._cachedClips || !window._cachedClips[idx]) return;
    const clip = window._cachedClips[idx];
    document.getElementById('rmd-viewer-content').textContent = clip.rmd_metadata || 'No metadata available.';
    document.getElementById('rmd-viewer-container').style.display = 'block';
  }

  function closeRmdViewer() {
    document.getElementById('rmd-viewer-container').style.display = 'none';
  }

  // RED MINI-MAG Firmware Slot Drag & Drop and Upload
  const dropzone = document.getElementById('mag-dropzone');
  if (dropzone) {
    ['dragenter', 'dragover'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
    });
    ['dragleave', 'drop'].forEach(name => {
      dropzone.addEventListener(name, (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });
    dropzone.addEventListener('drop', (e) => {
      if (e.dataTransfer && e.dataTransfer.files.length > 0) {
        handleFwFileSelect(e.dataTransfer.files);
      }
    });
  }

  function handleFwFileSelect(files) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const reader = new FileReader();
    reader.onload = function(e) {
      const b64Data = e.target.result;
      fetch('/api/firmware/upload', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filename: file.name, data: b64Data})
      }).then(r => r.json()).then(res => {
        if (res.status === 'ok') {
          updateFirmwareDisplay({
            active_name: res.active_name,
            active_file: res.filename,
            active_size: res.size,
            is_custom: true,
            metadata: res.metadata
          });
          pollStatus();
        }
      });
    };
    reader.readAsDataURL(file);
  }

  async function bootCustomFirmware() {
    const btn = document.getElementById('btn-boot-custom');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'BOOTING INTO DDR...';
    }
    try {
      const res = await fetch('/api/firmware/boot', {method: 'POST'});
      const data = await res.json();
      if (data.status === 'ok') {
        const statusEl = document.getElementById('fw-active-status');
        if (statusEl) {
          statusEl.textContent = 'Active in DDR (0x80000000)';
          statusEl.style.color = '#00ff77';
        }
        await pollStatus();
        const canvas = document.getElementById('touchCanvas');
        if (canvas) canvas.src = '/api/stream?t=' + Date.now();
      } else if (data.status === 'crash') {
        alert(`CUSTOM FIRMWARE CRASHED / HALTED!\n\nFault Address: ${data.pc}\nError: ${data.error}\n\nRegister dump and disassembly logged to terminal.\nClick 'Revert Baseline' to restore confirmed stock firmware.`);
        const statusEl = document.getElementById('fw-active-status');
        if (statusEl) {
          statusEl.textContent = `CRASHED at ${data.pc}`;
          statusEl.style.color = '#ff4444';
        }
      } else {
        alert('Boot error: ' + (data.message || 'unknown error'));
      }
    } catch (e) {
      console.error('Custom boot request failed:', e);
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = '⚡ Flash & Boot Mod';
      }
    }
  }

  function revertFirmwareBaseline() {
    fetch('/api/firmware/reset', {method: 'POST'}).then(r => r.json()).then(res => {
      if (res.status === 'ok') {
        updateFirmwareDisplay({
          active_name: res.active_name,
          active_file: 'dsmc_program.mem',
          active_size: 21614152,
          is_custom: false
        });
        pollStatus();
        const canvas = document.getElementById('touchCanvas');
        if (canvas) canvas.src = '/api/stream?t=' + Date.now();
      }
    });
  }

  function updateFirmwareDisplay(fw) {
    if (!fw) return;
    const nameEl = document.getElementById('fw-active-name');
    const statusEl = document.getElementById('fw-active-status');
    const detailsEl = document.getElementById('fw-active-details');
    const ledEl = document.getElementById('mag-led');
    const ledText = document.getElementById('mag-led-text');
    const bootBtn = document.getElementById('btn-boot-custom');

    if (nameEl) nameEl.textContent = fw.active_name;
    if (statusEl) statusEl.textContent = fw.is_custom ? 'Custom Mod Staged' : 'Confirmed Working Baseline';
    if (detailsEl) {
      const mb = (fw.active_size / (1024 * 1024)).toFixed(1);
      detailsEl.textContent = `${fw.active_file} • ${mb} MB`;
    }
    if (bootBtn) {
      bootBtn.style.display = fw.is_custom ? 'block' : 'none';
    }
    if (ledEl) {
      if (fw.is_custom) {
        ledEl.className = 'mag-led custom';
        if (ledText) ledText.textContent = 'CUSTOM MOD LOADED';
        if (nameEl) nameEl.style.color = '#00b0ff';
      } else {
        ledEl.className = 'mag-led';
        if (ledText) ledText.textContent = 'MEDIA READY';
        if (nameEl) nameEl.style.color = '#00e676';
      }
    }
  }

  // DSMC2 Camera Selection Modal Functions
  async function openModelModal() {
    const modal = document.getElementById('camera-modal');
    if (modal) {
      modal.style.display = 'flex';
      await renderModelCards();
    }
  }

  function closeModelModal() {
    const modal = document.getElementById('camera-modal');
    if (modal) modal.style.display = 'none';
  }

  async function renderModelCards() {
    try {
      const res = await fetch('/api/camera/models');
      const data = await res.json();
      const container = document.getElementById('camera-model-grid');
      if (!container) return;
      container.innerHTML = '';

      data.models.forEach(m => {
        const card = document.createElement('div');
        card.className = `cam-card ${m.is_active ? 'active' : ''}`;
        card.onclick = () => selectCameraModel(m.CAMERA_TYPE);
        card.innerHTML = `
          <div>
            <div class="cam-card-top">
              <span class="cam-card-name">${m.CAMERA_NAME}</span>
              <span class="cam-card-id">TAG ${m.CAMERA_TYPE}</span>
            </div>
            <div class="cam-card-sensor">${m.SENSOR_NAME}</div>
            <div class="cam-card-desc" style="margin-top: 8px;">${m.DESCRIPTION}</div>
          </div>
          <div>
            <div class="cam-card-specs" style="margin-bottom: 8px;">
              <span class="spec-pill">${m.SENSOR_WIDTH}x${m.SENSOR_HEIGHT}</span>
              <span class="spec-pill">Max ${m.MAX_FPS} FPS</span>
              <span class="spec-pill">${m.DEFAULT_FORMAT}</span>
            </div>
            <div class="cam-card-btn">${m.is_active ? '✓ ACTIVE CAMERA' : 'SELECT & BOOT'}</div>
          </div>
        `;
        container.appendChild(card);
      });
    } catch (e) {
      console.error('Error rendering model cards:', e);
    }
  }

  async function selectCameraModel(modelId) {
    const cards = document.querySelectorAll('.cam-card');
    cards.forEach(c => c.style.pointerEvents = 'none');
    const note = document.querySelector('.modal-foot-note');
    if (note) note.innerHTML = '<span style="color: #00ff77; font-weight: bold;">Booting selected DSMC2 personality & firmware into DDR...</span>';

    try {
      const res = await fetch('/api/camera/select', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model: modelId})
      });
      const data = await res.json();
      if (data.status === 'ok') {
        closeModelModal();
        await pollStatus();
        const canvas = document.getElementById('touchCanvas');
        if (canvas) {
          canvas.src = '/api/stream?t=' + Date.now();
        }
      } else {
        alert('Failed to boot camera model: ' + (data.message || 'unknown error'));
      }
    } catch (e) {
      console.error('Error selecting camera model:', e);
    } finally {
      const cards = document.querySelectorAll('.cam-card');
      cards.forEach(c => c.style.pointerEvents = 'auto');
      if (note) note.textContent = 'Firmware assets extracted from stock RED Combo Build v7.4.1.';
    }
  }

  // Load initial lens catalog and media clips on startup
  loadLensCatalog();
  loadClips();
  setInterval(loadClips, 2000);

  // Prompt camera chooser on launch before user interaction
  setTimeout(openModelModal, 250);

  // --- Broadcast HDMI Output & Clean Monitor ---
  let hdmiTimer = null;
  function openHdmiModal() {
    const modal = document.getElementById('hdmi-modal');
    if (modal) {
      modal.style.display = 'flex';
      refreshHdmiFrame();
      if (!hdmiTimer) hdmiTimer = setInterval(refreshHdmiFrame, 350);
    }
  }

  function closeHdmiModal() {
    const modal = document.getElementById('hdmi-modal');
    if (modal) modal.style.display = 'none';
    if (hdmiTimer) { clearInterval(hdmiTimer); hdmiTimer = null; }
  }

  function refreshHdmiFrame() {
    const img = document.getElementById('hdmi-monitor-img');
    if (img) img.src = '/api/video/hdmi?t=' + Date.now();
  }

  async function setHdmiMode(mode) {
    try {
      const res = await fetch('/api/video/hdmi/mode', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: mode})
      });
      const data = await res.json();
      ['clean', 'tally', 'guides'].forEach(m => {
        const btn = document.getElementById('hdmi-btn-' + m);
        if (btn) btn.style.background = '#222';
      });
      const activeBtn = document.getElementById('hdmi-btn-' + (mode.toLowerCase().includes('clean') ? 'clean' : mode.toLowerCase().includes('tally') ? 'tally' : 'guides'));
      if (activeBtn) activeBtn.style.background = '#0077ff';
      refreshHdmiFrame();
    } catch (e) {}
  }

  // --- Web Audio API Headphone Stream & Oscilloscope ---
  let audioCtx = null;
  let isAudioMonitoring = false;
  let audioTimer = null;
  let testToneActive = false;

  async function toggleAudioMonitor() {
    const btn = document.getElementById('audio-mon-btn');
    if (!isAudioMonitoring) {
      try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        audioCtx = new AudioContextClass();
        if (audioCtx.state === 'suspended') {
          await audioCtx.resume();
        }
        isAudioMonitoring = true;
        btn.textContent = '🎧 Headphone: ON (48kHz)';
        btn.style.background = '#1a3a20';
        btn.style.color = '#00e676';
        streamAudioLoop();
      } catch (e) {
        console.error('Failed to start Web Audio:', e);
      }
    } else {
      isAudioMonitoring = false;
      if (audioTimer) { clearTimeout(audioTimer); audioTimer = null; }
      if (audioCtx) { try { audioCtx.close(); } catch(e){} audioCtx = null; }
      btn.textContent = '🎧 Headphone Monitor: OFF';
      btn.style.background = '#222';
      btn.style.color = '#fff';
    }
  }

  async function streamAudioLoop() {
    if (!isAudioMonitoring || !audioCtx) return;
    try {
      const resp = await fetch('/api/audio/wav?t=' + Date.now());
      if (resp.ok) {
        const arrayBuf = await resp.arrayBuffer();
        audioCtx.decodeAudioData(arrayBuf, (audioBuf) => {
          if (!isAudioMonitoring || !audioCtx) return;
          const source = audioCtx.createBufferSource();
          source.buffer = audioBuf;
          source.connect(audioCtx.destination);
          source.start();
          drawAudioWaveform(audioBuf);
        }, () => {});
      }
    } catch (e) {}
    if (isAudioMonitoring) {
      audioTimer = setTimeout(streamAudioLoop, 450);
    }
  }

  function drawAudioWaveform(audioBuf) {
    const canvas = document.getElementById('audio-scope-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    ctx.fillStyle = '#080808';
    ctx.fillRect(0, 0, width, height);

    const data = audioBuf.getChannelData(0);
    const step = Math.ceil(data.length / width);
    const amp = height / 2;

    ctx.strokeStyle = '#00e676';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(0, amp);

    for (let i = 0; i < width; i++) {
      let min = 1.0;
      let max = -1.0;
      for (let j = 0; j < step; j++) {
        const datum = data[(i * step) + j];
        if (datum < min) min = datum;
        if (datum > max) max = datum;
      }
      ctx.lineTo(i, (1 + min) * amp);
      ctx.lineTo(i, (1 + max) * amp);
    }
    ctx.stroke();
  }

  async function toggleTestTone() {
    testToneActive = !testToneActive;
    const btn = document.getElementById('hw-audio-tone-btn');
    try {
      await fetch('/api/audio/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({test_tone: testToneActive, freq_hz: 1000})
      });
      if (btn) {
        btn.textContent = testToneActive ? 'Tone: 1kHz ACTIVE' : '1kHz Cal Tone';
        btn.style.background = testToneActive ? '#ffaa00' : '#222';
        btn.style.color = testToneActive ? '#000' : '#fff';
      }
    } catch (e) {}
  }

  function updateAudioTelemetry(aud) {
    if (!aud) return;
    if (aud.channels && aud.channels.length >= 2) {
      const ch1 = document.getElementById('hw-audio-ch1');
      const ch2 = document.getElementById('hw-audio-ch2');
      if (ch1) {
        ch1.textContent = `${aud.channels[0].peak_dbfs.toFixed(1)} dBFS`;
        ch1.style.color = aud.channels[0].clipping ? '#ff3333' : '#00e676';
      }
      if (ch2) {
        ch2.textContent = `${aud.channels[1].peak_dbfs.toFixed(1)} dBFS`;
        ch2.style.color = aud.channels[1].clipping ? '#ff3333' : '#00e676';
      }
    }
    const hp = document.getElementById('hw-audio-hp');
    if (hp) hp.textContent = `${aud.headphone_volume_pct}%`;
  }

  // --- RCP Automation Sequences & Multi-Cam Array ---
  async function runRcpPreset() {
    const sel = document.getElementById('rcp-preset-select');
    const badge = document.getElementById('script-status-badge');
    const summary = document.getElementById('script-summary-text');
    const traceBox = document.getElementById('script-trace-box');
    const traceContent = document.getElementById('script-trace-content');

    if (!sel) return;
    const presetKey = sel.value;
    badge.textContent = 'RUNNING';
    badge.style.background = '#aa5500';
    badge.style.color = '#fff';
    summary.textContent = `Executing sequence: ${sel.options[sel.selectedIndex].text}...`;

    try {
      const res = await fetch('/api/rcp/automation/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({preset: presetKey})
      });
      const data = await res.json();

      badge.textContent = data.status;
      badge.style.background = (data.status === 'PASSED') ? '#1a3320' : '#551111';
      badge.style.color = (data.status === 'PASSED') ? '#00e676' : '#ff4444';
      summary.textContent = `${data.script_name}: ${data.total_steps} steps in ${data.duration_ms}ms (Passed: ${data.passed_assertions}, Failed: ${data.failed_assertions})`;

      if (data.trace && data.trace.length > 0) {
        traceBox.style.display = 'block';
        let traceHtml = '';
        data.trace.forEach(t => {
          const col = (t.status === 'PASSED' || t.status === 'OK') ? '#00e676' : '#ff4444';
          traceHtml += `<div>[${t.step}] <span style="color:#aaa;">${t.action} ${t.param || ''}</span> -> <strong style="color:${col};">${t.status}</strong> (${t.elapsed_ms}ms): ${t.message}</div>`;
        });
        traceContent.innerHTML = traceHtml;
      }
      await pollStatus();
    } catch (e) {
      badge.textContent = 'ERROR';
      badge.style.background = '#551111';
      summary.textContent = `Execution failed: ${e.message}`;
    }
  }

  function renderMulticam(mc) {
    if (!mc || !mc.nodes) return;
    mc.nodes.forEach(n => {
      let el = null;
      if (n.id === 'A-CAM') el = document.getElementById('multicam-acam-state');
      else if (n.id === 'B-CAM') el = document.getElementById('multicam-bcam-state');
      else if (n.id === 'C-CAM') el = document.getElementById('multicam-ccam-state');
      if (el) {
        const recStr = (n.record_state === 2) ? '● RECORDING' : 'Idle Standby';
        el.textContent = `${recStr} (${n.timecode || '01:00:00:00'})`;
        el.style.color = (n.record_state === 2) ? '#ff3333' : '#aaa';
      }
    });
    const gBadge = document.getElementById('genlock-badge');
    if (gBadge) {
      gBadge.textContent = `GENLOCK: ${mc.genlock}`;
      gBadge.style.color = (mc.genlock === 'LOCKED') ? '#00e676' : '#ffaa00';
    }
  }

  async function syncMulticamGenlock() {
    try {
      await fetch('/api/rcp/multicam/sync', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({timecode: '01:00:00:00'})
      });
      await pollStatus();
    } catch (e) {}
  }

  async function triggerMulticamRecord() {
    try {
      await fetch('/api/rcp/multicam/record', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'START'})
      });
      await pollStatus();
    } catch (e) {}
  }

  // Start telemetry loop
  pollStatus();
</script>

<!-- DSMC2 Camera Selection Modal -->
<div id="camera-modal" class="modal-backdrop" style="display: none;">
  <div class="modal-box">
    <div class="modal-top">
      <div style="display: flex; align-items: center;">
        <span class="dsmc2-badge">DSMC2 BRAIN</span>
        <h2 style="font-size: 17px; letter-spacing: 1.5px; margin: 0; color: #fff;">SELECT CAMERA SYSTEM</h2>
      </div>
      <button class="modal-x-btn" onclick="closeModelModal()">✕</button>
    </div>
    <div class="modal-intro">
      Choose a genuine RED DSMC2 hardware personality and firmware package to boot into the virtual camera studio.
    </div>
    <div class="camera-model-grid" id="camera-model-grid">
      <!-- Populated via renderModelCards() -->
    </div>
    <div class="modal-bottom">
      <div class="modal-foot-note">Firmware assets extracted from stock RED Combo Build v7.4.1.</div>
      <button class="cam-btn" onclick="closeModelModal()" style="padding: 7px 16px;">Continue with Current</button>
    </div>
  </div>
</div>

<!-- Broadcast HDMI Output Monitor Modal -->
<div id="hdmi-modal" class="modal-backdrop" style="display: none;">
  <div class="modal-box" style="max-width: 860px; width: 90vw;">
    <div class="modal-top">
      <div style="display: flex; align-items: center; gap: 8px;">
        <span class="dsmc2-badge" style="background: #0077ff;">HDMI OUT</span>
        <h2 style="font-size: 16px; letter-spacing: 1px; margin: 0; color: #fff;">EXTERNAL BROADCAST MONITOR (1080p60)</h2>
      </div>
      <button class="modal-x-btn" onclick="closeHdmiModal()">✕</button>
    </div>
    <div style="padding: 12px; background: #000; display: flex; justify-content: center; align-items: center;">
      <img id="hdmi-monitor-img" src="/api/video/hdmi" alt="HDMI Output" style="width: 100%; aspect-ratio: 16/9; object-fit: contain; border-radius: 4px;" />
    </div>
    <div class="modal-bottom">
      <div style="display: flex; gap: 8px; align-items: center;">
        <span style="font-size: 11px; color: #888;">Mode:</span>
        <button id="hdmi-btn-clean" class="cam-btn" style="padding: 4px 8px; font-size: 11px; background: #0077ff;" onclick="setHdmiMode('CLEAN')">Clean Feed</button>
        <button id="hdmi-btn-tally" class="cam-btn" style="padding: 4px 8px; font-size: 11px; background: #222;" onclick="setHdmiMode('BROADCAST_TALLY')">Broadcast Tally + TC</button>
        <button id="hdmi-btn-guides" class="cam-btn" style="padding: 4px 8px; font-size: 11px; background: #222;" onclick="setHdmiMode('FRAME_GUIDES')">2.39:1 Frame Guides</button>
      </div>
      <button class="cam-btn" onclick="refreshHdmiFrame()" style="padding: 4px 10px; font-size: 11px;">Refresh Frame</button>
    </div>
  </div>
</div>
</body>
</html>
"""


def find_free_port(start_port: int = 8765, max_attempts: int = 20) -> int:
    """Find a free TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


def launch_web_studio(workspace_root: str, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True):
    """Launch the Web-Based RED DSMC2 Virtual Camera Studio."""
    free_port = find_free_port(port)
    studio = WebStudio(workspace_root, host=host, port=free_port)

    # Start camera worker
    studio.start_camera()

    # Create multi-threaded HTTP server
    handler_class = create_handler(studio)
    studio.http_server = ThreadedHTTPServer((host, free_port), handler_class)

    url = f"http://{host}:{free_port}/"
    print("\n" + "=" * 70, flush=True)
    print(f"  DSMC2 VIRTUAL BRAIN ONLINE", flush=True)
    print(f"  URL: {url}", flush=True)
    print(f"  Platform: Standard Library Web Studio (Port {free_port})", flush=True)
    print(f"  Firmware: RED SCARLET-W 5K (v7.4.1)", flush=True)
    print(f"  Ready for interactive touchscreen, physical buttons & RCP control.", flush=True)
    print("=" * 70 + "\n", flush=True)

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        studio.http_server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping DSMC2 Virtual Brain Web Studio...", flush=True)
    finally:
        studio.stop()


if __name__ == "__main__":
    root_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    launch_web_studio(root_dir)
