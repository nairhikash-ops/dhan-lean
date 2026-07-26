"""Project-wide offline test guard.

Importing the ``tests`` package installs process-wide protections used by the
normal unittest discovery command. Local loopback servers remain available for
tests such as the token-admin service; external network access never is.
"""

import socket
import urllib.parse
import urllib.request


class UnexpectedNetworkAttempt(AssertionError):
    """Raised when a project-owned test attempts external network access."""


def _is_loopback(host: object) -> bool:
    return str(host).strip("[]").lower() in {"localhost", "127.0.0.1", "::1"}


_original_socket_connect = socket.socket.connect
_original_socket_connect_ex = socket.socket.connect_ex
_original_urlopen = urllib.request.urlopen


def _guarded_socket_connect(sock: socket.socket, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return _original_socket_connect(sock, address)
    host = address[0] if isinstance(address, tuple) and address else address
    if not _is_loopback(host):
        raise UnexpectedNetworkAttempt(
            f"Unexpected external socket connection blocked by test guard: {host!r}"
        )
    return _original_socket_connect(sock, address)


def _guarded_socket_connect_ex(sock: socket.socket, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return _original_socket_connect_ex(sock, address)
    host = address[0] if isinstance(address, tuple) and address else address
    if not _is_loopback(host):
        raise UnexpectedNetworkAttempt(
            f"Unexpected external socket connection blocked by test guard: {host!r}"
        )
    return _original_socket_connect_ex(sock, address)


def _guarded_urlopen(url, *args, **kwargs):
    target = getattr(url, "full_url", url)
    parsed = urllib.parse.urlparse(str(target))
    if not _is_loopback(parsed.hostname or ""):
        raise UnexpectedNetworkAttempt(
            f"Unexpected external urlopen blocked by test guard: {target!r}"
        )
    return _original_urlopen(url, *args, **kwargs)


if not getattr(socket.socket.connect, "_offline_test_guard", False):
    _guarded_socket_connect._offline_test_guard = True
    _guarded_socket_connect_ex._offline_test_guard = True
    socket.socket.connect = _guarded_socket_connect
    socket.socket.connect_ex = _guarded_socket_connect_ex
    urllib.request.urlopen = _guarded_urlopen
