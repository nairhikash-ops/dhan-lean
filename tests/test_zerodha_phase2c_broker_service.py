"""Offline application-lifecycle coverage for the Phase 2C.2 broker service."""

import contextlib
import io
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dhan_lean.providers.zerodha import (
    BrokerServiceConfig, BrokerServiceExitStatus, BrokerServiceResult, DeterministicFakeBroker,
    UnixHistoricalBrokerClient, UnixHistoricalBrokerServer, run_broker_service,
)
from dhan_lean.providers.zerodha.broker_service import _SignalHandlers, main
from dhan_lean.providers.zerodha.broker_protocol import BrokerErrorCode, CandleRequest, ZerodhaBrokerError


ROOT = Path(__file__).parent.parent
REQUEST_ID = "12345678-1234-4678-8123-123456789abc"


def request():
    from datetime import datetime, timezone
    return CandleRequest(1, REQUEST_ID, "123", "minute",
                         datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc),
                         datetime(2026, 7, 20, 9, 17, tzinfo=timezone.utc), False, False)


class TestBrokerServiceConfiguration(unittest.TestCase):
    def test_help_and_invalid_cli_are_safe_without_socket_creation(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--help"]), 0)
        self.assertIn("--fake-upstream", output.getvalue())
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--socket-path", "/secret/socket"]),
                             int(BrokerServiceExitStatus.INVALID_CONFIGURATION))
        self.assertNotIn("/secret/socket", output.getvalue())

    def test_configuration_rejects_unsafe_values_and_safe_repr(self):
        for changes in ({"socket_path": "relative.sock"}, {"backlog": 0},
                        {"maximum_connections": 65}, {"socket_mode": 0o1000},
                        {"connection_timeout": 0}, {"shutdown_timeout": 0},
                        {"log_level": "debug"}):
            values = {"socket_path": Path("/tmp/broker.sock"), "fake_upstream": True}
            values.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaises(Exception):
                    BrokerServiceConfig(**values)
        safe_path = Path(tempfile.gettempdir()) / "broker.sock"
        self.assertNotIn(str(safe_path), repr(BrokerServiceConfig(safe_path, fake_upstream=True)))

    def test_runner_rejects_missing_fake_mode_before_start(self):
        events = []
        result = run_broker_service(BrokerServiceConfig(Path(tempfile.gettempdir()) / "broker.sock"), DeterministicFakeBroker([]),
                                    event_callback=events.append)
        self.assertEqual(result.exit_status, BrokerServiceExitStatus.INVALID_CONFIGURATION)
        self.assertFalse(result.readiness_reached)
        self.assertEqual(events, ["broker_service_configuration_failed"])

    def test_logger_failure_is_ignored_and_result_is_safe(self):
        event = threading.Event(); event.set()
        config = BrokerServiceConfig(Path(tempfile.gettempdir()) / "broker.sock", fake_upstream=True)
        if not hasattr(socket, "AF_UNIX"):
            result = run_broker_service(config, DeterministicFakeBroker([]), shutdown_event=event,
                                        event_callback=lambda _event: (_ for _ in ()).throw(RuntimeError("token")))
            self.assertEqual(result.exit_status, BrokerServiceExitStatus.UNSUPPORTED_PLATFORM)

    def test_partial_signal_installation_restores_previous_handler(self):
        if not hasattr(signal, "SIGTERM"):
            self.skipTest("SIGTERM is unavailable")
        original_int, original_term = object(), object()
        calls = []
        def get_handler(value):
            return original_int if value == signal.SIGINT else original_term
        def set_handler(value, handler):
            calls.append((value, handler))
            if value == signal.SIGTERM and handler is not original_term:
                raise RuntimeError("secret signal error")
        with patch("dhan_lean.providers.zerodha.broker_service.signal.getsignal", side_effect=get_handler), \
             patch("dhan_lean.providers.zerodha.broker_service.signal.signal", side_effect=set_handler):
            with self.assertRaises(RuntimeError):
                _SignalHandlers(threading.Event(), True).__enter__()
        self.assertIn((signal.SIGINT, original_int), calls)

    def test_result_invariants_reject_contradictory_states(self):
        with self.assertRaises(Exception):
            BrokerServiceResult(BrokerServiceExitStatus.CLEAN_SHUTDOWN, False, True,
                                "broker_service_stopped")


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "AF_UNIX is unavailable")
class TestBrokerServiceUnixLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "broker.sock"

    def tearDown(self):
        self.temp.cleanup()

    def config(self, **changes):
        values = {"socket_path": self.path, "fake_upstream": True, "connection_timeout": 0.2,
                  "shutdown_timeout": 2.0}
        values.update(changes)
        return BrokerServiceConfig(**values)

    def test_in_process_shutdown_event_orders_events_and_removes_socket(self):
        events, stop = [], threading.Event()
        def run():
            self.result = run_broker_service(self.config(), DeterministicFakeBroker([], allow_unexpected=True),
                                             shutdown_event=stop, event_callback=events.append,
                                             install_signal_handlers=False)
        thread = threading.Thread(target=run)
        thread.start()
        while "broker_service_ready" not in events:
            thread.join(0.01)
            self.assertTrue(thread.is_alive())
        self.assertTrue(self.path.exists())
        stop.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.result.exit_status, BrokerServiceExitStatus.CLEAN_SHUTDOWN)
        self.assertEqual(events.count("broker_service_ready"), 1)
        self.assertEqual(events[-2:], ["broker_service_stopping", "broker_service_stopped"])
        self.assertFalse(self.path.exists())

    def test_malformed_and_broker_failures_do_not_end_service(self):
        events, stop = [], threading.Event()
        def run():
            self.result = run_broker_service(self.config(), DeterministicFakeBroker([
                ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)], allow_unexpected=True),
                shutdown_event=stop, event_callback=events.append, install_signal_handlers=False)
        thread = threading.Thread(target=run); thread.start()
        while "broker_service_ready" not in events:
            thread.join(0.01)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.connect(os.fspath(self.path)); raw.sendall(b"\x00\x00\x00\x03bad")
        client = UnixHistoricalBrokerClient(self.path, response_timeout=1)
        self.assertEqual(client.fetch_candles(request()).error_code, BrokerErrorCode.BROKER_TIMEOUT)
        self.assertEqual(client.fetch_candles(request()).provider_http_status, 200)
        stop.set(); thread.join(3)
        self.assertEqual(self.result.exit_status, BrokerServiceExitStatus.CLEAN_SHUTDOWN)

    def test_previous_signal_handler_is_restored(self):
        original = signal.getsignal(signal.SIGINT)
        stop = threading.Event(); stop.set()
        run_broker_service(self.config(), DeterministicFakeBroker([]), shutdown_event=stop,
                           install_signal_handlers=True)
        self.assertIs(signal.getsignal(signal.SIGINT), original)

    def test_readiness_delivery_failure_aborts_without_socket_or_ready_state(self):
        for label in ("raise", "flush"):
            with self.subTest(label=label):
                events = []
                def callback(event):
                    if event == "broker_service_ready":
                        if label == "flush":
                            io.StringIO().write("ready")
                        raise RuntimeError("fake-token /absolute/path body-bytes")
                    events.append(event)
                result = run_broker_service(self.config(), DeterministicFakeBroker([]),
                                            event_callback=callback, install_signal_handlers=False)
                self.assertEqual(result.exit_status, BrokerServiceExitStatus.STARTUP_FAILURE)
                self.assertFalse(result.readiness_reached)
                self.assertNotIn("broker_service_ready", events)
                self.assertFalse(self.path.exists())
                self.assertNotIn("fake-token", repr(result))

    def test_uncooperative_broker_returns_bounded_runtime_failure(self):
        entered, release, stop = threading.Event(), threading.Event(), threading.Event()
        class BlockingBroker:
            def fetch_candles(self, _request):
                entered.set(); release.wait()
                raise ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)
        events = []
        def run():
            self.result = run_broker_service(self.config(shutdown_timeout=0.25), BlockingBroker(),
                                             shutdown_event=stop, event_callback=events.append,
                                             install_signal_handlers=False)
        service_thread = threading.Thread(target=run); service_thread.start()
        while "broker_service_ready" not in events:
            service_thread.join(0.01)
        client_thread = threading.Thread(target=lambda: self._ignored_client_error())
        client_thread.start()
        self.assertTrue(entered.wait(1))
        started = time.monotonic(); stop.set(); service_thread.join(1)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertFalse(service_thread.is_alive())
        self.assertEqual(self.result.exit_status, BrokerServiceExitStatus.RUNTIME_FAILURE)
        self.assertNotIn("broker_service_stopped", events)
        self.assertEqual(events[-1], "broker_service_runtime_failed")
        release.set(); client_thread.join(1)

    def _ignored_client_error(self):
        try:
            UnixHistoricalBrokerClient(self.path, response_timeout=1).fetch_candles(request())
        except ZerodhaBrokerError:
            pass

    def test_subprocess_ready_sigterm_and_bind_collision(self):
        command = [sys.executable, "-B", "-m", "dhan_lean.providers.zerodha.broker_service",
                   "--socket-path", os.fspath(self.path), "--fake-upstream", "--connection-timeout", "0.2"]
        first = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: first.poll() is None and first.kill())
        lines = []
        while "{\"event\":\"broker_service_ready\"}" not in lines:
            line = first.stdout.readline().strip()
            self.assertTrue(line)
            lines.append(line)
        client = UnixHistoricalBrokerClient(self.path, response_timeout=1)
        self.assertEqual(client.fetch_candles(request()).provider_http_status, 200)
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(second.returncode, int(BrokerServiceExitStatus.STARTUP_FAILURE))
        self.assertNotIn("broker_service_ready", second.stdout)
        self.assertEqual(client.fetch_candles(request()).provider_http_status, 200)
        first.send_signal(signal.SIGTERM)
        self.assertEqual(first.wait(5), int(BrokerServiceExitStatus.CLEAN_SHUTDOWN))
        lines.extend(line.strip() for line in first.stdout.readlines())
        self.assertEqual(lines.count('{"event":"broker_service_ready"}'), 1)
        self.assertIn('{"event":"broker_service_stopping"}', lines)
        self.assertIn('{"event":"broker_service_stopped"}', lines)
        self.assertFalse(self.path.exists())
        first.stdout.close(); first.stderr.close()

    def test_subprocess_sigint_and_stale_policy(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(os.fspath(self.path))
        command = [sys.executable, "-B", "-m", "dhan_lean.providers.zerodha.broker_service",
                   "--socket-path", os.fspath(self.path), "--fake-upstream", "--connection-timeout", "0.2"]
        refused = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertEqual(refused.returncode, int(BrokerServiceExitStatus.STARTUP_FAILURE))
        self.assertTrue(self.path.exists())
        command.append("--cleanup-stale-socket")
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        while True:
            line = process.stdout.readline().strip()
            self.assertTrue(line)
            if line == '{"event":"broker_service_ready"}':
                break
        process.send_signal(signal.SIGINT)
        self.assertEqual(process.wait(5), int(BrokerServiceExitStatus.CLEAN_SHUTDOWN))
        self.assertFalse(self.path.exists())
        process.stdout.close(); process.stderr.close()


if __name__ == "__main__":
    unittest.main()
