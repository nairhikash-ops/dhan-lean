"""Immutable provider-neutral contracts for offline market-data work."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple


class RegistrationStatus(Enum):
    CREATED = "CREATED"
    EXISTING_MATCH = "EXISTING_MATCH"


class ClaimStatus(Enum):
    CLAIMED = "CLAIMED"
    WORK_ITEM_NOT_FOUND = "WORK_ITEM_NOT_FOUND"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    ALREADY_SUCCEEDED = "ALREADY_SUCCEEDED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class NormalizedBar:
    """One source-normalized OHLCV bar; timestamps must be timezone-aware."""
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if type(self.volume) is not int or self.volume < 0:
            raise ValueError("volume must be a non-negative integer")
        object.__setattr__(self, "source_metadata", MappingProxyType(dict(self.source_metadata)))


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime
    interval_minutes: int = 1

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window datetimes must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("window start must precede end")
        if type(self.interval_minutes) is not int or self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be a positive integer")


@dataclass(frozen=True)
class DataWorkItem:
    symbol: str
    source_id: str
    bar_size: str
    session_date: date
    window: TimeWindow
    output_directory: Path
    work_item_key: str


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: Tuple[str, ...]
    bar_count: int
    timestamps_strictly_increasing: bool
    duplicate_timestamp_count: int
    non_increasing_timestamp_count: int
    invalid_ohlc_count: int
    non_positive_price_count: int
    negative_volume_count: int
    timestamp_delta_distribution: Mapping[int, int]
    error_code: Optional[str] = None
    error_summary: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "timestamp_delta_distribution", MappingProxyType(dict(self.timestamp_delta_distribution)))


@dataclass(frozen=True)
class IngestionResult:
    output_directory: Path
    bars: Tuple[NormalizedBar, ...]
    validation_result: ValidationResult
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class RegistrationResult:
    status: RegistrationStatus
    work_item_key: str
    artifact_directory_rel: str


@dataclass(frozen=True)
class WorkItemAttempt:
    attempt_id: str
    work_item_key: str
    attempt_number: int
    run_id: str
    state: str
    claim_owner: str
    claimed_at: str
    lease_duration_seconds: int
    lease_expires_at: str
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass(frozen=True)
class ClaimResult:
    status: ClaimStatus
    work_item_key: str
    attempt: Optional[WorkItemAttempt] = None


@dataclass(frozen=True)
class SingleExecutionResult:
    status: str
    work_item_key: str
    claim_status: ClaimStatus
    attempt: Optional[WorkItemAttempt] = None
    ingestion_result: Optional[IngestionResult] = None
    error_code: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass(frozen=True)
class LeanConversionResult:
    output_zip_path: Path
    member_filename: str
    normalized_symbol: str
    session_date: date
    rows_written: int
    bytes_written: int
