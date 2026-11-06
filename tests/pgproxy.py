"""A small threaded TCP forwarder used to simulate database outages in tests."""

from __future__ import annotations

import contextlib
import socket
import struct
import threading
import time


class PgProxy:
    """Forwards a fixed local port to an upstream host/port.

    refuse(): close the listener and reset open connections.
    blackhole(): keep accepting, but stop forwarding bytes in both directions.
    restore(): forward again on the same port.
    """

    def __init__(self, upstream_host: str, upstream_port: int) -> None:
        self.upstream = (upstream_host, upstream_port)
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        self.port: int = probe.getsockname()[1]
        probe.close()
        self.mode = "forward"
        self._lock = threading.Lock()
        self._conns: list[socket.socket] = []
        self._listener: socket.socket | None = None
        self._stop = False

    # -- lifecycle -----------------------------------------------------
    def start(self) -> None:
        self._open_listener()

    def stop(self) -> None:
        self._stop = True
        self._close_listener()
        self._reset_connections()

    def _open_listener(self) -> None:
        lst = socket.socket()
        lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        lst.bind(("127.0.0.1", self.port))
        lst.listen(64)
        lst.settimeout(0.2)
        self._listener = lst
        threading.Thread(target=self._accept_loop, args=(lst,), daemon=True).start()

    def _close_listener(self) -> None:
        lst, self._listener = self._listener, None
        if lst is not None:
            with contextlib.suppress(OSError):
                lst.close()

    def _reset_connections(self) -> None:
        with self._lock:
            conns, self._conns = self._conns, []
        for c in conns:
            with contextlib.suppress(OSError):
                c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                c.close()

    # -- modes -----------------------------------------------------------
    def refuse(self) -> None:
        self.mode = "refuse"
        self._close_listener()
        self._reset_connections()

    def blackhole(self) -> None:
        self.mode = "blackhole"
        if self._listener is None:
            self._open_listener()

    def restore(self) -> None:
        self.mode = "forward"
        if self._listener is None:
            self._open_listener()

    # -- forwarding ------------------------------------------------------
    def _accept_loop(self, lst: socket.socket) -> None:
        while not self._stop and self._listener is lst:
            try:
                client, _ = lst.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(client,), daemon=True).start()

    def _serve(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(self.upstream, timeout=5)
        except OSError:
            client.close()
            return
        with self._lock:
            self._conns += [client, upstream]
        for a, b in ((client, upstream), (upstream, client)):
            threading.Thread(target=self._pump, args=(a, b), daemon=True).start()

    def _pump(self, src: socket.socket, dst: socket.socket) -> None:
        src.settimeout(0.2)
        try:
            while not self._stop:
                if self.mode == "blackhole":
                    time.sleep(0.05)
                    continue
                try:
                    data = src.recv(65536)
                except TimeoutError:
                    continue
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                with contextlib.suppress(OSError):
                    s.close()
