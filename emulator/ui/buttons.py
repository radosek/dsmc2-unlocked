"""
Physical tactile button controls for RED DSMC2 Virtual Camera.
Includes Record, Power, Menu, 1:1 Magnify, Nav D-Pad, and User Keys.
"""

import tkinter as tk
from tkinter import ttk
from emulator.rcp.protocol import RcpProtocol


class PhysicalButtons(ttk.Frame):
    """
    Physical-style camera buttons modeled on the DSMC2 Sidekick / Top Handle / Brain body.
    """

    def __init__(self, parent, camera, on_action_callback=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.camera = camera
        self.on_action = on_action_callback
        self._last_state = None
        self._last_pct = None
        self._last_rec = None

        self._build_widgets()

    def _build_widgets(self):
        panel = tk.Frame(self, bg="#202020", padx=10, pady=8, relief=tk.RAISED, bd=2)
        panel.pack(fill=tk.X, expand=True, padx=5, pady=5)

        # Left Section: Primary Controls (REC & POWER)
        left_box = tk.Frame(panel, bg="#202020")
        left_box.pack(side=tk.LEFT, padx=10)

        # Big Distinctive RED Record Button
        self.rec_btn = tk.Button(
            left_box,
            text="● REC",
            bg="#990000",
            fg="#FFFFFF",
            activebackground="#FF2222",
            activeforeground="#FFFFFF",
            font=("Helvetica", 11, "bold"),
            relief=tk.RAISED,
            bd=3,
            width=8,
            height=2,
            cursor="hand2",
            command=self._on_rec_click
        )
        self.rec_btn.pack(side=tk.LEFT, padx=5)

        # Power Controls Box (LED + Button)
        power_box = tk.Frame(left_box, bg="#202020")
        power_box.pack(side=tk.LEFT, padx=5)

        self.power_led = tk.Label(
            power_box,
            text="[●] STANDBY",
            bg="#202020",
            fg="#FFAA00",
            font=("Consolas", 8, "bold")
        )
        self.power_led.pack(anchor="center", pady=(0, 2))

        # Power / Standby Button
        self.power_btn = tk.Button(
            power_box,
            text="POWER ON",
            bg="#1A401A",
            fg="#44FF66",
            activebackground="#2E7D32",
            activeforeground="#FFFFFF",
            font=("Helvetica", 9, "bold"),
            relief=tk.RAISED,
            bd=2,
            width=10,
            height=1,
            cursor="hand2",
            command=self._on_power_click
        )
        self.power_btn.pack(anchor="center")

        # Middle Section: Standard Function Keys (MENU, 1:1 MAG, USER1, USER2)
        mid_box = tk.Frame(panel, bg="#202020")
        mid_box.pack(side=tk.LEFT, padx=15)

        self.menu_btn = tk.Button(
            mid_box,
            text="MENU",
            bg="#2B2B2B",
            fg="#CCCCCC",
            activebackground="#555555",
            activeforeground="#FFFFFF",
            font=("Helvetica", 9, "bold"),
            width=7,
            cursor="hand2",
            command=lambda: self._press_gpio(pin=10)
        )
        self.menu_btn.pack(side=tk.LEFT, padx=3)

        self.mag_btn = tk.Button(
            mid_box,
            text="1:1 MAG",
            bg="#2B2B2B",
            fg="#CCCCCC",
            activebackground="#555555",
            activeforeground="#FFFFFF",
            font=("Helvetica", 9, "bold"),
            width=7,
            cursor="hand2",
            command=lambda: self._press_gpio(pin=11)
        )
        self.mag_btn.pack(side=tk.LEFT, padx=3)

        self.u1_btn = tk.Button(
            mid_box,
            text="USER 1",
            bg="#2B2B2B",
            fg="#CCCCCC",
            activebackground="#555555",
            activeforeground="#FFFFFF",
            font=("Helvetica", 9, "bold"),
            width=7,
            cursor="hand2",
            command=lambda: self._press_gpio(pin=14)
        )
        self.u1_btn.pack(side=tk.LEFT, padx=3)

        self.u2_btn = tk.Button(
            mid_box,
            text="USER 2",
            bg="#2B2B2B",
            fg="#CCCCCC",
            activebackground="#555555",
            activeforeground="#FFFFFF",
            font=("Helvetica", 9, "bold"),
            width=7,
            cursor="hand2",
            command=lambda: self._press_gpio(pin=15)
        )
        self.u2_btn.pack(side=tk.LEFT, padx=3)

        # Right Section: Directional Navigation D-Pad (Up, Down, Left, Right, Enter)
        nav_box = tk.Frame(panel, bg="#202020")
        nav_box.pack(side=tk.RIGHT, padx=10)

        # D-pad grid layout
        tk.Button(
            nav_box, text="▲", bg="#333333", fg="#FFFFFF",
            activebackground="#555555", activeforeground="#FFFFFF",
            width=3, cursor="hand2",
            command=lambda: self._press_gpio(pin=20)
        ).grid(row=0, column=1)

        tk.Button(
            nav_box, text="◀", bg="#333333", fg="#FFFFFF",
            activebackground="#555555", activeforeground="#FFFFFF",
            width=3, cursor="hand2",
            command=lambda: self._press_gpio(pin=21)
        ).grid(row=1, column=0)

        tk.Button(
            nav_box, text="●", bg="#444444", fg="#FFFFFF",
            activebackground="#666666", activeforeground="#FFFFFF",
            width=3, cursor="hand2",
            font=("Helvetica", 8, "bold"),
            command=lambda: self._press_gpio(pin=22)
        ).grid(row=1, column=1)

        tk.Button(
            nav_box, text="▶", bg="#333333", fg="#FFFFFF",
            activebackground="#555555", activeforeground="#FFFFFF",
            width=3, cursor="hand2",
            command=lambda: self._press_gpio(pin=23)
        ).grid(row=1, column=2)

        tk.Button(
            nav_box, text="▼", bg="#333333", fg="#FFFFFF",
            activebackground="#555555", activeforeground="#FFFFFF",
            width=3, cursor="hand2",
            command=lambda: self._press_gpio(pin=24)
        ).grid(row=2, column=1)

    def _on_rec_click(self):
        self.camera.press_record()
        self.refresh_state()
        if self.on_action:
            self.on_action("record_toggled")

    def _on_power_click(self):
        """Toggle camera power state between Standby and On."""
        self.camera.toggle_power()
        self.refresh_state()
        if self.on_action:
            self.on_action("power_toggled")

    def refresh_state(self):
        """Synchronize power button, REC button, and LED with camera state."""
        state = self.camera.power_state
        pct = int(self.camera.boot_progress * 100) if state == self.camera.POWER_BOOTING else None

        if state != self._last_state or pct != self._last_pct:
            self._last_state = state
            self._last_pct = pct

            if state == self.camera.POWER_STANDBY:
                self.power_led.config(text="[●] STANDBY", fg="#FFAA00")
                self.power_btn.config(
                    text="POWER ON",
                    bg="#1A401A",
                    fg="#44FF66",
                    state=tk.NORMAL
                )
            elif state == self.camera.POWER_BOOTING:
                self.power_led.config(text=f"[●] BOOTING {pct}%", fg="#00E5FF")
                self.power_btn.config(
                    text="BOOTING...",
                    bg="#2B2B2B",
                    fg="#888888",
                    state=tk.DISABLED
                )
            else: # POWER_ON
                self.power_led.config(text="[●] ONLINE", fg="#00FF44")
                self.power_btn.config(
                    text="POWER OFF\n(STANDBY)",
                    bg="#333333",
                    fg="#CCCCCC",
                    state=tk.NORMAL
                )

        # Synchronize REC button
        is_rec = (self.camera.rcp.state.get(RcpProtocol.PARAM_RECORD_STATE) == "2")
        if is_rec != self._last_rec:
            self._last_rec = is_rec
            if is_rec:
                self.rec_btn.config(bg="#FF0000", text="■ STOP")
                self.camera.log_system("[REC] Recording STARTED -> RED MINI-MAG (R3D 5K 24fps)")
            else:
                self.rec_btn.config(bg="#990000", text="● REC")
                self.camera.log_system("[REC] Recording STOPPED -> File saved safely")

    def _press_gpio(self, pin: int):
        pin_names = {
            10: "MENU", 11: "1:1 MAG", 14: "USER 1", 15: "USER 2",
            20: "NAV UP", 21: "NAV LEFT", 22: "NAV ENTER", 23: "NAV RIGHT", 24: "NAV DOWN"
        }
        key_name = pin_names.get(pin, f"PIN_{pin}")
        self.camera.log_system(f"[KEY] Physical button [{key_name}] pressed (GPIO pin {pin})")
        # Pulse GPIO pin high then low
        if 1 in self.camera.gpio:
            self.camera.gpio[1].set_input_pin(pin, True)
            self.camera.gpio[1].set_input_pin(pin, False)
        if self.on_action:
            self.on_action(f"gpio_pin_{pin}")
