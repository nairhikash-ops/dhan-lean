import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from unittest.mock import patch

from dhan_lean.data.models import DownloadWorkItem
from dhan_lean.data.planner import plan_one_minute_downloads

IST = ZoneInfo("Asia/Kolkata")



class TestPlanner(unittest.TestCase):

    def test_single_explicit_session_date(self):
        """Test planning for a single explicit date creates 1 DownloadWorkItem."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            session_d = date(2026, 7, 22)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[session_d]
            )

            self.assertIsInstance(items, tuple)
            self.assertEqual(len(items), 1)

            item = items[0]
            self.assertEqual(item.symbol, "HDFCBANK")
            self.assertEqual(item.security_id, "1333")
            self.assertEqual(item.exchange_segment, "NSE_EQ")
            self.assertEqual(item.instrument, "EQUITY")
            self.assertEqual(item.bar_size, "1m")
            self.assertEqual(item.session_date, session_d)

    def test_multiple_dates_are_sorted_chronologically(self):
        """Test input dates provided out of order are returned in chronological order."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            d1 = date(2026, 7, 22)
            d2 = date(2026, 7, 21)
            d3 = date(2026, 7, 23)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[d1, d2, d3]
            )

            self.assertEqual(len(items), 3)
            self.assertEqual(items[0].session_date, d2)
            self.assertEqual(items[1].session_date, d1)
            self.assertEqual(items[2].session_date, d3)

    def test_duplicate_dates_are_rejected(self):
        """Test duplicate dates raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            d1 = date(2026, 7, 22)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[d1, d1]
                )

    def test_empty_dates_are_rejected(self):
        """Test empty session_dates raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[]
                )

    def test_datetime_is_rejected(self):
        """Test datetime instances in session_dates raise TypeError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            dt_obj = datetime(2026, 7, 22, 9, 15, tzinfo=IST)

            with self.assertRaises(TypeError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[dt_obj]  # datetime rejected
                )

    def test_string_date_is_rejected(self):
        """Test string date representations in session_dates raise TypeError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(TypeError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=["2026-07-22"]  # string rejected
                )

    def test_invalid_security_id_is_rejected(self):
        """Test security_id containing non-digits raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333A",  # non-digit
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_unsupported_exchange_segment_is_rejected(self):
        """Test exchange_segment != 'NSE_EQ' raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="BSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_unsupported_instrument_is_rejected(self):
        """Test instrument != 'EQUITY' raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="FUTSTK",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_work_item_is_immutable(self):
        """Test DownloadWorkItem fields cannot be mutated."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            item = items[0]
            with self.assertRaises(AttributeError):
                item.symbol = "RELIANCE"

    def test_work_item_key_is_deterministic_and_includes_symbol(self):
        """Test work_item_key format is dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            item = items[0]
            self.assertEqual(item.work_item_key, "dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22")

    def test_request_window_uses_correct_exclusive_bounds(self):
        """Test request_window fromDate is 09:14:00 and toDate is 15:30:00."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            window = items[0].request_window
            self.assertEqual(window.from_date, "2026-07-22 09:14:00")
            self.assertEqual(window.to_date, "2026-07-22 15:30:00")
            self.assertEqual(window.desired_start_ist, "2026-07-22 09:15:00")
            self.assertEqual(window.desired_end_ist, "2026-07-22 15:30:00")

    def test_output_path_is_deterministic(self):
        """Test output_directory matches raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22 path structure."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            out_dir = items[0].output_directory
            expected = (storage_root / "raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22").resolve()
            self.assertEqual(out_dir, expected)

    def test_planning_does_not_create_storage_directories(self):
        """Test planning execution does NOT create directories on disk."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            out_dir = items[0].output_directory
            self.assertFalse(out_dir.exists())

    def test_repeated_planning_returns_equal_results(self):
        """Test calling plan_one_minute_downloads repeatedly produces identical results."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)
            session_d = date(2026, 7, 22)

            kwargs = {
                "storage_root": storage_root,
                "symbol": "HDFCBANK",
                "security_id": "1333",
                "exchange_segment": "NSE_EQ",
                "instrument": "EQUITY",
                "session_dates": [session_d]
            }

            res1 = plan_one_minute_downloads(**kwargs)
            res2 = plan_one_minute_downloads(**kwargs)

            self.assertEqual(res1, res2)

    def test_storage_root_must_be_path(self):
        """Test non-Path storage_root raises TypeError."""
        with self.assertRaises(TypeError):
            plan_one_minute_downloads(
                storage_root="/tmp/data",  # string raises TypeError
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

    def test_empty_symbol_is_rejected(self):
        """Test empty symbol raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_symbol_with_leading_whitespace_is_rejected(self):
        """Test symbol with leading whitespace raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol=" HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_symbol_with_trailing_whitespace_is_rejected(self):
        """Test symbol with trailing whitespace raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK ",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_empty_security_id_is_rejected(self):
        """Test empty security_id raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_security_id_with_trailing_newline_is_rejected(self):
        """Test security_id containing trailing newline '1333\\n' raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333\n",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_unicode_digit_security_id_is_rejected(self):
        """Test non-ASCII Unicode digit security_id raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="١٣٣٣",  # Arabic-Indic digits 1333
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_session_dates_must_be_a_sequence(self):
        """Test non-sequence session_dates raises TypeError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(TypeError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=date(2026, 7, 22)  # single date, not a sequence
                )

    def test_session_dates_string_container_is_rejected(self):
        """Test string container for session_dates raises TypeError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir)

            with self.assertRaises(TypeError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates="2026-07-22"  # string container raises TypeError
                )

    def test_relative_storage_root_is_rejected(self):
        """Test relative storage_root raises ValueError."""
        with self.assertRaises(ValueError):
            plan_one_minute_downloads(
                storage_root=Path("relative/storage/root"),
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

    def test_planning_does_not_call_path_resolve(self):
        """Test planning constructs pure lexical path without calling Path.resolve()."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir).resolve()
            session_d = date(2026, 7, 22)

            with patch.object(Path, "resolve", side_effect=AssertionError("Path.resolve() must not be called by pure planner")):
                items = plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HDFCBANK",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[session_d]
                )

            expected_dir = storage_root / "raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22"
            self.assertEqual(items[0].output_directory, expected_dir)
            self.assertFalse(items[0].output_directory.exists())

    def test_lowercase_symbol_is_rejected(self):
        """Test lowercase symbol raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir).resolve()

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="hdfcbank",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_mixed_case_symbol_is_rejected(self):
        """Test mixed-case symbol raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir).resolve()

            with self.assertRaises(ValueError):
                plan_one_minute_downloads(
                    storage_root=storage_root,
                    symbol="HdfcBank",
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    instrument="EQUITY",
                    session_dates=[date(2026, 7, 22)]
                )

    def test_symbol_matches_output_path_component(self):
        """Test symbol identity is canonical HDFCBANK across work item, key, and output path."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage_root = Path(tmp_dir).resolve()

            items = plan_one_minute_downloads(
                storage_root=storage_root,
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                session_dates=[date(2026, 7, 22)]
            )

            item = items[0]
            self.assertEqual(item.symbol, "HDFCBANK")
            self.assertIn(":HDFCBANK:", item.work_item_key)
            self.assertEqual(item.output_directory.parts[-6], "HDFCBANK")


if __name__ == "__main__":
    unittest.main()
