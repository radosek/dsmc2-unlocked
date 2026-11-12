"""
DSMC2 Virtual Brain Command Line Interface (CLI - dsmc2-vbrain).
Provides scriptable commands for booting, running, inspecting, snapshotting, and testing.
"""

import argparse
import json
import os
import sys
import time

from emulator.camera import Dsmc2Camera
from emulator.core.snapshot import SnapshotManager


def get_workspace_root() -> str:
    """Determine root directory containing firmware_store and persistent_store."""
    # Look for current directory or parent directory containing firmware_store
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, "firmware_store")):
        return cwd
    parent = os.path.dirname(cwd)
    if os.path.isdir(os.path.join(parent, "firmware_store")):
        return parent
    return cwd


def cmd_boot(args):
    """Execute firmware boot sequence and report status."""
    workspace = get_workspace_root()
    cam = Dsmc2Camera(workspace)
    cam.load_firmware(args.firmware)

    t0 = time.time()
    cam.boot(initial_instructions=args.instructions)
    duration = time.time() - t0

    threads = cam.get_threads()
    success = (cam.cpu.pc in cam.IDLE_LOOP_PCS) or (cam.instruction_count >= args.instructions)

    result = {
        "status": "SUCCESS" if success else "FAILED",
        "instructions_executed": cam.instruction_count,
        "duration_seconds": round(duration, 3),
        "pc": f"0x{cam.cpu.pc:08X}",
        "sp": f"0x{cam.cpu.sp:08X}",
        "cpsr": f"0x{cam.cpu.cpsr:08X}",
        "threads_detected": len(threads),
        "threads": threads,
        "unknown_mmio_count": len(cam.bus.unknown_mmio)
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"=== RED DSMC2 Boot Result: {result['status']} ===")
        print(f"Instructions: {result['instructions_executed']:,} in {result['duration_seconds']}s")
        print(f"PC: {result['pc']} | SP: {result['sp']} | CPSR: {result['cpsr']}")
        print(f"Active ThreadX Threads ({result['threads_detected']}):")
        for t in threads:
            print(f"  - [{t['name']}] state={t['state']} prio={t['priority']} SP={t['sp']}")
        print(f"Unknown MMIO Accesses: {result['unknown_mmio_count']}")

    sys.exit(0 if success else 1)


def cmd_run(args):
    """Run virtual camera either with Web Studio, desktop GUI, or headlessly."""
    workspace = get_workspace_root()

    if args.headless:
        # Headless mode
        cam = Dsmc2Camera(workspace)
        cam.load_firmware(args.firmware)
        print(f"[*] Booting RED DSMC2 Headless...")
        cam.boot()
        print(f"[*] DSMC2 Booted to PC: 0x{cam.cpu.pc:08X}")
        print(f"[*] Starting RCP TCP Server on {args.host}:{args.port}...")
        cam.rcp_server.host = args.host
        cam.rcp_server.port = args.port
        cam.start()
        print("[*] Camera running. Press Ctrl+C to terminate.")
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[*] Stopping virtual camera...")
            cam.stop()
            sys.exit(0)
    elif getattr(args, "ui", "web") == "tk":
        from emulator.ui.app import launch_gui
        launch_gui(workspace)
    else:
        # Launch modern Web-Based Virtual Camera Studio (default, freeze-proof)
        from emulator.ui.web import launch_web_studio
        web_port = getattr(args, "web_port", 8765)
        open_browser = not getattr(args, "no_browser", False)
        launch_web_studio(workspace, host=args.host, port=web_port, open_browser=open_browser)


def cmd_inspect(args):
    """Inspect ThreadX RTOS, MMIO registers, VFS, or camera state."""
    workspace = get_workspace_root()
    cam = Dsmc2Camera(workspace)
    cam.load_firmware()
    cam.boot()

    data = {}

    if args.threads or args.all:
        data["threads"] = cam.get_threads()

    if args.mmio or args.all:
        data["unknown_mmio"] = {
            f"0x{addr:08X}": info for addr, info in cam.bus.unknown_mmio.items()
        }

    if args.vfs or args.all:
        data["vfs"] = {
            "env": dict(cam.vfs.env.config),
            "mounts": cam.vfs.mounts
        }

    if args.rcp or args.all:
        data["rcp_state"] = dict(cam.rcp.state)

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        if "threads" in data:
            print(f"\n--- ThreadX RTOS Threads ({len(data['threads'])}) ---")
            for t in data["threads"]:
                print(f"  [{t['name']:<30}] State: {t['state']:<10} Prio: {t['priority']:<3} SP: {t['sp']} Entry: {t.get('entry')}")

        if "vfs" in data:
            print(f"\n--- Camera Environment (/env) ---")
            for k, v in data["vfs"]["env"].items():
                print(f"  {k:<20} = {v}")

        if "rcp_state" in data:
            print(f"\n--- Active Camera Parameters (RCP) ---")
            for k, v in data["rcp_state"].items():
                print(f"  {k:<20} = {v}")

        if "unknown_mmio" in data:
            print(f"\n--- Unknown MMIO Registers ({len(data['unknown_mmio'])}) ---")
            for addr, info in list(data["unknown_mmio"].items())[:20]:
                print(f"  {addr}: {info['count']} hits (last: 0x{info['last_val']:08X})")


