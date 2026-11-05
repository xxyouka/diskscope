from __future__ import annotations

import os
import shutil
import threading
import unittest
from pathlib import Path

from core.file_analyzer import FileAnalyzer, classify_extension
from core.scanner import DirectoryScanner, ScanCancelled, flatten_tree


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".tmp") / "tests" / "scan_fixture"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        (self.root / "a.txt").write_bytes(b"a" * 100)
        (self.root / "b.bin").write_bytes(b"b" * 250)
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "c.py").write_bytes(b"c" * 300)
        deep = sub / "deep"
        deep.mkdir()
        (deep / "d.jpg").write_bytes(b"d" * 50)
        excluded = self.root / "excluded"
        excluded.mkdir()
        (excluded / "secret.txt").write_bytes(b"x" * 1000)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_scan_counts_and_sizes(self) -> None:
        result = DirectoryScanner().scan(self.root)
        self.assertEqual(result.files_scanned, 5)
        self.assertEqual(result.total_size, 1700)
        self.assertEqual(result.dirs_scanned, 4)  # root, sub, deep, excluded
        self.assertEqual(result.root.file_count, 5)
        self.assertEqual(result.root.dir_count, 3)
        self.assertEqual(result.errors, 0)
        self.assertEqual(len(flatten_tree(result.root)), 4)
        self.assertEqual(result.category_sizes.get("code"), 300)
        self.assertEqual(result.category_sizes.get("image"), 50)

    def test_excluded_directory_is_omitted(self) -> None:
        result = DirectoryScanner(excluded_paths=[str(self.root / "excluded")]).scan(
            self.root
        )
        self.assertEqual(result.files_scanned, 4)
        names = {child.name for child in result.root.children}
        self.assertNotIn("excluded", names)
        self.assertEqual(result.root.dir_count, 2)

    def test_progress_callback_receives_final_counts(self) -> None:
        snapshots = []
        result = DirectoryScanner(progress_callback=snapshots.append).scan(self.root)
        self.assertTrue(snapshots)
        self.assertEqual(snapshots[-1].files_scanned, result.files_scanned)
        self.assertGreaterEqual(snapshots[-1].dirs_scanned, 1)

    def test_cancel_before_start_raises(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            DirectoryScanner(cancel_event=cancel).scan(self.root)

    def test_empty_and_missing_directories(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = DirectoryScanner().scan(empty)
        self.assertEqual(result.files_scanned, 0)
        self.assertEqual(result.root.children, [])
        with self.assertRaises(NotADirectoryError):
            DirectoryScanner().scan(self.root / "does-not-exist")

    def test_file_analyzer_lists_real_entries(self) -> None:
        scanner = DirectoryScanner()
        result = scanner.scan(self.root)
        entries = FileAnalyzer().list_entries(result.root)
        names = {entry.name for entry in entries}
        self.assertTrue({"a.txt", "b.bin", "sub", "excluded"}.issubset(names))
        folder = next(entry for entry in entries if entry.name == "sub")
        self.assertTrue(folder.is_dir)
        self.assertEqual(folder.size, 350)
        self.assertEqual(classify_extension(".jpg"), "image")
        self.assertEqual(classify_extension(".py"), "code")


if __name__ == "__main__":
    unittest.main()