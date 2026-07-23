from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional, Mapping, Tuple, Any


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
