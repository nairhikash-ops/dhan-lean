"""Tests for persistent SQLite request budget guard."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dhan_lean.data.request_budget import (
    RequestBudget,
    RequestBudgetExceeded,
    RequestBudgetStateError,
)


class TestRequestBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "budget.db"

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

    def test_invalid_scope_window_allowance_amount_inputs(self) -> None:
        budget = RequestBudget(self.db_path)
        with self.assertRaises(ValueError):
            budget.configure("", "window", 5)
        with self.assertRaises(ValueError):
            budget.configure("batch", "", 5)
        with self.assertRaises(ValueError):
            budget.configure("batch", "window", -1)

        budget.configure("batch", "window", 5)
        with self.assertRaises(ValueError):
            budget.consume("batch", "window", 0)
        with self.assertRaises(ValueError):
            budget.consume("batch", "window", -1)

    def test_missing_parent_directory_raises_state_error(self) -> None:
        missing_dir = Path(self.tmp.name) / "nonexistent" / "budget.db"
        with self.assertRaises(RequestBudgetStateError):
            RequestBudget(missing_dir)


if __name__ == "__main__":
    unittest.main()
