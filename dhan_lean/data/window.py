from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dhan_lean.data.models import RequestWindow

IST = ZoneInfo("Asia/Kolkata")


def calculate_request_window(
    start_time: datetime,
    end_time: datetime,
    interval_minutes: int = 1
) -> RequestWindow:
    """
    Calculates fromDate and toDate bounds for Dhan V2 historical intraday API queries.

    Verified API Semantics:
    - fromDate is exclusive.
    - toDate is exclusive.
    - To query desired minute interval [start, end), for 1-minute data:
        fromDate = start - 1 minute
        toDate   = end
    - Returned API timestamps will fall strictly in (fromDate, toDate),
      which matches [start, end).
    """
    if interval_minutes != 1:
        raise NotImplementedError(
            f"Interval {interval_minutes} minutes is not supported. Only interval_minutes=1 is implemented."
        )

    if start_time.tzinfo is None or start_time.tzinfo.utcoffset(start_time) is None:
        raise ValueError("start_time must be a timezone-aware datetime.")

    if end_time.tzinfo is None or end_time.tzinfo.utcoffset(end_time) is None:
        raise ValueError("end_time must be a timezone-aware datetime.")

    start_ist = start_time.astimezone(IST)
    end_ist = end_time.astimezone(IST)

    if start_ist.second != 0 or start_ist.microsecond != 0:
        raise ValueError(f"start_time must be minute-aligned (seconds and microseconds must be zero), got: {start_ist}")

    if end_ist.second != 0 or end_ist.microsecond != 0:
        raise ValueError(f"end_time must be minute-aligned (seconds and microseconds must be zero), got: {end_ist}")

    if start_ist >= end_ist:
        raise ValueError(f"start_time ({start_ist}) must be strictly less than end_time ({end_ist}).")

    from_date_dt = start_ist - timedelta(minutes=1)
    to_date_dt = end_ist

    date_format = "%Y-%m-%d %H:%M:%S"
    from_date_str = from_date_dt.strftime(date_format)
    to_date_str = to_date_dt.strftime(date_format)

    return RequestWindow(
        from_date=from_date_str,
        to_date=to_date_str,
        desired_start_ist=start_ist.strftime(date_format),
        desired_end_ist=end_ist.strftime(date_format),
        interval_minutes=1
    )
