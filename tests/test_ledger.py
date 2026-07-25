"""Tests for SQLite state ledger and work-item state machine."""

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import (
    ClaimStatus,
    DataWorkItem,
    RegistrationStatus,
)
from dhan_lean.data.planner import plan_minute_ingestion


class TestLedger(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()
        self.db_path = self.storage_root / "ledger.db"
        self.ledger = StateLedger(self.db_path, self.storage_root)
        self.sample_day = date(2026, 7, 20)
        items = plan_minute_ingestion(
            storage_root=self.storage_root,
            source_id="test_source",
            symbol="HDFCBANK",
            session_dates=[self.sample_day],
        )
        self.sample_item = items[0]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_new_database_initialization(self) -> None:
        self.assertTrue(self.db_path.exists())
        conn = sqlite3.connect(self.db_path)
        try:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            self.assertIn("work_items", tables)
            self.assertIn("attempts", tables)
        finally:
            conn.close()

    def test_ledger_requires_absolute_storage_root(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            StateLedger(self.db_path, Path("relative/path"))
        self.assertIn("storage_root must be absolute", str(ctx.exception))

    def test_register_work_item_creates_planned_record(self) -> None:
        res = self.ledger.register_work_item(self.sample_item)
        self.assertEqual(res.status, RegistrationStatus.CREATED)
        self.assertEqual(res.work_item_key, self.sample_item.work_item_key)

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT source_id, symbol, day, state FROM work_items WHERE key = ?;",
                (self.sample_item.work_item_key,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row, ("test_source", "HDFCBANK", "2026-07-20", "PLANNED"))
        finally:
            conn.close()

    def test_matching_registration_is_idempotent(self) -> None:
        res1 = self.ledger.register_work_item(self.sample_item)
        self.assertEqual(res1.status, RegistrationStatus.CREATED)

        res2 = self.ledger.register_work_item(self.sample_item)
        self.assertEqual(res2.status, RegistrationStatus.EXISTING_MATCH)

    def test_metadata_conflict_is_rejected(self) -> None:
        self.ledger.register_work_item(self.sample_item)

        conflicting_item = DataWorkItem(
            symbol="DIFFERENT",
            source_id="test_source",
            bar_size="1m",
            session_date=self.sample_day,
            window=self.sample_item.window,
            output_directory=self.sample_item.output_directory,
            work_item_key=self.sample_item.work_item_key,  # Same key, different symbol
        )
        with self.assertRaises(ValueError) as ctx:
            self.ledger.register_work_item(conflicting_item)
        self.assertIn("conflicts with existing metadata", str(ctx.exception))

    def test_output_path_outside_storage_root_is_rejected(self) -> None:
        outside_item = DataWorkItem(
            symbol="HDFCBANK",
            source_id="test_source",
            bar_size="1m",
            session_date=self.sample_day,
            window=self.sample_item.window,
            output_directory=Path("/outside/storage/root"),
            work_item_key=self.sample_item.work_item_key,
        )
        with self.assertRaises(ValueError):
            self.ledger.register_work_item(outside_item)

    def test_registration_does_not_create_directories(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        self.assertFalse(self.sample_item.output_directory.exists())

    def test_get_work_item_retrieval(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        retrieved = self.ledger.get_work_item(self.sample_item.work_item_key)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.work_item_key, self.sample_item.work_item_key)
        self.assertEqual(retrieved.symbol, self.sample_item.symbol)
        self.assertEqual(retrieved.session_date, self.sample_item.session_date)
        self.assertEqual(retrieved.bar_size, self.sample_item.bar_size)

        missing = self.ledger.get_work_item("missing_key")
        self.assertIsNone(missing)

    def test_bar_size_is_persisted_and_conflicts_are_rejected(self) -> None:
        item = DataWorkItem(
            symbol=self.sample_item.symbol,
            source_id=self.sample_item.source_id,
            bar_size="5m",
            session_date=self.sample_item.session_date,
            window=self.sample_item.window,
            output_directory=self.sample_item.output_directory,
            work_item_key=self.sample_item.work_item_key,
        )
        self.ledger.register_work_item(item)
        reopened = StateLedger(self.db_path, self.storage_root)
        self.assertEqual(reopened.get_work_item(item.work_item_key).bar_size, "5m")

        conflicting = DataWorkItem(
            symbol=item.symbol,
            source_id=item.source_id,
            bar_size="15m",
            session_date=item.session_date,
            window=item.window,
            output_directory=item.output_directory,
            work_item_key=item.work_item_key,
        )
        with self.assertRaises(ValueError):
            reopened.register_work_item(conflicting)

    def test_claim_transaction_rolls_back_after_update_failure(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TRIGGER fail_claim_update
                AFTER UPDATE OF state ON work_items
                WHEN NEW.state = 'CLAIMED'
                BEGIN
                    SELECT RAISE(ABORT, 'forced claim failure');
                END;
            """)
            conn.commit()
        finally:
            conn.close()

        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.claim_work_item(self.sample_item.work_item_key, "worker-1", 300)

        conn = sqlite3.connect(self.db_path)
        try:
            state = conn.execute("SELECT state FROM work_items WHERE key = ?", (self.sample_item.work_item_key,)).fetchone()[0]
            attempts = conn.execute("SELECT COUNT(*) FROM attempts WHERE key = ?", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(state, "PLANNED")
            self.assertEqual(attempts, 0)
            conn.execute("DROP TRIGGER fail_claim_update")
            conn.commit()
        finally:
            conn.close()

        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, "worker-1", 300)
        self.assertEqual(claim.status, ClaimStatus.CLAIMED)

    def test_successful_initial_claim(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        res = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)

        self.assertEqual(res.status, ClaimStatus.CLAIMED)
        self.assertEqual(res.work_item_key, self.sample_item.work_item_key)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.attempt_number, 1)
        self.assertEqual(res.attempt.state, "CLAIMED")
        self.assertEqual(res.attempt.claim_owner, "worker-1")

    def test_claim_missing_work_item(self) -> None:
        res = self.ledger.claim_work_item("nonexistent_key", claim_owner="worker-1", lease_duration_seconds=300)
        self.assertEqual(res.status, ClaimStatus.WORK_ITEM_NOT_FOUND)
        self.assertIsNone(res.attempt)

    def test_duplicate_claim_blocked(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        res1 = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)
        self.assertEqual(res1.status, ClaimStatus.CLAIMED)

        res2 = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-2", lease_duration_seconds=300)
        self.assertEqual(res2.status, ClaimStatus.ALREADY_CLAIMED)
        self.assertIsNone(res2.attempt)

    def test_claim_already_succeeded_blocked(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)
        self.ledger.mark_attempt_succeeded(claim.attempt.attempt_id)

        res2 = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-2", lease_duration_seconds=300)
        self.assertEqual(res2.status, ClaimStatus.ALREADY_SUCCEEDED)

    def test_successful_attempt_completion(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)

        attempt = self.ledger.mark_attempt_succeeded(claim.attempt.attempt_id)
        self.assertEqual(attempt.state, "SUCCEEDED")
        self.assertIsNotNone(attempt.completed_at)

        conn = sqlite3.connect(self.db_path)
        try:
            state = conn.execute("SELECT state FROM work_items WHERE key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(state, "SUCCEEDED")
        finally:
            conn.close()

    def test_failed_attempt_completion_with_error_details(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)

        attempt = self.ledger.mark_attempt_failed(claim.attempt.attempt_id, error_code="ERR_500", error_summary="Server Error")
        self.assertEqual(attempt.state, "FAILED")
        self.assertEqual(attempt.error_code, "ERR_500")
        self.assertEqual(attempt.error_summary, "Server Error")

        conn = sqlite3.connect(self.db_path)
        try:
            state = conn.execute("SELECT state FROM work_items WHERE key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(state, "REVIEW_REQUIRED")
        finally:
            conn.close()

    def test_interrupted_attempt_completion(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)

        attempt = self.ledger.mark_attempt_interrupted(claim.attempt.attempt_id, error_code="SIGINT", error_summary="Interrupted")
        self.assertEqual(attempt.state, "INTERRUPTED")

        conn = sqlite3.connect(self.db_path)
        try:
            state = conn.execute("SELECT state FROM work_items WHERE key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(state, "REVIEW_REQUIRED")
        finally:
            conn.close()

    def test_completing_invalid_or_non_claimed_attempt_rejected(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)
        self.ledger.mark_attempt_succeeded(claim.attempt.attempt_id)

        with self.assertRaises(ValueError) as ctx:
            self.ledger.mark_attempt_succeeded(claim.attempt.attempt_id)
        self.assertIn("attempt is not claimable", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx2:
            self.ledger.mark_attempt_succeeded("nonexistent_attempt_id")
        self.assertIn("attempt is not claimable", str(ctx2.exception))

    def test_attempt_history_preserved_on_completion(self) -> None:
        self.ledger.register_work_item(self.sample_item)
        claim = self.ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=300)
        self.ledger.mark_attempt_failed(claim.attempt.attempt_id, "ERR_1", "First failure")

        conn = sqlite3.connect(self.db_path)
        try:
            attempts = conn.execute("SELECT n, state, error_code FROM attempts WHERE key = ?;", (self.sample_item.work_item_key,)).fetchall()
            self.assertEqual(len(attempts), 1)
            self.assertEqual(attempts[0], (1, "FAILED", "ERR_1"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
