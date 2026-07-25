"""Generic ledger-backed execution seam for offline source adapters."""
from typing import Protocol
from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.models import ClaimStatus, DataWorkItem, IngestionResult, SingleExecutionResult

class OfflineDownloader(Protocol):
    def ingest(self, work_item: DataWorkItem, run_id: str) -> IngestionResult: ...

def _claim_summary(status: ClaimStatus) -> str:
    return {
        ClaimStatus.WORK_ITEM_NOT_FOUND: "Work item was not found.",
        ClaimStatus.ALREADY_CLAIMED: "Work item is already claimed.",
        ClaimStatus.ALREADY_SUCCEEDED: "Work item already succeeded.",
        ClaimStatus.REVIEW_REQUIRED: "Work item requires review before execution.",
    }.get(status, "Work item could not be claimed.")

def execute_single_work_item(ledger: StateLedger, downloader: OfflineDownloader, work_item_key: str, claim_owner: str = "executor", lease_duration_seconds: int = 900) -> SingleExecutionResult:
    claim = ledger.claim_work_item(work_item_key, claim_owner, lease_duration_seconds)
    if claim.attempt is None:
        return SingleExecutionResult(claim.status.name, work_item_key, claim.status, error_summary=_claim_summary(claim.status))
    item = ledger.get_work_item(work_item_key)
    if item is None:
        summary = "Work item could not be loaded after claim."
        attempt = ledger.mark_attempt_failed(claim.attempt.attempt_id, "WORK_ITEM_NOT_FOUND", summary)
        return SingleExecutionResult("FAILED", work_item_key, claim.status, attempt, error_code="WORK_ITEM_NOT_FOUND", error_summary=summary)
    try:
        result = downloader.ingest(item, claim.attempt.run_id)
    except (KeyboardInterrupt, SystemExit) as exc:
        code = type(exc).__name__
        summary = "Execution interrupted."
        attempt = ledger.mark_attempt_interrupted(claim.attempt.attempt_id, code, summary)
        return SingleExecutionResult("INTERRUPTED", work_item_key, claim.status, attempt, error_code=code, error_summary=summary)
    except Exception as exc:
        code = type(exc).__name__
        summary = f"Downloader raised {code}."
        attempt = ledger.mark_attempt_failed(claim.attempt.attempt_id, code, summary)
        return SingleExecutionResult("FAILED", work_item_key, claim.status, attempt, error_code=code, error_summary=summary)
    if result.success:
        attempt = ledger.mark_attempt_succeeded(claim.attempt.attempt_id)
        return SingleExecutionResult("SUCCEEDED", work_item_key, claim.status, attempt, result)
    code = result.error_code or result.validation_result.error_code or "INGESTION_FAILED"
    summary = result.error_message or result.validation_result.error_summary or "Ingestion failed."
    attempt = ledger.mark_attempt_failed(claim.attempt.attempt_id, code, summary)
    return SingleExecutionResult("FAILED", work_item_key, claim.status, attempt, result, error_code=code, error_summary=summary)
