"""
Developer Dashboard for RED DSMC2 Emulator.
Provides serial console, RCP control, ThreadX RTOS inspector, MMIO browser,
fault injection controls, and snapshot management.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional


class DeveloperDashboard(ttk.Notebook):
    """Multi-tab engineering workbench for DSMC2 development and diagnostics."""

    def __init__(self, parent, camera, **kwargs):
        super().__init__(parent, **kwargs)
        self.camera = camera

        # Create Tabs
        self.tab_serial = ttk.Frame(self)
        self.tab_rcp = ttk.Frame(self)
        self.tab_threads = ttk.Frame(self)
        self.tab_mmio = ttk.Frame(self)
        self.tab_faults = ttk.Frame(self)
        self.tab_snapshots = ttk.Frame(self)

        self.add(self.tab_serial, text="Console / Serial")
        self.add(self.tab_rcp, text="RCP & Parameters")
        self.add(self.tab_threads, text="ThreadX RTOS")
        self.add(self.tab_mmio, text="MMIO & Diagnostics")
        self.add(self.tab_faults, text="Fault Injection")
        self.add(self.tab_snapshots, text="Snapshots")

        self._build_serial_tab()
        self._build_rcp_tab()
        self._build_threads_tab()
        self._build_mmio_tab()
        self._build_faults_tab()
        self._build_snapshots_tab()

        self._last_log_count = 0

    # 1. Serial Tab
    def _build_serial_tab(self):
        frame = self.tab_serial
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, padx=5, pady=2)

        ttk.Button(toolbar, text="Clear Log", command=self._clear_serial_log).pack(side=tk.LEFT, padx=2)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Auto-scroll", variable=self.auto_scroll_var).pack(side=tk.LEFT, padx=10)

        self.log_text = tk.Text(
            frame,
            bg="#111111",
            fg="#00FF66",
            insertbackground="#FFFFFF",
            font=("Consolas", 9),
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def _clear_serial_log(self):
        self.log_text.delete("1.0", tk.END)
        self._last_log_count = 0

    # 2. RCP Tab
    def _build_rcp_tab(self):
        frame = self.tab_rcp
        # Parameters tree
        cols = ("Parameter", "Current Value")
        self.rcp_tree = ttk.Treeview(frame, columns=cols, show="headings", height=8)
        for col in cols:
            self.rcp_tree.heading(col, text=col)
            self.rcp_tree.column(col, width=150)
        self.rcp_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Command entry
        cmd_box = ttk.LabelFrame(frame, text="Send RED Command Protocol (RCP) Instruction")
        cmd_box.pack(fill=tk.X, padx=5, pady=5)

        row = ttk.Frame(cmd_box)
        row.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(row, text="Command:").pack(side=tk.LEFT, padx=5)
        self.rcp_cmd_entry = ttk.Entry(row, width=40)
        self.rcp_cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.rcp_cmd_entry.insert(0, "GET / PARAM ISO")

        ttk.Button(row, text="Send", command=self._send_rcp_cmd).pack(side=tk.RIGHT, padx=5)

        self.rcp_result_lbl = ttk.Label(cmd_box, text="Response: (none)", font=("Consolas", 9))
        self.rcp_result_lbl.pack(anchor="w", padx=10, pady=(0, 5))

    def _send_rcp_cmd(self):
        cmd = self.rcp_cmd_entry.get().strip()
        if not cmd:
            return
        resp = self.camera.rcp.process_command(cmd)
        self.rcp_result_lbl.config(text=f"Response: {resp}")
        self.refresh_rcp()

    def refresh_rcp(self):
        for item in self.rcp_tree.get_children():
            self.rcp_tree.delete(item)
        for param, val in self.camera.rcp.state.items():
            self.rcp_tree.insert("", tk.END, values=(param, val))

    # 3. Threads Tab
    def _build_threads_tab(self):
        frame = self.tab_threads
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, padx=5, pady=2)

        ttk.Button(toolbar, text="Refresh Threads", command=self.refresh_threads).pack(side=tk.LEFT, padx=2)

        cols = ("Address", "Thread Name", "State", "Priority", "Entry PC", "SP", "Stack Range")
        self.thread_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col in cols:
            self.thread_tree.heading(col, text=col)
            self.thread_tree.column(col, width=110)
        self.thread_tree.column("Thread Name", width=180)
        self.thread_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def refresh_threads(self):
        for item in self.thread_tree.get_children():
            self.thread_tree.delete(item)
        threads = self.camera.get_threads()
        for t in threads:
            self.thread_tree.insert("", tk.END, values=(
                t["address"],
                t["name"],
                t["state"],
                t["priority"],
                t.get("entry", "N/A"),
                t["sp"],
                t["stack_range"]
            ))

    # 4. MMIO Tab
    def _build_mmio_tab(self):
        frame = self.tab_mmio
        cols = ("Address", "Accesses", "Last Value", "Subsystem")
        self.mmio_tree = ttk.Treeview(frame, columns=cols, show="headings")
        for col in cols:
            self.mmio_tree.heading(col, text=col)
            self.mmio_tree.column(col, width=120)
        self.mmio_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    def refresh_mmio(self):
        for item in self.mmio_tree.get_children():
            self.mmio_tree.delete(item)
        # Sort unknown MMIO accesses by hit count
        sorted_mmio = sorted(
            self.camera.bus.unknown_mmio.items(),
            key=lambda item: item[1]["count"],
            reverse=True
        )
        for addr, info in sorted_mmio[:50]:
            subsystem = "OMAP3 / Peripheral"
            if 0x48000000 <= addr < 0x48010000:
                subsystem = "PRCM / Clocks"
            elif 0x48050000 <= addr < 0x48060000:
                subsystem = "DSS / Display"
            elif 0x48060000 <= addr < 0x48080000:
                subsystem = "I2C / Serial"
            self.mmio_tree.insert("", tk.END, values=(
                f"0x{addr:08X}",
                info["count"],
                f"0x{info['last_val']:08X}",
                subsystem
            ))

    # 5. Faults Tab
    def _build_faults_tab(self):
        frame = self.tab_faults
        lbl = ttk.Label(
            frame,
            text="Simulate DSMC2 Hardware, Sensor, and Communication Faults (Milestone 8)",
            font=("Helvetica", 9, "bold")
        )
        lbl.pack(anchor="w", padx=10, pady=10)

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        ttk.Button(
            grid,
            text="Disconnect LCD (I2C3 0x4B/0x50)",
            command=lambda: self._trigger_fault("monitor_disconnect")
        ).grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        ttk.Button(
            grid,
            text="Reconnect LCD",
            command=lambda: self._trigger_fault("monitor_connect")
        ).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        ttk.Button(
            grid,
            text="Inject I2C Bus NACK / Error",
            command=lambda: self._trigger_fault("i2c_nack")
        ).grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        ttk.Button(
            grid,
            text="Corrupt /env Calibration / Identity",
            command=lambda: self._trigger_fault("corrupt_env")
        ).grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        ttk.Button(
            grid,
            text="Trigger Watchdog Reset",
            command=lambda: self._trigger_fault("watchdog_reset")
        ).grid(row=2, column=0, columnspan=2, padx=5, pady=10, sticky="ew")

        self.fault_status_lbl = ttk.Label(frame, text="Status: Ready", foreground="#444444")
        self.fault_status_lbl.pack(anchor="w", padx=10, pady=10)

    def _trigger_fault(self, fault_type: str):
        self.camera.inject_fault(fault_type)
        self.fault_status_lbl.config(text=f"Injected Fault: {fault_type} triggered successfully!")

    # 6. Snapshots Tab
    def _build_snapshots_tab(self):
        frame = self.tab_snapshots
        box = ttk.LabelFrame(frame, text="State Snapshot Management")
        box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        btn_row = ttk.Frame(box)
        btn_row.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(btn_row, text="Save Snapshot to File...", command=self._save_snapshot_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_row, text="Restore Snapshot from File...", command=self._restore_snapshot_dialog).pack(side=tk.LEFT, padx=5)

        self.snap_info_text = tk.Text(box, height=10, bg="#1E1E1E", fg="#CCCCCC", font=("Consolas", 9))
        self.snap_info_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.snap_info_text.insert("1.0", "Snapshots store full CPU registers, memory segments, and peripheral state.\nClick Save to create a snapshot.")

    def _save_snapshot_dialog(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".dsmc2",
            filetypes=[("DSMC2 Snapshot", "*.dsmc2"), ("All Files", "*.*")]
        )
        if path:
            try:
                self.camera.save_snapshot(path, description="User GUI Snapshot")
                messagebox.showinfo("Snapshot Saved", f"Successfully saved state to:\n{path}")
                self.snap_info_text.delete("1.0", tk.END)
                self.snap_info_text.insert("1.0", f"Saved snapshot to {path}\nPC: 0x{self.camera.cpu.pc:08X}\nInstructions: {self.camera.instruction_count}")
            except Exception as e:
                messagebox.showerror("Snapshot Error", f"Failed to save snapshot:\n{e}")

    def _restore_snapshot_dialog(self):
        path = filedialog.askopenfilename(
            filetypes=[("DSMC2 Snapshot", "*.dsmc2"), ("All Files", "*.*")]
        )
        if path:
            try:
                meta = self.camera.restore_snapshot(path)
                messagebox.showinfo("Snapshot Restored", f"Successfully restored snapshot from:\n{path}\nPC: 0x{self.camera.cpu.pc:08X}")
                self.refresh_threads()
                self.refresh_rcp()
            except Exception as e:
                messagebox.showerror("Snapshot Error", f"Failed to restore snapshot:\n{e}")

    def update_logs(self):
        """Append newly received serial lines to console."""
        logs = self.camera.get_serial_logs()
        if len(logs) > self._last_log_count:
            new_lines = logs[self._last_log_count:]
            self.log_text.insert(tk.END, "\n".join(new_lines) + "\n")
            self._last_log_count = len(logs)
            if self.auto_scroll_var.get():
                self.log_text.see(tk.END)
