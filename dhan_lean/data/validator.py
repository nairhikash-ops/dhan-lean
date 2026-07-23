import math
import collections
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

from dhan_lean.data.models import ValidationResult

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


def _is_strict_number(val: Any) -> bool:
    """Checks if a value is a valid numeric scalar (excluding bools, NaN, and Inf)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    if math.isnan(val) or math.isinf(val):
        return False
    return True


def validate_dhan_response(
    response_data: dict[str, Any],
    expected_interval_seconds: int = 60
) -> ValidationResult:
    """
    Validates an already-loaded Dhan API V2 response dictionary.
    Does not mutate the supplied response dictionary.
    """
    errors: list[str] = []

    if not isinstance(response_data, dict):
        return ValidationResult(
            is_valid=False,
            errors=["Response data is not a dictionary."],
            candle_count=0,
            array_lengths={},
            arrays_equal_length=False,
            timestamps_strictly_increasing=False,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            zero_volume_count=0,
            timestamp_delta_distribution={},
            missing_gap_count=0,
            largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0,
            first_timestamp_utc=None,
            last_timestamp_utc=None,
            first_timestamp_ist=None,
            last_timestamp_ist=None,
        )

    # Check error fields in response
    if response_data.get("errorCode") is not None or response_data.get("errorMessage") is not None:
        errors.append(f"Dhan API Error: code={response_data.get('errorCode')}, message={response_data.get('errorMessage')}")

    # Identify timestamp key ('timestamp' or 'start_Time')
    time_key = None
    if "timestamp" in response_data:
        time_key = "timestamp"
    elif "start_Time" in response_data:
        time_key = "start_Time"

    required_keys = ["open", "high", "low", "close", "volume"]
    if time_key:
        required_keys.append(time_key)
    else:
        errors.append("Missing timestamp array key ('timestamp' or 'start_Time').")

    missing_keys = [k for k in ["open", "high", "low", "close", "volume"] if k not in response_data]
    if missing_keys:
        errors.append(f"Missing required array keys: {missing_keys}")

    if errors and (missing_keys or time_key is None):
        return ValidationResult(
            is_valid=False,
            errors=errors,
            candle_count=0,
            array_lengths={k: len(response_data[k]) for k in required_keys if k in response_data and isinstance(response_data[k], list)},
            arrays_equal_length=False,
            timestamps_strictly_increasing=False,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            zero_volume_count=0,
            timestamp_delta_distribution={},
            missing_gap_count=0,
            largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0,
            first_timestamp_utc=None,
            last_timestamp_utc=None,
            first_timestamp_ist=None,
            last_timestamp_ist=None,
        )

    # Check arrays
    array_lengths = {}
    for k in required_keys:
        val = response_data[k]
        if not isinstance(val, list):
            errors.append(f"Field '{k}' is not a list.")
            array_lengths[k] = 0
        else:
            array_lengths[k] = len(val)

    lengths_set = set(array_lengths.values())
    arrays_equal_length = len(lengths_set) == 1 if array_lengths else False
    if not arrays_equal_length:
        errors.append(f"Array lengths are inconsistent: {array_lengths}")

    candle_count = array_lengths.get("open", 0)

    if candle_count == 0 or not arrays_equal_length:
        return ValidationResult(
            is_valid=False,
            errors=errors,
            candle_count=candle_count,
            array_lengths=array_lengths,
            arrays_equal_length=arrays_equal_length,
            timestamps_strictly_increasing=False,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            zero_volume_count=0,
            timestamp_delta_distribution={},
            missing_gap_count=0,
            largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0,
            first_timestamp_utc=None,
            last_timestamp_utc=None,
            first_timestamp_ist=None,
            last_timestamp_ist=None,
        )

    opens = response_data["open"]
    highs = response_data["high"]
    lows = response_data["low"]
    closes = response_data["close"]
    volumes = response_data["volume"]
    timestamps = response_data[time_key]

    # Validate numeric types & values
    invalid_ohlc_count = 0
    non_positive_price_count = 0
    negative_volume_count = 0
    zero_volume_count = 0

    for i in range(candle_count):
        op, hi, lo, cl, vol = opens[i], highs[i], lows[i], closes[i], volumes[i]

        if not (_is_strict_number(op) and _is_strict_number(hi) and _is_strict_number(lo) and _is_strict_number(cl)):
            non_positive_price_count += 1
            errors.append(f"Row {i}: Non-numeric price value found.")
            continue

        if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
            non_positive_price_count += 1

        if not (lo <= op <= hi and lo <= cl <= hi and lo <= hi):
            invalid_ohlc_count += 1

        if not _is_strict_number(vol):
            negative_volume_count += 1
            errors.append(f"Row {i}: Non-numeric volume value found.")
            continue

        if vol < 0:
            negative_volume_count += 1
        elif vol == 0:
            zero_volume_count += 1

    if non_positive_price_count > 0:
        errors.append(f"Found {non_positive_price_count} candles with non-positive prices.")
    if invalid_ohlc_count > 0:
        errors.append(f"Found {invalid_ohlc_count} candles breaking OHLC relationship (low <= open/close <= high).")
    if negative_volume_count > 0:
        errors.append(f"Found {negative_volume_count} candles with negative volume.")

    # Validate Timestamps
    duplicate_timestamp_count = 0
    non_increasing_timestamp_count = 0
    deltas = []
    delta_distribution: dict[int, int] = collections.Counter()

    for i in range(candle_count):
        ts = timestamps[i]
        if not _is_strict_number(ts):
            errors.append(f"Row {i}: Non-numeric timestamp value '{ts}'.")

    for i in range(1, candle_count):
        ts_prev = timestamps[i - 1]
        ts_curr = timestamps[i]

        if not (_is_strict_number(ts_prev) and _is_strict_number(ts_curr)):
            continue

        delta = ts_curr - ts_prev
        int_delta = int(delta)
        deltas.append(int_delta)
        delta_distribution[int_delta] += 1

        if delta == 0:
            duplicate_timestamp_count += 1
            non_increasing_timestamp_count += 1
        elif delta < 0:
            non_increasing_timestamp_count += 1

    timestamps_strictly_increasing = (non_increasing_timestamp_count == 0)
    if not timestamps_strictly_increasing:
        errors.append(f"Timestamps are not strictly increasing: {duplicate_timestamp_count} duplicates, {non_increasing_timestamp_count} non-increasing.")

    missing_gap_count = sum(1 for d in deltas if d > expected_interval_seconds)
    largest_actual_interval_seconds = max(deltas) if deltas else 0
    largest_excess_gap_seconds = max(0, largest_actual_interval_seconds - expected_interval_seconds)

    # First and Last Datetimes
    first_ts = timestamps[0] if candle_count > 0 and _is_strict_number(timestamps[0]) else None
    last_ts = timestamps[-1] if candle_count > 0 and _is_strict_number(timestamps[-1]) else None

    first_timestamp_utc = datetime.fromtimestamp(first_ts, tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC') if first_ts is not None else None
    last_timestamp_utc = datetime.fromtimestamp(last_ts, tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC') if last_ts is not None else None

    first_timestamp_ist = datetime.fromtimestamp(first_ts, tz=IST).strftime('%Y-%m-%d %H:%M:%S IST') if first_ts is not None else None
    last_timestamp_ist = datetime.fromtimestamp(last_ts, tz=IST).strftime('%Y-%m-%d %H:%M:%S IST') if last_ts is not None else None

    is_valid = (len(errors) == 0)

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        candle_count=candle_count,
        array_lengths=array_lengths,
        arrays_equal_length=arrays_equal_length,
        timestamps_strictly_increasing=timestamps_strictly_increasing,
        duplicate_timestamp_count=duplicate_timestamp_count,
        non_increasing_timestamp_count=non_increasing_timestamp_count,
        invalid_ohlc_count=invalid_ohlc_count,
        non_positive_price_count=non_positive_price_count,
        negative_volume_count=negative_volume_count,
        zero_volume_count=zero_volume_count,
        timestamp_delta_distribution=dict(delta_distribution),
        missing_gap_count=missing_gap_count,
        largest_actual_interval_seconds=largest_actual_interval_seconds,
        largest_excess_gap_seconds=largest_excess_gap_seconds,
        first_timestamp_utc=first_timestamp_utc,
        last_timestamp_utc=last_timestamp_utc,
        first_timestamp_ist=first_timestamp_ist,
        last_timestamp_ist=last_timestamp_ist,
    )
