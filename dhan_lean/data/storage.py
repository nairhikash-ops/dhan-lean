import os
import re
import hashlib
import json
import shutil
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from pathlib import PureWindowsPath
from types import MappingProxyType
from typing import Union, Any, Mapping, Iterable

from dhan_lean.data.models import ValidationResult

_FORBIDDEN_PATH_CHARS = re.compile(r'[\x00-\x1f\x7f\\:*?"<>|]')
_WINDOWS_RESERVED_NAMES = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})


def _validate_bundle_filename(name: object) -> str:
    """Return one cross-platform-safe regular filename or raise ValueError."""
    if not isinstance(name, str) or not name or name in {".", ".."}:
        raise ValueError("bundle filename is invalid")
    if name[-1] in {".", " "} or "/" in name or "\\" in name or _FORBIDDEN_PATH_CHARS.search(name):
        raise ValueError("bundle filename is unsafe")
    windows = PureWindowsPath(name)
    if windows.is_absolute() or windows.drive or windows.root or Path(name).name != name:
        raise ValueError("bundle filename is not a single relative name")
    if name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError("bundle filename is a reserved device name")
    return name


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


def build_raw_artifact_path(
    *,
    storage_root: Path,
    source_id: str,
    venue: str,
    data_kind: str,
    symbol: str,
    instrument_id: str,
    resolution: str,
    session_date: date,
) -> Path:
    """
    Constructs a deterministic raw artifact directory path purely lexically.
    Does NOT call resolve(), absolute(), exists(), or perform any filesystem access.
    """
    if type(session_date) is not date:
        raise TypeError(f"session_date must be an exact datetime.date instance (got {type(session_date).__name__})")

    clean_source_id = _validate_path_component(source_id, "source_id").lower()
    clean_venue = _validate_path_component(venue, "venue").lower()
    clean_data_kind = _validate_path_component(data_kind, "data_kind").lower()
    clean_symbol = _validate_path_component(symbol, "symbol").upper()
    clean_instrument_id = _validate_path_component(instrument_id, "instrument_id")
    clean_resolution = _validate_path_component(resolution, "resolution").lower()

    year_str = f"{session_date.year:04d}"
    month_str = f"{session_date.month:02d}"
    day_str = f"{session_date.day:02d}"

    rel_path = Path("raw") / clean_source_id / clean_venue / clean_data_kind / clean_symbol / clean_instrument_id / clean_resolution / year_str / month_str / day_str

    target_dir = Path(storage_root) / rel_path
    return target_dir


def build_raw_artifact_dir(
    storage_root: Union[str, Path],
    source_id: str,
    venue: str,
    data_kind: str,
    symbol: str,
    instrument_id: str,
    resolution: str,
    session_date: date,
) -> Path:
    """
    Constructs a deterministic raw artifact directory path and resolves it.
    Does NOT create the directory on disk.

    Enforces casing:
    - source_id, venue, data_kind: lowercase
    - symbol: uppercase
    """
    root_path = Path(storage_root).resolve()
    target_dir = build_raw_artifact_path(
        storage_root=root_path,
        source_id=source_id,
        venue=venue,
        data_kind=data_kind,
        symbol=symbol,
        instrument_id=instrument_id,
        resolution=resolution,
        session_date=session_date,
    ).resolve()

    try:
        target_dir.relative_to(root_path)
    except ValueError:
        raise ValueError(f"Constructed path '{target_dir}' escapes storage_root '{root_path}'")

    return target_dir


