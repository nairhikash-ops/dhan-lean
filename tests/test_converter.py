"""Tests for convert_minute_bars_to_lean and LEAN CSV-in-ZIP generation."""

import os
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from dhan_lean.data.converter import (
    LeanConversionError,
    LeanConversionResult,
    convert_minute_bars_to_lean,
)
from dhan_lean.data.models import NormalizedBar

IST = ZoneInfo("Asia/Kolkata")


class TestLeanConverter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()
        self.session_date = date(2026, 7, 20)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_bar(
        self,
        symbol: str = "hdfcbank",
        minutes_offset: int = 0,
        open_p: str = "100.0000",
        high_p: str = "105.5000",
        low_p: str = "98.2500",
        close_p: str = "102.1000",
        volume: int = 1000,
    ) -> NormalizedBar:
        ts = datetime(2026, 7, 20, 9, 15, 0, tzinfo=IST) + datetime.resolution * 0
        from datetime import timedelta
        ts = datetime(2026, 7, 20, 9, 15, 0, tzinfo=IST) + timedelta(minutes=minutes_offset)
        return NormalizedBar(
            symbol=symbol,
            timestamp=ts,
            open=Decimal(open_p),
            high=Decimal(high_p),
            low=Decimal(low_p),
            close=Decimal(close_p),
            volume=volume,
        )

    def test_writes_expected_member_and_decimal_scaling(self) -> None:
        bars = [self._make_bar(minutes_offset=0), self._make_bar(minutes_offset=1)]
        res = convert_minute_bars_to_lean(
            storage_root=self.storage_root,
            symbol="HDFCBANK",
            session_date=self.session_date,
            bars=bars,
        )

        self.assertIsInstance(res, LeanConversionResult)
        self.assertEqual(res.normalized_symbol, "hdfcbank")
        self.assertEqual(res.session_date, self.session_date)
        self.assertEqual(res.rows_written, 2)
        self.assertTrue(res.output_zip_path.exists())

        expected_zip = self.storage_root / "Data" / "equity" / "india" / "minute" / "hdfcbank" / "20260720_trade.zip"
        self.assertEqual(res.output_zip_path, expected_zip)
        self.assertEqual(res.member_filename, "20260720_hdfcbank_minute_trade.csv")

        with zipfile.ZipFile(expected_zip, "r") as archive:
            self.assertIn("20260720_hdfcbank_minute_trade.csv", archive.namelist())
            csv_lines = archive.read("20260720_hdfcbank_minute_trade.csv").decode("ascii").strip().split("\n")
            self.assertEqual(len(csv_lines), 2)

            # 9:15:00 IST -> (9*3600 + 15*60)*1000 = 33,300,000 ms
            # Prices scaled by 10,000: 100.0 -> 1000000, 105.5 -> 1055000, 98.25 -> 982500, 102.1 -> 1021000
            self.assertEqual(csv_lines[0], "33300000,1000000,1055000,982500,1021000,1000")
            # 9:16:00 IST -> 33,360,000 ms
            self.assertEqual(csv_lines[1], "33360000,1000000,1055000,982500,1021000,1000")

    def test_sub_paise_decimal_rounding_round_half_up(self) -> None:
        # Test ROUND_HALF_UP precision (e.g. 100.00005 * 10000 = 1000000.5 -> 1000001)
        bar = self._make_bar(open_p="100.00005", high_p="105.00005", low_p="98.00004", close_p="102.00005")
        res = convert_minute_bars_to_lean(
            storage_root=self.storage_root,
            symbol="HDFCBANK",
            session_date=self.session_date,
            bars=[bar],
        )

        with zipfile.ZipFile(res.output_zip_path, "r") as archive:
            csv_line = archive.read(res.member_filename).decode("ascii").strip()
            self.assertEqual(csv_line, "33300000,1000001,1050001,980000,1020001,1000")

    def test_timezone_normalization_uses_ist_midnight(self) -> None:
        # UTC 03:45:00 is IST 09:15:00 (+5:30)
        from datetime import timezone
        dt_utc = datetime(2026, 7, 20, 3, 45, 0, tzinfo=timezone.utc)
        bar = NormalizedBar(
            symbol="HDFCBANK",
            timestamp=dt_utc,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("98"),
            close=Decimal("102"),
            volume=100,
        )

        res = convert_minute_bars_to_lean(
            storage_root=self.storage_root,
            symbol="HDFCBANK",
            session_date=self.session_date,
            bars=[bar],
        )
        with zipfile.ZipFile(res.output_zip_path, "r") as archive:
            csv_line = archive.read(res.member_filename).decode("ascii").strip()
            self.assertTrue(csv_line.startswith("33300000,"))

    def test_existing_output_fails_closed(self) -> None:
        bars = [self._make_bar()]
        convert_minute_bars_to_lean(
            storage_root=self.storage_root,
            symbol="HDFCBANK",
            session_date=self.session_date,
            bars=bars,
        )
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=bars,
            )
        self.assertIn("Target artifact already exists", str(ctx.exception))

    def test_wrong_session_date_fails(self) -> None:
        bars = [self._make_bar()]
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=date(2026, 7, 21),  # Bar is for 2026-07-20
                bars=bars,
            )
        self.assertIn("bar timestamp outside session_date", str(ctx.exception))

    def test_bar_symbol_mismatch_raises_error(self) -> None:
        bar = self._make_bar(symbol="TCS")
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=[bar],
            )
        self.assertIn("bar symbol mismatch", str(ctx.exception))

    def test_invalid_ohlc_is_reported(self) -> None:
        bar = self._make_bar(open_p="100", high_p="90", low_p="80", close_p="95")
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=[bar],
            )
        self.assertIn("invalid OHLC relationships", str(ctx.exception))

    def test_duplicate_and_non_monotonic_timestamps_are_reported(self) -> None:
        bar1 = self._make_bar(minutes_offset=0)
        bar2 = self._make_bar(minutes_offset=0)
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=[bar1, bar2],
            )
        self.assertIn("strictly increasing", str(ctx.exception))

    def test_unsupported_market_security_type_resolution_raises_error(self) -> None:
        bars = [self._make_bar()]
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=bars,
                market="usa",
            )
        self.assertIn("only india equity minute output is currently supported", str(ctx.exception))

    def test_path_traversal_in_symbol_rejected(self) -> None:
        bars = [self._make_bar()]
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="../hdfcbank",
                session_date=self.session_date,
                bars=bars,
            )
        self.assertIn("cannot contain path separators", str(ctx.exception))

    def test_empty_bars_sequence_raises_error(self) -> None:
        with self.assertRaises(LeanConversionError) as ctx:
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date=self.session_date,
                bars=[],
            )
        self.assertIn("No bars supplied", str(ctx.exception))

    def test_invalid_session_date_type_raises_type_error(self) -> None:
        bars = [self._make_bar()]
        with self.assertRaises(TypeError):
            convert_minute_bars_to_lean(
                storage_root=self.storage_root,
                symbol="HDFCBANK",
                session_date="2026-07-20",  # type: ignore[arg-type]
                bars=bars,
            )

    def test_atomic_publication_cleanup_on_failure(self) -> None:
        bars = [self._make_bar()]
        target_dir = self.storage_root / "Data" / "equity" / "india" / "minute" / "hdfcbank"
        target_dir.mkdir(parents=True, exist_ok=True)

        with patch("os.link", side_effect=OSError("Disk write error")):
            with self.assertRaises(LeanConversionError):
                convert_minute_bars_to_lean(
                    storage_root=self.storage_root,
                    symbol="HDFCBANK",
                    session_date=self.session_date,
                    bars=bars,
                )

        # Check no temporary file (.tmp.zip) was left behind in target_dir
        tmp_files = list(target_dir.glob("*.tmp.*"))
        self.assertEqual(len(tmp_files), 0)


if __name__ == "__main__":
    unittest.main()
