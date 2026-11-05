"""Background duplicate-file detection."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from core.duplicate_detector import DuplicateDetector, DuplicateProgress, DuplicateReport
from core.scanner import ScanCancelled

logger = logging.getLogger(__name__)


class DuplicateWorker(QThread):
    progress = Signal(object)
    scanFinished = Signal(object)
    scanFailed = Signal(str)
    scanCancelled = Signal()

    def __init__(self, root: str, *, excluded_paths: list[str] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.root = root
        self._excluded_paths = list(excluded_paths or [])
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self.setObjectName("DiskScopeDuplicateWorker")

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
        detector = DuplicateDetector(
            excluded_paths=self._excluded_paths,
            progress_callback=self._on_progress,
            pause_event=self._pause,
            cancel_event=self._cancel,
        )
        try:
            report: DuplicateReport = detector.find(self.root)
        except ScanCancelled:
            self.scanCancelled.emit()
        except (OSError, PermissionError) as exc:
            logger.warning("Duplicate scan failed: %s", exc)
            self.scanFailed.emit(f"无法读取所选目录：{exc}")
        except Exception as exc:
            logger.exception("Unexpected duplicate scan failure")
            self.scanFailed.emit(f"重复文件检测失败：{exc}")
        else:
            self.scanFinished.emit(report)

    def _on_progress(self, progress: DuplicateProgress) -> None:
        self.progress.emit(progress)