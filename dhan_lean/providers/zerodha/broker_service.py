"""Development-only offline application shell for the Unix historical broker."""

from __future__ import annotations

import argparse
import json
import math
import signal
import socket
import sys
import threading
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable, Sequence

from dhan_lean.providers.zerodha.broker_protocol import HistoricalBroker
from dhan_lean.providers.zerodha.fake_broker import DeterministicFakeBroker
from dhan_lean.providers.zerodha.unix_transport import (
    UnixHistoricalBrokerServer,
    UnixTransportConfigurationError,
    _validate_path,
)


_LOG_LEVELS = frozenset({"quiet", "normal", "verbose"})
_EVENTS = frozenset({
    "broker_service_starting", "broker_service_ready", "broker_service_shutdown_requested",
    "broker_service_stopping", "broker_service_stopped", "broker_service_configuration_failed",
    "broker_service_startup_failed", "broker_service_runtime_failed",
})


class BrokerServiceExitStatus(IntEnum):
    CLEAN_SHUTDOWN = 0
    INVALID_CONFIGURATION = 2
    STARTUP_FAILURE = 3
    RUNTIME_FAILURE = 4
    UNSUPPORTED_PLATFORM = 5


class BrokerServiceError(ValueError):
    """Sanitized service application error."""

    def __init__(self, code: str = "BROKER_SERVICE_CONFIGURATION_ERROR") -> None:
        self.code = code
        super().__init__("Invalid offline broker-service configuration.")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r})"


@dataclass(frozen=True, repr=False)
class BrokerServiceConfig:
    socket_path: Path | str
    socket_mode: int = 0o660
    backlog: int = 8
    maximum_connections: int = 4
    connection_timeout: float = 5.0
    shutdown_timeout: float = 10.0
    cleanup_stale_socket: bool = False
    log_level: str = "normal"
    fake_upstream: bool = False

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "socket_path", _validate_path(self.socket_path))
        except UnixTransportConfigurationError:
            raise BrokerServiceError()
        if type(self.socket_mode) is not int or not 0 <= self.socket_mode <= 0o777:
            raise BrokerServiceError()
        if type(self.backlog) is not int or not 1 <= self.backlog <= 128:
            raise BrokerServiceError()
        if type(self.maximum_connections) is not int or not 1 <= self.maximum_connections <= 64:
            raise BrokerServiceError()
        for value in (self.connection_timeout, self.shutdown_timeout):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 300:
                raise BrokerServiceError()
        if not isinstance(self.cleanup_stale_socket, bool) or not isinstance(self.fake_upstream, bool):
            raise BrokerServiceError()
        if not isinstance(self.log_level, str) or self.log_level not in _LOG_LEVELS:
            raise BrokerServiceError()

    def __repr__(self) -> str:
        return ("BrokerServiceConfig(socket_mode=%r, backlog=%r, maximum_connections=%r, "
                "connection_timeout=%r, shutdown_timeout=%r, cleanup_stale_socket=%r, "
                "log_level=%r, fake_upstream=%r)" % (
                    self.socket_mode, self.backlog, self.maximum_connections,
                    self.connection_timeout, self.shutdown_timeout,
                    self.cleanup_stale_socket, self.log_level, self.fake_upstream))


@dataclass(frozen=True, repr=False)
class BrokerServiceResult:
    exit_status: BrokerServiceExitStatus
    readiness_reached: bool
    shutdown_requested: bool
    terminal_event: str

    def __post_init__(self) -> None:
        if not isinstance(self.exit_status, BrokerServiceExitStatus) or self.terminal_event not in _EVENTS:
            raise BrokerServiceError()
        expected = {
            BrokerServiceExitStatus.CLEAN_SHUTDOWN: (True, "broker_service_stopped"),
            BrokerServiceExitStatus.INVALID_CONFIGURATION: (False, "broker_service_configuration_failed"),
            BrokerServiceExitStatus.STARTUP_FAILURE: (False, "broker_service_startup_failed"),
            BrokerServiceExitStatus.RUNTIME_FAILURE: (True, "broker_service_runtime_failed"),
            BrokerServiceExitStatus.UNSUPPORTED_PLATFORM: (False, "broker_service_startup_failed"),
        }
        ready, event = expected[self.exit_status]
        if self.readiness_reached is not ready or self.terminal_event != event or type(self.shutdown_requested) is not bool:
            raise BrokerServiceError()

    def __repr__(self) -> str:
        return (f"BrokerServiceResult(exit_status={self.exit_status.name!r}, "
                f"readiness_reached={self.readiness_reached!r}, "
                f"shutdown_requested={self.shutdown_requested!r}, "
                f"terminal_event={self.terminal_event!r})")


