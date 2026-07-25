import math
import time
from dataclasses import dataclass
from typing import Sequence, Tuple, Optional, Callable, Set

from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.downloader import DhanIntradayDownloader
from dhan_lean.data.executor import execute_single_work_item
from dhan_lean.data.models import SingleExecutionResult, ClaimStatus
from dhan_lean.data.request_budget import RequestBudget


@dataclass(frozen=True)
class BatchSummary:
    """Immutable summary of a batch execution run."""
    requested_keys: Tuple[str, ...]
    processed_results: Tuple[SingleExecutionResult, ...]
    success_count: int
    failure_count: int
    interrupted_count: int
    blocked_count: int
    max_items_reached: bool
    stopped_early: bool
    stop_reason: Optional[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requested_keys", tuple(self.requested_keys))
        object.__setattr__(self, "processed_results", tuple(self.processed_results))


def execute_batch(
    ledger: StateLedger,
    downloader: DhanIntradayDownloader,
    work_item_keys: Sequence[str],
    max_items: int = 100,
    delay_seconds: float = 1.0,
    sleep_fn: Optional[Callable[[float], None]] = None,
    stop_on_failure: bool = True,
    claim_owner: str = "batch_coordinator",
    lease_duration_seconds: int = 900,
    request_budget: Optional[RequestBudget] = None,
    budget_scope: str = "dhan_intraday",
    budget_window_id: str = "default",
) -> BatchSummary:
    """
    Executes a batch of planned work items sequentially, enforcing request limits,
    inter-request delays, error handling, and returning an immutable BatchSummary.
    """
    if not isinstance(ledger, StateLedger):
        raise TypeError(f"ledger must be a StateLedger instance, got {type(ledger).__name__}")
    if not isinstance(downloader, DhanIntradayDownloader):
        raise TypeError(f"downloader must be a DhanIntradayDownloader instance, got {type(downloader).__name__}")

    if not isinstance(max_items, int) or isinstance(max_items, bool) or max_items <= 0:
        raise ValueError(f"max_items must be a positive integer, got {max_items}")

    if not isinstance(delay_seconds, (int, float)) or isinstance(delay_seconds, bool):
        raise TypeError(f"delay_seconds must be a non-negative finite float/int, got {type(delay_seconds).__name__}")
    if math.isnan(delay_seconds) or math.isinf(delay_seconds) or delay_seconds < 0:
        raise ValueError(f"delay_seconds must be non-negative and finite, got {delay_seconds}")

    if not isinstance(work_item_keys, (list, tuple)):
        raise TypeError(f"work_item_keys must be a sequence of strings, got {type(work_item_keys).__name__}")

    seen_keys: Set[str] = set()
    validated_keys: list[str] = []
    for idx, key in enumerate(work_item_keys):
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"work_item_keys contains empty or non-string key at index {idx}: {key}")
        if key in seen_keys:
            raise ValueError(f"Duplicate key detected in work_item_keys: {key}")
        seen_keys.add(key)
        validated_keys.append(key)

    actual_sleep = sleep_fn if sleep_fn is not None else time.sleep

    results: list[SingleExecutionResult] = []
    success_count = 0
    failure_count = 0
    interrupted_count = 0
    blocked_count = 0
    max_items_reached = False
    stopped_early = False
    stop_reason: Optional[str] = None
    made_http_request_on_previous = False

    for idx, key in enumerate(validated_keys):
        if len(results) >= max_items:
            max_items_reached = True
            stopped_early = True
            stop_reason = f"MAX_ITEMS_REACHED ({max_items})"
            break

        try:
            if len(results) > 0 and made_http_request_on_previous and delay_seconds > 0:
                actual_sleep(delay_seconds)

            made_http_request_on_previous = False

            res = execute_single_work_item(
                ledger=ledger,
                downloader=downloader,
                work_item_key=key,
                claim_owner=claim_owner,
                lease_duration_seconds=lease_duration_seconds,
                request_budget=request_budget,
                budget_scope=budget_scope,
                budget_window_id=budget_window_id,
            )
            results.append(res)

            if res.claim_status != ClaimStatus.CLAIMED:
                blocked_count += 1
                made_http_request_on_previous = False
            elif res.status == "INTERRUPTED":
                interrupted_count += 1
                made_http_request_on_previous = True
                if stop_on_failure:
                    stopped_early = True
                    stop_reason = f"INTERRUPTED: {key}"
                    break
            elif res.download_result and res.download_result.success:
                success_count += 1
                made_http_request_on_previous = True
            else:
                failure_count += 1
                made_http_request_on_previous = True
                if stop_on_failure:
                    stopped_early = True
                    stop_reason = f"FAILED: {key}"
                    break
        except Exception as exc:
            stopped_early = True
            stop_reason = f"UNEXPECTED_EXCEPTION: {type(exc).__name__}: {exc}"
            break

    return BatchSummary(
        requested_keys=tuple(validated_keys),
        processed_results=tuple(results),
        success_count=success_count,
        failure_count=failure_count,
        interrupted_count=interrupted_count,
        blocked_count=blocked_count,
        max_items_reached=max_items_reached,
        stopped_early=stopped_early,
        stop_reason=stop_reason,
    )
