from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from dhan_lean.data.ledger import StateLedger
from dhan_lean.data.downloader import DhanIntradayDownloader
from dhan_lean.data.models import (
    ClaimStatus,
    SingleExecutionResult,
    WorkItemAttempt,
    DownloadResult
)
from dhan_lean.data.request_budget import RequestBudget


def execute_single_work_item(
    ledger: StateLedger,
    downloader: DhanIntradayDownloader,
    work_item_key: str,
    claim_owner: str = "single_executor",
    lease_duration_seconds: int = 900,
    request_budget: Optional[RequestBudget] = None,
    budget_scope: str = "dhan_intraday",
    budget_window_id: str = "default",
) -> SingleExecutionResult:
    """
    Executes a single registered work item by claiming it in the ledger,
    invoking the downloader exactly once using stored details, and updating the ledger state.
    """
    claim_res = ledger.claim_work_item(
        work_item_key=work_item_key,
        claim_owner=claim_owner,
        lease_duration_seconds=lease_duration_seconds
    )

    if claim_res.status != ClaimStatus.CLAIMED:
        return SingleExecutionResult(
            status=claim_res.status.name,
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=claim_res.attempt,
            download_result=None
        )

    work_item = ledger.get_work_item(work_item_key)
    if work_item is None:
        completed_attempt = ledger.mark_attempt_failed(
            attempt_id=claim_res.attempt.attempt_id,
            error_code="WORK_ITEM_NOT_FOUND",
            error_summary=f"Work item not found in database: {work_item_key}"
        )
        return SingleExecutionResult(
            status="FAILED",
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=completed_attempt,
            download_result=None,
            error_code="WORK_ITEM_NOT_FOUND",
            error_summary=f"Work item not found in database: {work_item_key}"
        )

    start_dt = datetime.fromisoformat(work_item.request_window.desired_start_ist)
    end_dt = datetime.fromisoformat(work_item.request_window.desired_end_ist)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=ZoneInfo("Asia/Kolkata"))

    try:
        if request_budget is not None:
            request_budget.consume(budget_scope, budget_window_id)
        download_result = downloader.download_intraday(
            symbol=work_item.symbol,
            security_id=work_item.security_id,
            exchange_segment=work_item.exchange_segment,
            instrument=work_item.instrument,
            start_time=start_dt,
            end_time=end_dt,
            run_id=claim_res.attempt.run_id
        )
    except (KeyboardInterrupt, SystemExit) as exc:
        completed_attempt = ledger.mark_attempt_interrupted(
            attempt_id=claim_res.attempt.attempt_id,
            error_code=type(exc).__name__,
            error_summary=str(exc) or "Execution interrupted."
        )
        return SingleExecutionResult(
            status="INTERRUPTED",
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=completed_attempt,
            download_result=None,
            error_code=type(exc).__name__,
            error_summary=str(exc) or "Execution interrupted."
        )
    except Exception as exc:
        err_code = type(exc).__name__
        err_msg = str(exc)[:500] if str(exc) else "Execution failed due to unhandled exception."
        completed_attempt = ledger.mark_attempt_failed(
            attempt_id=claim_res.attempt.attempt_id,
            error_code=err_code,
            error_summary=err_msg
        )
        return SingleExecutionResult(
            status="FAILED",
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=completed_attempt,
            download_result=None,
            error_code=err_code,
            error_summary=err_msg
        )

    if download_result.success:
        completed_attempt = ledger.mark_attempt_succeeded(claim_res.attempt.attempt_id)
        return SingleExecutionResult(
            status="SUCCEEDED",
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=completed_attempt,
            download_result=download_result
        )
    else:
        err_code = download_result.error_code or (
            f"HTTP_{download_result.status_code}" if download_result.status_code != 200 else "VALIDATION_FAILED"
        )
        err_summary = download_result.error_message or (
            ", ".join(download_result.validation_result.errors) if download_result.validation_result else "Download failed"
        )
        completed_attempt = ledger.mark_attempt_failed(
            attempt_id=claim_res.attempt.attempt_id,
            error_code=err_code,
            error_summary=err_summary
        )
        return SingleExecutionResult(
            status="FAILED",
            work_item_key=work_item_key,
            claim_status=claim_res.status,
            attempt=completed_attempt,
            download_result=download_result,
            error_code=err_code,
            error_summary=err_summary
        )
