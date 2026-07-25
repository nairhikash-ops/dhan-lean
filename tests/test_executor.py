import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.executor import execute_single_work_item
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.downloader import DhanIntradayDownloader
from dhan_lean.data.transport import DhanHttpTransport
from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.data.models import (
    DownloadWorkItem,
    RequestWindow,
    ClaimStatus,
    SingleExecutionResult,
    HttpResponse,
    ValidationResult
)

IST = ZoneInfo("Asia/Kolkata")


class TestExecutor(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "ledger.db"
        self.storage_root = self.root / "storage"
        self.storage_root.mkdir()

        self.ledger = StateLedger(self.db_path, self.storage_root)

        self.sample_window = RequestWindow(
            from_date="2026-07-22 09:14:00",
            to_date="2026-07-22 15:30:00",
            desired_start_ist="2026-07-22T09:15:00+05:30",
            desired_end_ist="2026-07-22T15:30:00+05:30"
        )
        self.sample_dir = self.storage_root / "raw" / "dhan" / "nse_eq" / "equity" / "HDFCBANK" / "1333" / "1m" / "2026" / "07" / "22"
        self.sample_item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=self.sample_window,
            output_directory=self.sample_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22"
        )
        self.ledger.register_work_item(self.sample_item)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _make_mock_downloader(self, success: bool = True, raise_exc: Exception = None):
        downloader = unittest.mock.MagicMock(spec=DhanIntradayDownloader)
        if raise_exc is not None:
            downloader.download_intraday.side_effect = raise_exc
        else:
            val_result = ValidationResult(
                is_valid=success,
                errors=() if success else ("Mock validation error",),
                candle_count=375 if success else 0,
                array_lengths={},
                arrays_equal_length=success,
                timestamps_strictly_increasing=success,
                duplicate_timestamp_count=0,
                non_increasing_timestamp_count=0,
                invalid_ohlc_count=0,
                non_positive_price_count=0,
                negative_volume_count=0,
                zero_volume_count=0,
                timestamp_delta_distribution={},
                missing_gap_count=0,
                largest_actual_interval_seconds=60,
                largest_excess_gap_seconds=0,
                first_timestamp_utc=None,
                last_timestamp_utc=None,
                first_timestamp_ist=None,
                last_timestamp_ist=None
            )
            mock_res = unittest.mock.MagicMock()
            mock_res.success = success
            mock_res.status_code = 200 if success else 500
            mock_res.error_code = None if success else "HTTP_500"
            mock_res.error_message = None if success else "Server Error"
            mock_res.validation_result = val_result
            downloader.download_intraday.return_value = mock_res
        return downloader

    def test_successful_execution(self) -> None:
        downloader = self._make_mock_downloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "SUCCEEDED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "SUCCEEDED")
        self.assertIsNotNone(res.download_result)
        self.assertTrue(res.download_result.success)

    def test_executor_does_not_consume_transport_budget(self) -> None:
        budget = RequestBudget(self.db_path)
        budget.configure("batch", "window", 1)
        downloader = self._make_mock_downloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)
        self.assertEqual(res.status, "SUCCEEDED")
        self.assertEqual(budget.snapshot("batch", "window").consumed, 0)

    def test_failed_execution(self) -> None:
        downloader = self._make_mock_downloader(success=False)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "FAILED")
        self.assertEqual(res.error_code, "HTTP_500")

    def test_interrupted_execution(self) -> None:
        downloader = self._make_mock_downloader(raise_exc=KeyboardInterrupt("User cancelled"))
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "INTERRUPTED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "INTERRUPTED")
        self.assertEqual(res.error_code, "KeyboardInterrupt")

    def test_unexpected_exception_marks_attempt_failed(self) -> None:
        downloader = self._make_mock_downloader(raise_exc=RuntimeError("Unexpected connection drop"))
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(downloader.download_intraday.call_count, 1)
        self.assertIsInstance(res, SingleExecutionResult)
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.claim_status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.state, "FAILED")
        self.assertEqual(res.error_code, "RuntimeError")

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            att_state = conn.execute("SELECT state FROM attempts WHERE attempt_id = ?;", (res.attempt.attempt_id,)).fetchone()[0]

            self.assertEqual(wi_state, "REVIEW_REQUIRED")
            self.assertEqual(att_state, "FAILED")
            self.assertNotEqual(att_state, "INTERRUPTED")
            self.assertNotEqual(wi_state, "CLAIMED")
        finally:
            conn.close()

    def test_downloader_called_exact_once(self) -> None:

        downloader = self._make_mock_downloader(success=True)
        execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(downloader.download_intraday.call_count, 1)

    def test_duplicate_execution_blocked_by_ledger(self) -> None:
        downloader1 = self._make_mock_downloader(success=True)
        res1 = execute_single_work_item(self.ledger, downloader1, self.sample_item.work_item_key)
        self.assertEqual(res1.status, "SUCCEEDED")
        self.assertEqual(downloader1.download_intraday.call_count, 1)

        downloader2 = self._make_mock_downloader(success=True)
        res2 = execute_single_work_item(self.ledger, downloader2, self.sample_item.work_item_key)
        self.assertEqual(res2.status, "ALREADY_SUCCEEDED")
        self.assertEqual(res2.claim_status, ClaimStatus.ALREADY_SUCCEEDED)
        self.assertIsNone(res2.download_result)
        self.assertEqual(downloader2.download_intraday.call_count, 0)

    def test_ledger_states_match_execution_result(self) -> None:
        downloader = self._make_mock_downloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            att_state = conn.execute("SELECT state FROM attempts WHERE attempt_id = ?;", (res.attempt.attempt_id,)).fetchone()[0]

            self.assertEqual(wi_state, res.status)
            self.assertEqual(att_state, res.attempt.state)
            self.assertEqual(wi_state, "SUCCEEDED")
            self.assertEqual(att_state, "SUCCEEDED")
        finally:
            conn.close()

    def test_executor_parses_naive_stored_timestamps_as_ist(self) -> None:
        naive_window = RequestWindow(
            from_date="2026-07-22 09:14:00",
            to_date="2026-07-22 15:30:00",
            desired_start_ist="2026-07-22 09:15:00",
            desired_end_ist="2026-07-22 15:30:00"
        )
        naive_item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=naive_window,
            output_directory=self.sample_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22:naive"
        )
        self.ledger.register_work_item(naive_item)
        downloader = self._make_mock_downloader(success=True)

        res = execute_single_work_item(self.ledger, downloader, naive_item.work_item_key)
        self.assertEqual(res.status, "SUCCEEDED")
        self.assertEqual(downloader.download_intraday.call_count, 1)

        call_kwargs = downloader.download_intraday.call_args.kwargs
        start_time = call_kwargs["start_time"]
        end_time = call_kwargs["end_time"]

        self.assertIsNotNone(start_time.tzinfo)
        self.assertIsNotNone(end_time.tzinfo)
        self.assertEqual(start_time.tzinfo, IST)
        self.assertEqual(end_time.tzinfo, IST)
        self.assertEqual(start_time.hour, 9)
        self.assertEqual(start_time.minute, 15)
        self.assertEqual(end_time.hour, 15)
        self.assertEqual(end_time.minute, 30)

    def test_executor_preserves_offset_aware_stored_timestamps(self) -> None:
        downloader = self._make_mock_downloader(success=True)
        res = execute_single_work_item(self.ledger, downloader, self.sample_item.work_item_key)

        self.assertEqual(res.status, "SUCCEEDED")
        self.assertEqual(downloader.download_intraday.call_count, 1)

        call_kwargs = downloader.download_intraday.call_args.kwargs
        start_time = call_kwargs["start_time"]
        end_time = call_kwargs["end_time"]

        self.assertIsNotNone(start_time.tzinfo)
        self.assertIsNotNone(end_time.tzinfo)
        self.assertEqual(start_time.hour, 9)
        self.assertEqual(start_time.minute, 15)
        self.assertEqual(end_time.hour, 15)
        self.assertEqual(end_time.minute, 30)


if __name__ == "__main__":
    unittest.main()