EventCallback = Callable[[str], None]


def _emit(callback: EventCallback | None, event: str) -> None:
    """Logging is best effort: a logger failure cannot keep the service alive."""
    if callback is None or event not in _EVENTS:
        return
    try:
        callback(event)
    except Exception:
        pass


def _publish_readiness(callback: EventCallback | None) -> None:
    """Readiness is mandatory because external supervision waits for it."""
    if callback is not None:
        callback("broker_service_ready")


class _SignalHandlers:
    def __init__(self, shutdown_event: threading.Event, enabled: bool) -> None:
        self._event = shutdown_event
        self._enabled = enabled and threading.current_thread() is threading.main_thread()
        self._previous: dict[int, object] = {}

    def __enter__(self) -> "_SignalHandlers":
        if not self._enabled:
            return self
        signals = [signal.SIGINT]
        if hasattr(signal, "SIGTERM"):
            signals.append(signal.SIGTERM)
        try:
            for value in signals:
                self._previous[value] = signal.getsignal(value)
                signal.signal(value, self._handle)
        except Exception:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        for value, previous in self._previous.items():
            try:
                signal.signal(value, previous)
            except (ValueError, OSError):
                pass

    def _handle(self, _signum: int, _frame: object) -> None:
        self._event.set()


def run_broker_service(
    config: BrokerServiceConfig,
    broker: HistoricalBroker,
    *,
    shutdown_event: threading.Event | None = None,
    event_callback: EventCallback | None = None,
    install_signal_handlers: bool = True,
    poll_interval: float = 0.05,
) -> BrokerServiceResult:
    """Run the fake-only local broker until a shutdown event or service fault."""
    if not isinstance(config, BrokerServiceConfig) or not config.fake_upstream:
        _emit(event_callback, "broker_service_configuration_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.INVALID_CONFIGURATION, False, False,
                                   "broker_service_configuration_failed")
    if not hasattr(socket, "AF_UNIX"):
        _emit(event_callback, "broker_service_startup_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.UNSUPPORTED_PLATFORM, False, False,
                                   "broker_service_startup_failed")
    if not callable(getattr(broker, "fetch_candles", None)):
        _emit(event_callback, "broker_service_startup_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.STARTUP_FAILURE, False, False,
                                   "broker_service_startup_failed")
    if isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float)) or not 0 < poll_interval <= 1:
        _emit(event_callback, "broker_service_configuration_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.INVALID_CONFIGURATION, False, False,
                                   "broker_service_configuration_failed")
    requested = shutdown_event or threading.Event()
    try:
        server = UnixHistoricalBrokerServer(
            config.socket_path, broker, backlog=config.backlog,
            max_connections=config.maximum_connections, socket_mode=config.socket_mode,
            connection_timeout=float(config.connection_timeout),
            cleanup_stale_socket=config.cleanup_stale_socket,
        )
    except UnixTransportConfigurationError:
        _emit(event_callback, "broker_service_configuration_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.INVALID_CONFIGURATION, False, False,
                                   "broker_service_configuration_failed")
    shutdown_requested = False
    runtime_failure = False
    ready = False
    try:
        with _SignalHandlers(requested, install_signal_handlers):
            _emit(event_callback, "broker_service_starting")
            try:
                server.start()
            except UnixTransportConfigurationError:
                _emit(event_callback, "broker_service_startup_failed")
                return BrokerServiceResult(BrokerServiceExitStatus.STARTUP_FAILURE, False, False,
                                           "broker_service_startup_failed")
            try:
                _publish_readiness(event_callback)
            except Exception:
                server.stop(config.shutdown_timeout)
                _emit(event_callback, "broker_service_startup_failed")
                return BrokerServiceResult(BrokerServiceExitStatus.STARTUP_FAILURE, False, False,
                                           "broker_service_startup_failed")
            ready = True
            thread = server.start_in_thread()
            while not requested.wait(float(poll_interval)):
                if not thread.is_alive():
                    runtime_failure = True
                    break
            shutdown_requested = requested.is_set()
            if shutdown_requested:
                _emit(event_callback, "broker_service_shutdown_requested")
    except Exception:
        if not ready:
            try:
                server.stop(config.shutdown_timeout)
            except Exception:
                pass
            _emit(event_callback, "broker_service_startup_failed")
            return BrokerServiceResult(BrokerServiceExitStatus.STARTUP_FAILURE, False, False,
                                       "broker_service_startup_failed")
        runtime_failure = True
    _emit(event_callback, "broker_service_stopping")
    try:
        complete = server.stop(config.shutdown_timeout)
    except Exception:
        complete = False
    if runtime_failure or not complete:
        _emit(event_callback, "broker_service_runtime_failed")
        return BrokerServiceResult(BrokerServiceExitStatus.RUNTIME_FAILURE, ready, shutdown_requested,
                                   "broker_service_runtime_failed")
    _emit(event_callback, "broker_service_stopped")
    return BrokerServiceResult(BrokerServiceExitStatus.CLEAN_SHUTDOWN, ready, shutdown_requested,
                               "broker_service_stopped")


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise BrokerServiceError("BROKER_SERVICE_CLI_USAGE")


