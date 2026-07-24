import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Union, Tuple, Optional


from dhan_lean.data.models import (
    DownloadWorkItem,
    RegistrationStatus,
    RegistrationResult,
    ClaimStatus,
    ClaimResult,
    WorkItemAttempt
)



CREATE_WORK_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS work_items (
    work_item_key TEXT PRIMARY KEY NOT NULL,
    symbol TEXT NOT NULL,
    security_id TEXT NOT NULL,
    exchange_segment TEXT NOT NULL,
    instrument TEXT NOT NULL,
    bar_size TEXT NOT NULL,
    session_date TEXT NOT NULL,
    desired_start_ist TEXT NOT NULL,
    desired_end_ist TEXT NOT NULL,
    request_from_date TEXT NOT NULL,
    request_to_date TEXT NOT NULL,
    artifact_directory_rel TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('PLANNED', 'CLAIMED', 'SUCCEEDED', 'REVIEW_REQUIRED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY NOT NULL,
    work_item_key TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    run_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('CLAIMED', 'SUCCEEDED', 'FAILED', 'INTERRUPTED')),
    claim_owner TEXT NOT NULL,
    claimed_at TEXT NOT NULL,
    lease_duration_seconds INTEGER NOT NULL CHECK (lease_duration_seconds > 0),
    lease_expires_at TEXT NOT NULL,
    completed_at TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (work_item_key) REFERENCES work_items(work_item_key) ON DELETE RESTRICT
);
"""

CREATE_RETRY_AUTHORIZATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS retry_authorizations (
    authorization_id TEXT PRIMARY KEY NOT NULL,
    work_item_key TEXT NOT NULL,
    approved_attempt_number INTEGER NOT NULL CHECK (approved_attempt_number >= 2),
    approval_actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT NULL,
    consuming_attempt_id TEXT NULL,
    FOREIGN KEY (work_item_key) REFERENCES work_items(work_item_key) ON DELETE RESTRICT
);
"""


