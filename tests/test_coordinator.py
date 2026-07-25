"""Tests for sequential batch coordination (execute_batch)."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from dhan_lean.data.coordinator import BatchSummary, execute_batch
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.planner import plan_minute_ingestion
from tests.test_executor import FakeOfflineDownloader



class TestCoordinator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()
        self.db_path = self.storage_root / "ledger.db"
        self.ledger = StateLedger(self.db_path, self.storage_root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_work_items(self, count: int = 3) -> list[str]:
        keys = []
        for i in range(count):
            day = date(2026, 7, 20 + i)
            items = plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=[day],
            )
            self.ledger.register_work_item(items[0])
            keys.append(items[0].work_item_key)
        return keys

    def test_successful_ordered_multi_item_execution(self) -> None:
        keys = self._create_work_items(3)
        downloader = FakeOfflineDownloader(success=True)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            max_items=100,
            delay_seconds=0.0,
        )

        self.assertIsInstance(summary, BatchSummary)
        self.assertEqual(summary.success_count, 3)
        self.assertEqual(summary.failure_count, 0)
        self.assertEqual(summary.interrupted_count, 0)
        self.assertEqual(summary.blocked_count, 0)
        self.assertFalse(summary.max_items_reached)
        self.assertFalse(summary.stopped_early)
        self.assertIsNone(summary.stop_reason)
        self.assertEqual(len(downloader.calls), 3)

    def test_max_items_enforcement(self) -> None:
        keys = self._create_work_items(3)
        downloader = FakeOfflineDownloader(success=True)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            max_items=2,
            delay_seconds=0.0,
        )

        self.assertEqual(summary.success_count, 2)
        self.assertEqual(len(summary.processed_results), 2)
        self.assertTrue(summary.max_items_reached)
        self.assertFalse(summary.stopped_early)

    def test_delays_inserted_between_executions(self) -> None:
        keys = self._create_work_items(3)
        downloader = FakeOfflineDownloader(success=True)
        sleep_calls: list[float] = []

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            delay_seconds=2.5,
            sleep_fn=sleep_calls.append,
        )

        self.assertEqual(summary.success_count, 3)
        # Sleep should be called between executions (2 times for 3 items)
        self.assertEqual(sleep_calls, [2.5, 2.5])

    def test_duplicate_input_keys_rejected(self) -> None:
        keys = self._create_work_items(1)
        downloader = FakeOfflineDownloader(success=True)

        with self.assertRaises(ValueError) as ctx:
            execute_batch(
                ledger=self.ledger,
                downloader=downloader,
                work_item_keys=[keys[0], keys[0]],
            )
        self.assertIn("must be unique non-empty strings", str(ctx.exception))

    def test_invalid_inputs_rejected(self) -> None:
        keys = self._create_work_items(1)
        downloader = FakeOfflineDownloader(success=True)

        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, keys, max_items=0)
        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, keys, delay_seconds=-1.0)
        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, [""])

    def test_fail_fast_after_normal_failure(self) -> None:
        keys = self._create_work_items(3)
        # First succeeds, second fails
        downloader = FakeOfflineDownloader(success=False)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=True,
        )

        self.assertEqual(summary.success_count, 0)
        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(len(summary.processed_results), 1)
        self.assertTrue(summary.stopped_early)
        self.assertIn("FAILED", str(summary.stop_reason))

    def test_continuation_when_stop_on_failure_false(self) -> None:
        keys = self._create_work_items(3)
        downloader = FakeOfflineDownloader(success=False)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=False,
        )

        self.assertEqual(summary.failure_count, 3)
        self.assertEqual(len(summary.processed_results), 3)
        self.assertFalse(summary.stopped_early)

    def test_interruption_stops_safely(self) -> None:
        keys = self._create_work_items(2)
        downloader = FakeOfflineDownloader(raise_exc=KeyboardInterrupt("cancelled"))

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=True,
        )

        self.assertEqual(summary.interrupted_count, 1)
        self.assertEqual(len(summary.processed_results), 1)
        self.assertTrue(summary.stopped_early)
        self.assertIn("INTERRUPTED", str(summary.stop_reason))

    def test_summary_counts_and_ordering(self) -> None:
        keys = self._create_work_items(2)
        downloader = FakeOfflineDownloader(success=True)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
        )

        self.assertEqual(summary.requested_keys, tuple(keys))
        self.assertEqual(len(summary.processed_results), 2)
        self.assertEqual(summary.success_count, 2)

    def test_empty_work_item_keys_list(self) -> None:
        downloader = FakeOfflineDownloader(success=True)
        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=[],
        )
        self.assertEqual(summary.success_count, 0)
        self.assertEqual(len(summary.processed_results), 0)


if __name__ == "__main__":
    unittest.main()
