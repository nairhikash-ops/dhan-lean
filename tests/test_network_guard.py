import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import urllib.request

from dhan_lean.data.models import HttpResponse
from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.data.transport import DhanHttpTransport, TransportError
from tests import UnexpectedNetworkAttempt


class TestProjectNetworkGuard(unittest.TestCase):
    def test_direct_external_socket_is_blocked(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaisesRegex(UnexpectedNetworkAttempt, "example.invalid"):
                sock.connect(("example.invalid", 443))
        finally:
            sock.close()

    def test_external_urlopen_is_blocked(self) -> None:
        with self.assertRaisesRegex(UnexpectedNetworkAttempt, "example.invalid"):
            urllib.request.urlopen("https://example.invalid/")

    def test_default_dhan_transport_cannot_escape_to_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            budget = RequestBudget(Path(tmp) / "budget.db")
            budget.configure("test", "window", 1)
            transport = DhanHttpTransport(
                "token",
                request_budget=budget,
                budget_scope="test",
                budget_window_id="window",
            )
            with self.assertRaises(TransportError):
                transport.post_intraday(b"{}")
            self.assertEqual(budget.snapshot("test", "window").consumed, 1)

    def test_injected_offline_executor_remains_usable(self) -> None:
        def offline_executor(_request, _timeout):
            return HttpResponse(200, b"{}", b"")

        transport = DhanHttpTransport("token", executor=offline_executor)
        self.assertEqual(transport.post_intraday(b"{}"), HttpResponse(200, b"{}", b""))

    def test_guard_is_active_during_unittest_discovery_import(self) -> None:
        self.assertTrue(getattr(socket.socket.connect, "_dhan_test_guard", False))
        self.assertIsNot(urllib.request.urlopen, None)


if __name__ == "__main__":
    unittest.main()
