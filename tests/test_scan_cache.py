from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from core.scanner import DirectoryScanner
from services.scan_cache_service import ScanCacheService


class ScanCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".tmp") / "tests" / "cache_case"
        shutil.rmtree(self.base, ignore_errors=True)
        self.root = self.base / "tree"
        self.root.mkdir(parents=True)
        (self.root / "one.txt").write_bytes(b"a" * 100)
        (self.root / "two.py").write_bytes(b"b" * 200)
        child = self.root / "child"
        child.mkdir()
        (child / "three.jpg").write_bytes(b"c" * 300)
        self.db_path = self.base / "cache.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_save_load_round_trip(self) -> None:
        result = DirectoryScanner().scan(self.root)
        service = ScanCacheService(self.db_path)
        self.assertTrue(service.save(result))
        meta = service.metadata(self.root)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.files_scanned, 3)
        self.assertEqual(meta.dirs_scanned, 2)
        self.assertEqual(meta.total_size, 600)
        loaded = service.load(self.root)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.files_scanned, 3)
        self.assertEqual(loaded.dirs_scanned, 2)
        self.assertEqual(loaded.total_size, 600)
        self.assertEqual(loaded.root.path, str(self.root.resolve()))
        names = {child.name for child in loaded.root.children}
        self.assertIn("child", names)
        self.assertEqual(loaded.category_sizes.get("code"), 200)
        self.assertEqual(loaded.category_sizes.get("image"), 300)

    def test_second_save_replaces_previous_cache(self) -> None:
        service = ScanCacheService(self.db_path)
        first = DirectoryScanner().scan(self.root)
        self.assertTrue(service.save(first))
        (self.root / "extra.bin").write_bytes(b"z" * 50)
        second = DirectoryScanner().scan(self.root)
        self.assertTrue(service.save(second))
        loaded = service.load(self.root)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.files_scanned, 4)
        self.assertEqual(loaded.total_size, 650)
        meta = service.metadata(self.root)
        self.assertEqual(meta.files_scanned, 4)

    def test_missing_cache_returns_none(self) -> None:
        service = ScanCacheService(self.db_path)
        self.assertIsNone(service.load(self.root))
        self.assertIsNone(service.metadata(self.root))
        self.assertFalse(service.save(DirectoryScanner().scan(self.root)) is None)

    def test_delete_removes_cache(self) -> None:
        service = ScanCacheService(self.db_path)
        service.save(DirectoryScanner().scan(self.root))
        self.assertIsNotNone(service.metadata(self.root))
        service.delete(self.root)
        self.assertIsNone(service.metadata(self.root))


if __name__ == "__main__":
    unittest.main()