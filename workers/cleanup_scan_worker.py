"""Background worker for cleanup candidate discovery."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from core.cleanup_engine import (
    CleanupDiscovery,
    CleanupProgress,
    CleanupReport,
    build_default_categories,
)
from core.scanner import ScanCancelled

logger = logging.getLogger(__name__)


class CleanupScanWorker(QThread):
    progress = Signal(object)  # CleanupProgress
    scanFinished = Signal(object)  # CleanupReport
    scanFailed = Signal(str)
    scanCancelled = Signal()

    def __init__(self, parent=None, *, include_read_only: bool = True) -> None:
        super().__init__(parent)
        self._include_read_only = bool(include_read_only)
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self.setObjectName("DiskScopeCleanupScanWorker")

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()

    def run(self) -> None:
        discovery = CleanupDiscovery(
            progress_callback=self._on_progress,
            pause_event=self._pause,
            cancel_event=self._cancel,
        )
        try:
            categories = build_default_categories()
            if not self._include_read_only:
                # Automatic scans skip only non-cleanable read-only entries
                # (the recycle bin).  WeChat attachments are cleanable, but
                # remain risk-level and require a separate confirmation.
                categories = [category for category in categories if category.cleanable]
            report = discovery.discover(categories)
        except ScanCancelled:
            self.scanCancelled.emit()
        except OSError as exc:
            logger.warning("Cleanup discovery failed: %s", exc)
            self.scanFailed.emit(f"清理建议读取失败：{exc}")
        except Exception as exc:
            logger.exception("Unexpected cleanup discovery failure")
            self.scanFailed.emit(f"清理建议读取失败：{exc}")
        else:
            self.scanFinished.emit(report)

    def _on_progress(self, progress: CleanupProgress) -> None:
        self.progress.emit(progress)