from __future__ import annotations

import os
import shutil
import threading
import unittest
from pathlib import Path

from core.duplicate_detector import DuplicateDetector
from core.scanner import ScanCancelled


class DuplicateDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".tmp") / "tests" / "duplicate_fixture"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_finds_same_content_after_size_prefilter(self) -> None:
        (self.root / "a.bin").write_bytes(b"same-content" * 100)
        (self.root / "b.bin").write_bytes(b"same-content" * 100)
        (self.root / "same-size-different.bin").write_bytes(b"different..." * 100)
        (self.root / "unique.bin").write_bytes(b"x" * 17)
        report = DuplicateDetector().find(self.root)
        self.assertEqual(len(report.groups), 1)
        group = report.groups[0]
        self.assertEqual(len(group.files), 2)
        self.assertEqual(group.size, len(b"same-content" * 100))
        self.assertEqual(report.wasted_size, group.size)
        self.assertEqual({Path(item.path).name for item in group.files}, {"a.bin", "b.bin"})

    def test_nested_duplicates_and_excluded_directory(self) -> None:
        nested = self.root / "nested"
        nested.mkdir()
        (self.root / "one.dat").write_bytes(b"Z" * 1024)
        (nested / "two.dat").write_bytes(b"Z" * 1024)
        ignored = self.root / "ignored"
        ignored.mkdir()
        (ignored / "three.dat").write_bytes(b"Z" * 1024)
        report = DuplicateDetector(excluded_paths=[str(ignored)]).find(self.root)
        self.assertEqual(len(report.groups), 1)
        self.assertEqual(len(report.groups[0].files), 2)
        self.assertFalse(any("ignored" in item.path for item in report.groups[0].files))

    def test_empty_files_are_ignored(self) -> None:
        (self.root / "one.empty").write_bytes(b"")
        (self.root / "two.empty").write_bytes(b"")
        report = DuplicateDetector().find(self.root)
        self.assertEqual(report.groups, [])

    def test_no_duplicates(self) -> None:
        (self.root / "a.txt").write_bytes(b"a")
        (self.root / "b.txt").write_bytes(b"b")
        report = DuplicateDetector().find(self.root)
        self.assertEqual(report.groups, [])
        self.assertEqual(report.total_files, 0)
        self.assertEqual(report.wasted_size, 0)

    def test_cancellation(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            DuplicateDetector(cancel_event=cancel).find(self.root)

    def test_progress_reports_hashed_bytes(self) -> None:
        (self.root / "a.bin").write_bytes(b"q" * 2048)
        (self.root / "b.bin").write_bytes(b"q" * 2048)
        snapshots = []
        report = DuplicateDetector(progress_callback=snapshots.append).find(self.root)
        self.assertTrue(report.groups)
        self.assertTrue(snapshots)
        self.assertGreater(snapshots[-1].bytes_hashed, 0)


if __name__ == "__main__":
    unittest.main()