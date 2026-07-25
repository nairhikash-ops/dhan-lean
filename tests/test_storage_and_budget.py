import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.models import NormalizedBar
from dhan_lean.data.request_budget import RequestBudget, RequestBudgetExceeded
from dhan_lean.data.storage import ArtifactWriter, build_raw_artifact_path
from dhan_lean.data.validator import validate_normalized_bars
from dhan_lean.data.window import calculate_minute_window


class TestStorageBudgetAndWindow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def test_source_neutral_path_rejects_traversal(self):
        with self.assertRaises(ValueError):
            build_raw_artifact_path(storage_root=self.root, source_id="fixture", venue="market", data_kind="bars", symbol="ACME", instrument_id="../bad", resolution="1m", session_date=date(2026, 7, 22))

    def test_source_artifacts_are_exclusive(self):
        bar = NormalizedBar("ACME", datetime(2026, 7, 22, 9, 15, tzinfo=ZoneInfo("Asia/Kolkata")), *(Decimal("1"),) * 4, 0)
        output = self.root / "artifacts"
        writer = ArtifactWriter()
        writer.write_source_artifacts(output, "20260722T091500Z", b'{}', b'{}', b'content-type: application/json', 200, validate_normalized_bars([bar]))
        with self.assertRaises(FileExistsError):
            writer.write_source_artifacts(output, "20260722T091500Z", b'{}', b'{}', b'content-type: application/json', 200, validate_normalized_bars([bar]))

    def test_request_budget_is_persistent_and_fail_closed(self):
        budget = RequestBudget(self.root / "budget.sqlite")
        self.assertEqual(budget.configure("offline-fixture", "2026-07", 2).remaining, 2)
        self.assertEqual(budget.consume("offline-fixture", "2026-07").remaining, 1)
        self.assertEqual(RequestBudget(self.root / "budget.sqlite").snapshot("offline-fixture", "2026-07").consumed, 1)
        with self.assertRaises(RequestBudgetExceeded):
            budget.consume("offline-fixture", "2026-07", 2)

    def test_window_requires_aware_minute_aligned_datetimes(self):
        zone = ZoneInfo("Asia/Kolkata")
        result = calculate_minute_window(datetime(2026, 7, 22, 9, 15, tzinfo=zone), datetime(2026, 7, 22, 9, 16, tzinfo=zone))
        self.assertEqual(result.interval_minutes, 1)
        with self.assertRaises(ValueError):
            calculate_minute_window(datetime(2026, 7, 22, 9, 15), datetime(2026, 7, 22, 9, 16))
