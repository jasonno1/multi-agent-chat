"""Unix Domain Socket chat bus for multi-agent communication.

The ChatBus runs in the orchestrator process. Agent wrapper processes
connect as clients and exchange JSON-line messages.

Protocol:
  - One JSON object per line (newline-delimited)
  - Server routes messages based on the `to` field
  - `to: "*"` means broadcast to all connected agents
"""

from __future__ import annotations

import os
import socket
import select
import threading
import time
from pathlib import Path
from typing import Callable

from .protocol import Message, MessageType, parse_message


class ChatBus:
    """Unix Domain Socket server for multi-agent chat communication."""

    SOCKET_DIR = "/tmp/mac-bus"

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.socket_dir = Path(self.SOCKET_DIR) / session_id
        self.socket_path = self.socket_dir / "chat-bus.sock"
        self._server_sock: socket.socket | None = None
        self._clients: dict[str, socket.socket] = {}  # profile_name -> socket
        self._reverse: dict[int, str] = {}  # fd -> profile_name
        self._pending: list[socket.socket] = []  # connected but not yet registered
        self._running = False
        self._lock = threading.Lock()

        # Callback hooks for the orchestrator
        self.on_message: Callable[[Message], None] | None = None
        self.on_join: Callable[[str], None] | None = None
        self.on_leave: Callable[[str], None] | None = None

    # ── Server Lifecycle ──────────────────────────────────

    def start(self) -> bool:
        """Start the UDS server. Called by orchestrator."""
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale_socket()

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self.socket_path))
        self._server_sock.listen(16)
        self._server_sock.setblocking(False)
        self._running = True
        return True

    def stop(self):
        """Shutdown the server and disconnect all clients."""
        self._running = False

        # Send shutdown to all clients
        shutdown_msg = Message(type=MessageType.SHUTDOWN, from_="orchestrator").to_json()
        for sock in list(self._clients.values()) + list(self._pending):
            try:
                self._send_raw(sock, shutdown_msg)
                sock.close()
            except Exception:
                pass

        self._clients.clear()
        self._reverse.clear()
        self._pending.clear()

        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass

        self._cleanup_stale_socket()

    # ── Event Loop ────────────────────────────────────────

    def run_loop(self):
        """Block and run the event loop. Call from a background thread."""
        import select

        while self._running:
            try:
                # Build fd lists (include pending sockets for JOIN detection)
                with self._lock:
                    socks = [self._server_sock] + list(self._clients.values()) + list(self._pending)

                if not socks:
                    time.sleep(0.05)
                    continue

                readable, _, errored = select.select(socks, [], socks, 0.5)

                for s in readable:
                    if s is self._server_sock:
                        self._accept()
                    else:
                        self._read_from_client(s)

                for s in errored:
                    self._remove_client_by_socket(s)

            except Exception:
                time.sleep(0.1)

    # ── Sending ───────────────────────────────────────────

    def send(self, msg: Message) -> bool:
        """Send a message to its destination. `to: "*"` broadcasts."""
        if msg.to == "*":
            return self._broadcast(msg)
        return self._send_to(msg.to, msg)

    def send_to(self, profile_name: str, msg: Message) -> bool:
        """Send a message to a specific profile."""
        return self._send_to(profile_name, msg)

    def broadcast(self, msg: Message) -> bool:
        """Send a message to all connected agents."""
        return self._broadcast(msg)

    # ── Client Info ───────────────────────────────────────

    @property
    def client_names(self) -> list[str]:
        with self._lock:
            return list(self._clients.keys())

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def is_connected(self, profile_name: str) -> bool:
        with self._lock:
            return profile_name in self._clients

    # ── Internal ──────────────────────────────────────────

    def _accept(self):
        try:
            client, _ = self._server_sock.accept()
            client.setblocking(False)
            with self._lock:
                self._pending.append(client)
        except Exception:
            return

    def _register_client(self, name: str, sock: socket.socket):
        with self._lock:
            old = self._clients.pop(name, None)
            if old:
                try:
                    old.close()
                except Exception:
                    pass
            self._clients[name] = sock
            self._reverse[sock.fileno()] = name

    def _remove_client_by_socket(self, sock: socket.socket):
        name = None
        with self._lock:
            fd = sock.fileno()
            name = self._reverse.pop(fd, None)
            if name:
                self._clients.pop(name, None)
            # Remove from pending if present
            if sock in self._pending:
                self._pending.remove(sock)
        try:
            sock.close()
        except Exception:
            pass
        if name and self.on_leave:
            self.on_leave(name)

    def _send_raw(self, sock: socket.socket, data: str) -> bool:
        try:
            sock.sendall((data + "\n").encode("utf-8"))
            return True
        except Exception:
            self._remove_client_by_socket(sock)
            return False

    def _send_to(self, name: str, msg: Message) -> bool:
        with self._lock:
            sock = self._clients.get(name)
        if not sock:
            return False
        return self._send_raw(sock, msg.to_json())

    def _broadcast(self, msg: Message) -> bool:
        data = msg.to_json()
        ok = True
        with self._lock:
            for name, sock in list(self._clients.items()):
                if name == msg.from_:
                    continue
                if not self._send_raw(sock, data):
                    ok = False
        return ok

    def _read_from_client(self, sock: socket.socket):
        try:
            raw = sock.recv(65536)
        except Exception:
            self._remove_client_by_socket(sock)
            return

        if not raw:
            self._remove_client_by_socket(sock)
            return

        # Buffer and process line by line
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue

            msg = parse_message(line)
            if msg is None:
                continue

            # Handle JOIN specially
            if msg.type == MessageType.JOIN:
                name = msg.from_
                # Move from pending to registered
                with self._lock:
                    if sock in self._pending:
                        self._pending.remove(sock)
                self._register_client(name, sock)
                if self.on_join:
                    self.on_join(name)
                # Send WELCOME back
                welcome = Message(
                    type=MessageType.WELCOME,
                    from_="orchestrator",
                    to=name,
                    payload=msg.payload,
                )
                self._send_raw(sock, welcome.to_json())
                continue

            # Route to callback
            if self.on_message:
                self.on_message(msg)

    def _cleanup_stale_socket(self):
        try:
            self.socket_path.unlink(missing_ok=True)
        except Exception:
            pass
