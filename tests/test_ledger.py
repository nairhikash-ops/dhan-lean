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
    RegistrationResult
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


if __name__ == "__main__":
    unittest.main()
