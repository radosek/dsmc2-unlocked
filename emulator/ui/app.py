"""
RED DSMC2 Virtual Camera Engineering Application.
Integrates Virtual RED Camera Zone (Screen + Physical Buttons) and
Emulator Developer Tools (Console, RCP, RTOS Inspector, MMIO, Faults, Snapshots).
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from emulator.camera import Dsmc2Camera
from emulator.ui.screen import CameraScreen
from emulator.ui.buttons import PhysicalButtons
from emulator.ui.dashboard import DeveloperDashboard


class Dsmc2DesktopApp:
    """Main Application Window."""

    def __init__(self, workspace_root: str):
        self.workspace_root = os.path.abspath(workspace_root)
        self.camera = Dsmc2Camera(self.workspace_root)

        # Initialize root window
        self.root = tk.Tk()
        self.root.title("DSMC2 Virtual Brain — Virtual Camera & Engineering Workbench")
        self.root.geometry("1400x900")
        self.root.minsize(1100, 750)
        self.root.configure(bg="#1E1E1E")

        # Styling
        self._setup_style()

        # Build Main Panels
        self._build_layout()

        # Build Menu Bar
        self._build_menu()

        # Track initialization of dashboard tabs
        self._dashboard_initialized = False
        self._frame_tick = 0

        # Window closing handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Initial display setup
        self.buttons.refresh_state()
        self.screen.refresh()

        # Start non-blocking chunked boot sequence once window is mapped
        self.root.after(50, self._start_boot_sequence)

        # Start single-threaded UI update loop (~25 FPS = 40ms interval)
        self.root.after(100, self._ui_loop)

    def _start_boot_sequence(self):
        """Perform responsive, non-blocking chunked firmware boot with live progress bar."""
        if self.camera.is_booted:
            self.dashboard.refresh_threads()
            self.dashboard.refresh_rcp()
            self.dashboard.update_logs()
            self.buttons.refresh_state()
            self.screen.refresh()
            return

        self.camera.power_state = self.camera.POWER_BOOTING
        self.camera.boot_progress = 0.0
        self.camera.log_system("[PWR] Powering on RED DSMC2 (Cortex-A8 @ 1GHz)...")
        self.camera.log_system(f"[PWR] Loading firmware from {os.path.basename(self.camera.firmware_slot_dir)} into DDR (0x80000000)...")
        self.camera.load_firmware()
        self.camera.log_system("[CRT] Reset vector 0x80829F2C -> Initializing C runtime and clearing BSS...")
        self.screen.refresh()
        self.buttons.refresh_state()
        self.dashboard.update_logs()

        self._boot_total = 45_000_000
        self._boot_chunk = 5_000_000
        self._boot_done = 0
        self.root.after(20, self._boot_step)

    def _boot_step(self):
        """Execute one chunk of boot instructions and yield to Windows event loop."""
        if self._boot_done < self._boot_total:
            n = min(self._boot_chunk, self._boot_total - self._boot_done)
            self.camera.cpu.run(self.camera.cpu.pc, 0, count=n)
            self._boot_done += n
            self.camera.boot_progress = self._boot_done / self._boot_total
            self.screen.refresh()
            self.buttons.refresh_state()
            self.dashboard.update_logs()
            self.root.after(20, self._boot_step)
        else:
            self.camera.instruction_count += self._boot_total
            self.camera.is_booted = True
            self.camera.power_state = self.camera.POWER_ON
            self.camera.boot_progress = 1.0
            self.camera.rcp_server.start()

            self.camera.log_system("[RTOS] ThreadX RTOS kernel initialized.")
            for t in self.camera.get_threads():
                self.camera.log_system(f"[RTOS] Thread [{t['name']}] state={t['state']} prio={t['priority']}")
            self.camera.log_system("[DSS] OMAP3630 DISPC online: 1024x576 32bpp frame stream ready.")
            self.camera.log_system("[UI] RED Touch 7.0 online (maXTouch @ 0x4B, EDID @ 0x50).")
            model = self.camera.vfs.env.get("CAMERA_NAME", "SCARLET-W 5K")
            self.camera.log_system(f"[SYS] RED {model} is ONLINE and READY.")

            self.dashboard.refresh_threads()
            self.dashboard.refresh_rcp()
            self.dashboard.update_logs()
            self.buttons.refresh_state()
            self.screen.refresh()

    def _setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background="#1E1E1E", foreground="#CCCCCC", font=("Segoe UI", 9))
        style.configure("TNotebook", background="#181818", borderwidth=0)
        style.configure("TNotebook.Tab", background="#282828", foreground="#AAAAAA", padding=[10, 4])
        style.map("TNotebook.Tab", background=[("selected", "#383838")], foreground=[("selected", "#FFFFFF")])
        style.configure("Treeview", background="#222222", foreground="#EEEEEE", fieldbackground="#222222", rowheight=22)
        style.configure("Treeview.Heading", background="#2F2F2F", foreground="#FFFFFF", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", "#0E4D92")])

    def _build_menu(self):
        menubar = tk.Menu(self.root, bg="#2B2B2B", fg="#FFFFFF")

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0, bg="#2B2B2B", fg="#FFFFFF")
        file_menu.add_command(label="Open Firmware Slot...", command=self._open_firmware)
        file_menu.add_separator()
        file_menu.add_command(label="Save Snapshot...", command=lambda: self.dashboard._save_snapshot_dialog())
        file_menu.add_command(label="Restore Snapshot...", command=lambda: self.dashboard._restore_snapshot_dialog())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        # Camera Menu
        cam_menu = tk.Menu(menubar, tearoff=0, bg="#2B2B2B", fg="#FFFFFF")
        cam_menu.add_command(label="Power On / Boot", command=self._power_on)
        cam_menu.add_command(label="Power Off / Standby", command=self._power_off)
        cam_menu.add_separator()
        cam_menu.add_command(label="Toggle Record (REC)", command=self._toggle_record)
        cam_menu.add_separator()
        cam_menu.add_command(label="Format SSD / Media", command=lambda: self._set_param("MEDIA_FORMAT", "OK"))
        menubar.add_cascade(label="Camera", menu=cam_menu)

        # Tools Menu
        tools_menu = tk.Menu(menubar, tearoff=0, bg="#2B2B2B", fg="#FFFFFF")
        tools_menu.add_command(label="Refresh ThreadX RTOS", command=lambda: self.dashboard.refresh_threads())
        tools_menu.add_command(label="Refresh MMIO Tracker", command=lambda: self.dashboard.refresh_mmio())
        tools_menu.add_separator()
        tools_menu.add_command(label="Export Boot Trace to JSON...", command=self._export_trace)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.root.config(menu=menubar)

    def _build_layout(self):
        # Master PanedWindow dividing Virtual Camera (Left) and Developer Tools (Right)
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left Pane: Virtual Camera Zone
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=3)

        # Screen widget
        self.screen = CameraScreen(left_frame, self.camera, scale=0.75)
        self.screen.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Physical buttons widget
        self.buttons = PhysicalButtons(left_frame, self.camera, on_action_callback=self._on_button_action)
        self.buttons.pack(side=tk.BOTTOM, fill=tk.X)

        # Right Pane: Developer Dashboard Zone
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=2)

        self.dashboard = DeveloperDashboard(right_frame, self.camera)
        self.dashboard.pack(fill=tk.BOTH, expand=True)

    def _on_button_action(self, action: str):
        # Route physical button or GPIO pin to RedUi
        pin_names = {
            10: "MENU", 11: "1:1 MAG", 14: "USER 1", 15: "USER 2",
            20: "NAV UP", 21: "NAV LEFT", 22: "NAV ENTER", 23: "NAV RIGHT", 24: "NAV DOWN"
        }
        if action.startswith("gpio_pin_"):
            try:
                pin = int(action.split("_")[-1])
                btn_name = pin_names.get(pin)
                if btn_name:
                    self.screen.handle_button(btn_name)
            except Exception:
                pass
        elif action in ("record_toggled", "power_toggled"):
            self.screen.refresh()

        self.buttons.refresh_state()
        self.dashboard.update_logs()

    def _power_on(self):
        if not self.camera.is_booted:
            self._start_boot_sequence()
        else:
            self.camera.power_on()
            self.buttons.refresh_state()
            self.screen.refresh()
            self.dashboard.update_logs()

    def _power_off(self):
        self.camera.power_off()
        self.buttons.refresh_state()
        self.screen.refresh()
        self.dashboard.update_logs()

    def _toggle_record(self):
        self.camera.press_record()
        self.buttons.refresh_state()
        self.screen.refresh()
        self.dashboard.update_logs()

    def _set_param(self, param: str, val: str):
        self.camera.rcp.process_command(f"SET / PARAM {param} {val}")
        self.screen.refresh()
        self.dashboard.refresh_rcp()

    def _open_firmware(self):
        folder = filedialog.askdirectory(
            title="Select Firmware Slot Directory",
            initialdir=os.path.join(self.workspace_root, "firmware_store")
        )
        if folder:
            mem_path = os.path.join(folder, "dsmc_program.mem")
            if os.path.exists(mem_path):
                self.camera.stop()
                self.camera.load_firmware(mem_path)
                self._start_boot_sequence()
                messagebox.showinfo("Firmware Loaded", f"Loaded firmware from:\n{folder}")
            else:
                messagebox.showerror("Error", "Selected directory does not contain dsmc_program.mem")

    def _export_trace(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Trace", "*.json"), ("All Files", "*.*")]
        )
        if path:
            import json
            trace_data = {
                "instruction_count": self.camera.instruction_count,
                "pc": f"0x{self.camera.cpu.pc:08X}",
                "threads": self.camera.get_threads(),
                "unknown_mmio": {f"0x{k:08X}": v for k, v in self.camera.bus.unknown_mmio.items()},
                "serial_logs": self.camera.get_serial_logs()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(trace_data, f, indent=2)
            messagebox.showinfo("Export Complete", f"Boot trace exported to:\n{path}")

    def _ui_loop(self):
        """Periodic UI update loop on main thread (~25 FPS)."""
        try:
            # Advance CPU instruction slice when camera is running
            if self.camera.power_state == self.camera.POWER_ON and self.camera.is_booted:
                self.camera.step_slice(20_000)

            # Smart refresh: refresh every frame when recording or interacting;
            # otherwise refresh at ~5 FPS (every 200ms) to update instruction counter
            self._frame_tick += 1
            is_rec = (self.camera.rcp.state.get("record_state") == "2")
            if is_rec or (self._frame_tick % 5 == 0):
                self.screen.refresh()

            self.buttons.refresh_state()
            self.dashboard.update_logs()
        except Exception:
            pass
        finally:
            self.root.after(40, self._ui_loop)

    def _on_close(self):
        self.camera.stop()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def launch_gui(workspace_root: str):
    print("[SYS] Launching RED DSMC2 Virtual Camera GUI...", flush=True)
    app = Dsmc2DesktopApp(workspace_root)
    app.run()


if __name__ == "__main__":
    root_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    launch_gui(root_dir)
