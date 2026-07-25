"""Offline Zerodha historical-request planning and deterministic fingerprints."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from dhan_lean.data.models import DataWorkItem, TimeWindow
from dhan_lean.providers.zerodha.broker_protocol import CandleRequest
from dhan_lean.providers.zerodha.instruments import InstrumentRecord, InstrumentSnapshot


IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
PLANNING_SCHEMA_VERSION = 1
FINGERPRINT_SCHEMA_VERSION = 1


class PlanningErrorCode(str, Enum):
    UNSUPPORTED_SOURCE = "UNSUPPORTED_SOURCE"
    UNSUPPORTED_RESOLUTION = "UNSUPPORTED_RESOLUTION"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    EXCHANGE_MISMATCH = "EXCHANGE_MISMATCH"
    INVALID_WORK_ITEM_WINDOW = "INVALID_WORK_ITEM_WINDOW"
    CROSS_SESSION_WINDOW = "CROSS_SESSION_WINDOW"
    NON_MINUTE_ALIGNED_WINDOW = "NON_MINUTE_ALIGNED_WINDOW"
    WINDOW_OUTSIDE_SESSION = "WINDOW_OUTSIDE_SESSION"
    SESSION_DATE_MISMATCH = "SESSION_DATE_MISMATCH"
    INVALID_SNAPSHOT_HASH = "INVALID_SNAPSHOT_HASH"
    INVALID_RESOLVED_INSTRUMENT = "INVALID_RESOLVED_INSTRUMENT"
    INVALID_DERIVATIVE_IDENTITY = "INVALID_DERIVATIVE_IDENTITY"
    UNSUPPORTED_CONTINUOUS_MODE = "UNSUPPORTED_CONTINUOUS_MODE"
    UNSUPPORTED_INSTRUMENT_TYPE = "UNSUPPORTED_INSTRUMENT_TYPE"
    INVALID_REQUEST_ID = "INVALID_REQUEST_ID"
    FINGERPRINT_SERIALIZATION_FAILURE = "FINGERPRINT_SERIALIZATION_FAILURE"


_SAFE_MESSAGES = {
    PlanningErrorCode.UNSUPPORTED_SOURCE: "Only the Zerodha source is supported.",
    PlanningErrorCode.UNSUPPORTED_RESOLUTION: "Only one-minute bars are supported.",
    PlanningErrorCode.SYMBOL_MISMATCH: "Work-item and instrument symbols do not match.",
    PlanningErrorCode.EXCHANGE_MISMATCH: "Requested and resolved exchanges do not match.",
    PlanningErrorCode.INVALID_WORK_ITEM_WINDOW: "The work-item window is invalid.",
    PlanningErrorCode.CROSS_SESSION_WINDOW: "The request crosses an IST session date.",
    PlanningErrorCode.NON_MINUTE_ALIGNED_WINDOW: "The request window is not minute-aligned.",
    PlanningErrorCode.WINDOW_OUTSIDE_SESSION: "The request is outside the approved trading session.",
    PlanningErrorCode.SESSION_DATE_MISMATCH: "The request does not match the work-item session date.",
    PlanningErrorCode.INVALID_SNAPSHOT_HASH: "The instrument snapshot hash is invalid.",
    PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT: "The resolved instrument identity is invalid.",
    PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY: "The resolved derivative identity is invalid.",
    PlanningErrorCode.UNSUPPORTED_CONTINUOUS_MODE: "Continuous instruments are not supported.",
    PlanningErrorCode.UNSUPPORTED_INSTRUMENT_TYPE: "The instrument type is not supported.",
    PlanningErrorCode.INVALID_REQUEST_ID: "The broker request ID is invalid.",
    PlanningErrorCode.FINGERPRINT_SERIALIZATION_FAILURE: "The request fingerprint could not be serialized.",
}


class ZerodhaPlanningError(ValueError):
    """Safe, stable error for provider-specific planning failures."""

    def __init__(self, code: PlanningErrorCode):
        self.code = PlanningErrorCode(code)
        super().__init__(_SAFE_MESSAGES[self.code])

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


@dataclass(frozen=True)
class ZerodhaPlanningInput:
    """All non-secret identity needed to plan one historical request."""

    work_item: DataWorkItem
    instrument: InstrumentRecord
    snapshot: InstrumentSnapshot
    exchange: str
    protocol_version: int = 1
    planning_schema_version: int = PLANNING_SCHEMA_VERSION
    continuous: bool = False
    oi: bool = False


@dataclass(frozen=True)
class ZerodhaPlannedRequest:
    candle_request: CandleRequest
    fingerprint: str
    canonical_metadata: Mapping[str, object]
    provider_instrument_id: str
    symbol: str
    exchange: str
    instrument_type: str
    expiry: date | None
    strike: Decimal | None
    instrument_snapshot_date: date
    instrument_snapshot_sha256: str
    planning_schema_version: int
    protocol_version: int
    session_date: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_metadata", MappingProxyType(dict(self.canonical_metadata)))


def _fail(code: PlanningErrorCode) -> None:
    raise ZerodhaPlanningError(code)


def _canonical_provider_id(value: object) -> str:
    if not isinstance(value, str) or not value or not all("0" <= char <= "9" for char in value):
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if int(value) <= 0:
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    return str(int(value))


def _valid_hash(value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower() or any(char not in "0123456789abcdef" for char in value):
        _fail(PlanningErrorCode.INVALID_SNAPSHOT_HASH)
    return value


def _canonical_decimal(value: Decimal) -> str:
    if not isinstance(value, Decimal) or not value.is_finite():
        _fail(PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
    if value.is_zero():
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


def _aware_ist(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(PlanningErrorCode.INVALID_WORK_ITEM_WINDOW)
    return value.astimezone(IST)


def _validate_identity(plan: ZerodhaPlanningInput) -> tuple[str, str, str, date | None, Decimal | None, str]:
    if not isinstance(plan.work_item, DataWorkItem) or not isinstance(plan.instrument, InstrumentRecord) or not isinstance(plan.snapshot, InstrumentSnapshot):
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if plan.work_item.source_id != "zerodha":
        _fail(PlanningErrorCode.UNSUPPORTED_SOURCE)
    if plan.work_item.bar_size != "1m":
        _fail(PlanningErrorCode.UNSUPPORTED_RESOLUTION)
    if type(plan.protocol_version) is not int or plan.protocol_version != 1 or type(plan.planning_schema_version) is not int or plan.planning_schema_version != PLANNING_SCHEMA_VERSION:
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if type(plan.continuous) is not bool or plan.continuous:
        _fail(PlanningErrorCode.UNSUPPORTED_CONTINUOUS_MODE)
    if type(plan.oi) is not bool:
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if not isinstance(plan.instrument.exchange, str) or not plan.instrument.exchange.strip() or plan.instrument.exchange != plan.instrument.exchange.strip().upper():
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if not isinstance(plan.instrument.tradingsymbol, str) or not plan.instrument.tradingsymbol.strip() or plan.instrument.tradingsymbol != plan.instrument.tradingsymbol.strip().upper():
        _fail(PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
    if not isinstance(plan.exchange, str) or plan.exchange != plan.exchange.strip().upper():
        _fail(PlanningErrorCode.EXCHANGE_MISMATCH)
    if plan.exchange != plan.instrument.exchange:
        _fail(PlanningErrorCode.EXCHANGE_MISMATCH)
    symbol = plan.work_item.symbol
    instrument_symbol = plan.instrument.tradingsymbol
    if not isinstance(symbol, str) or symbol != symbol.strip().upper() or not isinstance(instrument_symbol, str) or instrument_symbol != instrument_symbol.strip().upper() or symbol != instrument_symbol:
        _fail(PlanningErrorCode.SYMBOL_MISMATCH)
    provider_id = _canonical_provider_id(plan.instrument.instrument_token)
    instrument_type = plan.instrument.instrument_type
    if instrument_type not in {"EQ", "FUT", "CE", "PE"}:
        _fail(PlanningErrorCode.UNSUPPORTED_INSTRUMENT_TYPE)
    expiry = plan.instrument.expiry
    strike = plan.instrument.strike
    if instrument_type == "EQ":
        if expiry is not None or strike is not None:
            _fail(PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
    elif instrument_type == "FUT":
        if type(expiry) is not date or strike is not None:
            _fail(PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
    else:
        if type(expiry) is not date or not isinstance(strike, Decimal) or not strike.is_finite() or strike < 0:
            _fail(PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
    if type(plan.work_item.session_date) is not date:
        _fail(PlanningErrorCode.SESSION_DATE_MISMATCH)
    if instrument_type != "EQ" and plan.work_item.session_date > expiry:
        _fail(PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
    if type(plan.snapshot.snapshot_date) is not date:
        _fail(PlanningErrorCode.INVALID_SNAPSHOT_HASH)
    snapshot_hash = _valid_hash(plan.snapshot.content_sha256)
    return provider_id, symbol, instrument_type, expiry, strike, snapshot_hash


def _validate_window(work_item: DataWorkItem) -> tuple[datetime, datetime]:
    if not isinstance(work_item.window, TimeWindow):
        _fail(PlanningErrorCode.INVALID_WORK_ITEM_WINDOW)
    start = _aware_ist(work_item.window.start)
    end = _aware_ist(work_item.window.end)
    if start >= end:
        _fail(PlanningErrorCode.INVALID_WORK_ITEM_WINDOW)
    if start.date() != end.date():
        _fail(PlanningErrorCode.CROSS_SESSION_WINDOW)
    if type(work_item.session_date) is not date:
        _fail(PlanningErrorCode.SESSION_DATE_MISMATCH)
    if start.date() != work_item.session_date:
        _fail(PlanningErrorCode.SESSION_DATE_MISMATCH)
    if start.second or start.microsecond or end.second or end.microsecond:
        _fail(PlanningErrorCode.NON_MINUTE_ALIGNED_WINDOW)
    if start.time() < SESSION_OPEN or end.time() > SESSION_CLOSE:
        _fail(PlanningErrorCode.WINDOW_OUTSIDE_SESSION)
    return start, end


def _canonical_metadata(*, plan: ZerodhaPlanningInput, provider_id: str, symbol: str, instrument_type: str, expiry: date | None, strike: Decimal | None, snapshot_hash: str, start: datetime, end: datetime) -> dict[str, object]:
    return {
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "protocol_version": plan.protocol_version,
        "planning_schema_version": plan.planning_schema_version,
        "provider": "zerodha",
        "provider_instrument_id": provider_id,
        "exchange": plan.exchange,
        "tradingsymbol": symbol,
        "instrument_type": instrument_type,
        "expiry": expiry.isoformat() if expiry is not None else None,
        "strike": _canonical_decimal(strike) if strike is not None else None,
        "instrument_snapshot_date": plan.snapshot.snapshot_date.isoformat(),
        "instrument_snapshot_sha256": snapshot_hash,
        "interval": "minute",
        "from_timestamp": start.isoformat(),
        "to_timestamp": end.isoformat(),
        "continuous": False,
        "oi": plan.oi,
    }


def _fingerprint(metadata: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(metadata, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise ZerodhaPlanningError(PlanningErrorCode.FINGERPRINT_SERIALIZATION_FAILURE) from exc
    return hashlib.sha256(encoded).hexdigest()


def plan_historical_candles(plan: ZerodhaPlanningInput, *, request_id_factory: Callable[[], str] | None = None) -> ZerodhaPlannedRequest:
    """Plan exactly one validated, single-IST-session Zerodha candle request."""
    provider_id, symbol, instrument_type, expiry, strike, snapshot_hash = _validate_identity(plan)
    start, end = _validate_window(plan.work_item)
    metadata = _canonical_metadata(plan=plan, provider_id=provider_id, symbol=symbol, instrument_type=instrument_type, expiry=expiry, strike=strike, snapshot_hash=snapshot_hash, start=start, end=end)
    fingerprint = _fingerprint(metadata)
    factory = request_id_factory or (lambda: str(uuid.uuid4()))
    try:
        request_id = factory()
        candle_request = CandleRequest(1, request_id, provider_id, "minute", start, end, False, plan.oi)
    except ZerodhaPlanningError:
        raise
    except Exception as exc:
        raise ZerodhaPlanningError(PlanningErrorCode.INVALID_REQUEST_ID) from exc
    return ZerodhaPlannedRequest(candle_request, fingerprint, metadata, provider_id, symbol, plan.exchange, instrument_type, expiry, strike, plan.snapshot.snapshot_date, snapshot_hash, plan.planning_schema_version, plan.protocol_version, plan.work_item.session_date)
