"""Tests for TimeWindow and calculate_minute_window."""

import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dhan_lean.data.models import TimeWindow
from dhan_lean.data.window import calculate_minute_window

IST = ZoneInfo("Asia/Kolkata")


class TestWindow(unittest.TestCase):
    def test_time_window_creation_and_immutability(self) -> None:
        start = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
        end = datetime(2026, 7, 20, 15, 30, tzinfo=IST)
        window = TimeWindow(start=start, end=end, interval_minutes=1)
        self.assertEqual(window.start, start)
        self.assertEqual(window.end, end)
        self.assertEqual(window.interval_minutes, 1)

        with self.assertRaises(Exception):
            window.interval_minutes = 5  # type: ignore[misc]


    def test_calculate_minute_window_success(self) -> None:
        start = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
        end = datetime(2026, 7, 20, 15, 30, tzinfo=IST)
        window = calculate_minute_window(start, end, interval_minutes=1)
        self.assertEqual(window.start, start)
        self.assertEqual(window.end, end)
        self.assertEqual(window.interval_minutes, 1)

    def test_window_requires_timezone_aware_start_and_end(self) -> None:
        aware = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
        naive = datetime(2026, 7, 20, 9, 15)

        with self.assertRaises(ValueError) as ctx1:
            calculate_minute_window(naive, aware)
        self.assertIn("timezone-aware", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            calculate_minute_window(aware, naive)
        self.assertIn("timezone-aware", str(ctx2.exception))

        with self.assertRaises(ValueError) as ctx3:
            TimeWindow(start=naive, end=aware)
        self.assertIn("timezone-aware", str(ctx3.exception))

    def test_window_requires_minute_aligned_datetimes(self) -> None:
        start_ok = datetime(2026, 7, 20, 9, 15, 0, tzinfo=IST)
        end_sec = datetime(2026, 7, 20, 15, 30, 15, tzinfo=IST)
        end_micro = datetime(2026, 7, 20, 15, 30, 0, 500, tzinfo=IST)

        with self.assertRaises(ValueError) as ctx1:
            calculate_minute_window(start_ok, end_sec)
        self.assertIn("minute-aligned", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            calculate_minute_window(start_ok, end_micro)
        self.assertIn("minute-aligned", str(ctx2.exception))

    def test_window_rejects_start_equal_or_after_end(self) -> None:
        dt = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
        earlier = datetime(2026, 7, 20, 9, 14, tzinfo=IST)

        with self.assertRaises(ValueError) as ctx1:
            calculate_minute_window(dt, dt)
        self.assertIn("start must precede end", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            calculate_minute_window(dt, earlier)
        self.assertIn("start must precede end", str(ctx2.exception))

    def test_window_rejects_non_positive_interval_minutes(self) -> None:
        start = datetime(2026, 7, 20, 9, 15, tzinfo=IST)
        end = datetime(2026, 7, 20, 15, 30, tzinfo=IST)

        with self.assertRaises(ValueError) as ctx1:
            calculate_minute_window(start, end, interval_minutes=0)
        self.assertIn("interval_minutes must be a positive integer", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            TimeWindow(start, end, interval_minutes=-1)
        self.assertIn("interval_minutes must be a positive integer", str(ctx2.exception))

    def test_utc_and_ist_timezones_handled_correctly(self) -> None:
        start_utc = datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc)
        end_utc = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        window = calculate_minute_window(start_utc, end_utc)
        self.assertEqual(window.start, start_utc)
        self.assertEqual(window.end, end_utc)


if __name__ == "__main__":
    unittest.main()
