"""Build a cleanup plan and execute it safely via the recycle bin."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.cleanup_engine import (
    INSTALLER_AND_ARCHIVE,
    _OLD_FILE_SECONDS,
    build_default_categories,
)
from core.safety_guard import SafetyGuard, SafetyViolation
from core.scanner import FILE_ATTRIBUTE_REPARSE_POINT, ScanCancelled

logger = logging.getLogger(__name__)

_SYSTEM_DIR_NAMES = {"$recycle.bin", "system volume information", "recovery", "config.msi"}

DELETE_MODE_RECYCLE = "recycle"
DELETE_MODE_PERMANENT = "permanent"


class CleanupPermissionError(RuntimeError):
    """The process cannot delete or recycle files for this cleanup."""


def recycle_bin_probe(target_path: str | None = None) -> str | None:
    """Return an error string when the Windows recycle bin is unusable.

    The probe is created beside the first target file whenever possible.  This
    matters because Windows has one recycle bin per volume, and a process may
    have a redirected TEMP directory on a different drive.
    """

    import tempfile

    probe_path: str | None = None
    probe_dir = None
    if target_path:
        candidate = os.path.dirname(os.path.abspath(target_path))
        if os.path.isdir(candidate):
            probe_dir = candidate
    try:
        from send2trash import send2trash
    except ImportError as exc:  # pragma: no cover - dependency is required
        return f"未安装 send2trash：{exc}"
    try:
        fd, probe_path = tempfile.mkstemp(
            prefix=".diskscope-recycle-probe-",
            suffix=".tmp",
            dir=probe_dir,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"DiskScope recycle probe")
        send2trash(probe_path)
        probe_path = None
    except Exception as exc:
        return str(exc)
    finally:
        if probe_path:
            try:
                os.unlink(probe_path)
            except OSError:
                pass
    return None


@dataclass(slots=True)
class CleanupPlanItem:
    path: str
    size: int
    modified: float
    category_key: str
    category_title: str
    risk: str


@dataclass(slots=True)
class CleanupPlan:
    items: list[CleanupPlanItem]
    categories: list
    allowed_roots: list[str]
    total_size: int
    selected_keys: list[str]

    @property
    def total_files(self) -> int:
        return len(self.items)


@dataclass(slots=True)
class CleanupPlanProgress:
    stage: str
    current_path: str
    files_found: int
    bytes_found: int
    elapsed: float


@dataclass(slots=True)
class CleanupFailure:
    path: str
    category_key: str
    error: str


@dataclass(slots=True)
class CleanupExecutionProgress:
    processed: int
    total: int
    moved: int
    failed: int
    bytes_moved: int
    current_path: str
    elapsed: float


@dataclass(slots=True)
class CleanupExecutionResult:
    started_at: datetime
    finished_at: datetime
    duration: float
    total: int
    moved: int
    failed: int
    moved_size: int
    free_before: int
    free_after: int
    cancelled: bool
    failures: list[CleanupFailure] = field(default_factory=list)
    cancelled_remaining: int = 0
    delete_mode: str = DELETE_MODE_RECYCLE

    @property
    def actual_released(self) -> int:
        return max(0, self.free_after - self.free_before)


PlanProgressCallback = Callable[[CleanupPlanProgress], None]
ExecutionProgressCallback = Callable[[CleanupExecutionProgress], None]


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).rstrip("\\/")


class CleanupPlanner:
    def __init__(
        self,
        *,
        excluded_paths: list[str] | tuple[str, ...] | None = None,
        progress_callback: PlanProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._excluded = tuple(_norm(path) for path in (excluded_paths or []) if path)
        self._progress_callback = progress_callback
        self._pause = pause_event or threading.Event()
        self._cancel = cancel_event or threading.Event()
        self._started = 0.0
        self._last_progress = 0.0
        self._files = 0
        self._items_found = 0
        self._bytes = 0
        self._current = ""

    def build(self, selected_keys: list[str]) -> CleanupPlan:
        available = {
            category.key: category
            for category in build_default_categories()
            if category.cleanable
        }
        selected = [
            available[key] for key in selected_keys if key in available
        ]
        if not selected:
            raise ValueError("没有可执行的清理类别")
        self._started = time.monotonic()
        self._last_progress = 0.0
        items: list[CleanupPlanItem] = []
        allowed_roots: list[str] = []
        for category in selected:
            category_items: list[CleanupPlanItem] = []
            for root in category.roots:
                if not os.path.isdir(root):
                    continue
                allowed_roots.append(root)
                self._walk_category(category, root, category_items)
            items.extend(category_items)
            self._emit_progress("planning", category.roots[0] if category.roots else "")
        if not items:
            return CleanupPlan([], selected, allowed_roots, 0, list(selected_keys))
        items.sort(key=lambda item: (-item.size, item.path.casefold()))
        self._emit_progress("done", "")
        return CleanupPlan(
            items=items,
            categories=selected,
            allowed_roots=allowed_roots,
            total_size=sum(item.size for item in items),
            selected_keys=list(selected_keys),
        )

    def _walk_category(self, category, root: str, output: list[CleanupPlanItem]) -> None:
        stack = [root]
        old_threshold = time.time() - _OLD_FILE_SECONDS
        while stack:
            self._checkpoint()
            current = stack.pop()
            self._current = current
            self._maybe_progress(current)
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        self._checkpoint()
                        if self._is_excluded(entry.path):
                            continue
                        try:
                            stat_result = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir:
                            if entry.name.casefold() in _SYSTEM_DIR_NAMES:
                                continue
                            if category.recursive:
                                stack.append(entry.path)
                            continue
                        size = max(0, int(getattr(stat_result, "st_size", 0)))
                        modified = float(getattr(stat_result, "st_mtime", 0.0))
                        if category.key == "installers":
                            if Path(entry.name).suffix.lower() not in INSTALLER_AND_ARCHIVE:
                                continue
                            if modified > old_threshold:
                                continue
                        self._files += 1
                        self._items_found += 1
                        self._bytes += size
                        output.append(
                            CleanupPlanItem(
                                path=entry.path,
                                size=size,
                                modified=modified,
                                category_key=category.key,
                                category_title=category.title,
                                risk=category.risk,
                            )
                        )
                        self._maybe_progress(entry.path)
            except OSError as exc:
                logger.debug("Cleanup plan skipped %s: %s", current, exc)

    def _is_excluded(self, path: str) -> bool:
        if not self._excluded:
            return False
        normalised = _norm(path)
        return any(
            normalised == excluded or normalised.startswith(excluded + os.sep)
            for excluded in self._excluded
        )

    def _checkpoint(self) -> None:
        if self._cancel.is_set():
            raise ScanCancelled()
        while self._pause.is_set():
            if self._cancel.is_set():
                raise ScanCancelled()
            time.sleep(0.05)
        if self._cancel.is_set():
            raise ScanCancelled()

    def _maybe_progress(self, path: str) -> None:
        now = time.monotonic()
        if now - self._last_progress >= 0.12:
            self._emit_progress("planning", path)

    def _emit_progress(self, stage: str, path: str) -> None:
        if self._progress_callback is None:
            return
        now = time.monotonic()
        if now - self._last_progress < 0.12 and stage == "planning":
            return
        self._last_progress = now
        try:
            self._progress_callback(
                CleanupPlanProgress(
                    stage=stage,
                    current_path=path or self._current,
                    files_found=self._items_found,
                    bytes_found=self._bytes,
                    elapsed=now - self._started,
                )
            )
        except Exception:
            logger.exception("Cleanup plan progress callback failed")


class CleanupExecutor:
    def __init__(
        self,
        plan: CleanupPlan,
        *,
        volume_mount: str,
        guard: SafetyGuard | None = None,
        trash_function=None,
        progress_callback: ExecutionProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
        probe_recycle_bin: bool = True,
        delete_mode: str = DELETE_MODE_RECYCLE,
        batch_size: int = 50,
    ) -> None:
        self.plan = plan
        self.volume_mount = volume_mount
        self.guard = guard or SafetyGuard()
        self._probe_recycle_bin = probe_recycle_bin
        if delete_mode not in (DELETE_MODE_RECYCLE, DELETE_MODE_PERMANENT):
            raise ValueError("未知的删除方式")
        self.delete_mode = delete_mode
        self._batch_size = max(1, min(200, int(batch_size)))
        if delete_mode == DELETE_MODE_PERMANENT:
            self._trash = os.remove
        elif trash_function is not None:
            self._trash = trash_function
        else:
            try:
                from send2trash import send2trash

                self._trash = send2trash
            except ImportError as exc:  # pragma: no cover - dependency is required
                raise RuntimeError("未安装 send2trash，无法安全执行清理") from exc
        self._progress_callback = progress_callback
        self._pause = pause_event or threading.Event()
        self._cancel = cancel_event or threading.Event()
        self._last_progress = 0.0
        self._started = 0.0

    def execute(self) -> CleanupExecutionResult:
        started_at = datetime.now()
        self._started = time.monotonic()
        if self._probe_recycle_bin and self.plan.items:
            self._preflight_recycle_bin()
        free_before = self._disk_free()
        total = len(self.plan.items)
        moved = 0
        failed = 0
        moved_size = 0
        failures: list[CleanupFailure] = []
        cancelled = False
        processed = 0
        while processed < total:
            if self._cancel.is_set():
                cancelled = True
                break
            self._wait_if_paused()
            if self._cancel.is_set():
                cancelled = True
                break
            batch = self.plan.items[processed : processed + self._batch_size]
            processed += len(batch)
            prepared: list[tuple[CleanupPlanItem, str]] = []
            for item in batch:
                try:
                    candidate = self.guard.validate(
                        item.path,
                        allowed_roots=self.plan.allowed_roots,
                        category_key=item.category_key,
                    )
                    current_size = os.path.getsize(candidate)
                    if current_size != item.size:
                        raise SafetyViolation("文件大小已变化，已跳过")
                except Exception as exc:
                    failed += 1
                    failures.append(
                        CleanupFailure(
                            path=item.path,
                            category_key=item.category_key,
                            error=str(exc) or exc.__class__.__name__,
                        )
                    )
                else:
                    prepared.append((item, str(candidate)))
            if prepared:
                if self.delete_mode == DELETE_MODE_RECYCLE and len(prepared) > 1:
                    batch_error = self._delete_batch(prepared)
                    if batch_error is None:
                        for item, _candidate in prepared:
                            moved += 1
                            moved_size += item.size
                    else:
                        # Preserve precise failure attribution while avoiding a
                        # per-file retry storm when the whole recycle operation
                        # is rejected.
                        bulk_failure = self._is_bulk_recycle_failure(batch_error, prepared)
                        for item, candidate in prepared:
                            if not os.path.exists(candidate):
                                moved += 1
                                moved_size += item.size
                                continue
                            if bulk_failure:
                                failed += 1
                                failures.append(
                                    CleanupFailure(
                                        path=item.path,
                                        category_key=item.category_key,
                                        error=str(batch_error)
                                        or batch_error.__class__.__name__,
                                    )
                                )
                                continue
                            try:
                                self._trash(candidate)
                            except Exception as exc:
                                failed += 1
                                failures.append(
                                    CleanupFailure(
                                        path=item.path,
                                        category_key=item.category_key,
                                        error=str(exc) or exc.__class__.__name__,
                                    )
                                )
                            else:
                                moved += 1
                                moved_size += item.size
                else:
                    for item, candidate in prepared:
                        try:
                            self._trash(candidate)
                        except Exception as exc:
                            failed += 1
                            failures.append(
                                CleanupFailure(
                                    path=item.path,
                                    category_key=item.category_key,
                                    error=str(exc) or exc.__class__.__name__,
                                )
                            )
                        else:
                            moved += 1
                            moved_size += item.size
            self._maybe_progress(
                processed,
                total,
                moved,
                failed,
                moved_size,
                batch[-1].path if batch else "",
            )
        duration = max(0.0, time.monotonic() - self._started)
        free_after = self._disk_free()
        result = CleanupExecutionResult(
            started_at=started_at,
            finished_at=datetime.now(),
            duration=duration,
            total=total,
            moved=moved,
            failed=failed,
            moved_size=moved_size,
            free_before=free_before,
            free_after=free_after,
            cancelled=cancelled,
            failures=failures,
            cancelled_remaining=max(0, total - processed) if cancelled else 0,
            delete_mode=self.delete_mode,
        )
        return result

    def _delete_batch(self, prepared: list[tuple[CleanupPlanItem, str]]) -> Exception | None:
        paths = [candidate for _item, candidate in prepared]
        try:
            self._trash(paths)
        except Exception as exc:
            return exc
        return None

    @staticmethod
    def _is_bulk_recycle_failure(
        error: Exception,
        prepared: list[tuple[CleanupPlanItem, str]],
    ) -> bool:
        text = str(error)
        markers = (
            "0x80270021",
            "WinError 5",
            "Access is denied",
            "Access denied",
            "OLE error",
            "拒绝访问",
        )
        if not any(marker in text for marker in markers):
            return False
        # A bulk failure is only treated as systemic when every source file is
        # still present.  If any disappeared, the operation was partial and the
        # caller should attribute success/failure per file.
        return all(os.path.exists(candidate) for _item, candidate in prepared)

    def _preflight_recycle_bin(self) -> None:
        """Verify that this process can use its selected delete operation.

        This avoids attempting thousands of files only to collect an
        access-denied row for each one.  The probe is a tiny disposable file in
        the current user's temp directory.
        """

        import tempfile

        probe_path: str | None = None
        probe_dir = None
        if self.plan.items:
            candidate = os.path.dirname(os.path.abspath(self.plan.items[0].path))
            if os.path.isdir(candidate):
                probe_dir = candidate
        try:
            fd, probe_path = tempfile.mkstemp(
                prefix=".diskscope-cleanup-probe-",
                suffix=".tmp",
                dir=probe_dir,
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(b"DiskScope cleanup probe")
            if self.delete_mode == DELETE_MODE_PERMANENT:
                os.remove(probe_path)
            else:
                self._trash(probe_path)
            probe_path = None
        except Exception as exc:
            if probe_path:
                try:
                    os.unlink(probe_path)
                except OSError:
                    pass
            logger.error("Cleanup preflight failed: %s", exc)
            action = (
                "无法永久删除文件，当前进程没有写入或删除权限。"
                if self.delete_mode == DELETE_MODE_PERMANENT
                else "无法将文件移入 Windows 回收站，回收站不可用或当前进程没有相应权限。"
            )
            raise CleanupPermissionError(
                f"{action}\n\n"
                "请关闭盘析，并从资源管理器以普通用户身份重新启动，"
                "不要从受限终端、沙盒或权限受限的后台服务启动；"
                "同时检查安全软件是否拦截了文件操作。\n\n"
                f"系统返回：{exc}"
            ) from exc

    def _disk_free(self) -> int:
        try:
            return int(shutil.disk_usage(self.volume_mount).free)
        except OSError:
            return 0

    def _wait_if_paused(self) -> None:
        while self._pause.is_set():
            if self._cancel.is_set():
                return
            time.sleep(0.05)

    def _maybe_progress(
        self,
        processed: int,
        total: int,
        moved: int,
        failed: int,
        moved_size: int,
        path: str,
    ) -> None:
        if self._progress_callback is None:
            return
        now = time.monotonic()
        if processed != total and now - self._last_progress < 0.1:
            return
        self._last_progress = now
        try:
            self._progress_callback(
                CleanupExecutionProgress(
                    processed=processed,
                    total=total,
                    moved=moved,
                    failed=failed,
                    bytes_moved=moved_size,
                    current_path=path,
                    elapsed=now - self._started,
                )
            )
        except Exception:
            logger.exception("Cleanup execution progress callback failed")