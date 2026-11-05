"""QThread wrapper around :class:`core.scanner.DirectoryScanner`."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from core.scanner import DirectoryScanner, ScanCancelled, ScanProgress, ScanResult
from services.scan_cache_service import ScanCacheService

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    progress = Signal(object)  # ScanProgress
    scanFinished = Signal(object)  # ScanResult
    scanFailed = Signal(str)
    scanCancelled = Signal()

    def __init__(
        self,
        root: str,
        *,
        excluded_paths: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.root = root
        self._excluded_paths = list(excluded_paths or [])
        self._pause_event = threading.Event()
        self._cancel_event = threading.Event()
        self._scanner: DirectoryScanner | None = None
        self.setObjectName("DiskScopeScanWorker")

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def pause(self) -> None:
        self._pause_event.set()

    def resume(self) -> None:
        self._pause_event.clear()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_event.clear()

    def run(self) -> None:
        scanner = DirectoryScanner(
            excluded_paths=self._excluded_paths,
            progress_callback=self._on_progress,
            pause_event=self._pause_event,
            cancel_event=self._cancel_event,
        )
        self._scanner = scanner
        try:
            result: ScanResult = scanner.scan(self.root)
        except ScanCancelled:
            self.scanCancelled.emit()
        except (OSError, PermissionError) as exc:
            logger.warning("Scan failed for %s: %s", self.root, exc)
            self.scanFailed.emit(f"无法访问所选目录：{exc}")
        except Exception as exc:  # keep the UI alive on unexpected filesystem state
            logger.exception("Unexpected scan failure for %s", self.root)
            self.scanFailed.emit(f"扫描失败：{exc}")
        else:
            # Show the result immediately, then persist the directory cache in
            # the same background thread.  A cache failure must not affect the
            # scan result.
            self.scanFinished.emit(result)
            try:
                ScanCacheService().save(result)
            except Exception:
                logger.exception("Could not persist scan cache for %s", self.root)

    def _on_progress(self, progress: ScanProgress) -> None:
        self.progress.emit(progress)