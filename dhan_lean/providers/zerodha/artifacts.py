"""Offline Zerodha raw-response artifacts with strict redaction and replay."""

from __future__ import annotations

import hashlib
import json
import re
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional

from dhan_lean.data.storage import ArtifactWriter, _validate_bundle_filename, build_raw_artifact_path
from dhan_lean.data.validator import validate_normalized_bars
from dhan_lean.providers.zerodha.historical import HistoricalCandleParseError, parse_historical_candles
from dhan_lean.providers.zerodha.planning import ZerodhaPlannedRequest
from dhan_lean.providers.zerodha.broker_protocol import BrokerResponse
from dhan_lean.providers.zerodha.retry import AttemptRecord, BudgetedBrokerResult, run_planned_request


ARTIFACT_SCHEMA_VERSION = 1
PARSER_SCHEMA_VERSION = 1
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_REQUEST_KEYS = frozenset({
    "fingerprint_schema_version", "protocol_version", "planning_schema_version", "provider",
    "provider_instrument_id", "exchange", "tradingsymbol", "instrument_type", "expiry", "strike",
    "instrument_snapshot_date", "instrument_snapshot_sha256", "interval", "from_timestamp",
    "to_timestamp", "continuous", "oi", "request_fingerprint", "attempt_number", "attempt_request_id",
    "artifact_schema_version", "broker_protocol_version", "parser_schema_version", "run_id",
    "instrument_snapshot_hash",
})
_ATTEMPT_KEYS = frozenset({"attempt_number", "attempt_request_id", "broker_request_id", "transport_status", "provider_http_status", "session_state", "error_code", "capture_timestamp", "body_length", "body_sha256", "retry_permitted", "reauthentication_required"})
_RESPONSE_KEYS = frozenset({"body_length", "body_sha256", "provider_http_status"})
_PARSE_KEYS = frozenset({"outcome", "bar_count", "had_open_interest", "error_code"})
_VALIDATION_KEYS = frozenset({"is_valid", "error_code", "bar_count", "errors", "timestamps_strictly_increasing", "invalid_ohlc_count", "non_positive_price_count", "negative_volume_count"})
_APPROVED_METADATA_KEYS = _REQUEST_KEYS | _ATTEMPT_KEYS | _RESPONSE_KEYS | _PARSE_KEYS | _VALIDATION_KEYS
_FORBIDDEN_KEY_TERMS = ("token", "secret", "password", "authorization", "cookie", "session", "credential", "apikey", "bearer")


class ZerodhaArtifactError(ValueError):
    """Base class for safe provider-artifact errors."""

    code = "ARTIFACT_ERROR"

    def __init__(self, message: str = "Zerodha artifact operation failed"):
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


class InvalidArtifactInputError(ZerodhaArtifactError): code = "INVALID_ARTIFACT_INPUT"
class UnsafeMetadataError(ZerodhaArtifactError): code = "UNSAFE_METADATA"
class UnsafePathComponentError(ZerodhaArtifactError): code = "UNSAFE_PATH_COMPONENT"
class ResponseBodyHashMismatchError(ZerodhaArtifactError): code = "RESPONSE_BODY_HASH_MISMATCH"
class ArtifactCollisionError(ZerodhaArtifactError): code = "ARTIFACT_COLLISION"
class IncompleteArtifactError(ZerodhaArtifactError): code = "INCOMPLETE_ARTIFACT"
class ManifestMismatchError(ZerodhaArtifactError): code = "MANIFEST_MISMATCH"
class ImmutablePublicationError(ZerodhaArtifactError): code = "IMMUTABLE_PUBLICATION_FAILURE"
class ParseFailureAfterRawPreservationError(ZerodhaArtifactError): code = "PARSE_FAILURE_AFTER_RAW_PRESERVATION"
class NormalizedValidationFailureError(ZerodhaArtifactError): code = "NORMALIZED_VALIDATION_FAILURE"
class UnsupportedResponseStateError(ZerodhaArtifactError): code = "UNSUPPORTED_RESPONSE_STATE"
class UnexpectedArtifactPublicationError(ZerodhaArtifactError): code = "UNEXPECTED_PUBLICATION_FAILURE"


@dataclass(frozen=True, repr=False)
class ArtifactPublicationResult:
    request_fingerprint: str
    artifact_relative_path: str
    publication_status: str
    attempt_number: int
    published_filenames: tuple[str, ...]
    manifest_sha256: str
    response_body_sha256: Optional[str]
    parser_outcome: str
    validation_outcome: str
    idempotent_replay: bool = False
    review_required: bool = False

    def __repr__(self) -> str:
        return (f"ArtifactPublicationResult(request_fingerprint={self.request_fingerprint!r}, "
                f"publication_status={self.publication_status!r}, attempt_number={self.attempt_number}, "
                f"parser_outcome={self.parser_outcome!r}, validation_outcome={self.validation_outcome!r}, "
                f"idempotent_replay={self.idempotent_replay})")


