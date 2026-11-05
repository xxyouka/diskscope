"""Background plan builder and executor for safe cleanup."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QThread, Signal

from core.cleanup_executor import (
    CleanupExecutionProgress,
    CleanupExecutor,
    CleanupPermissionError,
    CleanupPlan,
    CleanupPlanProgress,
    CleanupPlanner,
)
from core.scanner import ScanCancelled

logger = logging.getLogger(__name__)


class CleanupPlanWorker(QThread):
    progress = Signal(object)
    planReady = Signal(object)
    scanFailed = Signal(str)
    scanCancelled = Signal()

    def __init__(
        self,
        selected_keys: list[str],
        *,
        excluded_paths: list[str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._selected_keys = list(selected_keys)
        self._excluded_paths = list(excluded_paths or [])
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self.setObjectName("DiskScopeCleanupPlanWorker")

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
        planner = CleanupPlanner(
            excluded_paths=self._excluded_paths,
            progress_callback=self._on_progress,
            pause_event=self._pause,
            cancel_event=self._cancel,
        )
        try:
            plan = planner.build(self._selected_keys)
        except ScanCancelled:
            self.scanCancelled.emit()
        except ValueError as exc:
            self.scanFailed.emit(str(exc))
        except Exception as exc:
            logger.exception("Cleanup plan build failed")
            self.scanFailed.emit(f"无法生成清理清单：{exc}")
        else:
            self.planReady.emit(plan)

    def _on_progress(self, progress: CleanupPlanProgress) -> None:
        self.progress.emit(progress)


class CleanupExecuteWorker(QThread):
    progress = Signal(object)
    executionFinished = Signal(object)
    executionFailed = Signal(str)
    executionCancelled = Signal()

    def __init__(
        self,
        plan: CleanupPlan,
        volume_mount: str,
        parent=None,
        *,
        delete_mode: str = "recycle",
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._volume_mount = volume_mount
        self._delete_mode = delete_mode
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self.setObjectName("DiskScopeCleanupExecuteWorker")

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
        executor = CleanupExecutor(
            self._plan,
            volume_mount=self._volume_mount,
            progress_callback=self._on_progress,
            pause_event=self._pause,
            cancel_event=self._cancel,
            delete_mode=self._delete_mode,
        )
        try:
            result = executor.execute()
        except CleanupPermissionError as exc:
            logger.warning("Cleanup permission preflight failed: %s", exc)
            self.executionFailed.emit(str(exc))
        except Exception as exc:
            logger.exception("Cleanup execution failed")
            self.executionFailed.emit(f"清理执行失败：{exc}")
        else:
            if result.cancelled:
                self.executionCancelled.emit()
            self.executionFinished.emit(result)

    def _on_progress(self, progress: CleanupExecutionProgress) -> None:
        self.progress.emit(progress)