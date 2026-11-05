"""Human-friendly formatting helpers used across the UI."""

from __future__ import annotations

from datetime import datetime

_BINARY_UNITS = (
    ("TB", 1024.0**4),
    ("GB", 1024.0**3),
    ("MB", 1024.0**2),
    ("KB", 1024.0),
    ("B", 1.0),
)


def split_size(size_bytes: float) -> tuple[str, str]:
    """Return a numeric string (without unit) and its binary unit."""

    value = max(0.0, float(size_bytes))
    for unit, factor in _BINARY_UNITS:
        if value >= factor or unit == "B":
            number = value / factor
            if number >= 100:
                precision = 0
            elif number >= 10:
                precision = 1
            else:
                precision = 2
            text = f"{number:.{precision}f}"
            if "." in text:
                text = text.rstrip("0").rstrip(".")
            if unit == "B":
                text = str(int(number))
            return text, unit
    return "0", "B"


def format_size(size_bytes: float) -> str:
    number, unit = split_size(size_bytes)
    return f"{number} {unit}"


def format_capacity(size_bytes: float) -> str:
    """Compact capacity label used in secondary captions."""

    number, unit = split_size(size_bytes)
    return f"{number} {unit}"


def format_percent(fraction: float, decimals: int = 0) -> str:
    value = max(0.0, min(100.0, fraction * 100.0))
    if decimals <= 0:
        return f"{value:.0f}%"
    return f"{value:.{decimals}f}%"


def format_datetime(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if value is None:
        return "—"
    return value.strftime(fmt)


def friendly_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {seconds:02d} 秒"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} 小时 {minutes:02d} 分"