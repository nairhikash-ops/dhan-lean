import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dhan_lean.data.request_budget import (
    RequestBudget,
    RequestBudgetExceeded,
    RequestBudgetStateError,
)
from dhan_lean.data.models import HttpResponse
from dhan_lean.data.transport import DhanHttpTransport, TransportError


class TestRequestBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "ledger.db"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persists_after_reopen_and_new_instance_observes_consumption(self) -> None:
        first = RequestBudget(self.db_path)
        first.configure("batch", "2026-07-25", 3)
        first.consume("batch", "2026-07-25")
        del first

        second = RequestBudget(self.db_path)
        snapshot = second.snapshot("batch", "2026-07-25")
        self.assertEqual(snapshot.consumed, 1)
        self.assertEqual(snapshot.remaining, 2)

    def test_within_allowance_and_exact_boundary_succeed(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 3)
        self.assertEqual(budget.consume("batch", "window", 2).remaining, 1)
        self.assertEqual(budget.consume("batch", "window").remaining, 0)

    def test_beyond_allowance_is_rejected_without_mutation(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 1)
        with self.assertRaises(RequestBudgetExceeded):
            budget.consume("batch", "window", 2)
        self.assertEqual(budget.snapshot("batch", "window").consumed, 0)

    def test_concurrent_callers_cannot_oversubscribe(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 5)

        def consume_one() -> bool:
            try:
                budget.consume("batch", "window")
                return True
            except RequestBudgetExceeded:
                return False

        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(lambda _: consume_one(), range(12)))
        self.assertEqual(sum(outcomes), 5)
        self.assertEqual(budget.snapshot("batch", "window").consumed, 5)

    def test_unconfigured_or_corrupt_state_fails_closed(self) -> None:
        budget = RequestBudget(self.db_path)
        with self.assertRaises(RequestBudgetStateError):
            budget.consume("batch", "missing")

        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DROP TABLE request_budgets")
            conn.execute("CREATE TABLE request_budgets (scope TEXT, window_id TEXT, allowance TEXT, consumed INTEGER)")
            conn.execute("INSERT INTO request_budgets VALUES ('batch', 'corrupt', 'not-an-int', 0)")
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(RequestBudgetStateError):
            budget.snapshot("batch", "corrupt")
        with self.assertRaises(RequestBudgetStateError):
            budget.consume("batch", "corrupt")

    def test_conflicting_reconfiguration_is_rejected(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 2)
        with self.assertRaises(RequestBudgetStateError):
            budget.configure("batch", "window", 3)

    def test_default_network_boundary_requires_budget_before_executor(self) -> None:
        with patch("dhan_lean.data.transport._default_executor") as executor:
            transport = DhanHttpTransport("token")
            with self.assertRaises(ValueError):
                transport.post_intraday(b"{}")
            executor.assert_not_called()

    def test_default_network_boundary_consumes_configured_budget(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 1)
        response = HttpResponse(200, b"{}", b"")
        with patch("dhan_lean.data.transport._default_executor", return_value=response) as executor:
            transport = DhanHttpTransport(
                "token", request_budget=budget, budget_scope="batch", budget_window_id="window"
            )
            self.assertEqual(transport.post_intraday(b"{}"), response)
            executor.assert_called_once()
        self.assertEqual(budget.snapshot("batch", "window").consumed, 1)

    def test_each_failed_outbound_attempt_consumes_one_budget_unit(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 2)
        with patch("dhan_lean.data.transport._default_executor", side_effect=TransportError("offline")):
            transport = DhanHttpTransport(
                "token", request_budget=budget, budget_scope="batch", budget_window_id="window"
            )
            for _ in range(2):
                with self.assertRaises(TransportError):
                    transport.post_intraday(b"{}")
        self.assertEqual(budget.snapshot("batch", "window").consumed, 2)
        with patch("dhan_lean.data.transport._default_executor") as executor:
            with self.assertRaises(RequestBudgetExceeded):
                transport.post_intraday(b"{}")
            executor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
