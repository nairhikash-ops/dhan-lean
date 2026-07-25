"""Validation for provider-normalized bars."""

from collections import Counter
from decimal import Decimal
from typing import Sequence

from dhan_lean.data.models import NormalizedBar, ValidationResult


def validate_normalized_bars(bars: Sequence[NormalizedBar], expected_interval_seconds: int = 60) -> ValidationResult:
    if type(expected_interval_seconds) is not int or expected_interval_seconds <= 0:
        raise ValueError("expected_interval_seconds must be a positive integer")
    errors: list[str] = []
    duplicate = non_increasing = invalid_ohlc = non_positive = negative_volume = 0
    invalid_price_type = False
    deltas: Counter[int] = Counter()
    previous = None
    for index, bar in enumerate(bars):
        if not isinstance(bar, NormalizedBar):
            errors.append(f"Row {index}: not a NormalizedBar")
            continue
        prices = (bar.open, bar.high, bar.low, bar.close)
        if any(not isinstance(price, Decimal) for price in prices):
            invalid_price_type = True
            non_positive += 1
        elif any(not price.is_finite() or price <= 0 for price in prices):
            non_positive += 1
        elif not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
            invalid_ohlc += 1
        if type(bar.volume) is not int or bar.volume < 0:
            negative_volume += 1
        if previous is not None:
            delta = int((bar.timestamp - previous).total_seconds())
            deltas[delta] += 1
            if delta == 0:
                duplicate += 1
                non_increasing += 1
            elif delta < 0:
                non_increasing += 1
        previous = bar.timestamp
    if not bars:
        errors.append("No bars supplied")
    if non_positive:
        errors.append(f"Found {non_positive} bars with non-positive or invalid prices")
    if invalid_ohlc:
        errors.append(f"Found {invalid_ohlc} bars with invalid OHLC relationships")
    if negative_volume:
        errors.append(f"Found {negative_volume} bars with negative volume")
    if non_increasing:
        errors.append(f"Timestamps are not strictly increasing: {duplicate} duplicates, {non_increasing} non-increasing")
    error_code = None
    if not errors:
        error_summary = None
    else:
        if not bars:
            error_code = "EMPTY_BARS"
        elif invalid_price_type:
            error_code = "INVALID_PRICE_TYPE"
        elif non_positive:
            error_code = "INVALID_PRICE_VALUE"
        elif invalid_ohlc:
            error_code = "INVALID_OHLC"
        elif non_increasing:
            error_code = "NON_MONOTONIC_TIMESTAMPS"
        elif negative_volume:
            error_code = "INVALID_VOLUME"
        else:
            error_code = "INVALID_NORMALIZED_BARS"
        error_summary = "; ".join(errors)[:500]
    return ValidationResult(not errors, tuple(errors), len(bars), non_increasing == 0, duplicate, non_increasing,
                            invalid_ohlc, non_positive, negative_volume, dict(deltas), error_code, error_summary)
