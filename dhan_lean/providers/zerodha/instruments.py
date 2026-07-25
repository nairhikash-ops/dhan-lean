"""Offline parsing and exact resolution of Zerodha instrument-master dumps."""

import csv
import gzip
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional


INSTRUMENT_COLUMNS = (
    "instrument_token", "exchange_token", "tradingsymbol", "name", "last_price",
    "expiry", "strike", "tick_size", "lot_size", "instrument_type", "segment", "exchange",
)


def _validate_csv_quoting(text: str) -> None:
    """Reject quotes that are not valid CSV field delimiters or escapes."""
    in_quotes = False
    after_quote = False
    field_start = True
    index = 0
    while index < len(text):
        char = text[index]
        if in_quotes:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = False
                after_quote = True
            index += 1
            continue
        if after_quote:
            if char == ',':
                after_quote = False
                field_start = True
            elif char in "\r\n":
                after_quote = False
                field_start = True
            else:
                raise csv.Error("characters after closing quote")
            index += 1
            continue
        if char == '"':
            if not field_start:
                raise csv.Error("embedded quote in unquoted field")
            in_quotes = True
            field_start = False
        elif char == ',':
            field_start = True
        elif char in "\r\n":
            field_start = True
        else:
            field_start = False
        index += 1
    if in_quotes:
        raise csv.Error("unterminated quoted field")


class InstrumentMasterParseError(ValueError):
    """The instrument-master snapshot is malformed."""


class InstrumentResolutionError(LookupError):
    """Base class for exact instrument-resolution failures."""


class InstrumentNotFoundError(InstrumentResolutionError):
    """No exact instrument matched the query."""


class AmbiguousInstrumentError(InstrumentResolutionError):
    """More than one exact instrument matched the query."""


@dataclass(frozen=True)
class InstrumentRecord:
    instrument_token: str
    exchange_token: str
    tradingsymbol: str
    name: str
    last_price: Optional[Decimal]
    expiry: Optional[date]
    strike: Optional[Decimal]
    tick_size: Optional[Decimal]
    lot_size: Optional[int]
    instrument_type: str
    segment: str
    exchange: str


@dataclass(frozen=True)
class InstrumentSnapshot:
    snapshot_date: date
    content_sha256: str
    instruments: tuple[InstrumentRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "instruments", tuple(self.instruments))


@dataclass(frozen=True)
class InstrumentQuery:
    exchange: str
    tradingsymbol: str
    instrument_type: str
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None

    def __post_init__(self) -> None:
        if self.instrument_type not in {"EQ", "FUT", "CE", "PE"}:
            raise ValueError(f"unsupported instrument type: {self.instrument_type!r}")
        if self.expiry is not None and type(self.expiry) is not date:
            raise TypeError("expiry must be an exact datetime.date instance")
        if self.instrument_type in {"CE", "PE"} and self.strike is not None and type(self.strike) is not Decimal:
            raise TypeError("option strike must be a Decimal")
        if self.strike is not None and (not self.strike.is_finite() or self.strike < 0):
            raise ValueError("strike must be a finite non-negative Decimal")
        if self.instrument_type == "EQ" and (self.expiry is not None or self.strike is not None):
            raise ValueError("equity queries must not specify expiry or strike")
        if self.instrument_type == "FUT" and (self.expiry is None or self.strike is not None):
            raise ValueError("future queries require expiry and must not specify strike")
        if self.instrument_type in {"CE", "PE"} and (self.expiry is None or self.strike is None):
            raise ValueError("option queries require expiry and strike")


def _optional_decimal(value: str, field: str) -> Optional[Decimal]:
    if value.strip() == "":
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise InstrumentMasterParseError(f"invalid {field}") from exc
    if not result.is_finite():
        raise InstrumentMasterParseError(f"invalid {field}")
    return result


def _optional_int(value: str, field: str) -> Optional[int]:
    if value.strip() == "":
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise InstrumentMasterParseError(f"invalid {field}") from exc
    if result != result.to_integral_value() or result < 0:
        raise InstrumentMasterParseError(f"invalid {field}")
    return int(result)


