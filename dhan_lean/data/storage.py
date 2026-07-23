import os
import re
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Union, Any

from dhan_lean.data.models import ValidationResult

_FORBIDDEN_PATH_CHARS = re.compile(r'[\x00-\x1f\x7f\\:*?"<>|]')


def _validate_path_component(component: str, name: str) -> str:
    """Validates a single path component against traversal and invalid characters."""
    if not isinstance(component, str):
        raise ValueError(f"{name} must be a string, got {type(component).__name__}")

    comp = component.strip()
    if not comp:
        raise ValueError(f"{name} cannot be empty or blank.")

    if comp in (".", ".."):
        raise ValueError(f"{name} cannot be '.' or '..'")

    if "/" in comp or "\\" in comp:
        raise ValueError(f"{name} cannot contain path separators ('/' or '\\'): '{comp}'")

    if _FORBIDDEN_PATH_CHARS.search(comp):
        raise ValueError(f"{name} contains forbidden control/path characters: '{comp}'")

    return comp


def build_raw_artifact_dir(
    storage_root: Union[str, Path],
    provider: str,
    exchange_segment: str,
    instrument: str,
    symbol: str,
    security_id: str,
    resolution: str,
    session_date: date,
) -> Path:
    """
    Constructs a deterministic raw artifact directory path.
    Does NOT create the directory on disk.

    Enforces casing:
    - provider, exchange_segment, instrument: lowercase
    - symbol: uppercase
    """
    if type(session_date) is not date:
        raise TypeError(f"session_date must be an exact datetime.date instance (got {type(session_date).__name__})")

    root_path = Path(storage_root).resolve()

    clean_provider = _validate_path_component(provider, "provider").lower()
    clean_exchange = _validate_path_component(exchange_segment, "exchange_segment").lower()
    clean_instrument = _validate_path_component(instrument, "instrument").lower()
    clean_symbol = _validate_path_component(symbol, "symbol").upper()
    clean_sec_id = _validate_path_component(security_id, "security_id")
    clean_resolution = _validate_path_component(resolution, "resolution").lower()

    year_str = f"{session_date.year:04d}"
    month_str = f"{session_date.month:02d}"
    day_str = f"{session_date.day:02d}"

    rel_path = Path("raw") / clean_provider / clean_exchange / clean_instrument / clean_symbol / clean_sec_id / clean_resolution / year_str / month_str / day_str

    target_dir = (root_path / rel_path).resolve()

    try:
        target_dir.relative_to(root_path)
    except ValueError:
        raise ValueError(f"Constructed path '{target_dir}' escapes storage_root '{root_path}'")

    return target_dir


