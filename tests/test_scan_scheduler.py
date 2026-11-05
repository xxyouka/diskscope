from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from app.config import AppSettings
from services.scan_scheduler import mark_scan_completed, startup_scan_due, weekly_scan_due


class ScanSchedulerTests(unittest.TestCase):
    def test_weekly_scan_due_when_never_scanned_and_enabled(self) -> None:
        settings = AppSettings(auto_weekly_scan=True)
        self.assertTrue(weekly_scan_due(settings, datetime(2026, 11, 5, 12, 0, 0)))

    def test_weekly_scan_disabled(self) -> None:
        settings = AppSettings(auto_weekly_scan=False)
        self.assertFalse(weekly_scan_due(settings, datetime(2026, 11, 5)))

    def test_weekly_scan_interval(self) -> None:
        now = datetime(2026, 11, 5, 12, 0, 0)
        settings = AppSettings(auto_weekly_scan=True)
        mark_scan_completed(settings, now - timedelta(days=6, hours=23))
        self.assertFalse(weekly_scan_due(settings, now))
        mark_scan_completed(settings, now - timedelta(days=7, seconds=1))
        self.assertTrue(weekly_scan_due(settings, now))

    def test_mark_scan_updates_timestamp(self) -> None:
        settings = AppSettings(auto_weekly_scan=True)
        now = datetime(2026, 11, 5, 12, 30, 0)
        mark_scan_completed(settings, now)
        self.assertEqual(settings.last_auto_scan_at, "2026-11-05T12:30:00")

    def test_startup_scan_flag(self) -> None:
        self.assertFalse(startup_scan_due(AppSettings(scan_on_startup=False)))
        self.assertTrue(startup_scan_due(AppSettings(scan_on_startup=True)))


if __name__ == "__main__":
    unittest.main()