class ArtifactWriter:
    """
    Persists immutable source artifacts to disk.
    Executes exclusive creation (never overwrites existing files).
    Enforces 0700 directory permissions and 0600 file permissions on POSIX.
    """

    _RUN_ID_REGEX = re.compile(r'^\d{8}T\d{6}Z$')
    _CREDENTIAL_KEYS = {"access-token", "client-id", "password", "secret", "token"}

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

    def build_artifact_paths(
        self,
        output_dir: Path,
        run_id: str,
    ) -> Mapping[str, Path]:
        """
        Validates run_id and returns deterministic mapping of target artifact paths.
        Does NOT create directories or files.
        """
        self._verify_valid_run_id(run_id)
        out_path = Path(output_dir)

        paths = {
            "request": out_path / f"request-{run_id}.json",
            "response": out_path / f"response-{run_id}.json",
            "headers": out_path / f"response-headers-{run_id}.txt",
            "status": out_path / f"http-status-{run_id}.txt",
            "validation": out_path / f"validation-{run_id}.txt",
            "sha256": out_path / f"sha256-{run_id}.txt",
        }
        return MappingProxyType(paths)

    def ensure_targets_available(
        self,
        output_dir: Path,
        run_id: str,
    ) -> Mapping[str, Path]:
        """
        Checks if any target artifact path already exists.
        Raises FileExistsError if any target file exists.
        Returns immutable mapping of available target paths.
        """
        targets = self.build_artifact_paths(output_dir, run_id)
        for target_path in targets.values():
            if target_path.exists():
                raise FileExistsError(f"Target artifact file already exists: {target_path}")
        return targets

    def write_source_artifacts(
        self,
        output_dir: Path,
        run_id: str,
        request_bytes: bytes,
        response_bytes: bytes,
        headers_bytes: bytes,
        http_status: int,
        validation_result: ValidationResult,
    ) -> Mapping[str, Path]:
        """
        Writes the six standard source artifacts exclusively.
        Raises FileExistsError if any target file already exists.
        """
        if not isinstance(http_status, int) or isinstance(http_status, bool):
            raise ValueError(f"http_status must be an integer, got {type(http_status).__name__}")

        if not isinstance(validation_result, ValidationResult):
            raise ValueError("validation_result must be a ValidationResult instance.")

        self._verify_no_credentials(request_bytes, "request_bytes")
        self._verify_no_credentials(headers_bytes, "headers_bytes")

        # Centralized preflight check
        target_map = self.ensure_targets_available(output_dir, run_id)
        req_path = target_map["request"]
        resp_path = target_map["response"]
        hdr_path = target_map["headers"]
        status_path = target_map["status"]
        val_path = target_map["validation"]
        sha_path = target_map["sha256"]

        # Ensure directory exists with 0700 permissions
        if not output_dir.exists():
            output_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
            if os.name == 'posix':
                os.chmod(output_dir, 0o700)

        # Prepare contents
        status_bytes = f"{http_status}\n".encode('utf-8')

        val_lines = [
            "--- SOURCE ARTIFACT VALIDATION REPORT ---",
            f"IS_VALID={validation_result.is_valid}",
            f"ERRORS={list(validation_result.errors)}",
            f"BAR_COUNT={validation_result.bar_count}",
            f"TIMESTAMPS_STRICTLY_INCREASING={validation_result.timestamps_strictly_increasing}",
            f"DUPLICATE_TIMESTAMP_COUNT={validation_result.duplicate_timestamp_count}",
            f"NON_INCREASING_TIMESTAMP_COUNT={validation_result.non_increasing_timestamp_count}",
            f"INVALID_OHLC_COUNT={validation_result.invalid_ohlc_count}",
            f"NON_POSITIVE_PRICE_COUNT={validation_result.non_positive_price_count}",
            f"NEGATIVE_VOLUME_COUNT={validation_result.negative_volume_count}",
            f"TIMESTAMP_DELTA_DISTRIBUTION={dict(validation_result.timestamp_delta_distribution)}",
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

        return target_map

    def write_immutable_bundle(self, output_dir: Path, files: Mapping[str, bytes], *, screened_names: Iterable[str] = (), _failure_injector: Any = None) -> Mapping[str, Path]:
        """Stage and atomically publish a named immutable file bundle.

        The final directory is created only by a non-overwriting rename after
        every payload and the completion manifest have been flushed in a unique
        sibling staging directory.
        """
        if not isinstance(files, Mapping) or not files:
            raise ValueError("files must map safe regular file names to bytes")
        try:
            names = tuple(_validate_bundle_filename(name) for name in files)
        except ValueError:
            raise ValueError("files must map safe regular file names to bytes") from None
        if len(set(names)) != len(names) or any(not isinstance(content, bytes) for content in files.values()):
            raise ValueError("files must map safe regular file names to bytes")
        manifest_name = "manifest.json"
        if manifest_name in names:
            raise ValueError("manifest.json is reserved")
        for name in screened_names:
            if name not in files:
                raise ValueError("screened file is not in bundle")
            self._verify_no_credentials(files[name], name)

        manifest = {"files": {name: {"length": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest()} for name in sorted(names)}}
        manifest_bytes = (json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        target_dir = Path(output_dir)
        if not target_dir.name or target_dir.name in {".", ".."}:
            raise ValueError("output directory is invalid")
        parent = target_dir.parent
        # Keep this compact: deep provider paths must also work on Windows.
        staging = parent / f".tmp-{uuid.uuid4().hex}"
        lock = parent / f".lock-{target_dir.name}"
        lock_created = False

        def inject(stage: str) -> None:
            if _failure_injector is not None:
                _failure_injector(stage)

        def sync_directory(path: Path) -> None:
            if os.name == "posix":
                descriptor = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

        try:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            staging.mkdir(mode=0o700)
            if os.name == "posix":
                os.chmod(staging, 0o700)
            inject("after_staging_directory")
            for index, name in enumerate(sorted(names), start=1):
                staged = staging / name
                with open(staged, "xb") as handle:
                    handle.write(files[name])
                    handle.flush()
                    os.fsync(handle.fileno())
                if os.name == "posix":
                    os.chmod(staged, 0o600)
                actual = staged.read_bytes()
                if len(actual) != len(files[name]) or hashlib.sha256(actual).hexdigest() != manifest["files"][name]["sha256"]:
                    raise OSError("staged bundle payload verification failed")
                if index == 1:
                    inject("after_first_payload")
            inject("before_manifest")
            with open(staging / manifest_name, "xb") as handle:
                handle.write(manifest_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name == "posix":
                os.chmod(staging / manifest_name, 0o600)
            sync_directory(staging)
            inject("after_manifest")
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(descriptor)
                    lock_created = True
                    break
                except FileExistsError:
                    if target_dir.exists() or time.monotonic() >= deadline:
                        raise FileExistsError("immutable bundle destination already exists") from None
                    time.sleep(0.005)
            if target_dir.exists():
                raise FileExistsError("immutable bundle destination already exists")
            inject("before_final_rename")
            os.rename(staging, target_dir)
            sync_directory(parent)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            if lock_created:
                try:
                    lock.unlink()
                except OSError:
                    pass
        return MappingProxyType({**{name: target_dir / name for name in names}, manifest_name: target_dir / manifest_name})
