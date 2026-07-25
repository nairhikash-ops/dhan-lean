"""Tests for NormalizedBar and validate_normalized_bars."""

import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from dhan_lean.data.models import NormalizedBar, ValidationResult
from dhan_lean.data.validator import validate_normalized_bars

IST = ZoneInfo("Asia/Kolkata")


class TestValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.base_time = datetime(2026, 7, 20, 9, 15, 0, tzinfo=IST)

    def _make_bar(
        self,
        symbol: str = "HDFCBANK",
        minutes_offset: int = 0,
        open_p: str = "100.0",
        high_p: str = "105.0",
        low_p: str = "98.0",
        close_p: str = "102.0",
        volume: int = 1000,
    ) -> NormalizedBar:
        return NormalizedBar(
            symbol=symbol,
            timestamp=self.base_time + timedelta(minutes=minutes_offset),
            open=Decimal(open_p),
            high=Decimal(high_p),
            low=Decimal(low_p),
            close=Decimal(close_p),
            volume=volume,
            source_metadata={"source": "test"},
        )

    def test_normalized_bar_creation_and_immutability(self) -> None:
        bar = self._make_bar()
        self.assertEqual(bar.symbol, "HDFCBANK")
        self.assertEqual(bar.open, Decimal("100.0"))
        self.assertEqual(bar.high, Decimal("105.0"))
        self.assertEqual(bar.low, Decimal("98.0"))
        self.assertEqual(bar.close, Decimal("102.0"))
        self.assertEqual(bar.volume, 1000)
        self.assertEqual(dict(bar.source_metadata), {"source": "test"})

        with self.assertRaises(Exception):
            bar.symbol = "TCS"  # type: ignore[misc]


    def test_normalized_bar_requires_timezone_aware_timestamp(self) -> None:
        naive_dt = datetime(2026, 7, 20, 9, 15, 0)
        with self.assertRaises(ValueError) as ctx:
            NormalizedBar(
                symbol="HDFCBANK",
                timestamp=naive_dt,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("98"),
                close=Decimal("102"),
                volume=100,
            )
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_normalized_bar_requires_non_empty_symbol(self) -> None:
        with self.assertRaises(ValueError):
            NormalizedBar(
                symbol="",
                timestamp=self.base_time,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("98"),
                close=Decimal("102"),
                volume=100,
            )
        with self.assertRaises(ValueError):
            NormalizedBar(
                symbol="   ",
                timestamp=self.base_time,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("98"),
                close=Decimal("102"),
                volume=100,
            )

    def test_normalized_bar_requires_non_negative_integer_volume(self) -> None:
        with self.assertRaises(ValueError):
            NormalizedBar(
                symbol="HDFCBANK",
                timestamp=self.base_time,
                open=Decimal("100"),
                high=Decimal("105"),
                low=Decimal("98"),
                close=Decimal("102"),
                volume=-1,
            )

    def test_normalized_bar_source_metadata_is_frozen_mapping(self) -> None:
        meta = {"key": "value"}
        bar = NormalizedBar(
            symbol="HDFCBANK",
            timestamp=self.base_time,
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("98"),
            close=Decimal("102"),
            volume=100,
            source_metadata=meta,
        )
        meta["key"] = "mutated"
        self.assertEqual(bar.source_metadata["key"], "value")

        with self.assertRaises(TypeError):
            bar.source_metadata["new_key"] = "forbidden"  # type: ignore[index]

    def test_valid_synthetic_sequence_validation(self) -> None:
        bars = [self._make_bar(minutes_offset=i) for i in range(5)]
        res = validate_normalized_bars(bars)
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.errors), 0)
        self.assertEqual(res.bar_count, 5)
        self.assertTrue(res.timestamps_strictly_increasing)
        self.assertEqual(res.duplicate_timestamp_count, 0)
        self.assertEqual(res.non_increasing_timestamp_count, 0)
        self.assertEqual(res.invalid_ohlc_count, 0)
        self.assertEqual(res.non_positive_price_count, 0)
        self.assertEqual(res.negative_volume_count, 0)
        self.assertEqual(res.timestamp_delta_distribution, {60: 4})

    def test_invalid_ohlc_relationships_reported(self) -> None:
        # high is lower than open
        bar1 = self._make_bar(open_p="100", high_p="95", low_p="90", close_p="92")
        # low is higher than close
        bar2 = self._make_bar(minutes_offset=1, open_p="100", high_p="105", low_p="103", close_p="102")
        res = validate_normalized_bars([bar1, bar2])
        self.assertFalse(res.is_valid)
        self.assertEqual(res.invalid_ohlc_count, 2)

    def test_non_positive_and_non_finite_price_validation(self) -> None:
        bar_zero = self._make_bar(open_p="0.0")
        bar_neg = self._make_bar(minutes_offset=1, close_p="-5.0")
        res = validate_normalized_bars([bar_zero, bar_neg])
        self.assertFalse(res.is_valid)
        self.assertEqual(res.non_positive_price_count, 2)

    def test_malformed_price_types_return_structured_failure(self) -> None:
        malformed = [
            self._make_bar(open_p="100"),
            self._make_bar(minutes_offset=1),
            self._make_bar(minutes_offset=2),
            self._make_bar(minutes_offset=3),
        ]
        malformed[0] = NormalizedBar("HDFCBANK", self.base_time, 100.0, Decimal("105"), Decimal("98"), Decimal("102"), 100)
        malformed[1] = NormalizedBar("HDFCBANK", self.base_time + timedelta(minutes=1), Decimal("100"), "105", Decimal("98"), Decimal("102"), 100)
        malformed[2] = NormalizedBar("HDFCBANK", self.base_time + timedelta(minutes=2), Decimal("100"), Decimal("105"), None, Decimal("102"), 100)
        malformed[3] = self._make_bar(minutes_offset=3)

        result = validate_normalized_bars(malformed)

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "INVALID_PRICE_TYPE")
        self.assertIsNotNone(result.error_summary)
        self.assertIn("invalid", result.error_summary.lower())

    def test_valid_decimal_prices_still_validate(self) -> None:
        result = validate_normalized_bars([self._make_bar()])
        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)
        self.assertIsNone(result.error_summary)

    def test_duplicate_timestamps_reported(self) -> None:
        bar1 = self._make_bar(minutes_offset=0)
        bar2 = self._make_bar(minutes_offset=0)
        res = validate_normalized_bars([bar1, bar2])
        self.assertFalse(res.is_valid)
        self.assertEqual(res.duplicate_timestamp_count, 1)
        self.assertEqual(res.non_increasing_timestamp_count, 1)
        self.assertFalse(res.timestamps_strictly_increasing)

    def test_non_monotonic_descending_timestamps_reported(self) -> None:
        bar1 = self._make_bar(minutes_offset=5)
        bar2 = self._make_bar(minutes_offset=2)
        res = validate_normalized_bars([bar1, bar2])
        self.assertFalse(res.is_valid)
        self.assertEqual(res.duplicate_timestamp_count, 0)
        self.assertEqual(res.non_increasing_timestamp_count, 1)

    def test_empty_input_bars_reported(self) -> None:
        res = validate_normalized_bars([])
        self.assertFalse(res.is_valid)
        self.assertEqual(res.bar_count, 0)
        self.assertIn("No bars supplied", res.errors)

    def test_non_normalized_bar_object_in_sequence(self) -> None:
        bars = [self._make_bar(), "not_a_bar"]  # type: ignore[list-item]
        res = validate_normalized_bars(bars)
        self.assertFalse(res.is_valid)
        self.assertTrue(any("not a NormalizedBar" in err for err in res.errors))

    def test_invalid_expected_interval_seconds_raised(self) -> None:
        with self.assertRaises(ValueError):
            validate_normalized_bars([self._make_bar()], expected_interval_seconds=0)
        with self.assertRaises(ValueError):
            validate_normalized_bars([self._make_bar()], expected_interval_seconds=-60)

    def test_validation_result_immutability_and_defensive_copies(self) -> None:
        res = validate_normalized_bars([self._make_bar()])
        self.assertIsInstance(res.errors, tuple)
        with self.assertRaises(TypeError):
            res.errors[0] = "mutated"  # type: ignore[index]


if __name__ == "__main__":
    unittest.main()
