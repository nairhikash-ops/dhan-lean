"""Deterministic planning for source-neutral offline ingestion."""
from datetime import date, datetime, time
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo
from dhan_lean.data.models import DataWorkItem, TimeWindow
from dhan_lean.data.storage import build_raw_artifact_path

IST = ZoneInfo("Asia/Kolkata")

def plan_minute_ingestion(*, storage_root: Path, source_id: str, symbol: str, session_dates: Sequence[date]) -> tuple[DataWorkItem, ...]:
    if not isinstance(storage_root, Path) or not storage_root.is_absolute():
        raise ValueError("storage_root must be an absolute Path")
    if not isinstance(source_id, str) or not source_id.strip() or not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("source_id and symbol must be non-empty strings")
    if not isinstance(session_dates, Sequence) or isinstance(session_dates, (str, bytes)):
        raise TypeError("session_dates must be a sequence of dates")
    if len(set(session_dates)) != len(session_dates) or any(type(day) is not date for day in session_dates):
        raise ValueError("session_dates must contain unique date values")
    planned = []
    for day in sorted(session_dates):
        start = datetime.combine(day, time(9, 15), IST)
        end = datetime.combine(day, time(15, 30), IST)
        key = f"{source_id}:{symbol.upper()}:1m:{day.isoformat()}"
        output = build_raw_artifact_path(
            storage_root=storage_root,
            source_id=source_id,
            venue="market",
            data_kind="bars",
            symbol=symbol.upper(),
            instrument_id="default",
            resolution="1m",
            session_date=day,
        )
        planned.append(DataWorkItem(symbol.upper(), source_id, "1m", day, TimeWindow(start, end), output, key))
    return tuple(planned)
