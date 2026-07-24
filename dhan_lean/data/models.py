from datetime import date
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Optional, Mapping, Tuple, Any


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
class RegistrationResult:
    """Immutable result of a DownloadWorkItem registration call."""
    status: RegistrationStatus
    work_item_key: str
    artifact_directory_rel: str


@dataclass(frozen=True)
class WorkItemAttempt:
    """Immutable representation of a download attempt record."""
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
    """Immutable result of an initial work item claim call."""
    status: ClaimStatus
    work_item_key: str
    attempt: Optional[WorkItemAttempt] = None


@dataclass(frozen=True)
class SingleExecutionResult:
    """Immutable result container for a single work-item execution."""
    status: str
    work_item_key: str
    claim_status: ClaimStatus
    attempt: Optional[WorkItemAttempt] = None
    download_result: Optional[DownloadResult] = None
    error_code: Optional[str] = None
    error_summary: Optional[str] = None




@dataclass(frozen=True)
class RequestWindow:
    """Represents calculated fromDate and toDate bounds for Dhan API V2."""
    from_date: str
    to_date: str
    desired_start_ist: str
    desired_end_ist: str
    interval_minutes: int = 1


@dataclass(frozen=True)
class ValidationResult:
    """Structured, immutable data validation result for Dhan intraday responses."""
    is_valid: bool
    errors: Tuple[str, ...]
    candle_count: int
    array_lengths: Mapping[str, int]
    arrays_equal_length: bool
    timestamps_strictly_increasing: bool
    duplicate_timestamp_count: int
    non_increasing_timestamp_count: int
    invalid_ohlc_count: int
    non_positive_price_count: int
    negative_volume_count: int
    zero_volume_count: int
    timestamp_delta_distribution: Mapping[int, int]
    missing_gap_count: int
    largest_actual_interval_seconds: int
    largest_excess_gap_seconds: int
    first_timestamp_utc: Optional[str]
    last_timestamp_utc: Optional[str]
    first_timestamp_ist: Optional[str]
    last_timestamp_ist: Optional[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(self, "array_lengths", MappingProxyType(dict(self.array_lengths)))
        object.__setattr__(self, "timestamp_delta_distribution", MappingProxyType(dict(self.timestamp_delta_distribution)))


@dataclass(frozen=True)
class HttpResponse:
    """Immutable HTTP response container."""
    status_code: int
    body: bytes
    headers: bytes

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or isinstance(self.status_code, bool):
            raise TypeError(f"status_code must be an integer, got {type(self.status_code).__name__}")
        if not (100 <= self.status_code <= 599):
            raise ValueError(f"status_code must be between 100 and 599 inclusive, got {self.status_code}")
        if not isinstance(self.body, bytes):
            raise TypeError(f"body must be bytes, got {type(self.body).__name__}")
        if not isinstance(self.headers, bytes):
            raise TypeError(f"headers must be bytes, got {type(self.headers).__name__}")


@dataclass(frozen=True)
class DownloadResult:
    """Structured, immutable downloader execution result."""
    run_id: str
    output_directory: Path
    status_code: int
    artifact_paths: Mapping[str, Path]
    validation_result: Optional[ValidationResult]
    error_code: Optional[str]
    error_message: Optional[str]
    success: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_paths", MappingProxyType(dict(self.artifact_paths)))


@dataclass(frozen=True)
class DownloadWorkItem:
    """Immutable 1-minute intraday download work unit for a single session date."""
    symbol: str
    security_id: str
    exchange_segment: str
    instrument: str
    bar_size: str
    session_date: date
    request_window: RequestWindow
    output_directory: Path
    work_item_key: str
