"""Generic timezone-aware minute-window construction."""
from datetime import datetime
from dhan_lean.data.models import TimeWindow

def calculate_minute_window(start: datetime, end: datetime, interval_minutes: int = 1) -> TimeWindow:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("window datetimes must be timezone-aware")
    if start.second or start.microsecond or end.second or end.microsecond:
        raise ValueError("window datetimes must be minute-aligned")
    return TimeWindow(start, end, interval_minutes)
