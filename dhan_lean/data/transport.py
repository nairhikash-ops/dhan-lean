import math
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple, List, Any

from dhan_lean.data.models import HttpResponse

_INVALID_CONTROL_CHARS = re.compile(r'[\r\n\x00]')


class TransportError(Exception):
    """Raised when HTTP transport network or request execution fails."""
    pass


def _serialize_response_headers(headers_obj: Any) -> bytes:
    """
    Deterministically serializes HTTP response headers.
    Sorts key-value pairs by lowercase header name then by header value.
    Preserves duplicate header fields. Serializes with UTF-8 and CRLF line endings.
    """
    items: List[Tuple[str, str]] = []
    if hasattr(headers_obj, "raw_items"):
        for k, v in headers_obj.raw_items():
            items.append((str(k), str(v)))
    elif hasattr(headers_obj, "items"):
        for k, v in headers_obj.items():
            items.append((str(k), str(v)))

    sorted_items = sorted(items, key=lambda x: (x[0].lower(), x[1]))
    lines = [f"{x[0]}: {x[1]}" for x in sorted_items]
    serialized = "\r\n".join(lines) + ("\r\n" if lines else "")
    return serialized.encode("utf-8")


def _default_executor(request: urllib.request.Request, timeout: float) -> HttpResponse:
    """Default HTTP request executor using urllib.request."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read()
            headers_bytes = _serialize_response_headers(resp.headers)
            return HttpResponse(
                status_code=resp.status,
                body=body,
                headers=headers_bytes
            )
    except urllib.error.HTTPError as e:
        body = e.read() if hasattr(e, "read") else b""
        headers_bytes = _serialize_response_headers(e.headers) if hasattr(e, "headers") else b""
        return HttpResponse(
            status_code=e.code,
            body=body,
            headers=headers_bytes
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        raise TransportError("Dhan HTTP transport failed.") from None


class DhanHttpTransport:
    """Standard-library HTTP transport for Dhan API V2."""

    def __init__(
        self,
        access_token: str,
        timeout_seconds: float = 30.0,
        endpoint: str = "https://api.dhan.co/v2/charts/intraday",
        executor: Optional[Callable[[urllib.request.Request, float], HttpResponse]] = None,
    ):
        if not isinstance(access_token, str):
            raise TypeError(f"access_token must be a string, got {type(access_token).__name__}")
        if len(access_token) == 0:
            raise ValueError("access_token cannot be empty.")
        if _INVALID_CONTROL_CHARS.search(access_token):
            raise ValueError("access_token contains invalid control characters (CR, LF, or null).")

        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool):
            raise TypeError(f"timeout_seconds must be a positive finite float/int, got {type(timeout_seconds).__name__}")
        if math.isnan(timeout_seconds) or math.isinf(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be positive and finite, got {timeout_seconds}")

        if not isinstance(endpoint, str):
            raise TypeError(f"endpoint must be a string, got {type(endpoint).__name__}")
        if _INVALID_CONTROL_CHARS.search(endpoint):
            raise ValueError("endpoint contains invalid control characters.")

        parsed_url = urllib.parse.urlparse(endpoint)
        if parsed_url.scheme != "https":
            raise ValueError(f"endpoint must use HTTPS scheme, got '{parsed_url.scheme}'")
        if not parsed_url.hostname:
            raise ValueError("endpoint URL must contain a non-empty hostname.")
        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError("endpoint URL must not contain username or password credentials.")

        self._access_token = access_token
        self.timeout_seconds = float(timeout_seconds)
        self.endpoint = endpoint
        self._executor = executor if executor is not None else _default_executor

    def __repr__(self) -> str:
        return f"<DhanHttpTransport endpoint='{self.endpoint}' token='[REDACTED]'>"

    def __str__(self) -> str:
        return f"DhanHttpTransport(endpoint='{self.endpoint}', token='[REDACTED]')"

    def post_intraday(self, request_payload: bytes) -> HttpResponse:
        """Executes exactly one HTTP POST request."""
        if not isinstance(request_payload, bytes):
            raise TypeError(f"request_payload must be bytes, got {type(request_payload).__name__}")

        req = urllib.request.Request(
            url=self.endpoint,
            data=request_payload,
            headers={
                "Content-Type": "application/json",
                "access-token": self._access_token,
            },
            method="POST"
        )

        try:
            res = self._executor(req, self.timeout_seconds)
            if not isinstance(res, HttpResponse):
                raise TransportError("Dhan HTTP transport failed.") from None
            return res
        except TransportError:
            raise
        except Exception:
            raise TransportError("Dhan HTTP transport failed.") from None
