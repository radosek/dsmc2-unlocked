"""
Virtual File System (VFS) and Flash Partition Mapper for RED DSMC2.
Maps /env, /image1, /image2, /data, /log, and /pdata to local storage trees.
"""

import os
from typing import Optional, Dict
from emulator.storage.env import CameraEnvironment


class VirtualFileSystem:
    """Provides path resolution and persistent backing for DSMC2 partitions."""

    def __init__(self, firmware_slot_dir: str, persistent_root: str):
        self.firmware_slot_dir = os.path.abspath(firmware_slot_dir)
        self.persistent_root = os.path.abspath(persistent_root)
        self.env = CameraEnvironment()

        # Ensure persistent directories exist
        self.data_dir = os.path.join(self.persistent_root, "data")
        self.log_dir = os.path.join(self.persistent_root, "log")
        self.pdata_dir = os.path.join(self.persistent_root, "pdata")

        for d in (self.data_dir, self.log_dir, self.pdata_dir):
            os.makedirs(d, exist_ok=True)

    @property
    def mounts(self) -> Dict[str, str]:
        """Return virtual mount map to host filesystem."""
        return {
            "/env": os.path.join(self.persistent_root, "env.bin"),
            "/image1": self.firmware_slot_dir,
            "/image2": self.firmware_slot_dir,
            "/data": self.data_dir,
            "/log": self.log_dir,
            "/pdata": self.pdata_dir
        }

    def resolve_path(self, virtual_path: str) -> Optional[str]:
        """Convert a virtual camera path into a host filesystem path."""
        norm = virtual_path.replace("\\", "/").strip()
        if not norm.startswith("/"):
            norm = "/" + norm

        if norm.startswith("/image1") or norm.startswith("/image2"):
            # Strip prefix
            sub = norm[7:].lstrip("/")
            return os.path.join(self.firmware_slot_dir, sub)
        elif norm.startswith("/data"):
            sub = norm[5:].lstrip("/")
            return os.path.join(self.data_dir, sub)
        elif norm.startswith("/log"):
            sub = norm[4:].lstrip("/")
            return os.path.join(self.log_dir, sub)
        elif norm.startswith("/pdata"):
            sub = norm[6:].lstrip("/")
            return os.path.join(self.pdata_dir, sub)
        elif norm == "/env":
            return os.path.join(self.persistent_root, "env.bin")
        return None

    def read_file(self, virtual_path: str) -> Optional[bytes]:
        if virtual_path.strip() == "/env":
            return self.env.serialize()

        host_path = self.resolve_path(virtual_path)
        if host_path and os.path.isfile(host_path):
            with open(host_path, "rb") as f:
                return f.read()
        return None

    def write_file(self, virtual_path: str, data: bytes) -> bool:
        if virtual_path.strip() == "/env":
            self.env = CameraEnvironment.deserialize(data)
            env_file = os.path.join(self.persistent_root, "env.bin")
            with open(env_file, "wb") as f:
                f.write(data)
            return True

        host_path = self.resolve_path(virtual_path)
        if host_path:
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, "wb") as f:
                f.write(data)
            return True
        return False

    def append_file(self, virtual_path: str, data: bytes) -> bool:
        host_path = self.resolve_path(virtual_path)
        if host_path:
            os.makedirs(os.path.dirname(host_path), exist_ok=True)
            with open(host_path, "ab") as f:
                f.write(data)
            return True
        return False

    def file_exists(self, virtual_path: str) -> bool:
        if virtual_path.strip() == "/env":
            return True
        host_path = self.resolve_path(virtual_path)
        return host_path is not None and os.path.exists(host_path)