def cmd_snapshot(args):
    """Manage emulator state snapshots."""
    workspace = get_workspace_root()
    cam = Dsmc2Camera(workspace)
    cam.load_firmware()

    if args.action == "save":
        cam.boot()
        SnapshotManager.save(cam, args.file, description=args.desc or "CLI Snapshot")
        print(f"[*] Snapshot successfully saved to: {args.file}")
    elif args.action == "restore":
        meta = SnapshotManager.restore(cam, args.file)
        print(f"[*] Snapshot successfully restored from: {args.file}")
        print(f"    Restored PC: 0x{cam.cpu.pc:08X}")
        print(f"    Instructions: {cam.instruction_count:,}")
        print(f"    Description: {meta.get('description', '')}")


def cmd_test(args):
    """Run automated regression test suite and export JSON report."""
    import pytest
    report_file = args.output_json or "test_report.json"

    pytest_args = ["-c", os.path.join(os.path.dirname(os.path.abspath(__file__)), "pytest.ini"), "-q"]
    if args.suite and args.suite != "all":
        pytest_args.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", f"test_{args.suite}.py"))
    else:
        pytest_args.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

    t0 = time.time()
    exit_code = pytest.main(pytest_args)
    duration = time.time() - t0

    report = {
        "timestamp": time.time(),
        "suite": args.suite or "all",
        "exit_code": int(exit_code),
        "status": "PASSED" if exit_code == 0 else "FAILED",
        "duration_seconds": round(duration, 3)
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\n[*] Test execution finished with status {report['status']} in {duration:.2f}s")
    print(f"[*] Structured report exported to: {report_file}")
    sys.exit(int(exit_code))


def main():
    parser = argparse.ArgumentParser(
        prog="dsmc2-vbrain",
        description="DSMC2 Virtual Brain ? Virtual Camera & Engineering Workbench"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: boot
    p_boot = subparsers.add_parser("boot", help="Execute firmware boot sequence")
    p_boot.add_argument("-n", "--instructions", type=int, default=45_000_000, help="Initial instructions to execute")
    p_boot.add_argument("-f", "--firmware", type=str, default=None, help="Path to dsmc_program.mem")
    p_boot.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_boot.set_defaults(func=cmd_boot)

    # Subcommand: run
    p_run = subparsers.add_parser("run", help="Run virtual camera")
    p_run.add_argument("--headless", action="store_true", help="Run without graphical display")
    p_run.add_argument("-f", "--firmware", type=str, default=None, help="Path to dsmc_program.mem")
    p_run.add_argument("--host", type=str, default="127.0.0.1", help="Server bind host")
    p_run.add_argument("-p", "--port", type=int, default=1111, help="RCP TCP server port (default: 1111)")
    p_run.add_argument("--web-port", type=int, default=8765, help="Web Studio HTTP port (default: 8765)")
    p_run.add_argument("--no-browser", action="store_true", help="Do not open browser automatically")
    p_run.add_argument("--ui", choices=["web", "tk"], default="web", help="UI interface: web (default) or tk")
    p_run.set_defaults(func=cmd_run)

    # Subcommand: inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect RTOS, MMIO, VFS, or camera state")
    p_inspect.add_argument("--threads", action="store_true", help="Dump ThreadX RTOS threads")
    p_inspect.add_argument("--mmio", action="store_true", help="Dump unknown MMIO accesses")
    p_inspect.add_argument("--vfs", action="store_true", help="Dump VFS mounts and environment")
    p_inspect.add_argument("--rcp", action="store_true", help="Dump camera parameters (RCP)")
    p_inspect.add_argument("--all", action="store_true", help="Dump all inspection categories")
    p_inspect.add_argument("--json", action="store_true", help="Output as JSON")
    p_inspect.set_defaults(func=cmd_inspect)

    # Subcommand: snapshot
    p_snap = subparsers.add_parser("snapshot", help="Manage state snapshots")
    p_snap.add_argument("action", choices=["save", "restore"], help="Snapshot action")
    p_snap.add_argument("file", type=str, help="Snapshot file path (.dsmc2)")
    p_snap.add_argument("--desc", type=str, default="", help="Description string for snapshot")
    p_snap.set_defaults(func=cmd_snapshot)

    # Subcommand: test
    p_test = subparsers.add_parser("test", help="Run automated regression test suite")
    p_test.add_argument("--suite", choices=["all", "camera_boot", "storage", "peripherals", "fault_injection"], default="all")
    p_test.add_argument("-o", "--output-json", type=str, default="test_report.json", help="Path to write JSON report")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
