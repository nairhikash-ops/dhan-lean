"""Offline Zerodha historical-adapter composition.

This module is deliberately a composition boundary: resolution, planning,
execution, evidence publication, parsing, and validation remain owned by the
existing provider components.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from decimal import Decimal
from typing import Callable, Optional

from dhan_lean.data.models import DataWorkItem, NormalizedBar, ValidationResult
from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.data.validator import validate_normalized_bars
from dhan_lean.providers.zerodha.artifacts import (
    ArtifactPublicationResult,
    ZerodhaArtifactInput,
    publish_budgeted_result,
)
from dhan_lean.providers.zerodha.broker_protocol import HistoricalBroker
from dhan_lean.providers.zerodha.historical import (
    HistoricalCandleParseError,
    ParsedHistoricalCandles,
    parse_historical_candles,
)
from dhan_lean.providers.zerodha.instruments import (
    InstrumentQuery,
    InstrumentResolutionError,
    InstrumentSnapshot,
    resolve_instrument,
)
from dhan_lean.providers.zerodha.planning import (
    ZerodhaPlanningError,
    ZerodhaPlanningInput,
    plan_historical_candles,
)
from dhan_lean.providers.zerodha.retry import (
    AttemptRecord,
    BudgetedBrokerResult,
    RetryPolicy,
    run_planned_request,
)


class ZerodhaAdapterStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RESOLUTION_FAILURE = "RESOLUTION_FAILURE"
    PLANNING_FAILURE = "PLANNING_FAILURE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    RETRY_LIMIT_EXHAUSTED = "RETRY_LIMIT_EXHAUSTED"
    REAUTHENTICATION_REQUIRED = "REAUTHENTICATION_REQUIRED"
    MALFORMED_PROVIDER_RESPONSE = "MALFORMED_PROVIDER_RESPONSE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    ARTIFACT_PUBLICATION_FAILURE = "ARTIFACT_PUBLICATION_FAILURE"
    LOCAL_FAILURE = "LOCAL_FAILURE"


@dataclass(frozen=True)
class ZerodhaHistoricalAdapterInput:
    """Immutable, non-secret context for one offline provider workflow."""

    instrument_snapshot: InstrumentSnapshot
    exchange: str
    instrument_type: str = "EQ"
    expiry: Optional[date] = None
    strike: Optional[Decimal] = None
    storage_root: Path = Path(".")
    run_id: str = ""
    retry_policy: Optional[RetryPolicy] = None
    request_budget: Optional[RequestBudget] = None
    broker: Optional[HistoricalBroker] = None
    oi: bool = False
    continuous: bool = False
    parser_schema_version: int = 1
    artifact_schema_version: int = 1
    request_id_factory: Optional[Callable[[], str]] = None
    planning_request_id_factory: Optional[Callable[[], str]] = None
    jitter_source: Optional[Callable[[int], object]] = None


@dataclass(frozen=True, repr=False)
class ZerodhaHistoricalAdapterResult:
    """Safe immutable result; response bytes and exception objects are excluded."""

    work_item_key: str
    status: ZerodhaAdapterStatus
    request_fingerprint: Optional[str] = None
    resolved_instrument_id: Optional[str] = None
    final_broker_outcome: Optional[str] = None
    broker_result: Optional[BudgetedBrokerResult] = None
    attempt_history: tuple[AttemptRecord, ...] = ()
    artifact_publications: tuple[ArtifactPublicationResult, ...] = ()
    bars: tuple[NormalizedBar, ...] = ()
    parsed: Optional[ParsedHistoricalCandles] = None
    validation: Optional[ValidationResult] = None
    retry_limit_exhausted: bool = False
    reauthentication_required: bool = False
    review_required: bool = False
    error_code: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_history", tuple(self.attempt_history))
        object.__setattr__(self, "artifact_publications", tuple(self.artifact_publications))
        object.__setattr__(self, "bars", tuple(self.bars))
        if self.status is ZerodhaAdapterStatus.SUCCESS:
            if not self.bars or self.validation is None or not self.validation.is_valid:
                raise ValueError("successful adapter result requires validated bars")
        if self.status is not ZerodhaAdapterStatus.SUCCESS and self.bars:
            raise ValueError("non-success adapter result cannot contain bars")
        if self.parsed is None and self.validation is not None:
            raise ValueError("validation requires parser success")

    @property
    def succeeded(self) -> bool:
        return self.status is ZerodhaAdapterStatus.SUCCESS

    def __repr__(self) -> str:
        return (f"ZerodhaHistoricalAdapterResult(work_item_key={self.work_item_key!r}, "
                f"status={self.status.value!r}, request_fingerprint={self.request_fingerprint!r}, "
                f"bar_count={len(self.bars)}, attempt_count={len(self.attempt_history)}, "
                f"error_code={self.error_code!r})")


class ZerodhaHistoricalAdapter:
    """Run one complete, deterministic, fake-broker-only Zerodha flow."""

    def __init__(self, context: ZerodhaHistoricalAdapterInput):
        self.context = context

    def run(self, work_item: DataWorkItem) -> ZerodhaHistoricalAdapterResult:
        context = self.context
        try:
            query = InstrumentQuery(context.exchange, work_item.symbol, context.instrument_type,
                                    context.expiry, context.strike)
            instrument = resolve_instrument(context.instrument_snapshot, query)
        except (InstrumentResolutionError, ValueError, TypeError):
            return ZerodhaHistoricalAdapterResult(work_item.work_item_key, ZerodhaAdapterStatus.RESOLUTION_FAILURE,
                                                  error_code="INSTRUMENT_RESOLUTION_FAILED")

        try:
            planned = plan_historical_candles(ZerodhaPlanningInput(
                work_item, instrument, context.instrument_snapshot, context.exchange,
                protocol_version=1, planning_schema_version=1,
                continuous=context.continuous, oi=context.oi,
            ), request_id_factory=context.planning_request_id_factory)
        except ZerodhaPlanningError as exc:
            return ZerodhaHistoricalAdapterResult(work_item.work_item_key, ZerodhaAdapterStatus.PLANNING_FAILURE,
                                                  resolved_instrument_id=instrument.instrument_token,
                                                  error_code=exc.code.value)

        if context.request_budget is None or context.retry_policy is None or context.broker is None:
            return ZerodhaHistoricalAdapterResult(work_item.work_item_key, ZerodhaAdapterStatus.LOCAL_FAILURE,
                                                  planned.fingerprint, instrument.instrument_token,
                                                  error_code="MISSING_EXECUTION_DEPENDENCY")

        observed = {}
        try:
            def observe(attempt, response):
                observed[attempt.attempt_number] = response

            kwargs = {"attempt_observer": observe}
            if context.request_id_factory is not None:
                kwargs["request_id_factory"] = context.request_id_factory
            if context.jitter_source is not None:
                kwargs["jitter_source"] = context.jitter_source
            broker_result = run_planned_request(planned, context.broker, context.request_budget,
                                                context.retry_policy, **kwargs)
        except Exception:
            return ZerodhaHistoricalAdapterResult(work_item.work_item_key, ZerodhaAdapterStatus.LOCAL_FAILURE,
                                                  planned.fingerprint, instrument.instrument_token,
                                                  error_code="BROKER_EXECUTION_FAILED")

        try:
            publications = publish_budgeted_result(ZerodhaArtifactInput(
                planned, broker_result, context.storage_root, context.run_id,
                context.instrument_snapshot.content_sha256, observed,
                context.parser_schema_version, context.artifact_schema_version,
            ))
        except Exception:
            return self._broker_result(work_item, planned, instrument, broker_result,
                                       ZerodhaAdapterStatus.ARTIFACT_PUBLICATION_FAILURE,
                                       error_code="ARTIFACT_PUBLICATION_FAILED", observed=observed)

        base = dict(work_item_key=work_item.work_item_key, request_fingerprint=planned.fingerprint,
                    resolved_instrument_id=instrument.instrument_token, broker_result=broker_result,
                    attempt_history=broker_result.attempt_history, artifact_publications=publications,
                    final_broker_outcome=broker_result.final_outcome,
                    retry_limit_exhausted=broker_result.attempt_limit_exhausted,
                    reauthentication_required=broker_result.reauthentication_required,
                    review_required=any(item.review_required for item in publications))
        if broker_result.budget_exhausted:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.BUDGET_EXHAUSTED, **base)
        if broker_result.attempt_limit_exhausted:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.RETRY_LIMIT_EXHAUSTED, **base)
        if broker_result.reauthentication_required:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.REAUTHENTICATION_REQUIRED, **base)
        if not broker_result.succeeded:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.PROVIDER_FAILURE, **base,
                                                  error_code=broker_result.final_outcome)

        response = broker_result.final_response
        if response is None:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.LOCAL_FAILURE, **base,
                                                  error_code="MISSING_FINAL_RESPONSE")
        try:
            parsed = parse_historical_candles(response.body, instrument)
        except HistoricalCandleParseError:
            return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.MALFORMED_PROVIDER_RESPONSE,
                                                  parsed=None, **base, error_code="HISTORICAL_CANDLE_PARSE_ERROR")
        validation = validate_normalized_bars(parsed.bars)
        if not validation.is_valid:
            status = (ZerodhaAdapterStatus.EMPTY_RESPONSE if validation.error_code == "EMPTY_BARS"
                      else ZerodhaAdapterStatus.VALIDATION_FAILURE)
            return ZerodhaHistoricalAdapterResult(status=status, parsed=parsed, validation=validation,
                                                  **base, error_code=validation.error_code)
        return ZerodhaHistoricalAdapterResult(status=ZerodhaAdapterStatus.SUCCESS, parsed=parsed,
                                              validation=validation, bars=parsed.bars, **base)

    @staticmethod
    def _broker_result(work_item, planned, instrument, broker_result, status, *, error_code, observed):
        return ZerodhaHistoricalAdapterResult(
            work_item_key=work_item.work_item_key, status=status,
            request_fingerprint=planned.fingerprint, resolved_instrument_id=instrument.instrument_token,
            final_broker_outcome=broker_result.final_outcome, broker_result=broker_result,
            attempt_history=broker_result.attempt_history,
            retry_limit_exhausted=broker_result.attempt_limit_exhausted,
            reauthentication_required=broker_result.reauthentication_required,
            error_code=error_code,
        )
