"""Offline protocol contracts for the future Zerodha historical broker."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")
MAX_REQUEST_PAYLOAD = 16 * 1024
MAX_RESPONSE_BODY = 16 * 1024 * 1024
MAX_RESPONSE_PAYLOAD = 24 * 1024 * 1024
_FRAME_HEADER = struct.Struct(">I")
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TransportStatus(_StringEnum):
    PROVIDER_RESPONSE = "PROVIDER_RESPONSE"
    BROKER_REJECTED = "BROKER_REJECTED"
    SESSION_UNAVAILABLE = "SESSION_UNAVAILABLE"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BROKER_FAILURE = "BROKER_FAILURE"


class SessionState(_StringEnum):
    READY = "READY"
    MISSING = "MISSING"
    UNREADABLE = "UNREADABLE"
    MALFORMED = "MALFORMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class BrokerErrorCode(_StringEnum):
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    MALFORMED_CLIENT_REQUEST = "MALFORMED_CLIENT_REQUEST"
    UNAUTHORIZED_CALLER = "UNAUTHORIZED_CALLER"
    UNSUPPORTED_INTERVAL = "UNSUPPORTED_INTERVAL"
    INVALID_DATE_WINDOW = "INVALID_DATE_WINDOW"
    SESSION_FILE_MISSING = "SESSION_FILE_MISSING"
    SESSION_FILE_UNREADABLE = "SESSION_FILE_UNREADABLE"
    MALFORMED_SESSION_FILE = "MALFORMED_SESSION_FILE"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_INVALIDATED = "SESSION_INVALIDATED"
    BROKER_UNAVAILABLE = "BROKER_UNAVAILABLE"
    BROKER_TIMEOUT = "BROKER_TIMEOUT"
    PROVIDER_400 = "PROVIDER_400"
    PROVIDER_403 = "PROVIDER_403"
    PROVIDER_404 = "PROVIDER_404"
    PROVIDER_429 = "PROVIDER_429"
    PROVIDER_5XX = "PROVIDER_5XX"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    DNS_TLS_CONNECTION_FAILURE = "DNS_TLS_CONNECTION_FAILURE"
    OVERSIZED_PROVIDER_RESPONSE = "OVERSIZED_PROVIDER_RESPONSE"
    MALFORMED_PROVIDER_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
    INTERNAL_BROKER_FAILURE = "INTERNAL_BROKER_FAILURE"


PROVIDER_ERROR_CODES = frozenset({
    BrokerErrorCode.PROVIDER_400,
    BrokerErrorCode.PROVIDER_403,
    BrokerErrorCode.PROVIDER_404,
    BrokerErrorCode.PROVIDER_429,
    BrokerErrorCode.PROVIDER_5XX,
})


@dataclass(frozen=True)
class ErrorPolicy:
    may_have_provider_request: bool
    retryable: bool
    reauthentication_required: bool
    raw_response_may_exist: bool
    safe_message: str
    budget_consumed_if_attempted: bool = True


_POLICIES = {
    BrokerErrorCode.PROTOCOL_VERSION_MISMATCH: ErrorPolicy(False, False, False, False, "Unsupported broker protocol."),
    BrokerErrorCode.MALFORMED_CLIENT_REQUEST: ErrorPolicy(False, False, False, False, "Invalid historical-data request."),
    BrokerErrorCode.UNAUTHORIZED_CALLER: ErrorPolicy(False, False, False, False, "Caller is not authorized."),
    BrokerErrorCode.UNSUPPORTED_INTERVAL: ErrorPolicy(False, False, False, False, "Interval is not supported."),
    BrokerErrorCode.INVALID_DATE_WINDOW: ErrorPolicy(False, False, False, False, "Date window is invalid."),
    BrokerErrorCode.SESSION_FILE_MISSING: ErrorPolicy(False, False, True, False, "Zerodha session is unavailable."),
    BrokerErrorCode.SESSION_FILE_UNREADABLE: ErrorPolicy(False, False, True, False, "Zerodha session is unavailable."),
    BrokerErrorCode.MALFORMED_SESSION_FILE: ErrorPolicy(False, False, True, False, "Zerodha session is invalid."),
    BrokerErrorCode.SESSION_EXPIRED: ErrorPolicy(False, False, True, False, "Zerodha reauthentication is required."),
    BrokerErrorCode.SESSION_INVALIDATED: ErrorPolicy(True, False, True, True, "Zerodha reauthentication is required."),
    BrokerErrorCode.BROKER_UNAVAILABLE: ErrorPolicy(True, True, False, False, "Historical broker is unavailable."),
    BrokerErrorCode.BROKER_TIMEOUT: ErrorPolicy(True, True, False, False, "Historical broker timed out."),
    BrokerErrorCode.PROVIDER_400: ErrorPolicy(True, False, False, True, "Provider rejected the request."),
    BrokerErrorCode.PROVIDER_403: ErrorPolicy(True, False, True, True, "Zerodha session is no longer valid."),
    BrokerErrorCode.PROVIDER_404: ErrorPolicy(True, False, False, True, "Provider instrument was not found."),
    BrokerErrorCode.PROVIDER_429: ErrorPolicy(True, True, False, True, "Provider rate limit reached."),
    BrokerErrorCode.PROVIDER_5XX: ErrorPolicy(True, True, False, True, "Provider is temporarily unavailable."),
    BrokerErrorCode.NETWORK_TIMEOUT: ErrorPolicy(True, True, False, False, "Provider request timed out."),
    BrokerErrorCode.DNS_TLS_CONNECTION_FAILURE: ErrorPolicy(True, True, False, False, "Provider connection failed."),
    BrokerErrorCode.OVERSIZED_PROVIDER_RESPONSE: ErrorPolicy(True, False, False, False, "Provider response exceeded the size limit."),
    BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE: ErrorPolicy(True, False, False, True, "Provider response was invalid."),
    BrokerErrorCode.INTERNAL_BROKER_FAILURE: ErrorPolicy(True, False, False, False, "Historical broker failure."),
}


def error_policy(code: BrokerErrorCode) -> ErrorPolicy:
    try:
        return _POLICIES[code]
    except KeyError as exc:
        raise ValueError("unknown broker error code") from exc


class ZerodhaBrokerError(Exception):
    """Safe typed error; raw provider exceptions and bodies must not be attached."""

    def __init__(self, code: BrokerErrorCode):
        self.code = BrokerErrorCode(code)
        self.policy = error_policy(self.code)
        super().__init__(self.policy.safe_message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code.value!r})"


class BrokerRequestValidationError(ZerodhaBrokerError):
    pass


class BrokerResponseValidationError(ZerodhaBrokerError):
    pass


class FramingError(BrokerRequestValidationError):
    pass


def _validation(code: BrokerErrorCode) -> None:
    raise BrokerRequestValidationError(code)


def _canonical_uuid(value: Any, code: BrokerErrorCode) -> str:
    if not isinstance(value, str):
        _validation(code)
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        _validation(code)
    if str(parsed) != value:
        _validation(code)
    return value


def _aware_datetime(value: Any, code: BrokerErrorCode) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _validation(code)
    if value.microsecond:
        _validation(code)
    return value


@dataclass(frozen=True)
class CandleRequest:
    protocol_version: int
    request_id: str
    instrument_token: str
    interval: str
    from_timestamp: datetime
    to_timestamp: datetime
    continuous: bool
    oi: bool

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int:
            _validation(BrokerErrorCode.PROTOCOL_VERSION_MISMATCH)
        if self.protocol_version != 1:
            _validation(BrokerErrorCode.PROTOCOL_VERSION_MISMATCH)
        object.__setattr__(self, "request_id", _canonical_uuid(self.request_id, BrokerErrorCode.MALFORMED_CLIENT_REQUEST))
        if not isinstance(self.instrument_token, str) or not self.instrument_token or not all("0" <= c <= "9" for c in self.instrument_token):
            _validation(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        if int(self.instrument_token) <= 0:
            _validation(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        if self.interval != "minute":
            _validation(BrokerErrorCode.UNSUPPORTED_INTERVAL)
        if type(self.continuous) is not bool or self.continuous:
            _validation(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        if type(self.oi) is not bool:
            _validation(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        start = _aware_datetime(self.from_timestamp, BrokerErrorCode.INVALID_DATE_WINDOW).astimezone(IST)
        end = _aware_datetime(self.to_timestamp, BrokerErrorCode.INVALID_DATE_WINDOW).astimezone(IST)
        if start >= end or end - start > timedelta(hours=24) or start.date() != end.date():
            _validation(BrokerErrorCode.INVALID_DATE_WINDOW)
        object.__setattr__(self, "from_timestamp", start)
        object.__setattr__(self, "to_timestamp", end)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "instrument_token": self.instrument_token,
            "interval": self.interval,
            "from_timestamp": self.from_timestamp.isoformat(),
            "to_timestamp": self.to_timestamp.isoformat(),
            "continuous": self.continuous,
            "oi": self.oi,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CandleRequest":
        expected = {"protocol_version", "request_id", "instrument_token", "interval", "from_timestamp", "to_timestamp", "continuous", "oi"}
        if not isinstance(value, Mapping) or set(value) != expected:
            _validation(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
        try:
            start = datetime.fromisoformat(value["from_timestamp"])
            end = datetime.fromisoformat(value["to_timestamp"])
        except (TypeError, ValueError):
            _validation(BrokerErrorCode.INVALID_DATE_WINDOW)
        return cls(value["protocol_version"], value["request_id"], value["instrument_token"], value["interval"], start, end, value["continuous"], value["oi"])


def _utc_capture(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
        raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
    if value.microsecond < 0:
        raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
    return value.astimezone(timezone.utc)


def _hash_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True)
class BrokerResponse:
    protocol_version: int
    request_id: str
    broker_request_id: str
    transport_status: TransportStatus
    provider_http_status: int | None
    session_state: SessionState
    captured_at: datetime
    body: bytes = b""
    body_length: int = 0
    body_sha256: str = _EMPTY_SHA256
    truncated: bool = False
    retry_after_seconds: int | None = None
    error_code: BrokerErrorCode | None = None
    audit_metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.protocol_version) is not int or self.protocol_version != 1:
            raise BrokerResponseValidationError(BrokerErrorCode.PROTOCOL_VERSION_MISMATCH)
        _canonical_uuid(self.request_id, BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        _canonical_uuid(self.broker_request_id, BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        try:
            status = TransportStatus(self.transport_status)
            session = SessionState(self.session_state)
        except ValueError as exc:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE) from exc
        object.__setattr__(self, "transport_status", status)
        object.__setattr__(self, "session_state", session)
        if not isinstance(self.body, bytes) or len(self.body) > MAX_RESPONSE_BODY:
            raise BrokerResponseValidationError(BrokerErrorCode.OVERSIZED_PROVIDER_RESPONSE)
        if self.truncated:
            raise BrokerResponseValidationError(BrokerErrorCode.OVERSIZED_PROVIDER_RESPONSE)
        if type(self.body_length) is not int or self.body_length != len(self.body):
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if not isinstance(self.body_sha256, str) or self.body_sha256 != self.body_sha256.lower() or len(self.body_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.body_sha256) or self.body_sha256 != _hash_bytes(self.body):
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        captured = _utc_capture(self.captured_at)
        object.__setattr__(self, "captured_at", captured)
        if self.provider_http_status is not None:
            if type(self.provider_http_status) is not int or isinstance(self.provider_http_status, bool) or not 100 <= self.provider_http_status <= 599 or status is not TransportStatus.PROVIDER_RESPONSE:
                raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        elif status is TransportStatus.PROVIDER_RESPONSE:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.provider_http_status is None and self.body:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.retry_after_seconds is not None and (type(self.retry_after_seconds) is not int or self.retry_after_seconds < 0 or self.retry_after_seconds > 3600):
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.error_code is not None:
            try:
                code = BrokerErrorCode(self.error_code)
            except ValueError as exc:
                raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE) from exc
            object.__setattr__(self, "error_code", code)
            if code is BrokerErrorCode.PROVIDER_403 and session is not SessionState.INVALIDATED:
                raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.error_code in PROVIDER_ERROR_CODES and status is not TransportStatus.PROVIDER_RESPONSE:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.retry_after_seconds is not None and self.error_code not in {BrokerErrorCode.PROVIDER_429, BrokerErrorCode.PROVIDER_5XX}:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if self.provider_http_status is not None:
            expected_code = {
                400: BrokerErrorCode.PROVIDER_400,
                403: BrokerErrorCode.PROVIDER_403,
                404: BrokerErrorCode.PROVIDER_404,
                429: BrokerErrorCode.PROVIDER_429,
            }.get(self.provider_http_status)
            if self.provider_http_status >= 500:
                expected_code = BrokerErrorCode.PROVIDER_5XX
            if expected_code is not None and self.error_code is not expected_code:
                raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
            if 200 <= self.provider_http_status < 300 and self.error_code is not None:
                raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if status is TransportStatus.SESSION_EXPIRED and session is not SessionState.EXPIRED:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        if status is TransportStatus.SESSION_UNAVAILABLE and session not in {SessionState.MISSING, SessionState.UNREADABLE, SessionState.MALFORMED}:
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        safe = {"request_fingerprint", "attempt_number", "session_fingerprint"}
        if not isinstance(self.audit_metadata, Mapping) or any(key not in safe or not isinstance(key, str) or not isinstance(value, str) for key, value in self.audit_metadata.items()):
            raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
        object.__setattr__(self, "audit_metadata", MappingProxyType(dict(self.audit_metadata)))

    @classmethod
    def for_provider(cls, *, request_id: str, broker_request_id: str, captured_at: datetime, status: int, body: bytes, session_state: SessionState = SessionState.READY, error_code: BrokerErrorCode | None = None, retry_after_seconds: int | None = None, audit_metadata: Mapping[str, str] | None = None) -> "BrokerResponse":
        return cls(1, request_id, broker_request_id, TransportStatus.PROVIDER_RESPONSE, status, session_state, captured_at, body, len(body), _hash_bytes(body), False, retry_after_seconds, error_code, audit_metadata or {})

    def with_request(self, request_id: str, broker_request_id: str) -> "BrokerResponse":
        return replace(self, request_id=request_id, broker_request_id=broker_request_id)


class HistoricalBroker(Protocol):
    def fetch_candles(self, request: CandleRequest) -> BrokerResponse:
        ...


def _reject_constant(value: str) -> None:
    raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)


def _reject_duplicate(key: str) -> None:
    raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)


def encode_json_frame(value: Mapping[str, Any], *, max_payload: int = MAX_REQUEST_PAYLOAD) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST) from exc
    if not encoded or len(encoded) > max_payload:
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
    return _FRAME_HEADER.pack(len(encoded)) + encoded


def decode_json_frame(frame: bytes, *, max_payload: int = MAX_REQUEST_PAYLOAD) -> Mapping[str, Any]:
    if not isinstance(frame, bytes) or len(frame) < _FRAME_HEADER.size:
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
    (length,) = _FRAME_HEADER.unpack(frame[:_FRAME_HEADER.size])
    if length == 0 or length > max_payload or len(frame) != _FRAME_HEADER.size + length:
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
    try:
        decoded = json.loads(frame[_FRAME_HEADER.size:].decode("utf-8"), object_pairs_hook=lambda pairs: _strict_object(pairs), parse_constant=_reject_constant)
    except ZerodhaBrokerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
    if not isinstance(decoded, Mapping):
        raise FramingError(BrokerErrorCode.MALFORMED_CLIENT_REQUEST)
    return decoded


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject_duplicate(key)
        result[key] = value
    return result


def encode_request(request: CandleRequest) -> bytes:
    return encode_json_frame(request.to_mapping())


def decode_request(frame: bytes) -> CandleRequest:
    return CandleRequest.from_mapping(decode_json_frame(frame))


def _response_mapping(response: BrokerResponse) -> dict[str, Any]:
    return {
        "protocol_version": response.protocol_version,
        "request_id": response.request_id,
        "broker_request_id": response.broker_request_id,
        "transport_status": response.transport_status.value,
        "provider_http_status": response.provider_http_status,
        "session_state": response.session_state.value,
        "captured_at": response.captured_at.isoformat().replace("+00:00", "Z"),
        "body_base64": base64.b64encode(response.body).decode("ascii"),
        "body_length": response.body_length,
        "body_sha256": response.body_sha256,
        "truncated": response.truncated,
        "retry_after_seconds": response.retry_after_seconds,
        "error_code": response.error_code.value if response.error_code else None,
        "audit_metadata": dict(response.audit_metadata),
    }


def encode_response(response: BrokerResponse) -> bytes:
    return encode_json_frame(_response_mapping(response), max_payload=MAX_RESPONSE_PAYLOAD)


def decode_response(frame: bytes) -> BrokerResponse:
    value = decode_json_frame(frame, max_payload=MAX_RESPONSE_PAYLOAD)
    expected = {"protocol_version", "request_id", "broker_request_id", "transport_status", "provider_http_status", "session_state", "captured_at", "body_base64", "body_length", "body_sha256", "truncated", "retry_after_seconds", "error_code", "audit_metadata"}
    if set(value) != expected:
        raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
    try:
        body = base64.b64decode(value["body_base64"], validate=True)
        if not isinstance(value["captured_at"], str):
            raise TypeError("captured_at must be a string")
        captured = datetime.fromisoformat(value["captured_at"].replace("Z", "+00:00"))
        status = TransportStatus(value["transport_status"])
        session = SessionState(value["session_state"])
        code = BrokerErrorCode(value["error_code"]) if value["error_code"] is not None else None
    except (ValueError, TypeError, base64.binascii.Error) as exc:
        raise BrokerResponseValidationError(BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE) from exc
    return BrokerResponse(value["protocol_version"], value["request_id"], value["broker_request_id"], status, value["provider_http_status"], session, captured, body, value["body_length"], value["body_sha256"], value["truncated"], value["retry_after_seconds"], code, value["audit_metadata"])
