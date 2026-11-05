"""Local desktop notifications with an optional in-window fallback."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtWidgets import QSystemTrayIcon

from core.disk_manager import VolumeInfo

logger = logging.getLogger(__name__)

TrayProvider = Callable[[], QSystemTrayIcon | None]
Fallback = Callable[[str, str], None]


def low_space_volumes(
    volumes: list[VolumeInfo],
    monitored_drives: list[str] | tuple[str, ...] | None = None,
    *,
    free_threshold: float = 0.10,
) -> list[VolumeInfo]:
    """Return volumes whose free fraction is below the warning threshold."""

    monitored = {str(letter).upper().rstrip(":\\") for letter in (monitored_drives or [])}
    result = []
    for volume in volumes:
        if monitored and volume.drive_letter.upper() not in monitored:
            continue
        if volume.total > 0 and volume.free_fraction < free_threshold:
            result.append(volume)
    return result


class NotificationService:
    def __init__(
        self,
        tray_provider: TrayProvider,
        fallback: Fallback | None = None,
    ) -> None:
        self._tray_provider = tray_provider
        self._fallback = fallback

    def notify(
        self,
        title: str,
        message: str,
        *,
        timeout_ms: int = 4200,
        use_fallback: bool = True,
    ) -> bool:
        tray = None
        try:
            tray = self._tray_provider()
        except Exception:
            logger.exception("Tray provider failed")
        if tray is not None:
            try:
                tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    int(timeout_ms),
                )
                return True
            except Exception:
                logger.exception("Could not show tray notification")
        if use_fallback and self._fallback is not None:
            try:
                self._fallback(title, message)
            except Exception:
                logger.exception("Notification fallback failed")
        return False