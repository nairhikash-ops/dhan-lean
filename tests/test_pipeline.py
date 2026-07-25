import tempfile
import unittest
from datetime import date
from pathlib import Path

from dhan_lean.data.coordinator import execute_batch
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import IngestionResult
from dhan_lean.data.planner import plan_minute_ingestion
from dhan_lean.data.validator import validate_normalized_bars


class FakeDownloader:
    def ingest(self, work_item, run_id):
        return IngestionResult(work_item.output_directory, (), validate_normalized_bars(()), True)


class TestOfflinePipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.ledger = StateLedger(self.root / "state.db", self.root)
    def tearDown(self): self.temp.cleanup()
    def test_source_neutral_plan_and_ledger_execution(self):
        item = plan_minute_ingestion(storage_root=self.root, source_id="fixture", symbol="ACME", session_dates=[date(2026, 7, 22)])[0]
        self.ledger.register_work_item(item)
        summary = execute_batch(self.ledger, FakeDownloader(), [item.work_item_key], delay_seconds=0)
        self.assertEqual(summary.success_count, 1)
        self.assertEqual(summary.processed_results[0].status, "SUCCEEDED")
    def test_duplicate_work_keys_are_rejected(self):
        with self.assertRaises(ValueError): execute_batch(self.ledger, FakeDownloader(), ["a", "a"])
