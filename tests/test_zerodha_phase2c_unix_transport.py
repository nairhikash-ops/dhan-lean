"""Offline Unix-domain socket coverage for Zerodha Phase 2C.1."""

import os
import socket
import stat
import tempfile
import threading
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from dhan_lean.data.models import DataWorkItem, TimeWindow
from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.providers.zerodha import (
    BrokerErrorCode, BrokerResponse, CandleRequest, DeterministicFakeBroker,
    RetryPolicy, SessionState, UnixHistoricalBrokerClient,
    UnixHistoricalBrokerServer, UnixTransportConfigurationError,
    ZerodhaBrokerError, ZerodhaHistoricalAdapter, ZerodhaHistoricalAdapterInput,
)
from dhan_lean.providers.zerodha.instruments import parse_instrument_snapshot
from tests import UnexpectedNetworkAttempt


ID_A = "12345678-1234-4678-8123-123456789abc"
ID_B = "87654321-4321-4876-8123-cba987654321"
CAPTURED = datetime(2026, 7, 20, 4, tzinfo=timezone.utc)
ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures" / "zerodha"


def request(request_id=ID_A):
    return CandleRequest(1, request_id, "123", "minute",
                         datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc),
                         datetime(2026, 7, 20, 9, 17, tzinfo=timezone.utc), False, False)


def response(request_id, body, *, status=200, error_code=None):
    return BrokerResponse.for_provider(request_id=request_id, broker_request_id=ID_B,
        captured_at=CAPTURED, status=status, body=body, error_code=error_code)


