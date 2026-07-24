import sqlite3
import tempfile
import unittest
import unittest.mock
from datetime import date
from pathlib import Path


from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import (
    DownloadWorkItem,
    RequestWindow,
    RegistrationStatus,
    RegistrationResult,
    ClaimStatus,
    ClaimResult,
    WorkItemAttempt
)



class TestStateLedger(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)
        self.db_path = self.root / "ledger.db"
        self.storage_root = self.root / "storage"
        self.storage_root.mkdir()

        self.sample_window = RequestWindow(
            from_date="2026-07-22 09:14:00",
            to_date="2026-07-22 15:30:00",
            desired_start_ist="2026-07-22T09:15:00Z",
            desired_end_ist="2026-07-22T15:30:00Z"
        )
        self.sample_dir = self.storage_root / "raw" / "dhan" / "nse_eq" / "equity" / "HDFCBANK" / "1333" / "1m" / "2026" / "07" / "22"
        self.sample_item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=self.sample_window,
            output_directory=self.sample_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22"
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_new_database_initialization(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        self.assertTrue(self.db_path.exists())

        conn = sqlite3.connect(self.db_path)
        try:
            version = conn.execute("PRAGMA user_version;").fetchone()[0]
            self.assertEqual(version, 1)

            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()]
            self.assertIn("work_items", tables)
            self.assertIn("attempts", tables)
            self.assertIn("retry_authorizations", tables)
        finally:
            conn.close()

    def test_unsupported_schema_version_is_refused(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        conn = sqlite3.connect(self.db_path, autocommit=True)
        conn.execute("PRAGMA user_version = 99;")
        conn.close()

        with self.assertRaises(ValueError) as ctx:
            StateLedger(self.db_path, self.storage_root)
        self.assertIn("Unsupported schema version 99", str(ctx.exception))

    def test_register_work_item_creates_planned_record(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        res = ledger.register_work_item(self.sample_item)

        self.assertIsInstance(res, RegistrationResult)
        self.assertEqual(res.status, RegistrationStatus.CREATED)
        self.assertEqual(res.work_item_key, self.sample_item.work_item_key)
        self.assertEqual(res.artifact_directory_rel, "raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22")

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT state, artifact_directory_rel FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "PLANNED")
            self.assertEqual(row[1], "raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22")
        finally:
            conn.close()

    def test_matching_registration_is_idempotent(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        res1 = ledger.register_work_item(self.sample_item)
        self.assertEqual(res1.status, RegistrationStatus.CREATED)

        res2 = ledger.register_work_item(self.sample_item)
        self.assertEqual(res2.status, RegistrationStatus.EXISTING_MATCH)
        self.assertEqual(res2.work_item_key, self.sample_item.work_item_key)

    def test_metadata_conflict_is_rejected(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        conflicting_item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="9999",  # Conflicting security_id
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=self.sample_window,
            output_directory=self.sample_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22"
        )

        with self.assertRaises(ValueError) as ctx:
            ledger.register_work_item(conflicting_item)
        self.assertIn("Metadata conflict", str(ctx.exception))

    def test_output_path_outside_storage_root_is_rejected(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        outside_dir = self.root / "outside" / "path"
        outside_item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=self.sample_window,
            output_directory=outside_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22"
        )

        with self.assertRaises(ValueError) as ctx:
            ledger.register_work_item(outside_item)
        self.assertIn("outside configured storage root", str(ctx.exception))

    def test_no_directories_are_created(self) -> None:
        target_dir = self.storage_root / "non_existent" / "dir"
        self.assertFalse(target_dir.exists())

        item = DownloadWorkItem(
            symbol="HDFCBANK",
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            bar_size="1m",
            session_date=date(2026, 7, 22),
            request_window=self.sample_window,
            output_directory=target_dir,
            work_item_key="dhan:nse_eq:equity:HDFCBANK:1333:1m:2026-07-22"
        )

        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(item)

        self.assertFalse(target_dir.exists())

    def test_registration_does_not_call_path_resolve(self) -> None:
        def raise_resolve(*args, **kwargs):
            raise RuntimeError("Path.resolve should not be called")

        ledger = StateLedger(self.db_path, self.storage_root)

        with unittest.mock.patch.object(Path, "resolve", side_effect=raise_resolve):
            res = ledger.register_work_item(self.sample_item)
            self.assertEqual(res.status, RegistrationStatus.CREATED)

    def test_successful_initial_claim(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
        self.assertIsInstance(res, ClaimResult)
        self.assertEqual(res.status, ClaimStatus.CLAIMED)
        self.assertIsNotNone(res.attempt)
        self.assertEqual(res.attempt.attempt_number, 1)
        self.assertEqual(res.attempt.claim_owner, "worker-1")
        self.assertEqual(res.attempt.lease_duration_seconds, 900)
        self.assertTrue(res.attempt.run_id.endswith("Z"))
        self.assertIsNone(res.attempt.completed_at)

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()
            self.assertEqual(row[0], "CLAIMED")
            att_row = conn.execute("SELECT attempt_number, run_id, claim_owner, state FROM attempts WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()
            self.assertIsNotNone(att_row)
            self.assertEqual(att_row[0], 1)
            self.assertEqual(att_row[1], res.attempt.run_id)
            self.assertEqual(att_row[2], "worker-1")
            self.assertEqual(att_row[3], "CLAIMED")
        finally:
            conn.close()

    def test_claim_missing_work_item(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        res = ledger.claim_work_item("non_existent_key", claim_owner="worker-1", lease_duration_seconds=900)
        self.assertEqual(res.status, ClaimStatus.WORK_ITEM_NOT_FOUND)
        self.assertIsNone(res.attempt)

    def test_duplicate_claim_blocked(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        res1 = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
        self.assertEqual(res1.status, ClaimStatus.CLAIMED)

        res2 = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-2", lease_duration_seconds=900)
        self.assertEqual(res2.status, ClaimStatus.ALREADY_CLAIMED)
        self.assertIsNone(res2.attempt)

    def test_transaction_rollback_on_injected_failure(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        orig_connect = ledger._connect

        class FaultyConnection:
            def __init__(self, real_conn):
                self._real_conn = real_conn

            def execute(self, sql, *args):
                if "UPDATE work_items" in sql:
                    raise RuntimeError("Injected update failure")
                return self._real_conn.execute(sql, *args)

            def close(self):
                self._real_conn.close()

        def faulty_connect():
            return FaultyConnection(orig_connect())

        with unittest.mock.patch.object(ledger, "_connect", side_effect=faulty_connect):
            with self.assertRaises(RuntimeError) as ctx:
                ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
            self.assertIn("Injected update failure", str(ctx.exception))

        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()
            self.assertEqual(row[0], "PLANNED")
            attempts = conn.execute("SELECT COUNT(*) FROM attempts WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(attempts, 0)
        finally:
            conn.close()


    def test_invalid_claim_parameters_rejected(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        with self.assertRaises(ValueError):
            ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="", lease_duration_seconds=900)
        with self.assertRaises(ValueError):
            ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker", lease_duration_seconds=0)
        with self.assertRaises(ValueError):
            ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker", lease_duration_seconds=-10)
        with self.assertRaises(ValueError):
            ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker", lease_duration_seconds=True)

    def test_claim_update_is_conditioned_on_planned_state(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        conn = sqlite3.connect(self.db_path, autocommit=True)
        conn.execute("UPDATE work_items SET state = 'SUCCEEDED' WHERE work_item_key = ?;", (self.sample_item.work_item_key,))
        conn.close()

        res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
        self.assertEqual(res.status, ClaimStatus.ALREADY_SUCCEEDED)

    def test_blocked_claim_does_not_create_additional_attempt(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)

        res1 = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
        self.assertEqual(res1.status, ClaimStatus.CLAIMED)

        res2 = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-2", lease_duration_seconds=900)
        self.assertEqual(res2.status, ClaimStatus.ALREADY_CLAIMED)

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM attempts WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            conn.close()



    def test_successful_attempt_completion(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)

        attempt = ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)
        self.assertIsInstance(attempt, WorkItemAttempt)
        self.assertEqual(attempt.state, "SUCCEEDED")
        self.assertIsNotNone(attempt.completed_at)

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(wi_state, "SUCCEEDED")
            att_row = conn.execute("SELECT state, completed_at FROM attempts WHERE attempt_id = ?;", (claim_res.attempt.attempt_id,)).fetchone()
            self.assertEqual(att_row[0], "SUCCEEDED")
            self.assertIsNotNone(att_row[1])
        finally:
            conn.close()

    def test_failed_attempt_completion_with_error_details(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)

        attempt = ledger.mark_attempt_failed(
            claim_res.attempt.attempt_id,
            error_code="HTTP_500",
            error_summary="Internal Server Error from upstream"
        )
        self.assertIsInstance(attempt, WorkItemAttempt)
        self.assertEqual(attempt.state, "FAILED")
        self.assertEqual(attempt.error_code, "HTTP_500")
        self.assertEqual(attempt.error_summary, "Internal Server Error from upstream")

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(wi_state, "REVIEW_REQUIRED")
            att_row = conn.execute("SELECT state, error_code, error_summary FROM attempts WHERE attempt_id = ?;", (claim_res.attempt.attempt_id,)).fetchone()
            self.assertEqual(att_row[0], "FAILED")
            self.assertEqual(att_row[1], "HTTP_500")
            self.assertEqual(att_row[2], "Internal Server Error from upstream")
        finally:
            conn.close()

    def test_interrupted_attempt_completion(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)

        attempt = ledger.mark_attempt_interrupted(
            claim_res.attempt.attempt_id,
            error_code="SIGINT",
            error_summary="Process terminated by signal"
        )
        self.assertIsInstance(attempt, WorkItemAttempt)
        self.assertEqual(attempt.state, "INTERRUPTED")

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(wi_state, "REVIEW_REQUIRED")
            att_state = conn.execute("SELECT state FROM attempts WHERE attempt_id = ?;", (claim_res.attempt.attempt_id,)).fetchone()[0]
            self.assertEqual(att_state, "INTERRUPTED")
        finally:
            conn.close()

    def test_invalid_attempt_id_rejected(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        with self.assertRaises(ValueError) as ctx:
            ledger.mark_attempt_succeeded("non_existent_attempt_id")
        self.assertIn("Attempt not found", str(ctx.exception))

        with self.assertRaises(ValueError):
            ledger.mark_attempt_succeeded("")

    def test_completing_already_completed_attempt_rejected(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)

        ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)

        with self.assertRaises(ValueError) as ctx:
            ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)
        self.assertIn("expected 'CLAIMED'", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            ledger.mark_attempt_failed(claim_res.attempt.attempt_id, error_code="FAIL")
        self.assertIn("expected 'CLAIMED'", str(ctx.exception))

    def test_completion_transaction_rollback_on_failure(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)

        orig_connect = ledger._connect

        class FaultyConnection:
            def __init__(self, real_conn):
                self._real_conn = real_conn

            def execute(self, sql, *args):
                if "UPDATE work_items" in sql:
                    raise RuntimeError("Injected work_items update failure during completion")
                return self._real_conn.execute(sql, *args)

            def close(self):
                self._real_conn.close()

        def faulty_connect():
            return FaultyConnection(orig_connect())

        with unittest.mock.patch.object(ledger, "_connect", side_effect=faulty_connect):
            with self.assertRaises(RuntimeError) as ctx:
                ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)
            self.assertIn("Injected work_items update failure", str(ctx.exception))

        conn = sqlite3.connect(self.db_path)
        try:
            wi_state = conn.execute("SELECT state FROM work_items WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(wi_state, "CLAIMED")
            att_state = conn.execute("SELECT state FROM attempts WHERE attempt_id = ?;", (claim_res.attempt.attempt_id,)).fetchone()[0]
            self.assertEqual(att_state, "CLAIMED")
        finally:
            conn.close()

    def test_attempt_history_preserved_on_completion(self) -> None:
        ledger = StateLedger(self.db_path, self.storage_root)
        ledger.register_work_item(self.sample_item)
        claim_res = ledger.claim_work_item(self.sample_item.work_item_key, claim_owner="worker-1", lease_duration_seconds=900)
        orig_attempt = claim_res.attempt

        completed_attempt = ledger.mark_attempt_succeeded(orig_attempt.attempt_id)

        self.assertEqual(completed_attempt.attempt_id, orig_attempt.attempt_id)
        self.assertEqual(completed_attempt.work_item_key, orig_attempt.work_item_key)
        self.assertEqual(completed_attempt.attempt_number, orig_attempt.attempt_number)
        self.assertEqual(completed_attempt.run_id, orig_attempt.run_id)
        self.assertEqual(completed_attempt.claim_owner, orig_attempt.claim_owner)
        self.assertEqual(completed_attempt.claimed_at, orig_attempt.claimed_at)
        self.assertEqual(completed_attempt.lease_duration_seconds, orig_attempt.lease_duration_seconds)
        self.assertEqual(completed_attempt.lease_expires_at, orig_attempt.lease_expires_at)

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT COUNT(*) FROM attempts WHERE work_item_key = ?;", (self.sample_item.work_item_key,)).fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
