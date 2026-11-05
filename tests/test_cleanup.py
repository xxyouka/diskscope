from __future__ import annotations

import os
import shutil
import time
import unittest
from pathlib import Path

from core.cleanup_engine import CleanupCategory, CleanupDiscovery, CleanupRisk


class CleanupDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".tmp") / "tests" / "cleanup_fixture"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.safe = CleanupCategory(
            key="system_temp",
            title="测试临时缓存",
            description="test",
            reason="test",
            risk=CleanupRisk.SAFE,
            icon="broom",
            roots=[str(self.root)],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_safe_category_counts_recursively(self) -> None:
        (self.root / "one.tmp").write_bytes(b"x" * 100)
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "two.tmp").write_bytes(b"x" * 200)
        report = CleanupDiscovery().discover([self.safe])
        self.assertEqual(len(report.categories), 1)
        category = report.categories[0]
        self.assertEqual(category.total_size, 300)
        self.assertEqual(category.file_count, 2)
        self.assertEqual(report.total_size, 300)
        self.assertEqual(category.risk_label, "安全清理")
        self.assertEqual(len(category.samples), 2)

    def test_installers_filter_old_files_only(self) -> None:
        old_exe = self.root / "old_setup.exe"
        old_exe.write_bytes(b"x" * 500)
        old_time = time.time() - 60 * 24 * 3600
        os.utime(old_exe, (old_time, old_time))
        (self.root / "recent_setup.exe").write_bytes(b"x" * 700)
        (self.root / "readme.txt").write_bytes(b"x" * 20)
        category = CleanupCategory(
            key="installers",
            title="安装包",
            description="test",
            reason="test",
            risk=CleanupRisk.REVIEW,
            icon="download",
            roots=[str(self.root)],
            recursive=False,
        )
        report = CleanupDiscovery().discover([category])
        self.assertEqual(len(report.categories), 1)
        self.assertEqual(report.categories[0].total_size, 500)
        self.assertEqual(report.categories[0].file_count, 1)
        self.assertEqual(Path(report.categories[0].samples[0].path).resolve(), old_exe.resolve())

    def test_empty_category_is_omitted(self) -> None:
        report = CleanupDiscovery().discover([self.safe])
        self.assertEqual(report.categories, [])
        self.assertEqual(report.total_size, 0)

    def test_parallel_categories_merge_into_ordered_report(self) -> None:
        (self.root / "one.tmp").write_bytes(b"x" * 100)
        other_root = Path(".tmp") / "tests" / "cleanup_fixture_other"
        shutil.rmtree(other_root, ignore_errors=True)
        other_root.mkdir(parents=True)
        (other_root / "two.tmp").write_bytes(b"x" * 250)
        other = CleanupCategory(
            key="browser_cache",
            title="测试浏览器缓存",
            description="test",
            reason="test",
            risk=CleanupRisk.REVIEW,
            icon="browser",
            roots=[str(other_root)],
        )
        try:
            report = CleanupDiscovery(parallelism=2).discover([self.safe, other])
            self.assertEqual([category.key for category in report.categories], ["system_temp", "browser_cache"])
            self.assertEqual(report.files_scanned, 2)
            self.assertEqual(report.total_size, 350)
            self.assertEqual(report.categories[1].file_count, 1)
        finally:
            shutil.rmtree(other_root, ignore_errors=True)

    def test_cancellation(self) -> None:
        import threading

        from core.scanner import ScanCancelled

        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            CleanupDiscovery(cancel_event=cancel).discover([self.safe])


if __name__ == "__main__":
    unittest.main()