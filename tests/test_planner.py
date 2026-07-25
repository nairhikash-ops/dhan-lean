"""Tests for deterministic minute ingestion planning."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.models import DataWorkItem
from dhan_lean.data.planner import plan_minute_ingestion

IST = ZoneInfo("Asia/Kolkata")


class TestPlanner(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_plan_minute_ingestion_single_date(self) -> None:
        day = date(2026, 7, 20)
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[day],
        )

        self.assertIsInstance(items, tuple)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIsInstance(item, DataWorkItem)
        self.assertEqual(item.symbol, "HDFCBANK")
        self.assertEqual(item.source_id, "test_source")
        self.assertEqual(item.bar_size, "1m")
        self.assertEqual(item.session_date, day)
        self.assertEqual(item.work_item_key, "test_source:HDFCBANK:1m:2026-07-20")
        self.assertEqual(item.window.start, datetime(2026, 7, 20, 9, 15, tzinfo=IST))
        self.assertEqual(item.window.end, datetime(2026, 7, 20, 15, 30, tzinfo=IST))

    def test_plan_minute_ingestion_multiple_dates_sorted_chronologically(self) -> None:
        day1 = date(2026, 7, 22)
        day2 = date(2026, 7, 20)
        day3 = date(2026, 7, 21)

        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="hdfcbank",  # lower case input normalized to upper
            session_dates=[day1, day2, day3],
        )

        self.assertEqual(len(items), 3)
        self.assertEqual([item.session_date for item in items], [day2, day3, day1])
        self.assertEqual([item.symbol for item in items], ["HDFCBANK", "HDFCBANK", "HDFCBANK"])

    def test_plan_minute_ingestion_duplicate_dates_rejected(self) -> None:
        day = date(2026, 7, 20)
        with self.assertRaises(ValueError) as ctx:
            plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=[day, day],
            )
        self.assertIn("unique date values", str(ctx.exception))

    def test_plan_minute_ingestion_empty_dates_rejected(self) -> None:
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[],
        )
        self.assertEqual(items, ())

    def test_plan_minute_ingestion_datetime_or_str_date_rejected(self) -> None:
        dt_val = datetime(2026, 7, 20, 0, 0)
        with self.assertRaises(ValueError) as ctx1:
            plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=[dt_val],  # type: ignore[list-item]
            )
        self.assertIn("unique date values", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=["2026-07-20"],  # type: ignore[list-item]
            )
        self.assertIn("unique date values", str(ctx2.exception))

    def test_plan_minute_ingestion_non_sequence_session_dates_rejected(self) -> None:
        with self.assertRaises(TypeError) as ctx1:
            plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=date(2026, 7, 20),  # type: ignore[arg-type]
            )
        self.assertIn("sequence of dates", str(ctx1.exception))

        with self.assertRaises(TypeError) as ctx2:
            plan_minute_ingestion(
                storage_root=self.storage_root,
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates="2026-07-20",  # type: ignore[arg-type]
            )
        self.assertIn("sequence of dates", str(ctx2.exception))

    def test_plan_minute_ingestion_storage_root_must_be_absolute_path(self) -> None:
        with self.assertRaises(ValueError) as ctx1:
            plan_minute_ingestion(
                storage_root=Path("relative/path"),
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=[date(2026, 7, 20)],
            )
        self.assertIn("absolute Path", str(ctx1.exception))

        with self.assertRaises(ValueError) as ctx2:
            plan_minute_ingestion(
                storage_root="not-a-path",  # type: ignore[arg-type]
                source_id="test_source",
                symbol="HDFCBANK",
                session_dates=[date(2026, 7, 20)],
            )
        self.assertIn("absolute Path", str(ctx2.exception))

    def test_plan_minute_ingestion_source_id_and_symbol_validation(self) -> None:
        day = date(2026, 7, 20)
        with self.assertRaises(ValueError):
            plan_minute_ingestion(storage_root=self.storage_root, source_id="", symbol="HDFCBANK", session_dates=[day])
        with self.assertRaises(ValueError):
            plan_minute_ingestion(storage_root=self.storage_root, source_id="source", symbol="", session_dates=[day])
        with self.assertRaises(ValueError):
            plan_minute_ingestion(storage_root=self.storage_root, source_id="   ", symbol="HDFCBANK", session_dates=[day])

    def test_plan_minute_ingestion_deterministic_work_item_key_and_output_path(self) -> None:
        day = date(2026, 7, 20)
        items1 = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[day],
        )
        items2 = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[day],
        )

        self.assertEqual(items1[0].work_item_key, items2[0].work_item_key)
        self.assertEqual(items1[0].output_directory, items2[0].output_directory)

    def test_plan_minute_ingestion_planning_does_not_touch_filesystem(self) -> None:
        day = date(2026, 7, 20)
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[day],
        )
        self.assertFalse(items[0].output_directory.exists())

    def test_plan_minute_ingestion_immutable_work_items(self) -> None:
        day = date(2026, 7, 20)
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[day],
        )
        with self.assertRaises(Exception):
            items[0].symbol = "TCS"  # type: ignore[misc]



if __name__ == "__main__":
    unittest.main()
