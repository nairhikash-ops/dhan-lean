import json
import re
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Union, Callable, Dict, Any

from dhan_lean.data.models import ValidationResult, HttpResponse, DownloadResult
from dhan_lean.data.window import calculate_request_window
from dhan_lean.data.validator import validate_dhan_response
from dhan_lean.data.storage import build_raw_artifact_dir, ArtifactWriter
from dhan_lean.data.transport import DhanHttpTransport

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

_DIGITS_ONLY_REGEX = re.compile(r'^\d+$')
_CONTROL_CHARS_REGEX = re.compile(r'[\x00-\x1f\x7f]')


def generate_utc_run_id(clock: Optional[Callable[[], datetime]] = None) -> str:
    """
    Generates UTC run ID in YYYYMMDDTHHMMSSZ format.
    Default clock is datetime.now(timezone.utc).
    Injected clock must return a timezone-aware datetime.
    """
    if clock is None:
        now_dt = datetime.now(UTC)
    else:
        now_dt = clock()
        if not isinstance(now_dt, datetime):
            raise TypeError(f"clock must return a datetime instance, got {type(now_dt).__name__}")
        if now_dt.tzinfo is None or now_dt.tzinfo.utcoffset(now_dt) is None:
            raise ValueError("Injected clock must return a timezone-aware datetime.")
        now_dt = now_dt.astimezone(UTC)

    return now_dt.strftime("%Y%m%dT%H%M%SZ")


def build_intraday_payload(
    security_id: str,
    exchange_segment: str,
    instrument: str,
    start_time: datetime,
    end_time: datetime,
    include_oi: bool = False,
) -> bytes:
    """
    Constructs deterministic JSON request payload bytes for NSE cash equities.
    """
    if not isinstance(security_id, str):
        raise TypeError(f"security_id must be a string, got {type(security_id).__name__}")
    if not _DIGITS_ONLY_REGEX.match(security_id):
        raise ValueError(f"security_id must contain digits only, got '{security_id}'")

    if exchange_segment != "NSE_EQ":
        raise ValueError(f"exchange_segment must be exactly 'NSE_EQ', got '{exchange_segment}'")

    if instrument != "EQUITY":
        raise ValueError(f"instrument must be exactly 'EQUITY', got '{instrument}'")

    if type(include_oi) is not bool:
        raise TypeError(f"include_oi must be a boolean, got {type(include_oi).__name__}")

    window = calculate_request_window(start_time, end_time, interval_minutes=1)

    # Dictionary constructed in exact required key order
    payload = {
        "securityId": security_id,
        "exchangeSegment": exchange_segment,
        "instrument": instrument,
        "interval": "1",
        "oi": include_oi,
        "fromDate": window.from_date,
        "toDate": window.to_date,
    }

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _extract_safe_dhan_error(response_dict: dict) -> tuple[Optional[str], Optional[str]]:
    """Extracts safe scalar errorCode and errorMessage from Dhan response dict."""
    code_val = response_dict.get("errorCode")
    msg_val = response_dict.get("errorMessage")

    err_code = None
    if isinstance(code_val, (str, int, float)) and not isinstance(code_val, bool):
        s = str(code_val)
        s = _CONTROL_CHARS_REGEX.sub('', s)[:500]
        err_code = s if s else None

    err_msg = None
    if isinstance(msg_val, (str, int, float)) and not isinstance(msg_val, bool):
        s = str(msg_val)
        s = _CONTROL_CHARS_REGEX.sub('', s)[:500]
        err_msg = s if s else None

    return err_code, err_msg