def _parse_mode(value: str) -> int:
    try:
        parsed = int(value, 8)
    except ValueError:
        raise argparse.ArgumentTypeError("invalid mode") from None
    if not 0 <= parsed <= 0o777:
        raise argparse.ArgumentTypeError("invalid mode")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(add_help=True, allow_abbrev=False)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--fake-upstream", action="store_true")
    parser.add_argument("--socket-mode", type=_parse_mode, default=0o660)
    parser.add_argument("--backlog", type=int, default=8)
    parser.add_argument("--maximum-connections", type=int, default=4)
    parser.add_argument("--connection-timeout", type=float, default=5.0)
    parser.add_argument("--shutdown-timeout", type=float, default=10.0)
    parser.add_argument("--cleanup-stale-socket", action="store_true")
    parser.add_argument("--log-level", choices=tuple(sorted(_LOG_LEVELS)), default="normal")
    return parser


def _stdout_event(event: str) -> None:
    sys.stdout.write(json.dumps({"event": event}, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    try:
        parsed = parser.parse_args(argv)
        config = BrokerServiceConfig(
            parsed.socket_path, socket_mode=parsed.socket_mode, backlog=parsed.backlog,
            maximum_connections=parsed.maximum_connections,
            connection_timeout=parsed.connection_timeout, shutdown_timeout=parsed.shutdown_timeout,
            cleanup_stale_socket=parsed.cleanup_stale_socket, log_level=parsed.log_level,
            fake_upstream=parsed.fake_upstream,
        )
        if not config.fake_upstream:
            raise BrokerServiceError("BROKER_SERVICE_FAKE_UPSTREAM_REQUIRED")
    except SystemExit as exc:
        if exc.code == 0:
            return int(BrokerServiceExitStatus.CLEAN_SHUTDOWN)
        _stdout_event("broker_service_configuration_failed")
        return int(BrokerServiceExitStatus.INVALID_CONFIGURATION)
    except BrokerServiceError:
        _stdout_event("broker_service_configuration_failed")
        return int(BrokerServiceExitStatus.INVALID_CONFIGURATION)
    try:
        broker = DeterministicFakeBroker([], allow_unexpected=True)
    except Exception:
        _stdout_event("broker_service_startup_failed")
        return int(BrokerServiceExitStatus.STARTUP_FAILURE)
    result = run_broker_service(config, broker, event_callback=_stdout_event)
    return int(result.exit_status)


if __name__ == "__main__":
    raise SystemExit(main())
