from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Sequence

from dhan_lean.data.models import DownloadWorkItem
from dhan_lean.data.window import calculate_request_window
from dhan_lean.data.storage import build_raw_artifact_path

IST = ZoneInfo("Asia/Kolkata")


def plan_one_minute_downloads(
    *,
    storage_root: Path,
    symbol: str,
    security_id: str,
    exchange_segment: str,
    instrument: str,
    session_dates: Sequence[date],
) -> tuple[DownloadWorkItem, ...]:
    """
    Pure explicit-date planner for Dhan 1-minute intraday downloads.

    Input rules:
    - storage_root must be an absolute Path instance (raises TypeError if not Path, ValueError if not absolute).
    - symbol must be a string (raises TypeError) and non-empty without leading/trailing whitespace using canonical uppercase form (raises ValueError).
    - security_id must be a string (raises TypeError) and a non-empty ASCII digit-only string (raises ValueError).
    - exchange_segment must currently be exactly "NSE_EQ" (raises ValueError).
    - instrument must currently be exactly "EQUITY" (raises ValueError).
    - session_dates must be a non-empty sequence (raises TypeError if invalid type, ValueError if empty).
    - Every element in session_dates must be an exact datetime.date instance (raises TypeError for datetime, strings, etc.).
    - Duplicate dates in session_dates raise ValueError.
    - Sorts accepted dates chronologically.
    - Performs zero filesystem, database, credential, or network access.
    """
    if not isinstance(storage_root, Path):
        raise TypeError(f"storage_root must be a Path instance, got {type(storage_root).__name__}")
    if not storage_root.is_absolute():
        raise ValueError("storage_root must be an absolute Path.")

    if not isinstance(symbol, str):
        raise TypeError(f"symbol must be a string, got {type(symbol).__name__}")
    if not symbol or symbol != symbol.strip():
        raise ValueError(f"symbol must be a non-empty string with no leading or trailing whitespace, got '{symbol}'")
    if symbol != symbol.upper():
        raise ValueError("symbol must use canonical uppercase form.")

    if not isinstance(security_id, str):
        raise TypeError(f"security_id must be a string, got {type(security_id).__name__}")
    if not security_id or not security_id.isascii() or not security_id.isdigit():
        raise ValueError("security_id must be a non-empty ASCII digit-only string.")

    if exchange_segment != "NSE_EQ":
        raise ValueError(f"exchange_segment must currently be exactly 'NSE_EQ', got '{exchange_segment}'")

    if instrument != "EQUITY":
        raise ValueError(f"instrument must currently be exactly 'EQUITY', got '{instrument}'")

    if not isinstance(session_dates, Sequence) or isinstance(session_dates, (str, bytes)):
        raise TypeError("session_dates must be a non-empty sequence of date objects.")
    if len(session_dates) == 0:
        raise ValueError("session_dates cannot be empty.")

    # Validate each date item strictly
    seen_dates: set[date] = set()
    validated_dates: list[date] = []

    for i, d in enumerate(session_dates):
        if type(d) is not date:
            raise TypeError(f"session_dates element at index {i} must be exact datetime.date instance, got {type(d).__name__}")
        if d in seen_dates:
            raise ValueError(f"Duplicate session_date detected: {d}")
        seen_dates.add(d)
        validated_dates.append(d)

    # Sort dates chronologically
    sorted_dates = sorted(validated_dates)

    work_items: list[DownloadWorkItem] = []

    for s_date in sorted_dates:
        start_ist = datetime(s_date.year, s_date.month, s_date.day, 9, 15, 0, tzinfo=IST)
        end_ist = datetime(s_date.year, s_date.month, s_date.day, 15, 30, 0, tzinfo=IST)

        request_window = calculate_request_window(start_ist, end_ist, interval_minutes=1)

        output_dir = build_raw_artifact_path(
            storage_root=storage_root,
            provider="dhan",
            exchange_segment=exchange_segment,
            instrument=instrument,
            symbol=symbol,
            security_id=security_id,
            resolution="1m",
            session_date=s_date,
        )

        date_str = s_date.strftime("%Y-%m-%d")
        work_item_key = f"dhan:nse_eq:equity:{symbol}:{security_id}:1m:{date_str}"

        item = DownloadWorkItem(
            symbol=symbol,
            security_id=security_id,
            exchange_segment=exchange_segment,
            instrument=instrument,
            bar_size="1m",
            session_date=s_date,
            request_window=request_window,
            output_directory=output_dir,
            work_item_key=work_item_key,
        )
        work_items.append(item)

    return tuple(work_items)