class DhanIntradayDownloader:
    """Downloader orchestrator for Dhan intraday 1-minute data."""

    def __init__(
        self,
        transport: DhanHttpTransport,
        storage_root: Union[str, Path],
        writer: Optional[ArtifactWriter] = None,
    ):
        if not isinstance(transport, DhanHttpTransport):
            raise TypeError("transport must be a DhanHttpTransport instance.")
        self.transport = transport
        self.storage_root = Path(storage_root)
        self.writer = writer if writer is not None else ArtifactWriter()

    def download_intraday(
        self,
        symbol: str,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        start_time: datetime,
        end_time: datetime,
        run_id: Optional[str] = None,
        include_oi: bool = False,
    ) -> DownloadResult:
        if start_time.tzinfo is None or start_time.tzinfo.utcoffset(start_time) is None:
            raise ValueError("start_time must be a timezone-aware datetime.")
        if end_time.tzinfo is None or end_time.tzinfo.utcoffset(end_time) is None:
            raise ValueError("end_time must be a timezone-aware datetime.")

        start_ist = start_time.astimezone(IST)
        end_ist = end_time.astimezone(IST)

        if start_ist.date() != end_ist.date():
            raise ValueError(f"start_time ({start_ist.date()}) and end_time ({end_ist.date()}) must resolve to the same IST calendar date.")

        session_date = start_ist.date()
        effective_run_id = run_id if run_id is not None else generate_utc_run_id()

        output_dir = build_raw_artifact_dir(
            storage_root=self.storage_root,
            provider="dhan",
            exchange_segment=exchange_segment,
            instrument=instrument,
            symbol=symbol,
            security_id=security_id,
            resolution="1m",
            session_date=session_date,
        )

        request_bytes = build_intraday_payload(
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument=instrument,
            start_time=start_time,
            end_time=end_time,
            include_oi=include_oi,
        )

        # Preflight collision check BEFORE making network call
        self.writer.ensure_targets_available(output_dir, effective_run_id)

        # Execute single HTTP call
        http_resp = self.transport.post_intraday(request_bytes)

        parsed_json: Optional[dict] = None
        json_parse_error: Optional[str] = None
        if http_resp.status_code == 200:
            try:
                data = json.loads(http_resp.body.decode("utf-8"))
                if isinstance(data, dict):
                    parsed_json = data
                else:
                    json_parse_error = "Response JSON is not an object."
            except Exception as e:
                json_parse_error = f"Response body is not valid JSON: {e}"

        dhan_err_code: Optional[str] = None
        dhan_err_msg: Optional[str] = None
        if parsed_json is not None:
            dhan_err_code, dhan_err_msg = _extract_safe_dhan_error(parsed_json)

        val_result: Optional[ValidationResult] = None
        success = False

        if http_resp.status_code == 200 and parsed_json is not None and dhan_err_code is None and dhan_err_msg is None:
            val_result = validate_dhan_response(parsed_json)
            success = val_result.is_valid
        else:
            # Build safe failure ValidationResult
            fail_errors = []
            if http_resp.status_code != 200:
                fail_errors.append(f"HTTP status is non-200: {http_resp.status_code}")
            if json_parse_error:
                fail_errors.append(json_parse_error)
            if dhan_err_code or dhan_err_msg:
                fail_errors.append(f"Dhan API Error: code={dhan_err_code}, message={dhan_err_msg}")

            val_result = ValidationResult(
                is_valid=False,
                errors=tuple(fail_errors),
                candle_count=0,
                array_lengths={},
                arrays_equal_length=False,
                timestamps_strictly_increasing=False,
                duplicate_timestamp_count=0,
                non_increasing_timestamp_count=0,
                invalid_ohlc_count=0,
                non_positive_price_count=0,
                negative_volume_count=0,
                zero_volume_count=0,
                timestamp_delta_distribution={},
                missing_gap_count=0,
                largest_actual_interval_seconds=0,
                largest_excess_gap_seconds=0,
                first_timestamp_utc=None,
                last_timestamp_utc=None,
                first_timestamp_ist=None,
                last_timestamp_ist=None,
            )
            success = False

        # Write immutable artifacts
        artifact_paths = self.writer.write_pilot_artifacts(
            output_dir=output_dir,
            run_id=effective_run_id,
            request_bytes=request_bytes,
            response_bytes=http_resp.body,
            headers_bytes=http_resp.headers,
            http_status=http_resp.status_code,
            validation_result=val_result,
        )

        return DownloadResult(
            run_id=effective_run_id,
            output_directory=output_dir,
            status_code=http_resp.status_code,
            artifact_paths=artifact_paths,
            validation_result=val_result,
            error_code=dhan_err_code,
            error_message=dhan_err_msg,
            success=success,
        )
