"""
RCP (RED Command Protocol) TCP Server for external camera control applications.
Standard default port: 1111.
Supports multi-client TCP control, asynchronous bidirectional notifications,
and seamless integration with RED Control and third-party remote systems.
"""

import socket
import threading
from typing import Optional, List, Any
from emulator.rcp.protocol import RcpProtocol


class RcpServer:
    """Provides a networked RCP bridge for third-party control apps."""

    def __init__(self, protocol: RcpProtocol, host: str = "127.0.0.1", port: int = 1111):
        self.protocol = protocol
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.clients: List[socket.socket] = []
        self._lock = threading.Lock()

        # Hook protocol state changes for live broadcasts
        self.protocol.add_listener(self._on_protocol_change)

    def start(self):
        """Start listening for external TCP clients."""
        if self.running:
            return
        try:
            self.running = True
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.server_socket.settimeout(0.5)

            self.thread = threading.Thread(target=self._accept_loop, daemon=True, name="RcpServer")
            self.thread.start()
        except Exception:
            self.running = False
            self.server_socket = None

    def stop(self):
        """Stop listening and cleanly disconnect all clients."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        with self._lock:
            for client in list(self.clients):
                try:
                    client.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.8)
            self.thread = None

    def get_client_count(self) -> int:
        """Return number of actively connected external RCP clients."""
        with self._lock:
            return len(self.clients)

    def broadcast(self, message: str, exclude_sock: Optional[socket.socket] = None):
        """Send notification line to connected external TCP clients."""
        if not message.endswith("\n"):
            message += "\n"
        data = message.encode("utf-8")

        dead_clients = []
        with self._lock:
            for sock in list(self.clients):
                if exclude_sock is not None and sock is exclude_sock:
                    continue
                try:
                    sock.sendall(data)
                except Exception:
                    dead_clients.append(sock)

            for dead in dead_clients:
                if dead in self.clients:
                    self.clients.remove(dead)
                try:
                    dead.close()
                except Exception:
                    pass

    def _on_protocol_change(self, param: str, val: str, origin: Optional[Any] = None):
        """Broadcast state change notification to other external clients."""
        if self.running:
            self.broadcast(f"NOTIFY {param} {val}", exclude_sock=origin)

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                with self._lock:
                    self.clients.append(client_sock)

                # Send initial greeting banner
                greeting = f"RED DSMC2 ONLINE | MODEL {self.protocol.state.get('camera_name', 'SCARLET-W')} | READY\n"
                try:
                    client_sock.sendall(greeting.encode("utf-8"))
                except Exception:
                    pass

                t = threading.Thread(target=self._client_handler, args=(client_sock,), daemon=True, name=f"RcpClient-{addr}")
                t.start()
            except socket.timeout:
                continue
            except Exception:
                break

    def _client_handler(self, sock: socket.socket):
        sock.settimeout(1.0)
        buffer = ""
        while self.running:
            try:
                data = sock.recv(2048)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip("\r")
                    if not line:
                        continue
                    resp = self.protocol.process_command(line, origin=sock)
                    if resp:
                        sock.sendall(resp.encode("utf-8"))
            except socket.timeout:
                continue
            except Exception:
                break

        # Cleanup on disconnect
        with self._lock:
            if sock in self.clients:
                self.clients.remove(sock)
        try:
            sock.close()
        except Exception:
            pass
