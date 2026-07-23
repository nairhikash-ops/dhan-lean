import unittest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from dhan_lean.data.window import calculate_request_window
from dhan_lean.data.models import RequestWindow

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


class TestRequestWindow(unittest.TestCase):

    def test_full_session_request_window(self):
        """Test desired full session 09:15 to 15:30 IST produces fromDate 09:14:00 and toDate 15:30:00."""
        start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        window = calculate_request_window(start, end, interval_minutes=1)

        self.assertEqual(window.from_date, "2026-07-22 09:14:00")
        self.assertEqual(window.to_date, "2026-07-22 15:30:00")
        self.assertEqual(window.desired_start_ist, "2026-07-22 09:15:00")
        self.assertEqual(window.desired_end_ist, "2026-07-22 15:30:00")

    def test_short_interval_request_window(self):
        """Test desired short 5-minute range 09:15 to 09:20 IST produces fromDate 09:14:00 and toDate 09:20:00."""
        start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        end = datetime(2026, 7, 22, 9, 20, 0, tzinfo=IST)

        window = calculate_request_window(start, end, interval_minutes=1)

        self.assertEqual(window.from_date, "2026-07-22 09:14:00")
        self.assertEqual(window.to_date, "2026-07-22 09:20:00")

    def test_utc_input_converted_to_ist(self):
        """Test UTC input is converted correctly to Asia/Kolkata."""
        # 09:15 IST is 03:45 UTC
        start_utc = datetime(2026, 7, 22, 3, 45, 0, tzinfo=UTC)
        # 15:30 IST is 10:00 UTC
        end_utc = datetime(2026, 7, 22, 10, 0, 0, tzinfo=UTC)

        window = calculate_request_window(start_utc, end_utc, interval_minutes=1)

        self.assertEqual(window.from_date, "2026-07-22 09:14:00")
        self.assertEqual(window.to_date, "2026-07-22 15:30:00")

    def test_naive_datetime_rejection(self):
        """Test naive datetimes are rejected with ValueError."""
        start_naive = datetime(2026, 7, 22, 9, 15, 0)
        end_aware = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        with self.assertRaises(ValueError):
            calculate_request_window(start_naive, end_aware)

        with self.assertRaises(ValueError):
            calculate_request_window(end_aware, start_naive)

    def test_non_minute_aligned_rejection(self):
        """Test non-zero seconds or microseconds are rejected."""
        start_sec = datetime(2026, 7, 22, 9, 15, 30, tzinfo=IST)
        end_valid = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        with self.assertRaises(ValueError):
            calculate_request_window(start_sec, end_valid)

        start_micro = datetime(2026, 7, 22, 9, 15, 0, 100, tzinfo=IST)
        with self.assertRaises(ValueError):
            calculate_request_window(start_micro, end_valid)

    def test_invalid_ordering_rejection(self):
        """Test start >= end raises ValueError."""
        dt1 = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        dt2 = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        dt3 = datetime(2026, 7, 22, 9, 10, 0, tzinfo=IST)

        with self.assertRaises(ValueError):
            calculate_request_window(dt1, dt2)

        with self.assertRaises(ValueError):
            calculate_request_window(dt1, dt3)

    def test_unsupported_interval_rejection(self):
        """Test interval_minutes != 1 raises NotImplementedError."""
        start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        with self.assertRaises(NotImplementedError):
            calculate_request_window(start, end, interval_minutes=5)


if __name__ == "__main__":
    unittest.main()