class StateLedger:
    """Offline SQLite state ledger for managing download work items."""

    def __init__(self, db_path: Union[str, Path], storage_root: Path) -> None:
        self._db_path = Path(db_path)
        storage_root_path = Path(storage_root)

        if not storage_root_path.is_absolute():
            raise ValueError(f"storage_root must be an absolute path, got {storage_root}")
        if ".." in storage_root_path.parts:
            raise ValueError(f"storage_root path cannot contain '..', got {storage_root}")

        self._storage_root = storage_root_path

        if not self._db_path.exists():
            self._init_database()
        else:
            self._verify_schema_version()


    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, autocommit=True)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_database(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("BEGIN IMMEDIATE;")
            conn.executescript(CREATE_WORK_ITEMS_TABLE)
            conn.executescript(CREATE_ATTEMPTS_TABLE)
            conn.executescript(CREATE_RETRY_AUTHORIZATIONS_TABLE)
            conn.execute("PRAGMA user_version = 1;")
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            conn.close()
            raise
        finally:
            conn.close()

    def _verify_schema_version(self) -> None:
        conn = self._connect()
        try:
            version = conn.execute("PRAGMA user_version;").fetchone()[0]
            if version != 1:
                raise ValueError(f"Unsupported schema version {version}, expected 1.")
        finally:
            conn.close()

    def register_work_item(self, item: DownloadWorkItem) -> RegistrationResult:
        rel_path = self._compute_relative_path(item.output_directory)
        rel_posix = rel_path.as_posix()

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                """
                SELECT symbol, security_id, exchange_segment, instrument, bar_size,
                       session_date, desired_start_ist, desired_end_ist,
                       request_from_date, request_to_date, artifact_directory_rel
                FROM work_items WHERE work_item_key = ?
                """,
                (item.work_item_key,)
            )
            row = cursor.fetchone()

            if row is not None:
                (
                    ex_symbol, ex_sec_id, ex_ex_seg, ex_inst, ex_bar_sz,
                    ex_sess_date, ex_start_ist, ex_end_ist,
                    ex_req_from, ex_req_to, ex_rel_path
                ) = row

                matches = (
                    ex_symbol == item.symbol and
                    ex_sec_id == item.security_id and
                    ex_ex_seg == item.exchange_segment and
                    ex_inst == item.instrument and
                    ex_bar_sz == item.bar_size and
                    ex_sess_date == item.session_date.isoformat() and
                    ex_start_ist == item.request_window.desired_start_ist and
                    ex_end_ist == item.request_window.desired_end_ist and
                    ex_req_from == item.request_window.from_date and
                    ex_req_to == item.request_window.to_date and
                    ex_rel_path == rel_posix
                )

                if matches:
                    conn.execute("COMMIT;")
                    return RegistrationResult(
                        status=RegistrationStatus.EXISTING_MATCH,
                        work_item_key=item.work_item_key,
                        artifact_directory_rel=rel_posix
                    )
                else:
                    conn.execute("ROLLBACK;")
                    raise ValueError(f"Metadata conflict for existing work item key: {item.work_item_key}")

            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO work_items (
                    work_item_key, symbol, security_id, exchange_segment, instrument,
                    bar_size, session_date, desired_start_ist, desired_end_ist,
                    request_from_date, request_to_date, artifact_directory_rel,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PLANNED', ?, ?)
                """,
                (
                    item.work_item_key,
                    item.symbol,
                    item.security_id,
                    item.exchange_segment,
                    item.instrument,
                    item.bar_size,
                    item.session_date.isoformat(),
                    item.request_window.desired_start_ist,
                    item.request_window.desired_end_ist,
                    item.request_window.from_date,
                    item.request_window.to_date,
                    rel_posix,
                    now_iso,
                    now_iso
                )
            )
            conn.execute("COMMIT;")
            return RegistrationResult(
                status=RegistrationStatus.CREATED,
                work_item_key=item.work_item_key,
                artifact_directory_rel=rel_posix
            )
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def claim_work_item(
        self,
        work_item_key: str,
        claim_owner: str,
        lease_duration_seconds: int
    ) -> ClaimResult:
        if not claim_owner or not isinstance(claim_owner, str) or not claim_owner.strip():
            raise ValueError("claim_owner must be a non-empty string.")
        if type(lease_duration_seconds) is not int or isinstance(lease_duration_seconds, bool) or lease_duration_seconds <= 0:
            raise ValueError(f"lease_duration_seconds must be a positive integer, got {lease_duration_seconds}.")

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "SELECT state FROM work_items WHERE work_item_key = ?;",
                (work_item_key,)
            )
            row = cursor.fetchone()

            if row is None:
                conn.execute("COMMIT;")
                return ClaimResult(status=ClaimStatus.WORK_ITEM_NOT_FOUND, work_item_key=work_item_key)

            current_state = row[0]
            if current_state == "CLAIMED":
                conn.execute("COMMIT;")
                return ClaimResult(status=ClaimStatus.ALREADY_CLAIMED, work_item_key=work_item_key)
            elif current_state == "SUCCEEDED":
                conn.execute("COMMIT;")
                return ClaimResult(status=ClaimStatus.ALREADY_SUCCEEDED, work_item_key=work_item_key)
            elif current_state == "REVIEW_REQUIRED":
                conn.execute("COMMIT;")
                return ClaimResult(status=ClaimStatus.REVIEW_REQUIRED, work_item_key=work_item_key)
            elif current_state != "PLANNED":
                conn.execute("ROLLBACK;")
                raise ValueError(f"Unexpected work item state: {current_state}")

            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()
            lease_expires_iso = (now_dt + timedelta(seconds=lease_duration_seconds)).isoformat()
            run_id_str = now_dt.strftime("%Y%m%dT%H%M%SZ")
            attempt_id_str = str(uuid.uuid4())
            attempt_number = 1

            conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id, work_item_key, attempt_number, run_id, state,
                    claim_owner, claimed_at, lease_duration_seconds, lease_expires_at,
                    completed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'CLAIMED', ?, ?, ?, ?, NULL, ?, ?);
                """,
                (
                    attempt_id_str, work_item_key, attempt_number, run_id_str,
                    claim_owner, now_iso, lease_duration_seconds, lease_expires_iso,
                    now_iso, now_iso
                )
            )

            update_cursor = conn.execute(
                """
                UPDATE work_items
                SET state = 'CLAIMED', updated_at = ?
                WHERE work_item_key = ? AND state = 'PLANNED';
                """,
                (now_iso, work_item_key)
            )

            if update_cursor.rowcount != 1:
                conn.execute("ROLLBACK;")
                raise RuntimeError(f"State transition conflict while claiming work item: {work_item_key}")

            conn.execute("COMMIT;")


            attempt = WorkItemAttempt(
                attempt_id=attempt_id_str,
                work_item_key=work_item_key,
                attempt_number=attempt_number,
                run_id=run_id_str,
                state="CLAIMED",
                claim_owner=claim_owner,
                claimed_at=now_iso,
                lease_duration_seconds=lease_duration_seconds,
                lease_expires_at=lease_expires_iso,
                completed_at=None
            )

            return ClaimResult(status=ClaimStatus.CLAIMED, work_item_key=work_item_key, attempt=attempt)
        except Exception:
            try:
                conn.execute("ROLLBACK;")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def _compute_relative_path(self, target_path: Path) -> Path:
        target = Path(target_path)
        if not target.is_absolute():
            raise ValueError(f"output_directory must be an absolute path, got {target_path}")
        if ".." in target.parts:
            raise ValueError(f"output_directory path cannot contain '..', got {target_path}")
        try:
            rel = target.relative_to(self._storage_root)
        except ValueError:
            raise ValueError(f"Output directory {target_path} is outside configured storage root {self._storage_root}")
        return rel
