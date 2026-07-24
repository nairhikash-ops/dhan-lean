import os
import tempfile
from pathlib import Path
from typing import List


class TokenStoreError(Exception):
    """Base exception for token storage operations."""
    pass


class PermissionDeniedError(TokenStoreError):
    """Raised when writing to the environment file fails due to file permissions."""
    pass


class SymlinkNotAllowedError(TokenStoreError):
    """Raised when target environment file or parent is a symbolic link."""
    pass


class InvalidTokenError(TokenStoreError):
    """Raised when provided access token fails validation checks."""
    pass


MAX_TOKEN_LENGTH = 4096
TOKEN_ENV_KEY = "DHAN_ACCESS_TOKEN"


def validate_token(token: str) -> None:
    """
    Validates token string safety without logging or echoing the value.

    Rejects:
    - Non-string or empty / whitespace-only values
    - Control characters (ASCII < 32 or 127), CR, LF, null bytes
    - Tokens exceeding maximum length limit
    """
    if not isinstance(token, str):
        raise InvalidTokenError("Token must be a string.")

    stripped = token.strip()
    if not stripped:
        raise InvalidTokenError("Token cannot be empty or whitespace-only.")

    if len(token) > MAX_TOKEN_LENGTH:
        raise InvalidTokenError(f"Token length exceeds maximum limit of {MAX_TOKEN_LENGTH} characters.")

    for char in token:
        code = ord(char)
        if code < 32 or code == 127:
            raise InvalidTokenError("Token contains control characters, newlines, or null bytes.")


def check_token_configured(env_path: Path) -> bool:
    """
    Checks if DHAN_ACCESS_TOKEN is configured in env_path without returning its value.

    Returns False if file does not exist, is empty, or token is missing.
    Raises SymlinkNotAllowedError if env_path is a symbolic link.
    """
    path = Path(env_path)
    if os.path.islink(path):
        raise SymlinkNotAllowedError("Environment path cannot be a symbolic link.")

    if not path.exists() or not path.is_file():
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith("#"):
                    continue
                if "=" in line_str:
                    key, value = line_str.split("=", 1)
                    if key.strip() == TOKEN_ENV_KEY:
                        val_stripped = value.strip().strip('"').strip("'")
                        if val_stripped:
                            return True
    except OSError:
        return False

    return False


def save_dhan_token(env_path: Path, token: str) -> None:
    """
    Atomically saves DHAN_ACCESS_TOKEN to env_path.

    Preserves other environment variables, comments, and structure.
    Replaces all duplicate DHAN_ACCESS_TOKEN entries with exactly one.
    Sets mode 0600 on the target file.
    Uses tempfile + os.replace within the same directory.
    Refuses symbolic links.
    """
    path = Path(env_path).resolve(strict=False)

    if os.path.islink(env_path) or os.path.islink(path):
        raise SymlinkNotAllowedError("Target environment file cannot be a symbolic link.")

    validate_token(token)

    parent_dir = path.parent
    if os.path.islink(parent_dir):
        raise SymlinkNotAllowedError("Environment file parent directory cannot be a symbolic link.")

    try:
        parent_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise PermissionDeniedError("Permission denied creating configuration directory.") from None
    except OSError as e:
        raise PermissionDeniedError("Error creating configuration directory.") from None

    lines: List[str] = []
    newline_char = "\n"
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                if "\r\n" in content:
                    newline_char = "\r\n"
                lines = content.splitlines(keepends=True)
        except PermissionError:
            raise PermissionDeniedError("Permission denied reading existing environment file.") from None
        except OSError as e:
            raise PermissionDeniedError("Error reading existing environment file.") from None

    new_lines: List[str] = []
    token_updated = False

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _ = stripped.split("=", 1)
            if key.strip() == TOKEN_ENV_KEY:
                if not token_updated:
                    new_lines.append(f"{TOKEN_ENV_KEY}={token}{newline_char}")
                    token_updated = True
                # Skip duplicate DHAN_ACCESS_TOKEN entries
                continue
        new_lines.append(line)

    if not token_updated:
        if new_lines and not new_lines[-1].endswith(("\n", "\r")):
            new_lines[-1] += newline_char
        new_lines.append(f"{TOKEN_ENV_KEY}={token}{newline_char}")

    tmp_path: Path = None
    tmp_fd: int = -1

    try:
        fd, tmp_file_str = tempfile.mkstemp(dir=parent_dir, prefix="dhan_env_tmp_")
        tmp_fd = fd
        tmp_path = Path(tmp_file_str)

        os.chmod(tmp_path, 0o600)

        with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
            tmp_fd = -1  # os.fdopen takes ownership of fd
            tmp_file.writelines(new_lines)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())

        os.replace(tmp_path, path)
        tmp_path = None  # Replaced successfully

        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    except PermissionError:
        raise PermissionDeniedError("Permission denied writing temporary or target environment file.") from None
    except OSError as e:
        raise PermissionDeniedError("File system error saving environment file.") from None
    finally:
        if tmp_fd != -1:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
