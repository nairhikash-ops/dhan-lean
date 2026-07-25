"""Offline conversion of normalized minute bars to LEAN equity ZIP data."""

import os
import tempfile
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Sequence, Union
from zoneinfo import ZoneInfo

from dhan_lean.data.models import LeanConversionResult, NormalizedBar
from dhan_lean.data.storage import _validate_path_component
from dhan_lean.data.validator import validate_normalized_bars

IST = ZoneInfo("Asia/Kolkata")


class LeanConversionError(ValueError):
    pass


def _scale(price: Decimal, name: str, index: int) -> int:
    if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
        raise LeanConversionError(f"Invalid {name} at index {index}")
    return int((price * Decimal("10000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def convert_minute_bars_to_lean(*, storage_root: Union[str, Path], symbol: str, session_date: date,
                                bars: Sequence[NormalizedBar], market: str = "india",
                                security_type: str = "equity", resolution: str = "minute") -> LeanConversionResult:
    """Write source-neutral bars as deterministic LEAN minute CSV-in-ZIP data."""
    if type(session_date) is not date:
        raise TypeError("session_date must be an exact date")
    root = Path(storage_root)
    try:
        clean_symbol = _validate_path_component(symbol, "symbol").lower()
        market = _validate_path_component(market, "market").lower()
        security_type = _validate_path_component(security_type, "security_type").lower()
        resolution = _validate_path_component(resolution, "resolution").lower()
    except ValueError as exc:
        raise LeanConversionError(str(exc)) from exc
    if (market, security_type, resolution) != ("india", "equity", "minute"):
        raise LeanConversionError("only india equity minute output is currently supported")
    result = validate_normalized_bars(bars)
    if not result.is_valid:
        raise LeanConversionError("; ".join(result.errors))
    if not bars:
        raise LeanConversionError("bars must not be empty")
    rows = []
    for index, bar in enumerate(bars):
        if bar.symbol.lower() != clean_symbol:
            raise LeanConversionError(f"bar symbol mismatch at index {index}")
        local = bar.timestamp.astimezone(IST)
        if local.date() != session_date:
            raise LeanConversionError(f"bar timestamp outside session_date at index {index}")
        millis = ((local.hour * 3600 + local.minute * 60 + local.second) * 1000) + local.microsecond // 1000
        rows.append(
            f"{millis},{_scale(bar.open, 'open', index)},{_scale(bar.high, 'high', index)},"
            f"{_scale(bar.low, 'low', index)},{_scale(bar.close, 'close', index)},{bar.volume}"
        )
    day = session_date.strftime("%Y%m%d")
    target_dir = root / "Data" / security_type / market / resolution / clean_symbol
    output = target_dir / f"{day}_trade.zip"
    member = f"{day}_{clean_symbol}_{resolution}_trade.csv"
    if output.exists():
        raise LeanConversionError(f"Target artifact already exists: {output}")
    target_dir.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=output.name + ".tmp.", suffix=".zip", delete=False) as temp:
            temp_name = Path(temp.name)
        with zipfile.ZipFile(temp_name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, ("\n".join(rows) + "\n").encode("ascii"))
        os.link(temp_name, output)
        temp_name.unlink()
    except FileExistsError as exc:
        raise LeanConversionError(f"Target artifact already exists: {output}") from exc
    except OSError as exc:
        raise LeanConversionError(f"Unable to publish LEAN output: {exc}") from exc
    finally:
        if temp_name is not None and temp_name.exists():
            temp_name.unlink(missing_ok=True)
    return LeanConversionResult(output, member, clean_symbol, session_date, len(rows), output.stat().st_size)
