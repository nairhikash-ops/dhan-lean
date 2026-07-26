"""Offline Unix-domain-socket transport for the Zerodha historical broker.

This module deliberately owns only local IPC.  It has no HTTP, credential, or
session concerns.  A connection carries one existing protocol frame in each
direction and is then closed.
"""

from __future__ import annotations

import hashlib
import errno
import math
import os
import socket
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from dhan_lean.providers.zerodha.broker_protocol import (
    MAX_REQUEST_PAYLOAD,
    MAX_RESPONSE_PAYLOAD,
    BrokerErrorCode,
    BrokerResponse,
    CandleRequest,
    HistoricalBroker,
    ZerodhaBrokerError,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)


_HEADER_SIZE: Final = 4
_UNIX_PATH_MAX: Final = 100  # Conservative across supported Unix kernels.
_STALE_PROBE_TIMEOUT: Final = 0.1


class UnixTransportConfigurationError(ValueError):
    """Safe configuration rejection; no filesystem details are exposed."""

    def __init__(self) -> None:
        super().__init__("Invalid local broker transport configuration.")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _validate_path(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        raise UnixTransportConfigurationError()
    raw = os.fspath(value)
    if not raw or "\x00" in raw or any(ord(character) < 32 for character in raw):
        raise UnixTransportConfigurationError()
    path = Path(raw)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise UnixTransportConfigurationError()
    if len(os.fsencode(str(path))) > _UNIX_PATH_MAX or path.name in {"", ".", ".."}:
        raise UnixTransportConfigurationError()
    parent = path.parent
    while True:
        try:
            parent_mode = os.lstat(parent).st_mode
        except OSError:
            raise UnixTransportConfigurationError() from None
        if not stat.S_ISDIR(parent_mode) or stat.S_ISLNK(parent_mode):
            raise UnixTransportConfigurationError()
        if parent == parent.parent:
            break
        parent = parent.parent
    return path


def _timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or value > 300:
        raise UnixTransportConfigurationError()
    return float(value)


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise EOFError
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _receive_frame(connection: socket.socket, maximum: int) -> bytes:
    header = _read_exact(connection, _HEADER_SIZE)
    size = int.from_bytes(header, "big")
    if size == 0 or size > maximum:
        raise ValueError
    return header + _read_exact(connection, size)


def _transport_error(code: BrokerErrorCode) -> ZerodhaBrokerError:
    return ZerodhaBrokerError(code)


def _socket_identity(entry: os.stat_result) -> tuple[int, int, int] | None:
    """Return a stable socket identity, or reject non-socket entries."""
    file_type = stat.S_IFMT(entry.st_mode)
    if not stat.S_ISSOCK(entry.st_mode):
        return None
    return (entry.st_dev, entry.st_ino, file_type)


@dataclass(frozen=True, repr=False)
class UnixHistoricalBrokerClient(HistoricalBroker):
    """One-shot AF_UNIX client implementing the existing broker protocol."""

    socket_path: Path | str
    connect_timeout: float = 2.0
    response_timeout: float = 10.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "socket_path", _validate_path(self.socket_path))
        object.__setattr__(self, "connect_timeout", _timeout(self.connect_timeout))
        object.__setattr__(self, "response_timeout", _timeout(self.response_timeout))
        if not hasattr(socket, "AF_UNIX"):
            raise UnixTransportConfigurationError()

    def __repr__(self) -> str:
        return (f"UnixHistoricalBrokerClient(connect_timeout={self.connect_timeout!r}, "
                f"response_timeout={self.response_timeout!r})")

    def fetch_candles(self, request: CandleRequest) -> BrokerResponse:
        if not isinstance(request, CandleRequest):
            raise _transport_error(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        try:
            outbound = encode_request(request)
        except ZerodhaBrokerError:
            raise
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.connect_timeout)
                try:
                    connection.connect(os.fspath(self.socket_path))
                except socket.timeout:
                    raise _transport_error(BrokerErrorCode.BROKER_TIMEOUT) from None
                except OSError:
                    raise _transport_error(BrokerErrorCode.BROKER_UNAVAILABLE) from None
                connection.settimeout(self.response_timeout)
                try:
                    connection.sendall(outbound)
                    inbound = _receive_frame(connection, MAX_RESPONSE_PAYLOAD)
                except socket.timeout:
                    raise _transport_error(BrokerErrorCode.BROKER_TIMEOUT) from None
                except (EOFError, ValueError, OSError):
                    raise _transport_error(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE) from None
        except ZerodhaBrokerError:
            raise
        except OSError:
            raise _transport_error(BrokerErrorCode.BROKER_UNAVAILABLE) from None
        try:
            response = decode_response(inbound)
        except ZerodhaBrokerError:
            raise _transport_error(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE) from None
        if response.request_id != request.request_id:
            raise _transport_error(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        return response


class UnixHistoricalBrokerServer:
    """Bounded local broker server; malformed clients are closed without a reply.

    The configured path must have an already-existing non-symlink parent.  A
    stale cleanup is opt-in and only removes a socket after a failed active
    probe and device/inode revalidation.  Cleanup removes only the path this
    instance successfully bound.
    """

    def __init__(self, socket_path: Path | str, broker: HistoricalBroker, *, backlog: int = 8,
                 max_connections: int = 4, socket_mode: int = 0o660,
                 connection_timeout: float = 5.0, cleanup_stale_socket: bool = False) -> None:
        self.socket_path = _validate_path(socket_path)
        if not hasattr(socket, "AF_UNIX") or not callable(getattr(broker, "fetch_candles", None)):
            raise UnixTransportConfigurationError()
        if type(backlog) is not int or not 1 <= backlog <= 128 or type(max_connections) is not int or not 1 <= max_connections <= 64:
            raise UnixTransportConfigurationError()
        if type(socket_mode) is not int or not 0 <= socket_mode <= 0o777 or not isinstance(cleanup_stale_socket, bool):
            raise UnixTransportConfigurationError()
        self.broker, self.backlog, self.max_connections = broker, backlog, max_connections
        self.socket_mode, self.connection_timeout, self.cleanup_stale_socket = socket_mode, _timeout(connection_timeout), cleanup_stale_socket
        self._listener: socket.socket | None = None
        self._stop = threading.Event()
        self._workers: set[threading.Thread] = set()
        self._connections: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(max_connections)
        self._owned_identity: tuple[int, int, int] | None = None
        self._serve_thread: threading.Thread | None = None

    def __repr__(self) -> str:
        return (f"UnixHistoricalBrokerServer(backlog={self.backlog}, "
                f"max_connections={self.max_connections})")

    def __enter__(self) -> "UnixHistoricalBrokerServer":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()

    def start(self) -> None:
        if self._listener is not None:
            return
        self._remove_stale_socket()
        listener: socket.socket | None = None
        try:
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(os.fspath(self.socket_path))
            identity = self._bound_identity()
            self._owned_identity = identity
            if os.name == "posix":
                os.chmod(self.socket_path, self.socket_mode)
            listener.listen(self.backlog)
            listener.settimeout(0.2)
            self._listener = listener
            self._stop.clear()
        except (OSError, UnixTransportConfigurationError):
            try:
                if listener is not None:
                    listener.close()
            except OSError:
                pass
            self._cleanup_owned()
            raise UnixTransportConfigurationError() from None

    def serve_forever(self) -> None:
        listener = self._listener
        if listener is None:
            raise UnixTransportConfigurationError()
        while not self._stop.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._stop.is_set() or not self._slots.acquire(blocking=False):
                connection.close()
                continue
            worker = threading.Thread(target=self._serve_one, args=(connection,), daemon=True)
            with self._lock:
                self._workers.add(worker)
                self._connections.add(connection)
            worker.start()

    def start_in_thread(self) -> threading.Thread:
        self.start()
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        self._serve_thread = thread
        return thread

    def stop(self, timeout: float | None = None) -> bool:
        """Stop within one total deadline and report whether all threads ended."""
        if timeout is None:
            timeout = self.connection_timeout + 1
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise UnixTransportConfigurationError()
        deadline = time.monotonic() + float(timeout)
        self._stop.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._lock:
            connections = tuple(self._connections)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        serve_thread = self._serve_thread
        if serve_thread is not None and serve_thread is not threading.current_thread():
            serve_thread.join(max(0.0, deadline - time.monotonic()))
            if not serve_thread.is_alive():
                self._serve_thread = None
        with self._lock:
            workers = tuple(self._workers)
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            complete = not any(worker.is_alive() for worker in self._workers)
        if self._serve_thread is not None and self._serve_thread.is_alive():
            complete = False
        self._cleanup_owned()
        return complete

    def _remove_stale_socket(self) -> None:
        try:
            original = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        except OSError:
            raise UnixTransportConfigurationError() from None
        identity = _socket_identity(original)
        if identity is None or not self.cleanup_stale_socket:
            raise UnixTransportConfigurationError()
        outcome = self._probe_existing_socket()
        if outcome is None:
            return
        if not outcome:
            raise UnixTransportConfigurationError()
        self._before_stale_revalidation()
        try:
            current = os.lstat(self.socket_path)
        except FileNotFoundError:
            return
        except OSError:
            raise UnixTransportConfigurationError() from None
        if _socket_identity(current) != identity:
            raise UnixTransportConfigurationError()
        try:
            self.socket_path.unlink()
        except OSError:
            raise UnixTransportConfigurationError() from None

    def _probe_existing_socket(self) -> bool | None:
        """Return True only for a proven stale endpoint; None means vanished."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(_STALE_PROBE_TIMEOUT)
                result = probe.connect_ex(os.fspath(self.socket_path))
        except (socket.timeout, OSError):
            return False
        if result == 0:
            return False
        if result == errno.ENOENT:
            return None
        if result == errno.ECONNREFUSED:
            return True
        # Includes EAGAIN, EWOULDBLOCK, EINPROGRESS, EACCES, resource
        # exhaustion, and unknown platform-specific values: fail closed.
        return False

    def _before_stale_revalidation(self) -> None:
        """Test seam for deterministic identity-change coverage."""

    def _bound_identity(self) -> tuple[int, int, int]:
        try:
            identity = _socket_identity(os.lstat(self.socket_path))
        except OSError:
            raise UnixTransportConfigurationError() from None
        if identity is None:
            raise UnixTransportConfigurationError()
        return identity

    def _cleanup_owned(self) -> None:
        identity = self._owned_identity
        if identity is None:
            return
        try:
            if _socket_identity(os.lstat(self.socket_path)) == identity:
                self.socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        self._owned_identity = None

    def _serve_one(self, connection: socket.socket) -> None:
        current = threading.current_thread()
        try:
            with connection:
                connection.settimeout(self.connection_timeout)
                try:
                    request = decode_request(_receive_frame(connection, MAX_REQUEST_PAYLOAD))
                except (ZerodhaBrokerError, EOFError, ValueError, OSError, socket.timeout):
                    return
                try:
                    response = self.broker.fetch_candles(request)
                    if not isinstance(response, BrokerResponse) or response.request_id != request.request_id:
                        raise RuntimeError
                except ZerodhaBrokerError as error:
                    response = self._local_failure(request, error.code)
                except Exception:
                    response = self._local_failure(request, BrokerErrorCode.INTERNAL_BROKER_FAILURE)
                try:
                    connection.sendall(encode_response(response))
                except (ZerodhaBrokerError, OSError, socket.timeout):
                    return
        finally:
            self._slots.release()
            with self._lock:
                self._workers.discard(current)
                self._connections.discard(connection)

    @staticmethod
    def _local_failure(request: CandleRequest, code: BrokerErrorCode) -> BrokerResponse:
        return BrokerResponse(1, request.request_id, str(uuid.uuid4()), "BROKER_FAILURE", None,
                              "READY", datetime.now(timezone.utc), b"", 0,
                              hashlib.sha256(b"").hexdigest(), False, None, code, {})
