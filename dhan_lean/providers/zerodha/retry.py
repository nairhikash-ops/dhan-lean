"""Offline Zerodha request-budget admission and retry orchestration."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable, Optional

from dhan_lean.data.request_budget import RequestBudget, RequestBudgetExceeded
from dhan_lean.providers.zerodha.broker_protocol import (
    BrokerErrorCode,
    BrokerResponse,
    CandleRequest,
    HistoricalBroker,
    ZerodhaBrokerError,
    error_policy,
)
from dhan_lean.providers.zerodha.planning import ZerodhaPlannedRequest


APPROVED_RETRYABLE_CODES = frozenset({
    BrokerErrorCode.BROKER_UNAVAILABLE,
    BrokerErrorCode.BROKER_TIMEOUT,
    BrokerErrorCode.PROVIDER_429,
    BrokerErrorCode.PROVIDER_5XX,
    BrokerErrorCode.NETWORK_TIMEOUT,
    BrokerErrorCode.DNS_TLS_CONNECTION_FAILURE,
})
POLICY_RETRYABLE_CODES = frozenset(code for code in BrokerErrorCode if error_policy(code).retryable)
if POLICY_RETRYABLE_CODES != APPROVED_RETRYABLE_CODES:
    raise RuntimeError("Phase 2B.3 retry allowlist differs from broker error policy")
RETRYABLE_CODES = POLICY_RETRYABLE_CODES


class ZerodhaRetryError(RuntimeError):
    """Safe base class for orchestration failures."""

    def __init__(self, message: str):
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)!r})"


class InvalidRetryPolicyError(ZerodhaRetryError):
    pass


class InvalidRequestIdError(ZerodhaRetryError):
    pass


class DuplicateRequestIdError(ZerodhaRetryError):
    pass


class BudgetConfigurationError(ZerodhaRetryError):
    pass


class BudgetExhaustedError(ZerodhaRetryError):
    pass


class UnexpectedBrokerException(ZerodhaRetryError):
    pass


class InconsistentBrokerResponseError(ZerodhaRetryError):
    pass


class AttemptObserverError(ZerodhaRetryError):
    pass


def _duration(value: object, name: str) -> timedelta:
    if isinstance(value, bool) or not isinstance(value, timedelta):
        raise InvalidRetryPolicyError(f"{name} must be a timedelta")
    if value.total_seconds() < 0 or not math.isfinite(value.total_seconds()):
        raise InvalidRetryPolicyError(f"{name} must be non-negative and finite")
    return value


@dataclass(frozen=True, init=False)
class RetryPolicy:
    """Immutable retry settings and the explicit durable budget identity."""

    maximum_attempts: int
    backoff_base: timedelta
    backoff_cap: timedelta
    jitter_max: timedelta
    maximum_retry_after: timedelta
    budget_scope: str
    budget_window_id: str

    def __init__(
        self,
        maximum_attempts: int = 3,
        backoff_base: timedelta = timedelta(seconds=1),
        backoff_cap: timedelta = timedelta(seconds=30),
        jitter_max: timedelta = timedelta(milliseconds=250),
        maximum_retry_after: timedelta = timedelta(seconds=60),
        budget_scope: str = "",
        budget_window_id: str = "",
        **aliases: object,
    ) -> None:
        if "max_attempts" in aliases:
            maximum_attempts = aliases.pop("max_attempts")  # type: ignore[assignment]
        if "base_delay" in aliases:
            backoff_base = aliases.pop("base_delay")  # type: ignore[assignment]
        if "max_retry_after" in aliases:
            maximum_retry_after = aliases.pop("max_retry_after")  # type: ignore[assignment]
        if aliases:
            raise InvalidRetryPolicyError("unknown retry-policy field")
        if type(maximum_attempts) is not int or maximum_attempts <= 0:
            raise InvalidRetryPolicyError("maximum_attempts must be a positive integer")
        base = _duration(backoff_base, "backoff_base")
        cap = _duration(backoff_cap, "backoff_cap")
        jitter = _duration(jitter_max, "jitter_max")
        retry_after = _duration(maximum_retry_after, "maximum_retry_after")
        if cap < base:
            raise InvalidRetryPolicyError("backoff_cap cannot be lower than backoff_base")
        if jitter > timedelta(seconds=60):
            raise InvalidRetryPolicyError("jitter_max exceeds the safe bound")
        if not isinstance(budget_scope, str) or not budget_scope.strip():
            raise InvalidRetryPolicyError("budget_scope must be non-empty")
        if not isinstance(budget_window_id, str) or not budget_window_id.strip():
            raise InvalidRetryPolicyError("budget_window_id must be non-empty")
        object.__setattr__(self, "maximum_attempts", maximum_attempts)
        object.__setattr__(self, "backoff_base", base)
        object.__setattr__(self, "backoff_cap", cap)
        object.__setattr__(self, "jitter_max", jitter)
        object.__setattr__(self, "maximum_retry_after", retry_after)
        object.__setattr__(self, "budget_scope", budget_scope)
        object.__setattr__(self, "budget_window_id", budget_window_id)

    @property
    def max_attempts(self) -> int:
        return self.maximum_attempts

    @property
    def base_delay(self) -> timedelta:
        return self.backoff_base

    @property
    def max_retry_after(self) -> timedelta:
        return self.maximum_retry_after


def _jitter_value(source: Callable[[int], object], retry_number: int, policy: RetryPolicy) -> timedelta:
    value = source(retry_number)
    if not isinstance(value, timedelta) or value < timedelta(0) or value > policy.jitter_max:
        raise InvalidRetryPolicyError("jitter source returned an invalid duration")
    return value


def calculate_retry_delay(
    policy: RetryPolicy,
    retry_number: int,
    *,
    retry_after_seconds: Optional[int] = None,
    jitter_source: Callable[[int], object] = lambda _number: timedelta(0),
) -> timedelta:
    """Return capped exponential delay plus deterministic jitter.

    The exponential component is capped before jitter. A valid Retry-After is
    capped and then raises the resulting delay using ``max``.
    """
    if type(retry_number) is not int or retry_number <= 0:
        raise InvalidRetryPolicyError("retry_number must be a positive integer")
    exponent = retry_number - 1
    if policy.backoff_base == timedelta(0) or policy.backoff_base >= policy.backoff_cap:
        exponential = min(policy.backoff_base, policy.backoff_cap)
    else:
        # Compare before multiplying so an adversarial retry number cannot
        # overflow timedelta. The final multiplication is only done when it
        # is known to be below the configured cap.
        cap_units = policy.backoff_cap.total_seconds() / policy.backoff_base.total_seconds()
        if exponent >= 0 and (exponent >= 63 or (1 << exponent) >= cap_units):
            exponential = policy.backoff_cap
        else:
            exponential = policy.backoff_base * (1 << exponent)
    delay = exponential + _jitter_value(jitter_source, retry_number, policy)
    if type(retry_after_seconds) is int and not isinstance(retry_after_seconds, bool) and retry_after_seconds >= 0:
        retry_after = min(timedelta(seconds=retry_after_seconds), policy.maximum_retry_after)
        delay = max(delay, retry_after)
    return delay


@dataclass(frozen=True)
class AttemptRecord:
    attempt_number: int
    request_id: str
    planned_fingerprint: str
    budget_consumed: bool
    broker_request_id: Optional[str] = None
    transport_status: Optional[str] = None
    provider_http_status: Optional[int] = None
    session_state: Optional[str] = None
    error_code: Optional[BrokerErrorCode] = None
    body_length: Optional[int] = None
    body_sha256: Optional[str] = None
    retry_permitted: bool = False
    next_delay: Optional[timedelta] = None
    reauthentication_required: bool = False


@dataclass(frozen=True, repr=False)
class BudgetedBrokerResult:
    attempt_history: tuple[AttemptRecord, ...]
    final_outcome: str
    final_response: Optional[BrokerResponse]
    request_fingerprint: str
    total_budget_units_consumed: int
    budget_exhausted: bool
    attempt_limit_exhausted: bool
    reauthentication_required: bool
    succeeded: bool
    next_recommended_delay: Optional[timedelta] = None

    def __post_init__(self) -> None:
        if type(self.total_budget_units_consumed) is not int or self.total_budget_units_consumed < 0:
            raise ValueError("total_budget_units_consumed must be non-negative")
        if self.succeeded and (self.budget_exhausted or self.attempt_limit_exhausted or self.reauthentication_required):
            raise ValueError("successful result has contradictory terminal flags")
        if self.budget_exhausted and self.attempt_limit_exhausted:
            raise ValueError("budget exhaustion and attempt-limit exhaustion conflict")
        if self.attempt_limit_exhausted and not self.attempt_history:
            raise ValueError("attempt-limit exhaustion requires an attempt")
        if self.attempt_limit_exhausted and self.final_outcome not in {code.value for code in RETRYABLE_CODES}:
            raise ValueError("attempt-limit exhaustion requires a retryable final error")
        if self.attempt_limit_exhausted and self.reauthentication_required:
            raise ValueError("attempt-limit exhaustion cannot require reauthentication")
        if self.budget_exhausted and self.reauthentication_required:
            raise ValueError("budget exhaustion cannot require reauthentication")

    @property
    def attempts(self) -> tuple[AttemptRecord, ...]:
        return self.attempt_history

    def __repr__(self) -> str:
        return (
            f"BudgetedBrokerResult(attempt_history={self.attempt_history!r}, "
            f"final_outcome={self.final_outcome!r}, request_fingerprint={self.request_fingerprint!r}, "
            f"total_budget_units_consumed={self.total_budget_units_consumed}, "
            f"budget_exhausted={self.budget_exhausted}, reauthentication_required={self.reauthentication_required}, "
            f"succeeded={self.succeeded})"
        )


def _canonical_request_id(value: object) -> str:
    if not isinstance(value, str):
        raise InvalidRequestIdError("request-ID factory returned an invalid ID")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise InvalidRequestIdError("request-ID factory returned an invalid ID")
    if str(parsed) != value:
        raise InvalidRequestIdError("request-ID factory returned an invalid ID")
    return value


def _attempt_from_response(number: int, request_id: str, fingerprint: str, response: BrokerResponse, *, delay: Optional[timedelta], retry: bool) -> AttemptRecord:
    code = response.error_code
    return AttemptRecord(number, request_id, fingerprint, True, response.broker_request_id, response.transport_status.value, response.provider_http_status, response.session_state.value, code, response.body_length, response.body_sha256, retry, delay, bool(code and error_policy(code).reauthentication_required))


def _observe(observer: Callable[[AttemptRecord, Optional[BrokerResponse]], None] | None, record: AttemptRecord, response: Optional[BrokerResponse]) -> None:
    if observer is None:
        return
    try:
        observer(record, response)
    except Exception:
        raise AttemptObserverError("attempt observer failed") from None


def run_planned_request(
    planned_request: ZerodhaPlannedRequest,
    broker: HistoricalBroker,
    request_budget: RequestBudget,
    retry_policy: RetryPolicy,
    request_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    jitter_source: Callable[[int], object] = lambda _number: timedelta(0),
    attempt_observer: Callable[[AttemptRecord, Optional[BrokerResponse]], None] | None = None,
) -> BudgetedBrokerResult:
    """Admit and run attempts immediately; this function never sleeps."""
    if not isinstance(planned_request, ZerodhaPlannedRequest):
        raise InconsistentBrokerResponseError("planned request is invalid")
    if not isinstance(request_budget, RequestBudget):
        raise BudgetConfigurationError("request budget is invalid")
    history: list[AttemptRecord] = []
    used = 0
    seen: set[str] = set()
    next_delay: Optional[timedelta] = None
    for number in range(1, retry_policy.maximum_attempts + 1):
        request_id = _canonical_request_id(request_id_factory())
        if request_id in seen:
            raise DuplicateRequestIdError("request-ID factory returned a duplicate ID")
        seen.add(request_id)
        original = planned_request.candle_request
        try:
            request = CandleRequest(1, request_id, planned_request.provider_instrument_id, original.interval, original.from_timestamp, original.to_timestamp, original.continuous, original.oi)
        except Exception as exc:
            if isinstance(exc, ZerodhaBrokerError):
                raise InconsistentBrokerResponseError("planned request cannot produce a broker request") from None
            raise
        try:
            request_budget.consume(retry_policy.budget_scope, retry_policy.budget_window_id)
        except RequestBudgetExceeded:
            record = AttemptRecord(number, request_id, planned_request.fingerprint, False)
            history.append(record)
            return BudgetedBrokerResult(tuple(history), "BUDGET_EXHAUSTED", None, planned_request.fingerprint, used, True, False, False, False, next_delay)
        except Exception:
            raise BudgetConfigurationError("request budget could not admit the attempt") from None
        used += 1
        try:
            response = broker.fetch_candles(request)
        except ZerodhaBrokerError as exc:
            code = exc.code
            permitted = error_policy(code).retryable and code in RETRYABLE_CODES and number < retry_policy.maximum_attempts
            attempt_limit = error_policy(code).retryable and code in RETRYABLE_CODES and number >= retry_policy.maximum_attempts
            delay = calculate_retry_delay(retry_policy, number, jitter_source=jitter_source) if permitted else None
            record = AttemptRecord(number, request_id, planned_request.fingerprint, True, error_code=code, retry_permitted=permitted, next_delay=delay, reauthentication_required=exc.policy.reauthentication_required)
            history.append(record)
            _observe(attempt_observer, record, None)
            if not permitted:
                return BudgetedBrokerResult(tuple(history), code.value, None, planned_request.fingerprint, used, False, attempt_limit, exc.policy.reauthentication_required, False, None)
            next_delay = delay
            continue
        except Exception:
            raise UnexpectedBrokerException("broker call failed with an unexpected exception") from None
        if not isinstance(response, BrokerResponse) or response.request_id != request_id:
            raise InconsistentBrokerResponseError("broker returned an inconsistent response")
        code = response.error_code
        success = code is None and response.provider_http_status is not None and 200 <= response.provider_http_status < 300
        permitted = bool(code and error_policy(code).retryable and code in RETRYABLE_CODES and number < retry_policy.maximum_attempts)
        attempt_limit = bool(code and error_policy(code).retryable and code in RETRYABLE_CODES and number >= retry_policy.maximum_attempts)
        delay = calculate_retry_delay(retry_policy, number, retry_after_seconds=response.retry_after_seconds, jitter_source=jitter_source) if permitted else None
        record = _attempt_from_response(number, request_id, planned_request.fingerprint, response, delay=delay, retry=permitted)
        history.append(record)
        _observe(attempt_observer, record, response)
        if success:
            return BudgetedBrokerResult(tuple(history), "SUCCESS", response, planned_request.fingerprint, used, False, False, False, True, None)
        if not permitted:
            return BudgetedBrokerResult(tuple(history), code.value if code else "INCONSISTENT_RESPONSE", response, planned_request.fingerprint, used, False, attempt_limit, bool(code and error_policy(code).reauthentication_required), False, None)
        next_delay = delay
