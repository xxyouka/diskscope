from __future__ import annotations

import os
import unittest

from core.software_manager import (
    build_software_record,
    read_installed_software,
    split_windows_command,
)


class SoftwareRecordTests(unittest.TestCase):
    def test_builds_display_record_and_size(self) -> None:
        record = build_software_record(
            r"Foo\Bar",
            {
                "DisplayName": "Foo Studio",
                "Publisher": "Acme",
                "DisplayVersion": "2.4.1",
                "InstallDate": "20260102",
                "InstallLocation": r"C:\Program Files\Foo",
                "EstimatedSize": 102400,
                "UninstallString": r'"C:\Program Files\Foo\unins.exe" /S',
            },
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.name, "Foo Studio")
        self.assertEqual(record.estimated_size, 102400 * 1024)
        self.assertEqual(record.install_date_display, "2026-01-02")
        self.assertTrue(record.can_uninstall)

    def test_hides_updates_and_system_components(self) -> None:
        self.assertIsNone(
            build_software_record(
                "update",
                {
                    "DisplayName": "Security Update for Foo",
                    "ReleaseType": "Security Update",
                    "UninstallString": "x.exe",
                },
            )
        )
        self.assertIsNone(
            build_software_record(
                "component",
                {
                    "DisplayName": "Foo Runtime",
                    "SystemComponent": 1,
                    "UninstallString": "x.exe",
                },
            )
        )

    def test_msi_entry_without_explicit_uninstall_string(self) -> None:
        record = build_software_record(
            r"Microsoft\Windows\CurrentVersion\Uninstall\{ABC-123}",
            {
                "DisplayName": "MSI App",
                "WindowsInstaller": 1,
                "EstimatedSize": 1,
            },
        )
        assert record is not None
        self.assertEqual(record.uninstall_string, "MsiExec.exe /I{ABC-123}")
        self.assertTrue(record.can_uninstall)

    @unittest.skipUnless(os.name == "nt", "Windows command line parsing")
    def test_splits_quoted_uninstall_command(self) -> None:
        parts = split_windows_command(
            r'"C:\Program Files\Foo Bar\uninstall.exe" /S /LANG=zh'
        )
        self.assertEqual(
            parts,
            [r"C:\Program Files\Foo Bar\uninstall.exe", "/S", "/LANG=zh"],
        )

    def test_reads_some_real_windows_programs(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows registry only")
        records = read_installed_software()
        self.assertTrue(all(record.name for record in records))
        self.assertEqual(
            len({record.key for record in records}),
            len(records),
        )


if __name__ == "__main__":
    unittest.main()