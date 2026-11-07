"""
Virtual Camera Screen for RED DSMC2.
Renders authentic 1024x576 LCD panel frames, splash screen, and handles maXTouch touch events.
"""

import os
import zlib
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw, ImageFont
from typing import Optional, Tuple
from emulator.ui.redui import RedUiEngine


class CameraScreen(ttk.Frame):
    """
    Virtual LCD Touchscreen for the DSMC2 Camera.
    Native resolution: 1024 x 576 (16:9).
    Scales to canvas size while preserving touch coordinate mapping.
    """

    NATIVE_WIDTH = 1024
    NATIVE_HEIGHT = 576

    def __init__(self, parent, camera, scale: float = 0.75, **kwargs):
        super().__init__(parent, **kwargs)
        self.camera = camera
        self.scale = scale
        self.display_width = int(self.NATIVE_WIDTH * self.scale)
        self.display_height = int(self.NATIVE_HEIGHT * self.scale)

        self.splash_image: Optional[Image.Image] = self._load_splash_screen()
        self.sensor_feed_image: Optional[Image.Image] = self._load_sensor_feed_image()
        self.current_tk_image: Optional[ImageTk.PhotoImage] = None

        # Build UI
        self._build_widgets()

        # Touch and frame state
        self.is_touch_down = False
        self.canvas_image_id: Optional[int] = None
        self._zero_fb_buf = b"\x00" * (self.NATIVE_WIDTH * self.NATIVE_HEIGHT * 4)

        # Interactive RedUi Engine
        self.redui = RedUiEngine(self.camera)

    def _load_sensor_feed_image(self) -> Optional[Image.Image]:
        """Load authentic cinema sensor background in place of the gaussian swirl."""
        sensor_path = os.path.join(self.camera.workspace_root, "res", "sensor_feed_cinema.jpg")
        if not os.path.exists(sensor_path):
            return None
        try:
            im = Image.open(sensor_path)
            if im.size != (self.NATIVE_WIDTH, self.NATIVE_HEIGHT):
                im = im.resize((self.NATIVE_WIDTH, self.NATIVE_HEIGHT), Image.Resampling.LANCZOS)
            return im.convert("RGB")
        except Exception as e:
            print(f"[Screen] Failed to load cinema sensor feed: {e}")
            return None

    def _load_splash_screen(self) -> Optional[Image.Image]:
        """Load and decompress authentic RED splash screen if present."""
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
                img = Image.frombytes("RGB", (1024, 576), pixels)
                return img
        except Exception as e:
            print(f"[Screen] Failed to load splash screen: {e}")
            return None

    def _build_widgets(self):
        # Frame outer border (styling like RED Touch 7.0 aluminum bezel)
        self.bezel = tk.Frame(
            self,
            bg="#181818",
            padx=10,
            pady=10,
            highlightthickness=2,
            highlightbackground="#333333"
        )
        self.bezel.pack(padx=5, pady=5)

        # Header label: "RED TOUCH 7.0 - 1024x576"
        self.header = tk.Label(
            self.bezel,
            text="RED TOUCH 7.0 LCD | 1024x576 NATIVE",
            bg="#181818",
            fg="#888888",
            font=("Consolas", 9, "bold")
        )
        self.header.pack(anchor="w", pady=(0, 4))

        # Canvas for the LCD panel
        self.canvas = tk.Canvas(
            self.bezel,
            width=self.display_width,
            height=self.display_height,
            bg="#000000",
            highlightthickness=0,
            cursor="hand2"
        )
        self.canvas.pack()

        # Bind mouse touch events
        self.canvas.bind("<ButtonPress-1>", self._on_touch_down)
        self.canvas.bind("<B1-Motion>", self._on_touch_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_touch_up)
        self.canvas.bind("<Leave>", self._on_leave)

    def _map_coords(self, event) -> Tuple[int, int]:
        """Map canvas mouse coordinates back to native 1024x576 screen space."""
        x = int(event.x / self.scale)
        y = int(event.y / self.scale)
        x = max(0, min(self.NATIVE_WIDTH - 1, x))
        y = max(0, min(self.NATIVE_HEIGHT - 1, y))
        return x, y

    def _on_leave(self, event):
        """Cleanly release touch if mouse dragged outside the virtual screen."""
        if self.is_touch_down:
            self.is_touch_down = False
            if self.redui.last_touch_pos:
                x, y = self.redui.last_touch_pos
                self._dispatch_touch(x, y, pressed=False, is_release=True)
                self.refresh()

    def _on_touch_down(self, event):
        x, y = self._map_coords(event)
        self.is_touch_down = True
        self._dispatch_touch(x, y, pressed=True, is_release=False)
        self.refresh()

    def _on_touch_move(self, event):
        if self.is_touch_down:
            x, y = self._map_coords(event)
            # Update position for reticle overlay without flooding redraws
            self.redui.last_touch_pos = (x, y)

    def _on_touch_up(self, event):
        x, y = self._map_coords(event)
        self.is_touch_down = False
        self._dispatch_touch(x, y, pressed=False, is_release=True)
        self.refresh()

    def _dispatch_touch(self, x: int, y: int, pressed: bool, is_release: bool = False):
        self.camera.touch(x, y, pressed=pressed)
        self.redui.handle_touch(x, y, pressed=pressed)
        if pressed:
            self.camera.log_system(f"[TOUCH] Touch down at ({x}, {y}) -> maXTouch (0x4B)")
        elif is_release:
            self.camera.log_system(f"[TOUCH] Touch release at ({x}, {y}) -> maXTouch (0x4B)")

    def toggle_menu(self):
        self.redui.toggle_menu()
        self.refresh()

    def toggle_magnify(self):
        self.redui.toggle_magnify()
        self.refresh()

    def toggle_false_color(self):
        self.redui.toggle_false_color()
        self.refresh()

    def toggle_zebras(self):
        self.redui.toggle_zebras()
        self.refresh()

    def handle_button(self, button_name: str):
        self.redui.handle_button_press(button_name)
        self.refresh()

    def compose_frame(self) -> Image.Image:
        """Compose raw LCD frame with overlays and scale to display size."""
        state = self.camera.power_state

        if state == self.camera.POWER_STANDBY:
            img = self._render_standby_screen()
        elif state == self.camera.POWER_BOOTING:
            img = self._render_booting_screen()
        else: # POWER_ON
            fb_bytes = self.camera.get_frame()
            is_blank = (fb_bytes == self._zero_fb_buf)

            if not is_blank and len(fb_bytes) >= self.NATIVE_WIDTH * self.NATIVE_HEIGHT * 4:
                # 32bpp BGRA/RGBA from DISPC
                img = Image.frombytes("RGBA", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), fb_bytes)
            elif self.sensor_feed_image:
                img = self.sensor_feed_image.copy()
            elif self.splash_image:
                img = self.splash_image.copy()
            else:
                img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))

            # Draw RED authentic HUD overlay (driven directly from camera state & RCP)
            try:
                self._draw_hud(img)
            except Exception:
                pass

            # Render RedUi interactive layer (Menu, Quick Dialogs, Exposure Tools, Touch Reticle)
            try:
                img = self.redui.render(img)
            except Exception:
                pass

        # Scale to display size
        if self.scale != 1.0:
            img = img.resize((self.display_width, self.display_height), Image.Resampling.BILINEAR)

        return img

    def blit_image(self, img: Image.Image):
        """Update canvas display with new PhotoImage on Tk thread."""
        self.current_tk_image = ImageTk.PhotoImage(img)
        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.current_tk_image)
        else:
            self.canvas.itemconfig(self.canvas_image_id, image=self.current_tk_image)

    def refresh(self):
        """Synchronously compose and redraw canvas."""
        img = self.compose_frame()
        self.blit_image(img)

    def _render_standby_screen(self) -> Image.Image:
        """Render standby / soft-off screen with guidance."""
        img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (8, 8, 8))
        draw = ImageDraw.Draw(img)

        # Ambient border
        draw.rectangle([(10, 10), (1014, 566)], outline=(25, 25, 25), width=2)

        # Center Standby Card
        cx, cy = 512, 288
        draw.rectangle([(cx - 260, cy - 90), (cx + 260, cy + 90)], fill=(16, 16, 16), outline=(40, 40, 40), width=2)

        model_name = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K")
        draw.text((cx - 150, cy - 70), f"RED DIGITAL CINEMA  |  {model_name}", fill=(200, 200, 200))
        draw.text((cx - 100, cy - 35), "[ SYSTEM IN STANDBY ]", fill=(255, 170, 0))
        draw.text((cx - 120, cy + 0), "DC IN 14.8V  •  Hardware Ready", fill=(100, 100, 100))
        draw.text((cx - 165, cy + 40), ">>> CLICK [POWER ON] BUTTON BELOW TO BOOT <<<", fill=(0, 255, 120))
        return img

    def _render_booting_screen(self) -> Image.Image:
        """Render splash screen with animated boot progress bar."""
        if self.splash_image:
            img = self.splash_image.copy()
        else:
            img = Image.new("RGB", (self.NATIVE_WIDTH, self.NATIVE_HEIGHT), (15, 15, 15))
        draw = ImageDraw.Draw(img)

        # Progress Box
        cx, cy = 512, 288
        draw.rectangle([(cx - 240, cy - 50), (cx + 240, cy + 50)], fill=(0, 0, 0, 210), outline=(0, 200, 100), width=2)

        pct = int(self.camera.boot_progress * 100)
        draw.text((cx - 120, cy - 35), f"BOOTING RED DSMC2... {pct}%", fill=(255, 255, 255))

        # Bar outline
        bar_x1, bar_y1 = cx - 200, cy - 5
        bar_x2, bar_y2 = cx + 200, cy + 15
        draw.rectangle([(bar_x1, bar_y1), (bar_x2, bar_y2)], outline=(80, 80, 80), width=1)

        # Bar fill
        fill_width = int(400 * max(0.0, min(1.0, self.camera.boot_progress)))
        if fill_width > 0:
            draw.rectangle([(bar_x1 + 1, bar_y1 + 1), (bar_x1 + fill_width, bar_y2 - 1)], fill=(0, 220, 100))

        draw.text((cx - 140, cy + 25), "Bringing up Cortex-A8, ThreadX & OMAP3...", fill=(160, 160, 160))
        return img

    def _draw_hud(self, img: Image.Image):
        """Render genuine DSMC2 HUD indicators driven by camera state."""
        draw = ImageDraw.Draw(img)

        # Read camera parameters from RCP / camera state
        rcp = self.camera.rcp
        fps = rcp.state.get(rcp.PARAM_FPS, "24.00")
        shutter = rcp.state.get(rcp.PARAM_SHUTTER, "1/48")
        iso = rcp.state.get(rcp.PARAM_ISO, "800")
        format_name = rcp.state.get(rcp.PARAM_FORMAT, "5K 16:9")
        record_state = rcp.state.get(rcp.PARAM_RECORD_STATE, "0")
        is_recording = (record_state == "2")

        # Top Bar Background
        draw.rectangle([(0, 0), (1024, 40)], fill=(0, 0, 0, 200))
        draw.line([(0, 40), (1024, 40)], fill=(40, 40, 40), width=1)

        # REC / STBY Touch Button
        if is_recording:
            draw.rectangle([(12, 6), (82, 34)], fill=(200, 20, 20), outline=(255, 60, 60), width=1)
            draw.text((22, 11), "• REC", fill=(255, 255, 255))
        else:
            draw.rectangle([(12, 6), (82, 34)], fill=(32, 32, 32), outline=(70, 70, 70), width=1)
            draw.text((24, 11), "STBY", fill=(180, 180, 180))

        # Camera Model / Menu Button (Tapping opens DSMC2 Menu)
        menu_hl = (220, 20, 20) if self.redui.is_menu_open else (60, 60, 60)
        draw.rectangle([(88, 6), (295, 34)], fill=(28, 28, 28), outline=menu_hl, width=1)
        model_name = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K")
        draw.text((96, 11), f"RED {model_name} [MENU]", fill=(220, 220, 220))

        # FPS Touch Button
        fps_hl = (220, 20, 20) if self.redui.active_dialog == "FPS" else (60, 60, 60)
        draw.rectangle([(310, 6), (430, 34)], fill=(28, 28, 28), outline=fps_hl, width=1)
        draw.text((320, 11), f"FPS: {fps}", fill=(255, 255, 255))

        # SHUTTER Touch Button
        shutter_hl = (220, 20, 20) if self.redui.active_dialog == "SHUTTER" else (60, 60, 60)
        draw.rectangle([(440, 6), (600, 34)], fill=(28, 28, 28), outline=shutter_hl, width=1)
        draw.text((450, 11), f"SHUTTER: {shutter}", fill=(255, 255, 255))

        # ISO Touch Button
        iso_hl = (220, 20, 20) if self.redui.active_dialog == "ISO" else (60, 60, 60)
        draw.rectangle([(610, 6), (730, 34)], fill=(28, 28, 28), outline=iso_hl, width=1)
        draw.text((620, 11), f"ISO: {iso}", fill=(255, 255, 255))

        # FORMAT Touch Button
        fmt_hl = (220, 20, 20) if self.redui.active_dialog == "FORMAT" else (60, 60, 60)
        draw.rectangle([(740, 6), (910, 34)], fill=(28, 28, 28), outline=fmt_hl, width=1)
        draw.text((750, 11), f"FORMAT: {format_name}", fill=(255, 255, 255))

        # DC / Battery indicator
        draw.rectangle([(920, 6), (1014, 34)], fill=(20, 35, 20), outline=(0, 180, 60), width=1)
        draw.text((930, 11), "DC 14.8V", fill=(80, 240, 80))

        # Bottom Bar Background
        draw.rectangle([(0, 540), (1024, 576)], fill=(0, 0, 0, 200))
        draw.line([(0, 540), (1024, 540)], fill=(40, 40, 40), width=1)

        # Timecode Touch Button
        timecode = "01:00:00:00" if not is_recording else f"01:00:{int(self.camera.instruction_count/1000000)%60:02d}:12"
        tc_color = (255, 50, 50) if is_recording else (200, 200, 200)
        draw.rectangle([(12, 544), (240, 572)], fill=(28, 28, 28), outline=(60, 60, 60), width=1)
        draw.text((20, 550), f"TC: {timecode}", fill=tc_color)

        # Media status Touch Button
        media_hl = (220, 20, 20) if self.redui.active_dialog == "MEDIA" else (60, 60, 60)
        draw.rectangle([(250, 544), (660, 572)], fill=(28, 28, 28), outline=media_hl, width=1)
        draw.text((260, 550), "MEDIA: RED MINI-MAG 512GB [78% FREE]", fill=(200, 200, 200))

        # Audio meters Touch Button
        audio_hl = (220, 20, 20) if self.redui.active_dialog == "AUDIO" else (60, 60, 60)
        draw.rectangle([(670, 544), (860, 572)], fill=(28, 28, 28), outline=audio_hl, width=1)
        draw.text((680, 550), "AUDIO: CH1/2 -18dB", fill=(120, 200, 120))

        # Instruction counter
        instr_m = self.camera.instruction_count / 1_000_000
        draw.rectangle([(870, 544), (1014, 572)], fill=(22, 22, 22), outline=(50, 50, 50), width=1)
        draw.text((880, 550), f"INSTR: {instr_m:.1f}M", fill=(140, 140, 140))
