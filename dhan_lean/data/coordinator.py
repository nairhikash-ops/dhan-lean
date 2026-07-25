"""Sequential source-neutral batch coordination."""
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence, Tuple
from dhan_lean.data.executor import OfflineDownloader, execute_single_work_item
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import ClaimStatus, SingleExecutionResult

@dataclass(frozen=True)
class BatchSummary:
    requested_keys: Tuple[str, ...]
    processed_results: Tuple[SingleExecutionResult, ...]
    success_count: int
    failure_count: int
    interrupted_count: int
    blocked_count: int
    max_items_reached: bool
    stopped_early: bool
    stop_reason: Optional[str]

def execute_batch(ledger: StateLedger, downloader: OfflineDownloader, work_item_keys: Sequence[str], max_items: int = 100, delay_seconds: float = 0, sleep_fn: Optional[Callable[[float], None]] = None, stop_on_failure: bool = True, claim_owner: str = "batch", lease_duration_seconds: int = 900) -> BatchSummary:
    if type(max_items) is not int or max_items <= 0: raise ValueError("max_items must be positive")
    if delay_seconds < 0: raise ValueError("delay_seconds must be non-negative")
    keys = tuple(work_item_keys)
    if len(set(keys)) != len(keys) or any(not isinstance(key, str) or not key for key in keys): raise ValueError("work_item_keys must be unique non-empty strings")
    sleep = sleep_fn or time.sleep; results = []; stop = None
    for key in keys[:max_items]:
        if results and delay_seconds: sleep(delay_seconds)
        result = execute_single_work_item(ledger, downloader, key, claim_owner, lease_duration_seconds); results.append(result)
        if stop_on_failure and result.status in {"FAILED", "INTERRUPTED"}: stop = f"{result.status}: {key}"; break
    return BatchSummary(keys, tuple(results), sum(r.status == "SUCCEEDED" for r in results), sum(r.status == "FAILED" for r in results), sum(r.status == "INTERRUPTED" for r in results), sum(r.claim_status != ClaimStatus.CLAIMED for r in results), len(keys) > max_items, stop is not None, stop)
