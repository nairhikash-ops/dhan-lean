"""Persistent, fail-closed request allowance guard."""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Union


class RequestBudgetError(RuntimeError):
    """Base error for budget configuration, storage, or exhaustion failures."""


class RequestBudgetStateError(RequestBudgetError):
    """Raised when durable budget state is missing, corrupt, or inconsistent."""


class RequestBudgetExceeded(RequestBudgetError):
    """Raised when consuming would exceed the configured allowance."""


@dataclass(frozen=True)
class RequestBudgetSnapshot:
    scope: str
    window_id: str
    allowance: int
    consumed: int

    @property
    def remaining(self) -> int:
        return self.allowance - self.consumed


CREATE_REQUEST_BUDGETS_TABLE = """
CREATE TABLE IF NOT EXISTS request_budgets (
    scope TEXT NOT NULL,
    window_id TEXT NOT NULL,
    allowance INTEGER NOT NULL,
    consumed INTEGER NOT NULL,
    PRIMARY KEY (scope, window_id),
    CHECK (length(scope) > 0),
    CHECK (length(window_id) > 0),
    CHECK (allowance >= 0),
    CHECK (consumed >= 0),
    CHECK (consumed <= allowance)
);
"""


class RequestBudget:
    """SQLite-backed allowance state shared by independently launched processes.

    A budget is identified by ``(scope, window_id)``.  A new window_id is the
    explicit reset boundary; there is no implicit clock-based reset.
    """

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._db_path = Path(db_path)
        if not self._db_path.parent.exists():
            raise RequestBudgetStateError(
                f"Budget database parent does not exist: {self._db_path.parent}"
            )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self._db_path, timeout=30, autocommit=True)
            conn.execute("PRAGMA foreign_keys = ON;")
            return conn
        except (sqlite3.Error, OSError) as exc:
            raise RequestBudgetStateError(
                f"Cannot open request-budget database {self._db_path}: {exc}"
            ) from exc

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute(CREATE_REQUEST_BUDGETS_TABLE)
        except sqlite3.Error as exc:
            raise RequestBudgetStateError(
                f"Cannot initialize request-budget storage: {exc}"
            ) from exc
        finally:
            conn.close()

    @staticmethod
    def _validate_identity(scope: str, window_id: str) -> None:
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if not isinstance(window_id, str) or not window_id.strip():
            raise ValueError("window_id must be a non-empty string")

    @staticmethod
    def _validate_nonnegative_int(value: int, name: str) -> None:
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")

    def configure(self, scope: str, window_id: str, allowance: int) -> RequestBudgetSnapshot:
        self._validate_identity(scope, window_id)
        self._validate_nonnegative_int(allowance, "allowance")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT allowance, consumed FROM request_budgets WHERE scope = ? AND window_id = ?",
                (scope, window_id),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO request_budgets(scope, window_id, allowance, consumed) VALUES (?, ?, ?, 0)",
                    (scope, window_id, allowance),
                )
                consumed = 0
            else:
                existing_allowance, consumed = row
                if type(existing_allowance) is not int or type(consumed) is not int:
                    raise RequestBudgetStateError("Request-budget state contains non-integer values")
                if existing_allowance != allowance or consumed < 0 or consumed > existing_allowance:
                    raise RequestBudgetStateError(
                        "Existing request-budget configuration conflicts with the requested allowance"
                    )
            conn.execute("COMMIT;")
            return RequestBudgetSnapshot(scope, window_id, allowance, consumed)
        except RequestBudgetError:
            conn.execute("ROLLBACK;")
            raise
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK;")
            raise RequestBudgetStateError(f"Cannot configure request budget: {exc}") from exc
        finally:
            conn.close()

    def snapshot(self, scope: str, window_id: str) -> RequestBudgetSnapshot:
        self._validate_identity(scope, window_id)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT allowance, consumed FROM request_budgets WHERE scope = ? AND window_id = ?",
                (scope, window_id),
            ).fetchone()
            if row is None:
                raise RequestBudgetStateError("Request-budget state is not configured")
            allowance, consumed = row
            if (type(allowance) is not int or type(consumed) is not int or
                    allowance < 0 or consumed < 0 or consumed > allowance):
                raise RequestBudgetStateError("Request-budget state is corrupt or inconsistent")
            return RequestBudgetSnapshot(scope, window_id, allowance, consumed)
        except RequestBudgetError:
            raise
        except sqlite3.Error as exc:
            raise RequestBudgetStateError(f"Cannot read request-budget state: {exc}") from exc
        finally:
            conn.close()

    def consume(self, scope: str, window_id: str, amount: int = 1) -> RequestBudgetSnapshot:
        self._validate_identity(scope, window_id)
        if type(amount) is not int or amount <= 0:
            raise ValueError("amount must be a positive integer")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            row = conn.execute(
                "SELECT allowance, consumed FROM request_budgets WHERE scope = ? AND window_id = ?",
                (scope, window_id),
            ).fetchone()
            if row is None:
                raise RequestBudgetStateError("Request-budget state is not configured")
            allowance, consumed = row
            if (type(allowance) is not int or type(consumed) is not int or
                    allowance < 0 or consumed < 0 or consumed > allowance):
                raise RequestBudgetStateError("Request-budget state is corrupt or inconsistent")
            if amount > allowance - consumed:
                raise RequestBudgetExceeded(
                    f"Request allowance exhausted for scope={scope!r}, window={window_id!r}; "
                    f"remaining={allowance - consumed}, requested={amount}"
                )
            new_consumed = consumed + amount
            cursor = conn.execute(
                "UPDATE request_budgets SET consumed = ? WHERE scope = ? AND window_id = ? AND consumed = ?",
                (new_consumed, scope, window_id, consumed),
            )
            if cursor.rowcount != 1:
                raise RequestBudgetStateError("Atomic request-budget update affected an unexpected number of rows")
            conn.execute("COMMIT;")
            return RequestBudgetSnapshot(scope, window_id, allowance, new_consumed)
        except RequestBudgetError:
            conn.execute("ROLLBACK;")
            raise
        except sqlite3.Error as exc:
            conn.execute("ROLLBACK;")
            raise RequestBudgetStateError(f"Cannot consume request budget: {exc}") from exc
        finally:
            conn.close()
