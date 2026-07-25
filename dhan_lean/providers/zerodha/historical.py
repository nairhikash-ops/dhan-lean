"""Pure offline parsing of Zerodha historical-candle responses."""

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Union
from zoneinfo import ZoneInfo

from dhan_lean.data.models import NormalizedBar
from dhan_lean.providers.zerodha.instruments import InstrumentRecord

IST = ZoneInfo("Asia/Kolkata")


class HistoricalCandleParseError(ValueError):
    """The provider response is not a valid historical-candle response."""


@dataclass(frozen=True)
class ParsedHistoricalCandles:
    """Immutable normalized bars plus provider-side open-interest values."""

    bars: tuple[NormalizedBar, ...]
    open_interest: tuple[Decimal | None, ...]
    had_open_interest: bool

    def __post_init__(self) -> None:
        if len(self.bars) != len(self.open_interest):
            raise ValueError("bars and open_interest must have equal lengths")
        object.__setattr__(self, "bars", tuple(self.bars))
        object.__setattr__(self, "open_interest", tuple(self.open_interest))


def _json_payload(payload: Union[bytes, bytearray, Mapping[str, Any]]) -> Mapping[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            decoded = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HistoricalCandleParseError("response is not valid UTF-8 JSON") from exc
    elif isinstance(payload, Mapping):
        decoded = payload
    else:
        raise TypeError("payload must be decoded JSON mapping or raw JSON bytes")
    if not isinstance(decoded, Mapping):
        raise HistoricalCandleParseError("response root must be an object")
    return decoded


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise HistoricalCandleParseError(f"{field} must be a numeric non-boolean value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HistoricalCandleParseError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise HistoricalCandleParseError(f"{field} must be finite")
    return result


def _volume(value: Any) -> int:
    result = _decimal(value, "volume")
    if result != result.to_integral_value() or result < 0:
        raise HistoricalCandleParseError("volume must be a lossless non-negative integer")
    return int(result)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise HistoricalCandleParseError("timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HistoricalCandleParseError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HistoricalCandleParseError("timestamp must be timezone-aware")
    return parsed.astimezone(IST)


def parse_historical_candles(
    payload: Union[bytes, bytearray, Mapping[str, Any]],
    instrument: InstrumentRecord,
) -> ParsedHistoricalCandles:
    """Parse a documented response without repairing provider data."""
    root = _json_payload(payload)
    for key in ("status", "data"):
        if key not in root:
            raise HistoricalCandleParseError(f"response missing required field: {key}")
    if root["status"] != "success":
        raise HistoricalCandleParseError("response status is not success")
    data = root["data"]
    if not isinstance(data, Mapping) or "candles" not in data:
        raise HistoricalCandleParseError("response data must contain candles")
    candles = data["candles"]
    if not isinstance(candles, list):
        raise HistoricalCandleParseError("candles must be a list")
    if not candles:
        # Empty is valid at the provider-parser layer; future ingestion/coverage
        # logic must classify it before marking a work item successful.
        return ParsedHistoricalCandles((), (), False)

    row_length = None
    bars: list[NormalizedBar] = []
    open_interest: list[Decimal | None] = []
    previous: datetime | None = None
    for index, row in enumerate(candles):
        if not isinstance(row, list) or len(row) not in (6, 7):
            raise HistoricalCandleParseError(f"candle row {index} must contain 6 or 7 fields")
        if row_length is None:
            row_length = len(row)
        elif len(row) != row_length:
            raise HistoricalCandleParseError("candle rows must use one consistent schema")

        timestamp = _timestamp(row[0])
        if previous is not None and timestamp <= previous:
            reason = "duplicate" if timestamp == previous else "out-of-order"
            raise HistoricalCandleParseError(f"candle row {index} has {reason} timestamp")
        previous = timestamp

        prices = tuple(_decimal(row[offset], name) for offset, name in zip(
            range(1, 5), ("open", "high", "low", "close")
        ))
        if any(price <= 0 for price in prices):
            raise HistoricalCandleParseError(f"candle row {index} has non-positive price")
        open_price, high_price, low_price, close_price = prices
        if not (low_price <= open_price <= high_price and low_price <= close_price <= high_price):
            raise HistoricalCandleParseError(f"candle row {index} has invalid OHLC relationship")

        oi = _decimal(row[6], "open interest") if len(row) == 7 else None
        bars.append(NormalizedBar(
            symbol=instrument.tradingsymbol,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=_volume(row[5]),
        ))
        open_interest.append(oi)

    return ParsedHistoricalCandles(tuple(bars), tuple(open_interest), row_length == 7)
