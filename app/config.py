"""Runtime paths and lightweight application settings.

The app writes only to the current user's local application data directory.
``DISKSCOPE_DATA_DIR`` can relocate this for portable builds and tests.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _directory_writable(path: Path) -> bool:
    """Best-effort writability probe without leaving a file behind."""

    probe = path / f".diskscope-write-test-{os.getpid()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _default_data_dir() -> Path:
    override = os.environ.get("DISKSCOPE_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()

    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "DiskScope")
    candidates.append(Path.home() / ".diskscope")
    candidates.append(PROJECT_ROOT / "data")

    for candidate in candidates:
        if _directory_writable(candidate):
            return candidate

    # Keep the preferred location so startup raises a meaningful permission
    # error rather than silently scattering data somewhere unexpected.
    return candidates[0]


DATA_DIR: Path = _default_data_dir()
LOG_DIR: Path = DATA_DIR / "logs"
CACHE_DIR: Path = DATA_DIR / "cache"
DATABASE_PATH: Path = DATA_DIR / "diskscope.db"
SETTINGS_PATH: Path = DATA_DIR / "settings.json"
LOG_PATH: Path = LOG_DIR / "diskscope.log"

APP_ICON_PATH: Path = Path(__file__).resolve().parent.parent / "resources" / "app_icon.png"

MIN_WINDOW_WIDTH = 1200
MIN_WINDOW_HEIGHT = 720
DEFAULT_WINDOW_WIDTH = 1380
DEFAULT_WINDOW_HEIGHT = 930
WINDOW_SHADOW_MARGIN = 18
WINDOW_CORNER_RADIUS = 22


_fallback_notice_shown = False


def ensure_runtime_dirs() -> None:
    """Create the writable application directories.

    Called once during startup.  Errors bubble up so the bootstrap layer can
    report them in a readable way instead of silently swallowing them.
    """

    global _fallback_notice_shown
    for directory in (DATA_DIR, LOG_DIR, CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    if (
        not _fallback_notice_shown
        and not os.environ.get("DISKSCOPE_DATA_DIR")
        and DATA_DIR != _preferred_data_dir()
    ):
        _fallback_notice_shown = True
        sys.stderr.write(
            "DiskScope: 默认应用数据目录不可写，已回退到 "
            f"{DATA_DIR}\n"
        )


def _preferred_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "DiskScope"
    return Path.home() / ".diskscope"


@dataclass(slots=True)
class AppSettings:
    """User-facing preferences that are safe to persist as JSON.

    Only a small subset is exercised in stage one; the schema is intentionally
    forward-compatible so later stages can add fields without a migration.
    """

    minimize_to_tray: bool = True
    confirm_before_cleanup: bool = True
    delete_mode: str = "recycle_bin"
    scan_threads: int = 4
    excluded_paths: list[str] = field(default_factory=list)
    auto_weekly_scan: bool = True
    scan_on_startup: bool = False
    low_space_warning: bool = True
    ssd_safe_mode: bool = True
    cache_retention_days: int = 30
    recycle_bin_days: int = 30
    notify_scan_complete: bool = True
    notify_low_space: bool = True
    notify_cleanup_complete: bool = True
    monitored_drives: list[str] = field(default_factory=list)
    last_analysis_path: str = ""
    last_auto_scan_at: str = ""
    last_page: int = 0
    window_width: int = DEFAULT_WINDOW_WIDTH
    window_height: int = DEFAULT_WINDOW_HEIGHT

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "AppSettings":
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return cls()

        if not isinstance(raw, dict):
            return cls()

        known = {f.name for f in cls.__dataclass_fields__.values()}
        values = {key: value for key, value in raw.items() if key in known}
        try:
            settings = cls(**values)
            settings.scan_threads = max(1, min(16, int(settings.scan_threads)))
            settings.last_page = max(0, min(5, int(settings.last_page)))
            settings.cache_retention_days = max(
                1, min(365, int(settings.cache_retention_days))
            )
            settings.recycle_bin_days = max(0, min(365, int(settings.recycle_bin_days)))
            if not isinstance(settings.excluded_paths, list):
                settings.excluded_paths = []
            if not isinstance(settings.monitored_drives, list):
                settings.monitored_drives = []
            settings.excluded_paths = [
                str(path) for path in settings.excluded_paths if str(path).strip()
            ][:200]
            settings.monitored_drives = [
                str(drive).upper().rstrip(":\\")
                for drive in settings.monitored_drives
                if str(drive).strip()
            ][:26]
            settings.last_analysis_path = str(settings.last_analysis_path or "")[:2048]
            settings.last_auto_scan_at = str(settings.last_auto_scan_at or "")[:64]
            settings.window_width = max(
                MIN_WINDOW_WIDTH, min(7680, int(settings.window_width))
            )
            settings.window_height = max(
                MIN_WINDOW_HEIGHT, min(4320, int(settings.window_height))
            )
        except (TypeError, ValueError):
            return cls()
        return settings

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "minimize_to_tray": bool(self.minimize_to_tray),
            "confirm_before_cleanup": bool(self.confirm_before_cleanup),
            "delete_mode": str(self.delete_mode),
            "scan_threads": max(1, min(16, int(self.scan_threads))),
            "excluded_paths": [str(p) for p in self.excluded_paths][:200],
            "auto_weekly_scan": bool(self.auto_weekly_scan),
            "scan_on_startup": bool(self.scan_on_startup),
            "low_space_warning": bool(self.low_space_warning),
            "ssd_safe_mode": bool(self.ssd_safe_mode),
            "cache_retention_days": max(1, min(365, int(self.cache_retention_days))),
            "recycle_bin_days": max(0, min(365, int(self.recycle_bin_days))),
            "notify_scan_complete": bool(self.notify_scan_complete),
            "notify_low_space": bool(self.notify_low_space),
            "notify_cleanup_complete": bool(self.notify_cleanup_complete),
            "monitored_drives": [str(d).upper().rstrip(":\\") for d in self.monitored_drives][:26],
            "last_analysis_path": str(self.last_analysis_path or "")[:2048],
            "last_auto_scan_at": str(self.last_auto_scan_at or "")[:64],
            "last_page": max(0, min(5, int(self.last_page))),
            "window_width": max(MIN_WINDOW_WIDTH, int(self.window_width)),
            "window_height": max(MIN_WINDOW_HEIGHT, int(self.window_height)),
        }
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp_path.replace(path)