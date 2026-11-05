"""Real Windows volume discovery.

This module has no UI dependencies.  It only reads local volume metadata and
usage counters; it never opens or modifies files.
"""

from __future__ import annotations

import ctypes
import logging
import os
import string
from dataclasses import dataclass
from datetime import datetime
from ctypes import wintypes

import psutil

from app.constants import DRIVE_ROLE_NAMES

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VolumeInfo:
    """A local volume with real capacity counters."""

    mount_point: str
    device: str
    label: str
    filesystem: str
    total: int
    used: int
    free: int
    percent: float
    drive_letter: str = ""
    is_removable: bool = False

    @property
    def role_name(self) -> str:
        if self.drive_letter:
            return DRIVE_ROLE_NAMES.get(self.drive_letter.upper(), "本地磁盘")
        return "本地磁盘"

    @property
    def display_name(self) -> str:
        if self.drive_letter:
            return f"{self.role_name} {self.drive_letter.upper()}:"
        return self.role_name

    @property
    def used_fraction(self) -> float:
        return (self.used / self.total) if self.total else 0.0

    @property
    def free_fraction(self) -> float:
        return (self.free / self.total) if self.total else 0.0


# ---------------------------------------------------------------------------
# Windows volume label lookup (best effort, no admin rights required)
# ---------------------------------------------------------------------------

def _volume_label(root: str) -> str:
    if os.name != "nt":
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_component = wintypes.DWORD()
        flags = wintypes.DWORD()
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            name,
            261,
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_name,
            261,
        )
        if ok:
            return name.value.strip()
    except (OSError, AttributeError, ValueError) as exc:
        logger.debug("Volume label lookup failed for %s: %s", root, exc)
    return ""


def _drive_letter(mount_point: str) -> str:
    if len(mount_point) >= 2 and mount_point[1] == ":":
        return mount_point[0].upper()
    return ""


def _is_local_volume(part: psutil._common.sdiskpart) -> bool:
    """Return whether a partition is a local, materialized volume.

    Network shares can block for seconds and optical drives without media
    report a zero capacity, so neither belongs in a local storage overview.
    """

    opts = {item.strip().lower() for item in (part.opts or "").split(",")}
    if "network" in opts or "cdrom" in opts:
        return False
    return bool(part.fstype)


class DiskManager:
    """Enumerate and read the machine's local volumes."""

    def __init__(self) -> None:
        self._last_refresh: datetime | None = None

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    def list_volumes(self) -> list[VolumeInfo]:
        volumes: list[VolumeInfo] = []
        try:
            partitions = psutil.disk_partitions(all=False)
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not enumerate disk partitions: %s", exc)
            return volumes

        for part in partitions:
            if not _is_local_volume(part):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, FileNotFoundError, OSError) as exc:
                # An inaccessible volume is not a zero-byte volume.  Record the
                # failure and move on so one unhealthy drive cannot break the
                # overview page.
                logger.warning("Volume unavailable: %s (%s)", part.mountpoint, exc)
                continue

            if usage.total <= 0:
                continue

            letter = _drive_letter(part.mountpoint)
            label = _volume_label(part.mountpoint)
            volumes.append(
                VolumeInfo(
                    mount_point=part.mountpoint,
                    device=part.device,
                    label=label,
                    filesystem=part.fstype,
                    total=int(usage.total),
                    used=int(usage.used),
                    free=int(usage.free),
                    percent=float(usage.percent),
                    drive_letter=letter,
                    is_removable="removable" in (part.opts or "").lower(),
                )
            )

        volumes.sort(key=lambda volume: (volume.drive_letter == "", volume.drive_letter))
        self._last_refresh = datetime.now()
        return volumes

    @staticmethod
    def default_volume(volumes: list[VolumeInfo]) -> VolumeInfo | None:
        if not volumes:
            return None
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\").upper()
        for volume in volumes:
            if f"{volume.drive_letter}:" == system_drive:
                return volume
        return volumes[0]

    @staticmethod
    def drive_options() -> list[str]:
        """Letters with potentially mountable local drives (for later stages)."""

        return [f"{letter}:" for letter in string.ascii_uppercase]