def _optional_date(value: str, field: str) -> Optional[date]:
    if value.strip() == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InstrumentMasterParseError(f"invalid {field}") from exc


def parse_instrument_snapshot(payload: bytes, snapshot_date: date) -> InstrumentSnapshot:
    """Parse plain or gzipped CSV bytes and hash the exact supplied bytes."""
    if type(snapshot_date) is not date:
        raise TypeError("snapshot_date must be an exact date")
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    try:
        raw_csv = gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
    except (OSError, EOFError) as exc:
        raise InstrumentMasterParseError("instrument payload is not valid gzip") from exc
    try:
        text = raw_csv.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstrumentMasterParseError("instrument CSV is not UTF-8") from exc
    try:
        _validate_csv_quoting(text)
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != INSTRUMENT_COLUMNS:
            raise InstrumentMasterParseError("instrument CSV header does not match documented schema")
        records: list[InstrumentRecord] = []
        for index, row in enumerate(reader):
            if None in row or any(value is None for value in row.values()):
                raise InstrumentMasterParseError(f"malformed instrument CSV row {index}")
            try:
                identity = {key: row[key] for key in ("instrument_token", "tradingsymbol", "exchange", "instrument_type")}
                if any(not value or value != value.strip() for value in identity.values()):
                    raise InstrumentMasterParseError(f"malformed instrument identity at row {index}")
                token = identity["instrument_token"]
                if not token.isdigit() or int(token) <= 0:
                    raise InstrumentMasterParseError(f"invalid instrument_token at row {index}")
                instrument_type = identity["instrument_type"]
                if instrument_type not in {"EQ", "FUT", "CE", "PE"}:
                    raise InstrumentMasterParseError(f"unsupported instrument_type at row {index}")
                expiry = _optional_date(row["expiry"], "expiry")
                strike = _optional_decimal(row["strike"], "strike")
                if instrument_type == "EQ":
                    if expiry is not None or (strike is not None and strike != 0):
                        raise InstrumentMasterParseError(f"invalid EQ expiry/strike at row {index}")
                elif instrument_type == "FUT":
                    if expiry is None or (strike is not None and strike != 0):
                        raise InstrumentMasterParseError(f"invalid FUT expiry/strike at row {index}")
                elif expiry is None or strike is None or strike < 0:
                    raise InstrumentMasterParseError(f"invalid option expiry/strike at row {index}")
                records.append(InstrumentRecord(
                    instrument_token=token,
                    exchange_token=row["exchange_token"],
                    tradingsymbol=identity["tradingsymbol"],
                    name=row["name"],
                    last_price=_optional_decimal(row["last_price"], "last_price"),
                    expiry=expiry,
                    strike=strike,
                    tick_size=_optional_decimal(row["tick_size"], "tick_size"),
                    lot_size=_optional_int(row["lot_size"], "lot_size"),
                    instrument_type=instrument_type,
                    segment=row["segment"],
                    exchange=identity["exchange"],
                ))
            except KeyError as exc:
                raise InstrumentMasterParseError(f"malformed instrument CSV row {index}") from exc
    except csv.Error as exc:
        raise InstrumentMasterParseError("malformed instrument CSV quoting") from exc
    return InstrumentSnapshot(snapshot_date, hashlib.sha256(payload).hexdigest(), tuple(records))


def resolve_instrument(snapshot: InstrumentSnapshot, query: InstrumentQuery) -> InstrumentRecord:
    """Resolve only exact identity fields; never infer derivative attributes."""
    matches = [record for record in snapshot.instruments
               if record.exchange == query.exchange
               and record.tradingsymbol == query.tradingsymbol
               and record.instrument_type == query.instrument_type
               and record.expiry == query.expiry
               and record.strike == query.strike]
    if not matches:
        raise InstrumentNotFoundError(
            f"no exact instrument match for {query.exchange}:{query.tradingsymbol}:{query.instrument_type}"
        )
    if len(matches) > 1:
        raise AmbiguousInstrumentError(
            f"{len(matches)} exact instrument matches for {query.exchange}:{query.tradingsymbol}:{query.instrument_type}"
        )
    return matches[0]
