"""Pure scheduling helpers for automatic local scans."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import AppSettings

WEEKLY_INTERVAL = timedelta(days=7)


def _parse(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def weekly_scan_due(settings: AppSettings, now: datetime | None = None) -> bool:
    if not settings.auto_weekly_scan:
        return False
    now = now or datetime.now()
    last = _parse(settings.last_auto_scan_at)
    if last is None:
        return True
    return now - last >= WEEKLY_INTERVAL


def startup_scan_due(settings: AppSettings) -> bool:
    return bool(settings.scan_on_startup)


def mark_scan_completed(settings: AppSettings, now: datetime | None = None) -> None:
    settings.last_auto_scan_at = (now or datetime.now()).isoformat(timespec="seconds")