@dataclass(frozen=True)
class ZerodhaArtifactInput:
    planned_request: ZerodhaPlannedRequest
    broker_result: BudgetedBrokerResult
    storage_root: Path
    run_id: str
    instrument_snapshot_hash: str
    attempt_responses: Mapping[int, Optional[BrokerResponse]]
    parser_schema_version: int = PARSER_SCHEMA_VERSION
    artifact_schema_version: int = ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.planned_request, ZerodhaPlannedRequest) or not isinstance(self.broker_result, BudgetedBrokerResult):
            raise InvalidArtifactInputError()
        if not isinstance(self.storage_root, Path) or not isinstance(self.attempt_responses, Mapping):
            raise InvalidArtifactInputError()
        if not isinstance(self.run_id, str) or not re.fullmatch(r"\d{8}T\d{6}Z", self.run_id):
            raise InvalidArtifactInputError()
        try:
            datetime.strptime(self.run_id, "%Y%m%dT%H%M%SZ")
        except ValueError:
            raise InvalidArtifactInputError() from None
        object.__setattr__(self, "attempt_responses", MappingProxyType(dict(self.attempt_responses)))


def _safe_key(key: object) -> str:
    if not isinstance(key, str):
        raise UnsafeMetadataError()
    if key in _APPROVED_METADATA_KEYS or key == "provider_instrument_id":
        return key
    normal = re.sub(r"[^a-z0-9]", "", key.lower())
    if any(term in normal for term in _FORBIDDEN_KEY_TERMS):
        raise UnsafeMetadataError()
    return key


