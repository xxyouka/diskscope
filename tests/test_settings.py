from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from app.config import AppSettings


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".tmp") / "tests"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "settings_roundtrip.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_defaults_are_safe(self) -> None:
        settings = AppSettings()
        self.assertTrue(settings.minimize_to_tray)
        self.assertTrue(settings.confirm_before_cleanup)
        self.assertEqual(settings.delete_mode, "recycle_bin")
        self.assertGreaterEqual(settings.scan_threads, 1)

    def test_save_and_load_round_trip(self) -> None:
        original = AppSettings(
            minimize_to_tray=False,
            confirm_before_cleanup=True,
            scan_threads=6,
            last_page=2,
            window_width=1300,
            window_height=900,
            excluded_paths=["C:\\Temp\\Skip"],
            auto_weekly_scan=False,
            cache_retention_days=45,
            monitored_drives=["C", "e:"],
            last_analysis_path="C:\\Users\\Example\\Documents",
            last_auto_scan_at="2026-11-05T12:00:00",
        )
        original.save(self.path)
        loaded = AppSettings.load(self.path)
        self.assertFalse(loaded.minimize_to_tray)
        self.assertEqual(loaded.scan_threads, 6)
        self.assertEqual(loaded.last_page, 2)
        self.assertEqual(loaded.excluded_paths, ["C:\\Temp\\Skip"])
        self.assertFalse(loaded.auto_weekly_scan)
        self.assertEqual(loaded.cache_retention_days, 45)
        self.assertEqual(loaded.monitored_drives, ["C", "E"])
        self.assertEqual(loaded.last_analysis_path, "C:\\Users\\Example\\Documents")
        self.assertEqual(loaded.last_auto_scan_at, "2026-11-05T12:00:00")

    def test_invalid_json_falls_back_to_defaults(self) -> None:
        self.path.write_text("{not-json", encoding="utf-8")
        loaded = AppSettings.load(self.path)
        self.assertEqual(loaded.scan_threads, 4)
        self.assertTrue(loaded.minimize_to_tray)

    def test_unknown_keys_are_ignored_and_ranges_clamped(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "scan_threads": 999,
                    "last_page": -4,
                    "unknown_key": "ignored",
                    "window_width": 20,
                }
            ),
            encoding="utf-8",
        )
        loaded = AppSettings.load(self.path)
        self.assertEqual(loaded.scan_threads, 16)
        self.assertEqual(loaded.last_page, 0)
        self.assertGreaterEqual(loaded.window_width, 1200)

    def test_atomic_save_leaves_valid_file(self) -> None:
        first = AppSettings(scan_threads=2)
        first.save(self.path)
        second = AppSettings(scan_threads=8)
        second.save(self.path)
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["scan_threads"], 8)
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()