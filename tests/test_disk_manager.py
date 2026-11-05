from __future__ import annotations

import os
import unittest

from core.disk_manager import DiskManager


class DiskManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manager = DiskManager()
        cls.volumes = cls.manager.list_volumes()

    def test_volumes_have_real_capacity(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows volume discovery test")
        self.assertGreaterEqual(len(self.volumes), 1)
        for volume in self.volumes:
            self.assertGreater(volume.total, 0)
            self.assertGreaterEqual(volume.used, 0)
            self.assertGreaterEqual(volume.free, 0)
            self.assertLessEqual(volume.used + volume.free, volume.total + 1024 * 1024)

    def test_volume_letters_are_unique(self) -> None:
        letters = [volume.drive_letter for volume in self.volumes if volume.drive_letter]
        self.assertEqual(len(letters), len(set(letters)))

    def test_default_volume_prefers_system_drive(self) -> None:
        default = self.manager.default_volume(self.volumes)
        if not self.volumes:
            self.assertIsNone(default)
            return
        system = os.environ.get("SystemDrive", "").rstrip("\\").upper()
        if system:
            self.assertEqual(f"{default.drive_letter}:", system)

    def test_display_names_are_human_readable(self) -> None:
        for volume in self.volumes:
            self.assertTrue(volume.display_name)
            self.assertIn(":", volume.display_name)


if __name__ == "__main__":
    unittest.main()