def _safe_metadata(value: object, allowed_keys: frozenset[str] | None = None) -> object:
    if isinstance(value, Mapping):
        cleaned = {_safe_key(key): _safe_metadata(item) for key, item in value.items()}
        if allowed_keys is not None and set(cleaned) - allowed_keys:
            raise UnsafeMetadataError()
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_safe_metadata(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise UnsafeMetadataError()


def _json(value: Mapping[str, object], allowed_keys: frozenset[str] | None = None) -> bytes:
    try:
        return (json.dumps(_safe_metadata(value, allowed_keys), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise UnsafeMetadataError() from None


def _safe_component(value: str, name: str) -> str:
    try:
        safe = _validate_bundle_filename(value)
    except ValueError:
        raise UnsafePathComponentError()
    if not _SAFE_NAME.fullmatch(safe):
        raise UnsafePathComponentError()
    return safe


def _attempt_path(inp: ZerodhaArtifactInput, attempt: AttemptRecord) -> Path:
    planned = inp.planned_request
    try:
        root = inp.storage_root.resolve()
        base = build_raw_artifact_path(storage_root=root, source_id="zerodha", venue=_safe_component(planned.exchange, "venue"),
            data_kind="historical", symbol=_safe_component(planned.symbol, "symbol"), instrument_id=_safe_component(planned.provider_instrument_id, "provider_instrument_id"),
            resolution=_safe_component(planned.candle_request.interval, "resolution"), session_date=planned.session_date)
        target = (base / _safe_component(planned.fingerprint, "fingerprint") / _safe_component(f"attempt-{attempt.attempt_number:04d}-{attempt.request_id}", "attempt")).resolve()
        target.relative_to(root)
        return target
    except (ValueError, TypeError):
        raise UnsafePathComponentError() from None


def _response_metadata(response: BrokerResponse | None, attempt: AttemptRecord) -> dict[str, object]:
    return {
        "attempt_number": attempt.attempt_number, "attempt_request_id": attempt.request_id,
        "broker_request_id": response.broker_request_id if response else attempt.broker_request_id,
        "transport_status": response.transport_status.value if response else attempt.transport_status,
        "provider_http_status": response.provider_http_status if response else attempt.provider_http_status,
        "session_state": response.session_state.value if response else attempt.session_state,
        "error_code": response.error_code.value if response and response.error_code else (attempt.error_code.value if attempt.error_code else None),
        "capture_timestamp": response.captured_at.isoformat() if response else None,
        "body_length": response.body_length if response else None,
        "body_sha256": response.body_sha256 if response else None,
        "retry_permitted": attempt.retry_permitted, "reauthentication_required": attempt.reauthentication_required,
    }


def _validation_summary(result) -> dict[str, object]:
    return {"is_valid": result.is_valid, "error_code": result.error_code, "bar_count": result.bar_count,
            "errors": list(result.errors)[:10], "timestamps_strictly_increasing": result.timestamps_strictly_increasing,
            "invalid_ohlc_count": result.invalid_ohlc_count, "non_positive_price_count": result.non_positive_price_count,
            "negative_volume_count": result.negative_volume_count}


def _expected_files(inp: ZerodhaArtifactInput, attempt: AttemptRecord, response: BrokerResponse | None) -> tuple[dict[str, bytes], str, str, bool]:
    planned = inp.planned_request
    request_metadata = dict(planned.canonical_metadata)
    request_metadata.update({"request_fingerprint": planned.fingerprint, "provider_instrument_id": planned.provider_instrument_id,
                             "attempt_number": attempt.attempt_number, "attempt_request_id": attempt.request_id,
                             "artifact_schema_version": inp.artifact_schema_version,
                             "planning_schema_version": planned.planning_schema_version, "broker_protocol_version": planned.protocol_version,
                             "parser_schema_version": inp.parser_schema_version, "run_id": inp.run_id,
                             "instrument_snapshot_hash": inp.instrument_snapshot_hash})
    files: dict[str, bytes] = {"request-metadata.json": _json(request_metadata, _REQUEST_KEYS), "attempt-metadata.json": _json(_response_metadata(response, attempt), _ATTEMPT_KEYS)}
    parser_outcome, validation_outcome = "NOT_ATTEMPTED", "NOT_ATTEMPTED"
    if response is not None:
        if response.body_length != len(response.body) or response.body_sha256 != hashlib.sha256(response.body).hexdigest():
            raise ResponseBodyHashMismatchError()
        files["response-body.bin"] = response.body
        files["response-metadata.json"] = _json({"body_length": len(response.body), "body_sha256": hashlib.sha256(response.body).hexdigest(), "provider_http_status": response.provider_http_status}, _RESPONSE_KEYS)
        if response.provider_http_status is not None and 200 <= response.provider_http_status < 300:
            try:
                parsed = parse_historical_candles(response.body, _instrument_from_planned(planned))
                parser_outcome = "SUCCESS"
                validation = validate_normalized_bars(parsed.bars)
                validation_outcome = "SUCCESS" if validation.is_valid else validation.error_code or "INVALID"
                files["parse-result.json"] = _json({"outcome": parser_outcome, "bar_count": len(parsed.bars), "had_open_interest": parsed.had_open_interest}, _PARSE_KEYS)
                files["validation-result.json"] = _json(_validation_summary(validation), _VALIDATION_KEYS)
            except HistoricalCandleParseError:
                parser_outcome = "FAILURE"
                validation_outcome = "NOT_RUN"
                files["parse-result.json"] = _json({"outcome": "FAILURE", "error_code": "HISTORICAL_CANDLE_PARSE_ERROR"}, _PARSE_KEYS)
    return files, parser_outcome, validation_outcome, response is not None


def _instrument_from_planned(planned: ZerodhaPlannedRequest):
    from types import SimpleNamespace
    return SimpleNamespace(tradingsymbol=planned.symbol)


def _validate_response_evidence(attempt: AttemptRecord, response: BrokerResponse | None) -> None:
    """Require an explicit, matching observation for every provider response."""
    claims_response = attempt.body_length is not None or attempt.body_sha256 is not None
    if response is None:
        if claims_response:
            raise InvalidArtifactInputError()
        return
    if response.body_length != len(response.body) or response.body_sha256 != hashlib.sha256(response.body).hexdigest():
        raise ResponseBodyHashMismatchError()
    if response.request_id != attempt.request_id or not claims_response:
        raise InvalidArtifactInputError()
    if (response.broker_request_id != attempt.broker_request_id or response.body_length != attempt.body_length
            or response.body_sha256 != attempt.body_sha256 or response.provider_http_status != attempt.provider_http_status
            or response.transport_status.value != attempt.transport_status):
        raise InvalidArtifactInputError()


def _manifest_bytes(files: Mapping[str, bytes]) -> bytes:
    manifest_data = {"files": {name: {"length": len(content), "sha256": hashlib.sha256(content).hexdigest()} for name, content in sorted(files.items())}}
    return (json.dumps(manifest_data, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _verify_existing_bundle(directory: Path, files: Mapping[str, bytes]) -> None:
    expected = dict(files)
    expected["manifest.json"] = _manifest_bytes(files)
    try:
        entries = list(directory.iterdir())
    except OSError:
        raise IncompleteArtifactError() from None
    actual_names = {entry.name for entry in entries}
    if actual_names != set(expected):
        raise IncompleteArtifactError() if not {"manifest.json"}.issubset(actual_names) else ArtifactCollisionError()
    actual: dict[str, bytes] = {}
    for entry in entries:
        try:
            mode = os.lstat(entry).st_mode
        except OSError:
            raise ArtifactCollisionError() from None
        if not stat.S_ISREG(mode):
            raise ArtifactCollisionError()
        try:
            actual[entry.name] = entry.read_bytes()
        except OSError:
            raise ArtifactCollisionError() from None
    if actual.get("manifest.json") != expected["manifest.json"]:
        raise ManifestMismatchError()
    for name, content in files.items():
        if actual[name] != content or len(actual[name]) != len(content) or hashlib.sha256(actual[name]).hexdigest() != hashlib.sha256(content).hexdigest():
            raise ArtifactCollisionError()


def publish_attempt_artifact(inp: ZerodhaArtifactInput, attempt: AttemptRecord, response: BrokerResponse | None) -> ArtifactPublicationResult:
    if attempt.planned_fingerprint != inp.planned_request.fingerprint or attempt.attempt_number <= 0:
        raise InvalidArtifactInputError()
    if inp.instrument_snapshot_hash != inp.planned_request.instrument_snapshot_sha256:
        raise InvalidArtifactInputError()
    _validate_response_evidence(attempt, response)
    writer = ArtifactWriter()
    directory = _attempt_path(inp, attempt)
    files, parser_outcome, validation_outcome, has_response = _expected_files(inp, attempt, response)
    try:
        if directory.exists():
            if not directory.is_dir():
                raise ArtifactCollisionError()
            _verify_existing_bundle(directory, files)
            expected = {**files, "manifest.json": _manifest_bytes(files)}
            return ArtifactPublicationResult(inp.planned_request.fingerprint, str(directory.relative_to(inp.storage_root)), "REUSED", attempt.attempt_number,
                    tuple(sorted(expected)), hashlib.sha256(expected["manifest.json"]).hexdigest(), hashlib.sha256(response.body).hexdigest() if has_response else None,
                    parser_outcome, validation_outcome, True, parser_outcome == "FAILURE" or validation_outcome not in {"SUCCESS", "NOT_ATTEMPTED"})
        targets = writer.write_immutable_bundle(directory, files, screened_names=tuple(name for name in files if name.endswith(".json")))
    except ZerodhaArtifactError:
        raise
    except FileExistsError:
        if directory.exists() and directory.is_dir():
            _verify_existing_bundle(directory, files)
            expected = {**files, "manifest.json": _manifest_bytes(files)}
            return ArtifactPublicationResult(inp.planned_request.fingerprint, str(directory.relative_to(inp.storage_root)), "REUSED", attempt.attempt_number,
                    tuple(sorted(expected)), hashlib.sha256(expected["manifest.json"]).hexdigest(), hashlib.sha256(response.body).hexdigest() if has_response else None,
                    parser_outcome, validation_outcome, True, parser_outcome == "FAILURE" or validation_outcome not in {"SUCCESS", "NOT_ATTEMPTED"})
        raise ArtifactCollisionError() from None
    except Exception:
        raise ImmutablePublicationError() from None
    manifest_hash = hashlib.sha256(targets["manifest.json"].read_bytes()).hexdigest()
    return ArtifactPublicationResult(inp.planned_request.fingerprint, str(directory.relative_to(inp.storage_root)), "PUBLISHED", attempt.attempt_number,
            tuple(sorted(targets)), manifest_hash, hashlib.sha256(response.body).hexdigest() if has_response else None,
            parser_outcome, validation_outcome, False, parser_outcome == "FAILURE" or validation_outcome not in {"SUCCESS", "NOT_ATTEMPTED"})


def publish_budgeted_result(inp: ZerodhaArtifactInput) -> tuple[ArtifactPublicationResult, ...]:
    """Publish every admitted attempt; budget-only attempts have metadata only."""
    if inp.broker_result.request_fingerprint != inp.planned_request.fingerprint:
        raise InvalidArtifactInputError()
    attempt_numbers = {attempt.attempt_number for attempt in inp.broker_result.attempt_history}
    if set(inp.attempt_responses) - attempt_numbers:
        raise InvalidArtifactInputError()
    results = []
    for attempt in inp.broker_result.attempt_history:
        response = inp.attempt_responses.get(attempt.attempt_number)
        results.append(publish_attempt_artifact(inp, attempt, response))
    return tuple(results)


def execute_and_publish(planned_request, broker, request_budget, retry_policy, *, storage_root: Path, run_id: str,
                        instrument_snapshot_hash: str | None = None, request_id_factory=None, jitter_source=None):
    """Run the deterministic broker seam and publish its observed attempts."""
    observed: dict[int, BrokerResponse | None] = {}
    def observe(attempt, response):
        observed[attempt.attempt_number] = response
    kwargs = {"attempt_observer": observe}
    if request_id_factory is not None: kwargs["request_id_factory"] = request_id_factory
    if jitter_source is not None: kwargs["jitter_source"] = jitter_source
    result = run_planned_request(planned_request, broker, request_budget, retry_policy, **kwargs)
    inp = ZerodhaArtifactInput(planned_request, result, Path(storage_root), run_id, instrument_snapshot_hash or planned_request.instrument_snapshot_sha256, observed)
    return result, publish_budgeted_result(inp)