class ArtifactWriter:
    """
    Persists immutable Dhan historical API artifacts to disk.
    Executes exclusive creation (never overwrites existing files).
    Enforces 0700 directory permissions and 0600 file permissions on POSIX.
    """

    _RUN_ID_REGEX = re.compile(r'^\d{8}T\d{6}Z$')
    _CREDENTIAL_KEYS = {"access-token", "client-id", "dhan_access_token", "dhan_client_id", "password", "secret", "token"}

    def _verify_valid_run_id(self, run_id: str) -> None:
        """Validates run_id against format YYYYMMDDTHHMMSSZ and real calendar dates."""
        if not isinstance(run_id, str) or not self._RUN_ID_REGEX.match(run_id):
            raise ValueError(f"run_id must match UTC format YYYYMMDDTHHMMSSZ, got '{run_id}'")
        try:
            dt = datetime.strptime(run_id, "%Y%m%dT%H%M%SZ")
            if dt.strftime("%Y%m%dT%H%M%SZ") != run_id:
                raise ValueError(f"run_id calendar round-trip mismatch: '{run_id}'")
        except ValueError as e:
            raise ValueError(f"run_id represents an invalid calendar date or time: '{run_id}'") from e

    def _verify_no_credentials(self, data_bytes: bytes, name: str) -> None:
        """Verifies that no raw credential keys appear in data bytes."""
        lower_content = data_bytes.lower()
        for cred in self._CREDENTIAL_KEYS:
            if cred.encode('utf-8') in lower_content:
                raise ValueError(f"Credential key '{cred}' detected in {name} payload.")

    def write_pilot_artifacts(
        self,
        output_dir: Path,
        run_id: str,
        request_bytes: bytes,
        response_bytes: bytes,
        headers_bytes: bytes,
        http_status: int,
        validation_result: ValidationResult,
    ) -> dict[str, Path]:
        """
        Writes the 6 standard pilot artifacts exclusively.
        Raises FileExistsError if any target file already exists.
        """
        self._verify_valid_run_id(run_id)

        if not isinstance(http_status, int) or isinstance(http_status, bool):
            raise ValueError(f"http_status must be an integer, got {type(http_status).__name__}")

        if not isinstance(validation_result, ValidationResult):
            raise ValueError("validation_result must be a ValidationResult instance.")

        self._verify_no_credentials(request_bytes, "request_bytes")
        self._verify_no_credentials(headers_bytes, "headers_bytes")

        # Define file targets
        req_path = output_dir / f"request-{run_id}.json"
        resp_path = output_dir / f"response-{run_id}.json"
        hdr_path = output_dir / f"response-headers-{run_id}.txt"
        status_path = output_dir / f"http-status-{run_id}.txt"
        val_path = output_dir / f"validation-{run_id}.txt"
        sha_path = output_dir / f"sha256-{run_id}.txt"

        targets = [req_path, resp_path, hdr_path, status_path, val_path, sha_path]
        for t in targets:
            if t.exists():
                raise FileExistsError(f"Target artifact file already exists: {t}")

        # Ensure directory exists with 0700 permissions
        if not output_dir.exists():
            output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            if os.name == 'posix':
                os.chmod(output_dir, 0o700)

        # Prepare contents
        status_bytes = f"{http_status}\n".encode('utf-8')

        val_lines = [
            "--- DHAN HISTORICAL PILOT VALIDATION REPORT ---",
            f"IS_VALID={validation_result.is_valid}",
            f"ERRORS={list(validation_result.errors)}",
            f"CANDLE_COUNT={validation_result.candle_count}",
            f"ARRAY_LENGTHS={dict(validation_result.array_lengths)}",
            f"ARRAYS_EQUAL_LENGTH={validation_result.arrays_equal_length}",
            f"TIMESTAMPS_STRICTLY_INCREASING={validation_result.timestamps_strictly_increasing}",
            f"DUPLICATE_TIMESTAMP_COUNT={validation_result.duplicate_timestamp_count}",
            f"NON_INCREASING_TIMESTAMP_COUNT={validation_result.non_increasing_timestamp_count}",
            f"INVALID_OHLC_COUNT={validation_result.invalid_ohlc_count}",
            f"NON_POSITIVE_PRICE_COUNT={validation_result.non_positive_price_count}",
            f"NEGATIVE_VOLUME_COUNT={validation_result.negative_volume_count}",
            f"ZERO_VOLUME_COUNT={validation_result.zero_volume_count}",
            f"TIMESTAMP_DELTA_DISTRIBUTION={dict(validation_result.timestamp_delta_distribution)}",
            f"MISSING_GAP_COUNT={validation_result.missing_gap_count}",
            f"LARGEST_ACTUAL_INTERVAL_SECONDS={validation_result.largest_actual_interval_seconds}",
            f"LARGEST_EXCESS_GAP_SECONDS={validation_result.largest_excess_gap_seconds}",
            f"FIRST_TIMESTAMP_UTC={validation_result.first_timestamp_utc}",
            f"LAST_TIMESTAMP_UTC={validation_result.last_timestamp_utc}",
            f"FIRST_TIMESTAMP_IST={validation_result.first_timestamp_ist}",
            f"LAST_TIMESTAMP_IST={validation_result.last_timestamp_ist}",
        ]
        val_bytes = ("\n".join(val_lines) + "\n").encode('utf-8')

        files_to_write = [
            (req_path, request_bytes),
            (resp_path, response_bytes),
            (hdr_path, headers_bytes),
            (status_path, status_bytes),
            (val_path, val_bytes),
        ]

        written_paths: list[Path] = []
        try:
            for filepath, content in files_to_write:
                # Exclusive file creation ('xb')
                with open(filepath, 'xb') as f:
                    f.write(content)
                if os.name == 'posix':
                    os.chmod(filepath, 0o600)
                written_paths.append(filepath)

            # Compute SHA-256 for the 5 artifact files
            sha_lines = []
            for filepath, _ in files_to_write:
                h = hashlib.sha256()
                with open(filepath, 'rb') as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
                sha_lines.append(f"{h.hexdigest()}  {filepath.name}")

            sha_bytes = ("\n".join(sha_lines) + "\n").encode('utf-8')
            with open(sha_path, 'xb') as f:
                f.write(sha_bytes)
            if os.name == 'posix':
                os.chmod(sha_path, 0o600)
            written_paths.append(sha_path)

        except Exception as e:
            # Clean up any partial files if failure occurs during writing
            for wp in written_paths:
                if wp.exists():
                    try:
                        wp.unlink()
                    except OSError:
                        pass
            raise e

        return {
            "request": req_path,
            "response": resp_path,
            "headers": hdr_path,
            "status": status_path,
            "validation": val_path,
            "sha256": sha_path,
        }
