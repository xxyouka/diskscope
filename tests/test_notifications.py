from __future__ import annotations

import unittest

from core.disk_manager import VolumeInfo
from services.notification_service import NotificationService, low_space_volumes


def _volume(letter: str, total: int, free: int) -> VolumeInfo:
    used = total - free
    return VolumeInfo(
        mount_point=f"{letter}:\\",
        device=f"{letter}:\\",
        label="",
        filesystem="NTFS",
        total=total,
        used=used,
        free=free,
        percent=used / total * 100,
        drive_letter=letter,
    )


class FakeTray:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.visible = True

    def showMessage(self, title, message, icon, timeout) -> None:  # noqa: N802
        del icon, timeout
        self.messages.append((title, message))


class LowSpaceTests(unittest.TestCase):
    def test_detects_volumes_below_threshold(self) -> None:
        volumes = [_volume("C", 1000, 80), _volume("E", 1000, 400)]
        low = low_space_volumes(volumes, [])
        self.assertEqual([volume.drive_letter for volume in low], ["C"])

    def test_respects_monitored_drives(self) -> None:
        volumes = [_volume("C", 1000, 80), _volume("E", 1000, 90)]
        self.assertEqual(low_space_volumes(volumes, ["E"]), [volumes[1]])
        self.assertEqual(low_space_volumes(volumes, ["D"]), [])

    def test_custom_threshold(self) -> None:
        volumes = [_volume("C", 1000, 180)]
        self.assertEqual(low_space_volumes(volumes, [], free_threshold=0.1), [])
        self.assertEqual(low_space_volumes(volumes, [], free_threshold=0.25), volumes)


class NotificationServiceTests(unittest.TestCase):
    def test_uses_tray_when_available(self) -> None:
        tray = FakeTray()
        fallback_calls = []
        service = NotificationService(lambda: tray, lambda title, message: fallback_calls.append(title))
        result = service.notify("标题", "内容")
        self.assertTrue(result)
        self.assertEqual(tray.messages, [("标题", "内容")])
        self.assertEqual(fallback_calls, [])

    def test_falls_back_without_tray(self) -> None:
        calls = []
        service = NotificationService(lambda: None, lambda title, message: calls.append((title, message)))
        result = service.notify("标题", "内容")
        self.assertFalse(result)
        self.assertEqual(calls, [("标题", "内容")])

    def test_no_fallback_when_disabled(self) -> None:
        calls = []
        service = NotificationService(lambda: None, lambda title, message: calls.append(title))
        result = service.notify("标题", "内容", use_fallback=False)
        self.assertFalse(result)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()