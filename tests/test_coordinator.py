import gc
import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.coordinator import execute_batch, BatchSummary
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.downloader import DhanIntradayDownloader
from dhan_lean.data.models import (
    DownloadWorkItem,
    RequestWindow,
    DownloadResult,
    HttpResponse,
    ValidationResult,
)

IST = ZoneInfo("Asia/Kolkata")


class TestCoordinator(unittest.TestCase):

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
            desired_end_ist="2026-07-22T15:30:00+05:30",
        )

    def tearDown(self) -> None:
        del self.ledger
        gc.collect()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _create_work_item(self, symbol: str, sec_id: str, session_date_str: str) -> DownloadWorkItem:
        d = date.fromisoformat(session_date_str)
        out_dir = self.storage_root / "raw" / "dhan" / "nse_eq" / "equity" / symbol / sec_id / "1m" / session_date_str.replace("-", "/")
        key = f"dhan:nse_eq:equity:{symbol}:{sec_id}:1m:{session_date_str}"
        item = DownloadWorkItem(
            symbol=symbol,
            security_id=sec_id,
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=d,
            request_window=self.sample_window,
            output_directory=out_dir,
            work_item_key=key,
        )
        self.ledger.register_work_item(item)
        return item

    def _make_mock_downloader(self, success: bool = True, raise_exc: Exception = None):
        downloader = unittest.mock.MagicMock(spec=DhanIntradayDownloader)
        if raise_exc:
            downloader.download_intraday.side_effect = raise_exc
        else:
            mock_val_res = ValidationResult(
                is_valid=success,
                errors=() if success else ("Error",),
                candle_count=5 if success else 0,
                array_lengths={"timestamp": 5 if success else 0},
                arrays_equal_length=True,
                timestamps_strictly_increasing=True,
                duplicate_timestamp_count=0,
                non_increasing_timestamp_count=0,
                invalid_ohlc_count=0,
                non_positive_price_count=0,
                negative_volume_count=0,
                zero_volume_count=0,
                timestamp_delta_distribution={60: 4} if success else {},
                missing_gap_count=0,
                largest_actual_interval_seconds=60,
                largest_excess_gap_seconds=0,
                first_timestamp_utc=None,
                last_timestamp_utc=None,
                first_timestamp_ist="2026-07-22 09:15:00" if success else None,
                last_timestamp_ist="2026-07-22 09:19:00" if success else None,
            )
            mock_dl_result = DownloadResult(
                run_id="run_123",
                output_directory=self.storage_root,
                status_code=200 if success else 400,
                artifact_paths={},
                validation_result=mock_val_res,
                error_code=None if success else "DH-906",
                error_message=None if success else "Invalid Token",
                success=success,
            )
            downloader.download_intraday.return_value = mock_dl_result
        return downloader

    def test_successful_ordered_multi_item_execution(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")
        item3 = self._create_work_item("HDFCBANK", "1333", "2026-07-22")

        downloader = self._make_mock_downloader(success=True)
        keys = [item1.work_item_key, item2.work_item_key, item3.work_item_key]

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            delay_seconds=0.0,
        )

        self.assertEqual(summary.success_count, 3)
        self.assertEqual(summary.failure_count, 0)
        self.assertEqual(summary.blocked_count, 0)
        self.assertFalse(summary.stopped_early)
        self.assertFalse(summary.max_items_reached)
        self.assertIsNone(summary.stop_reason)
        self.assertEqual(downloader.download_intraday.call_count, 3)

        called_symbols = [call[1]["symbol"] for call in downloader.download_intraday.call_args_list]
        self.assertEqual(called_symbols, ["HDFCBANK", "HDFCBANK", "HDFCBANK"])

    def test_max_items_enforcement(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")
        item3 = self._create_work_item("HDFCBANK", "1333", "2026-07-22")

        downloader = self._make_mock_downloader(success=True)
        keys = [item1.work_item_key, item2.work_item_key, item3.work_item_key]

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            max_items=2,
            delay_seconds=0.0,
        )

        self.assertEqual(len(summary.processed_results), 2)
        self.assertTrue(summary.max_items_reached)
        self.assertTrue(summary.stopped_early)
        self.assertEqual(summary.stop_reason, "MAX_ITEMS_REACHED (2)")
        self.assertEqual(downloader.download_intraday.call_count, 2)

    def test_downloader_called_sequentially_and_exact_delays(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")
        item3 = self._create_work_item("HDFCBANK", "1333", "2026-07-22")

        downloader = self._make_mock_downloader(success=True)
        keys = [item1.work_item_key, item2.work_item_key, item3.work_item_key]
        sleep_calls = []

        def mock_sleep(sec: float) -> None:
            sleep_calls.append(sec)

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            delay_seconds=1.5,
            sleep_fn=mock_sleep,
        )

        self.assertEqual(summary.success_count, 3)
        self.assertEqual(sleep_calls, [1.5, 1.5])

    def test_no_delay_for_blocked_items(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")

        claim_res = self.ledger.claim_work_item(item1.work_item_key, "other_owner", 900)
        self.ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)

        downloader = self._make_mock_downloader(success=True)
        keys = [item1.work_item_key, item2.work_item_key]
        sleep_calls = []

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            delay_seconds=2.0,
            sleep_fn=lambda sec: sleep_calls.append(sec),
        )

        self.assertEqual(summary.blocked_count, 1)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(sleep_calls, [])

    def test_duplicate_input_keys_rejected(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        downloader = self._make_mock_downloader(success=True)
        keys = [item1.work_item_key, item1.work_item_key]

        with self.assertRaises(ValueError) as cm:
            execute_batch(self.ledger, downloader, keys)
        self.assertIn("Duplicate key detected", str(cm.exception))

    def test_invalid_inputs_rejected(self) -> None:
        downloader = self._make_mock_downloader(success=True)

        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, ["key1"], max_items=0)

        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, ["key1"], delay_seconds=-1.0)

        with self.assertRaises(ValueError):
            execute_batch(self.ledger, downloader, [""])

    def test_blocked_claim_does_not_call_downloader(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        claim_res = self.ledger.claim_work_item(item1.work_item_key, "other_owner", 900)
        self.ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)

        downloader = self._make_mock_downloader(success=True)
        summary = execute_batch(self.ledger, downloader, [item1.work_item_key])

        self.assertEqual(summary.blocked_count, 1)
        self.assertEqual(summary.success_count, 0)
        self.assertEqual(downloader.download_intraday.call_count, 0)

    def test_fail_fast_after_normal_failure(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")
        item3 = self._create_work_item("HDFCBANK", "1333", "2026-07-22")

        downloader = self._make_mock_downloader(success=False)
        keys = [item1.work_item_key, item2.work_item_key, item3.work_item_key]

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=True,
            delay_seconds=0.0,
        )

        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(len(summary.processed_results), 1)
        self.assertTrue(summary.stopped_early)
        self.assertIn("FAILED", summary.stop_reason)
        self.assertEqual(downloader.download_intraday.call_count, 1)

    def test_continuation_when_stop_on_failure_false(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")

        downloader = unittest.mock.MagicMock(spec=DhanIntradayDownloader)
        res_fail = DownloadResult("r1", self.storage_root, 400, {}, None, "ERR", "Fail", False)
        res_succ = DownloadResult("r2", self.storage_root, 200, {}, None, None, None, True)
        downloader.download_intraday.side_effect = [res_fail, res_succ]

        keys = [item1.work_item_key, item2.work_item_key]
        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=False,
            delay_seconds=0.0,
        )

        self.assertEqual(summary.failure_count, 1)
        self.assertEqual(summary.success_count, 1)
        self.assertFalse(summary.stopped_early)
        self.assertEqual(len(summary.processed_results), 2)

    def test_interruption_stops_safely(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")

        downloader = self._make_mock_downloader(raise_exc=KeyboardInterrupt("User cancelled"))
        keys = [item1.work_item_key, item2.work_item_key]

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=keys,
            stop_on_failure=True,
            delay_seconds=0.0,
        )

        self.assertEqual(summary.interrupted_count, 1)
        self.assertTrue(summary.stopped_early)
        self.assertIn("INTERRUPTED", summary.stop_reason)
        self.assertEqual(downloader.download_intraday.call_count, 1)

    def test_unexpected_exception_stops_safely(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")
        downloader = self._make_mock_downloader(success=True)

        def crashing_sleep(sec: float) -> None:
            raise RuntimeError("Unexpected timer crash")

        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=[item1.work_item_key, item2.work_item_key],
            delay_seconds=1.0,
            sleep_fn=crashing_sleep,
        )

        self.assertTrue(summary.stopped_early)
        self.assertIn("UNEXPECTED_EXCEPTION", summary.stop_reason)

    def test_summary_counts_and_ordering(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        item2 = self._create_work_item("HDFCBANK", "1333", "2026-07-21")

        downloader = self._make_mock_downloader(success=True)
        summary = execute_batch(
            ledger=self.ledger,
            downloader=downloader,
            work_item_keys=[item1.work_item_key, item2.work_item_key],
            delay_seconds=0.0,
        )

        self.assertIsInstance(summary.requested_keys, tuple)
        self.assertIsInstance(summary.processed_results, tuple)
        self.assertEqual(summary.requested_keys, (item1.work_item_key, item2.work_item_key))
        self.assertEqual(len(summary.processed_results), 2)

    def test_no_retry_authorization_created(self) -> None:
        item1 = self._create_work_item("HDFCBANK", "1333", "2026-07-20")
        downloader = self._make_mock_downloader(success=False)

        execute_batch(self.ledger, downloader, [item1.work_item_key], delay_seconds=0.0)

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM retry_authorizations").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
