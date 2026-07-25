"""Tests for generic ledger-backed execution seam (execute_single_work_item)."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from dhan_lean.data.executor import execute_single_work_item
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import (
    ClaimStatus,
    DataWorkItem,
    IngestionResult,
    SingleExecutionResult,
    ValidationResult,
)
from dhan_lean.data.planner import plan_minute_ingestion


class FakeOfflineDownloader:
    def __init__(self, success: bool = True, raise_exc: Optional[Exception] = None) -> None:
        self.success = success
        self.raise_exc = raise_exc
        self.calls: list[tuple[DataWorkItem, str]] = []

    def ingest(self, work_item: DataWorkItem, run_id: str) -> IngestionResult:
        self.calls.append((work_item, run_id))
        if self.raise_exc is not None:
            raise self.raise_exc

        val_res = ValidationResult(
            is_valid=self.success,
            errors=() if self.success else ("Failed validation",),
            bar_count=5 if self.success else 0,
            timestamps_strictly_increasing=self.success,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            timestamp_delta_distribution={60: 4} if self.success else {},
        )
        return IngestionResult(
            output_directory=work_item.output_directory,
            bars=(),
            validation_result=val_res,
            success=self.success,
            error_code=None if self.success else "INGESTION_FAILED",
            error_message=None if self.success else "Failed validation",
        )


class TestExecutor(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()
        self.db_path = self.storage_root / "ledger.db"
        self.ledger = StateLedger(self.db_path, self.storage_root)
        self.sample_day = date(2026, 7, 20)
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[self.sample_day],
        )
        self.sample_item = items[0]
        self.ledger.register_work_item(self.sample_item)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_successful_execution(self) -> None:
        downloader = FakeOfflineDownloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "SUCCEEDED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "SUCCEEDED")
        self.assertIsNotNone(res.ingestion_result)
        self.assertTrue(res.ingestion_result.success)
        self.assertEqual(len(downloader.calls), 1)

    def test_failed_execution_with_error_code(self) -> None:
        downloader = FakeOfflineDownloader(success=False)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "FAILED")
        self.assertEqual(res.error_code, "INGESTION_FAILED")
        self.assertEqual(res.error_summary, "Failed validation")
        self.assertEqual(res.attempt.error_code, res.error_code)
        self.assertEqual(res.attempt.error_summary, res.error_summary)

    def test_interrupted_execution_keyboard_interrupt(self) -> None:
        downloader = FakeOfflineDownloader(raise_exc=KeyboardInterrupt("User cancelled"))
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "INTERRUPTED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "INTERRUPTED")
        self.assertEqual(res.error_code, "KeyboardInterrupt")
        self.assertEqual(res.error_summary, "Execution interrupted.")
        self.assertEqual(res.attempt.error_summary, res.error_summary)

    def test_interrupted_execution_system_exit(self) -> None:
        downloader = FakeOfflineDownloader(raise_exc=SystemExit(1))
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(res.status, "INTERRUPTED")
        self.assertEqual(res.error_code, "SystemExit")
        self.assertEqual(res.error_summary, "Execution interrupted.")
        self.assertEqual(res.attempt.error_code, res.error_code)
        self.assertEqual(res.attempt.error_summary, res.error_summary)

    def test_unexpected_exception_marks_attempt_failed(self) -> None:
        downloader = FakeOfflineDownloader(raise_exc=RuntimeError("Unexpected error"))
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(len(downloader.calls), 1)
        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "FAILED")
        self.assertEqual(res.error_code, "RuntimeError")
        self.assertEqual(res.error_summary, "Downloader raised RuntimeError.")
        self.assertEqual(res.attempt.error_code, res.error_code)
        self.assertEqual(res.attempt.error_summary, res.error_summary)

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute(
                "SELECT state FROM work_items WHERE key = ?;", (self.sample_item.work_item_key,)
            ).fetchone()[0]
            self.assertEqual(wi_state, "REVIEW_REQUIRED")
        finally:
            conn.close()

    def test_downloader_called_exact_once(self) -> None:
        downloader = FakeOfflineDownloader(success=True)
        execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)
        self.assertEqual(len(downloader.calls), 1)

    def test_duplicate_execution_blocked_by_ledger(self) -> None:
        downloader1 = FakeOfflineDownloader(success=True)
        res1 = execute_single_work_item(self.ledger, downloader1, self.sample_item.work_item_key)
        self.assertEqual(res1.status, "SUCCEEDED")
        self.assertEqual(len(downloader1.calls), 1)

        downloader2 = FakeOfflineDownloader(success=True)
        res2 = execute_single_work_item(self.ledger, downloader2, self.sample_item.work_item_key)
        self.assertEqual(res2.status, "ALREADY_SUCCEEDED")
        self.assertEqual(res2.claim_status, ClaimStatus.ALREADY_SUCCEEDED)
        self.assertIsNone(res2.ingestion_result)
        self.assertEqual(res2.error_summary, "Work item already succeeded.")
        self.assertEqual(len(downloader2.calls), 0)

    def test_missing_work_item_has_consistent_error_summary(self) -> None:
        downloader = FakeOfflineDownloader(success=True)
        with patch.object(self.ledger, "get_work_item", return_value=None):
            result = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.error_code, "WORK_ITEM_NOT_FOUND")
        self.assertEqual(result.error_summary, "Work item could not be loaded after claim.")
        self.assertEqual(result.attempt.error_code, result.error_code)
        self.assertEqual(result.attempt.error_summary, result.error_summary)

    def test_ledger_states_match_execution_result(self) -> None:
        downloader = FakeOfflineDownloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute(
                "SELECT state FROM work_items WHERE key = ?;", (self.sample_item.work_item_key,)
            ).fetchone()[0]
            att_state = conn.execute(
                "SELECT state FROM attempts WHERE id = ?;", (res.attempt.attempt_id,)
            ).fetchone()[0]

            self.assertEqual(wi_state, res.status)
            self.assertEqual(att_state, res.attempt.state)
            self.assertEqual(wi_state, "SUCCEEDED")
            self.assertEqual(att_state, "SUCCEEDED")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