@unittest.skipUnless(hasattr(socket, "AF_UNIX"), "AF_UNIX is unavailable")
class TestUnixHistoricalBrokerTransport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "historical.sock"
        self.server = None

    def tearDown(self):
        if self.server:
            self.server.stop()
        self.temp.cleanup()

    def running(self, broker, **kwargs):
        self.server = UnixHistoricalBrokerServer(self.path, broker, **kwargs)
        self.server.start_in_thread()
        return UnixHistoricalBrokerClient(self.path, connect_timeout=0.5, response_timeout=0.5)

    def test_round_trip_preserves_binary_empty_and_malformed_bytes(self):
        for body in (b"", b"\xff\x00binary", b"not-json"):
            with self.subTest(body=body):
                fake = DeterministicFakeBroker([lambda value, _, b=body: response(value.request_id, b)])
                client = self.running(fake)
                received = client.fetch_candles(request())
                self.assertEqual(received.body, body)
                self.assertEqual(fake.call_count, 1)
                self.server.stop()
                self.server = None

    def test_provider_error_is_transported_unchanged(self):
        fake = DeterministicFakeBroker([lambda value, _: response(value.request_id, b"limited", status=429,
            error_code=BrokerErrorCode.PROVIDER_429)])
        received = self.running(fake).fetch_candles(request())
        self.assertEqual((received.provider_http_status, received.error_code, received.body),
                         (429, BrokerErrorCode.PROVIDER_429, b"limited"))

    def test_missing_socket_is_safe_unavailable_error(self):
        client = UnixHistoricalBrokerClient(self.path, connect_timeout=0.1, response_timeout=0.1)
        with self.assertRaises(ZerodhaBrokerError) as captured:
            client.fetch_candles(request())
        self.assertEqual(captured.exception.code, BrokerErrorCode.BROKER_UNAVAILABLE)
        self.assertNotIn(str(self.path), repr(captured.exception))

    def test_malformed_connection_does_not_call_broker_or_kill_server(self):
        fake = DeterministicFakeBroker([lambda value, _: response(value.request_id, b"ok")])
        client = self.running(fake)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as raw:
            raw.connect(os.fspath(self.path))
            raw.sendall(b"\x00\x00\x00\x03bad")
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(client.fetch_candles(request()).body, b"ok")
        self.assertEqual(fake.call_count, 1)

    def test_truncated_response_and_timeout_are_safe(self):
        # A controlled local socket server sends an incomplete frame.
        ready = threading.Event()
        def truncated():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(os.fspath(self.path)); listener.listen(1); ready.set()
                connection, _ = listener.accept()
                with connection:
                    connection.recv(4096); connection.sendall(b"\x00\x00")
        thread = threading.Thread(target=truncated); thread.start(); ready.wait(1)
        with self.assertRaises(ZerodhaBrokerError) as captured:
            UnixHistoricalBrokerClient(self.path, response_timeout=0.2).fetch_candles(request())
        thread.join(1)
        self.assertEqual(captured.exception.code, BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)

    def test_existing_non_socket_entries_are_rejected_and_owned_cleanup_is_scoped(self):
        self.path.write_bytes(b"not a socket")
        with self.assertRaises(UnixTransportConfigurationError):
            UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([])).start()
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaises(UnixTransportConfigurationError):
            UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([])).start()
        self.path.rmdir()
        client = self.running(DeterministicFakeBroker([]))
        self.assertTrue(self.path.exists())
        self.server.stop(); self.server = None
        self.assertFalse(self.path.exists())
        self.assertTrue(self.root.exists())

    @unittest.skipUnless(os.name == "posix", "POSIX socket permissions are unavailable")
    def test_configured_socket_mode_is_applied(self):
        self.running(DeterministicFakeBroker([]), socket_mode=0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_concurrent_requests_remain_correlated(self):
        fake = DeterministicFakeBroker([lambda value, _: response(value.request_id, value.request_id.encode()),
                                        lambda value, _: response(value.request_id, value.request_id.encode())])
        client = self.running(fake, max_connections=2)
        results = []
        def call(value): results.append(client.fetch_candles(request(value)))
        threads = [threading.Thread(target=call, args=(value,)) for value in (ID_A, ID_B)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(1)
        self.assertEqual({result.request_id for result in results}, {ID_A, ID_B})
        self.assertEqual({result.body.decode() for result in results}, {ID_A, ID_B})

    def test_adapter_retry_owns_two_calls_budgets_and_artifacts(self):
        snapshot = parse_instrument_snapshot((FIXTURES / "instrument_master.csv").read_bytes(), date(2026, 7, 20))
        body = (FIXTURES / "historical_valid.json").read_bytes()
        fake = DeterministicFakeBroker([
            lambda value, _: response(value.request_id, b"limited", status=429, error_code=BrokerErrorCode.PROVIDER_429),
            lambda value, _: response(value.request_id, body),
        ])
        client = self.running(fake)
        budget = RequestBudget(self.root / "budget.sqlite"); budget.configure("socket", "window", 2)
        adapter = ZerodhaHistoricalAdapter(ZerodhaHistoricalAdapterInput(
            snapshot, "NSE", instrument_type="EQ", storage_root=self.root, run_id="20260720T040000Z",
            retry_policy=RetryPolicy(maximum_attempts=2, budget_scope="socket", budget_window_id="window"),
            request_budget=budget, broker=client, request_id_factory=iter((ID_A, ID_B)).__next__,
            planning_request_id_factory=lambda: ID_A))
        item = DataWorkItem("ACME", "zerodha", "1m", date(2026, 7, 20),
            TimeWindow(datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc), datetime(2026, 7, 20, 9, 17, tzinfo=timezone.utc)), Path("ignored"), "work")
        result = adapter.run(item)
        self.assertEqual((fake.call_count, budget.snapshot("socket", "window").consumed), (2, 2))
        self.assertEqual(len(result.artifact_publications), 2)
        self.assertEqual(len(result.bars), 2)
        self.assertNotEqual(result.attempt_history[0].request_id, result.attempt_history[1].request_id)
        self.assertEqual(len({record.planned_fingerprint for record in result.attempt_history}), 1)
        final = self.root / result.artifact_publications[1].artifact_relative_path / "response-body.bin"
        self.assertEqual(final.read_bytes(), body)

    def test_server_converts_unexpected_broker_exception_without_dying(self):
        def raises(_value, _index):
            raise RuntimeError("secret")
        fake = DeterministicFakeBroker([raises, lambda value, _: response(value.request_id, b"ok")])
        client = self.running(fake)
        first = client.fetch_candles(request())
        self.assertEqual(first.error_code, BrokerErrorCode.INTERNAL_BROKER_FAILURE)
        self.assertEqual(client.fetch_candles(request(ID_B)).body, b"ok")

    def test_active_endpoint_is_never_unlinked_by_stale_cleanup(self):
        fake = DeterministicFakeBroker([
            lambda value, _: response(value.request_id, b"first"),
            lambda value, _: response(value.request_id, b"second"),
        ])
        client = self.running(fake)
        self.assertEqual(client.fetch_candles(request()).body, b"first")
        other = UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([]), cleanup_stale_socket=True)
        with self.assertRaises(UnixTransportConfigurationError):
            other.start()
        self.assertTrue(self.path.exists())
        self.assertEqual(client.fetch_candles(request(ID_B)).body, b"second")
        self.server.stop(); self.server = None
        self.assertFalse(self.path.exists())

    def test_genuine_stale_socket_requires_explicit_cleanup(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(os.fspath(self.path))
        with self.assertRaises(UnixTransportConfigurationError):
            UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([])).start()
        self.assertTrue(self.path.exists())
        client = self.running(DeterministicFakeBroker([lambda value, _: response(value.request_id, b"fresh")]),
                              cleanup_stale_socket=True)
        self.assertEqual(client.fetch_candles(request()).body, b"fresh")
        self.server.stop(); self.server = None
        self.assertFalse(self.path.exists())

    def test_identity_change_before_stale_unlink_fails_closed(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(os.fspath(self.path))
        server = UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([]), cleanup_stale_socket=True)
        def replace_entry():
            self.path.unlink()
            self.path.write_bytes(b"replacement")
        server._before_stale_revalidation = replace_entry
        with self.assertRaises(UnixTransportConfigurationError):
            server.start()
        self.assertEqual(self.path.read_bytes(), b"replacement")
        self.assertIsNone(server._listener)

    def test_owned_cleanup_does_not_remove_replacement(self):
        self.running(DeterministicFakeBroker([]))
        self.path.unlink()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as replacement:
            replacement.bind(os.fspath(self.path))
            self.server.stop(); self.server = None
            self.assertTrue(self.path.exists())

    def test_stop_uses_one_deadline_for_multiple_blocked_connections(self):
        self.server = UnixHistoricalBrokerServer(self.path, DeterministicFakeBroker([]),
                                                  max_connections=4, connection_timeout=5)
        self.server.start_in_thread()
        clients = []
        try:
            for _ in range(4):
                client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                client.connect(os.fspath(self.path)); client.sendall(b"\x00\x00")
                clients.append(client)
            limit = time.monotonic() + 1
            while True:
                with self.server._lock:
                    count = len(self.server._workers)
                if count == 4:
                    break
                self.assertLess(time.monotonic(), limit)
                time.sleep(0.01)
            started = time.monotonic()
            self.assertTrue(self.server.stop(timeout=0.25))
            self.assertLess(time.monotonic() - started, 0.7)
            self.assertTrue(self.server.stop(timeout=0))
            self.server = None
            self.assertFalse(self.path.exists())
        finally:
            for client in clients:
                client.close()


class TestUnixTransportNetworkGuard(unittest.TestCase):
    def test_external_tcp_remains_blocked(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            with self.assertRaises(UnexpectedNetworkAttempt):
                client.connect(("example.invalid", 443))

    def test_loopback_tcp_remains_permitted(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(1)
            address = listener.getsockname()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect(address)
            connection, _ = listener.accept()
            connection.close()


if __name__ == "__main__":
    unittest.main()
