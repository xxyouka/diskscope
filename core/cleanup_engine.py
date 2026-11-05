"""Cleanup candidate discovery.

This stage performs read-only discovery.  It never deletes, moves or modifies
files.  Candidate lists are built from a conservative allow-list of cache
locations plus a clearly separated review/risk bucket.  Execution will be added
in the cleanup stage with a preview and recycle-bin confirmation flow.
"""

from __future__ import annotations

import ctypes
import heapq
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.scanner import FILE_ATTRIBUTE_REPARSE_POINT, ScanCancelled

logger = logging.getLogger(__name__)

INSTALLER_AND_ARCHIVE = {
    ".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso",
}
_OLD_FILE_SECONDS = 30 * 24 * 3600


class CleanupRisk:
    SAFE = "safe"
    REVIEW = "review"
    RISK = "risk"

    LABELS = {
        SAFE: "安全清理",
        REVIEW: "建议确认",
        RISK: "风险提示",
    }


@dataclass(slots=True)
class CleanupSample:
    path: str
    size: int
    modified: float


@dataclass(slots=True)
class CleanupCategory:
    key: str
    title: str
    description: str
    reason: str
    risk: str
    icon: str
    roots: list[str] = field(default_factory=list)
    total_size: int = 0
    file_count: int = 0
    errors: int = 0
    samples: list[CleanupSample] = field(default_factory=list)
    selected: bool = False
    recursive: bool = True
    cleanable: bool = True

    @property
    def risk_label(self) -> str:
        return CleanupRisk.LABELS.get(self.risk, "未知")


@dataclass(slots=True)
class CleanupProgress:
    current_path: str
    files_scanned: int
    bytes_found: int
    errors: int
    current_target: str
    completed_targets: int
    total_targets: int
    elapsed: float


@dataclass(slots=True)
class CleanupReport:
    categories: list[CleanupCategory]
    started_at: datetime
    duration: float
    files_scanned: int
    errors: int
    scanned_paths: int

    @property
    def total_size(self) -> int:
        return sum(category.total_size for category in self.categories)

    @property
    def total_files(self) -> int:
        return sum(category.file_count for category in self.categories)

    def totals_by_risk(self) -> dict[str, int]:
        totals = {CleanupRisk.SAFE: 0, CleanupRisk.REVIEW: 0, CleanupRisk.RISK: 0}
        for category in self.categories:
            totals[category.risk] = totals.get(category.risk, 0) + category.total_size
        return totals


ProgressCallback = Callable[[CleanupProgress], None]


def _local_appdata() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def _windows_dir() -> Path:
    value = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    return Path(value)


def _browser_cache_roots() -> list[str]:
    local = _local_appdata()
    roots: list[str] = []
    for product in ("Google/Chrome", "Microsoft/Edge", "BraveSoftware/Brave-Browser"):
        user_data = local / product / "User Data"
        if not user_data.is_dir():
            continue
        for profile in ("Default", "Profile 1", "Profile 2", "Profile 3"):
            for cache_name in ("Cache/Cache_Data", "Code Cache", "GPUCache"):
                path = user_data / profile / cache_name
                if path.is_dir():
                    roots.append(str(path))
    firefox = local / "Mozilla" / "Firefox" / "Profiles"
    if firefox.is_dir():
        try:
            for profile in firefox.iterdir():
                cache = profile / "cache2"
                if cache.is_dir():
                    roots.append(str(cache))
        except OSError:
            pass
    return roots


def _dev_cache_roots() -> list[str]:
    home = Path.home()
    candidates = [
        home / ".npm" / "_cacache",
        home / ".cache",
        home / ".gradle" / "caches",
        home / ".cargo" / "registry" / "cache",
        _local_appdata() / "pip" / "Cache",
        _local_appdata() / "Microsoft" / "VisualStudio" / "Packages",
    ]
    return [str(path) for path in candidates if path.is_dir()]


def _wechat_roots() -> list[str]:
    """Return only chat attachment/media folders, never message databases.

    WeChat 3 keeps attachments under each account's ``FileStorage``.  WeChat 4
    keeps received files in ``msg/attach``, ``msg/file`` and ``msg/video``.
    ``db_storage``, ``msg`` database files and ``config`` remain protected.
    """

    home = Path.home()
    candidates: list[Path] = []
    legacy = home / "Documents" / "WeChat Files"
    if legacy.is_dir():
        try:
            for account in legacy.iterdir():
                storage = account / "FileStorage"
                if storage.is_dir():
                    candidates.append(storage)
        except OSError:
            pass

    modern = home / "Documents" / "xwechat_files"
    if modern.is_dir():
        try:
            for account in modern.iterdir():
                if not account.is_dir() or account.name.casefold() in {
                    "all_users",
                    "backup",
                    "wmpf",
                }:
                    continue
                for relative in (
                    "msg/attach",
                    "msg/file",
                    "msg/video",
                    "cache",
                    "temp",
                ):
                    path = account / relative
                    if path.is_dir():
                        candidates.append(path)
        except OSError:
            pass
    seen: set[str] = set()
    roots: list[str] = []
    for path in candidates:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        roots.append(str(path))
    return roots


def _recycle_bin_roots() -> list[str]:
    roots: list[str] = []
    for letter in "CDEFGH":
        path = Path(f"{letter}:\\$Recycle.Bin")
        if path.exists():
            roots.append(str(path))
    return roots


class _ShQueryRbInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("i64Size", ctypes.c_longlong),
        ("i64NumItems", ctypes.c_longlong),
    ]


def query_recycle_bin_size(root: str) -> tuple[int, int] | None:
    """Return (bytes, item_count) for a drive's recycle bin via Windows Shell.

    Reading the ``$Recycle.Bin`` tree directly can involve hundreds of
    thousands of protected entries.  The Shell API returns the same totals
    instantly and without opening user files.
    """

    if os.name != "nt":
        return None
    try:
        info = _ShQueryRbInfo()
        info.cbSize = ctypes.sizeof(info)
        result = ctypes.windll.shell32.SHQueryRecycleBinW(
            ctypes.c_wchar_p(root), ctypes.byref(info)
        )
        if result == 0:
            return max(0, int(info.i64Size)), max(0, int(info.i64NumItems))
    except (AttributeError, OSError, ValueError) as exc:
        logger.debug("SHQueryRecycleBin failed for %s: %s", root, exc)
    return None


def _downloads_roots() -> list[str]:
    downloads = Path.home() / "Downloads"
    return [str(downloads)] if downloads.is_dir() else []


def build_default_categories() -> list[CleanupCategory]:
    temp_roots = []
    temp_dir = Path(os.environ.get("TEMP", str(Path.home() / "AppData/Local/Temp")))
    windows_temp = _windows_dir() / "Temp"
    if temp_dir.is_dir():
        temp_roots.append(str(temp_dir))
    if windows_temp.is_dir() and str(windows_temp).casefold() != str(temp_dir).casefold():
        temp_roots.append(str(windows_temp))

    categories = [
        CleanupCategory(
            key="system_temp",
            title="系统临时缓存",
            description="系统与应用程序生成的临时文件",
            reason="临时文件可安全移除，不会影响系统文件与个人文档。",
            risk=CleanupRisk.SAFE,
            icon="broom",
            roots=temp_roots,
        ),
        CleanupCategory(
            key="browser_cache",
            title="浏览器缓存",
            description="Chrome、Edge、Firefox 的网页缓存",
            reason="网页缓存可重新下载；浏览器正在使用时部分文件可能被跳过。",
            risk=CleanupRisk.SAFE,
            icon="browser",
            roots=_browser_cache_roots(),
        ),
        CleanupCategory(
            key="installers",
            title="安装包与下载",
            description="下载目录中超过 30 天的安装包与压缩包",
            reason="长期未使用的安装包通常可以重新获取，建议确认后手动处理。",
            risk=CleanupRisk.REVIEW,
            icon="download",
            roots=_downloads_roots(),
            recursive=False,
        ),
        CleanupCategory(
            key="dev_cache",
            title="开发工具缓存",
            description="npm、pip、Gradle 等可重新生成的缓存",
            reason="缓存可按需重新下载，但这可能让下一次构建变慢，建议确认。",
            risk=CleanupRisk.REVIEW,
            icon="code",
            roots=_dev_cache_roots(),
        ),
        CleanupCategory(
            key="recycle_bin",
            title="回收站",
            description="各磁盘回收站中的已删除文件",
            reason="清空回收站不可撤销；请先确认里面没有仍需恢复的文件。",
            risk=CleanupRisk.REVIEW,
            icon="recycle",
            roots=_recycle_bin_roots(),
            cleanable=False,
        ),
        CleanupCategory(
            key="wechat",
            title="微信聊天附件",
            description="聊天中接收的图片、视频与文件附件",
            reason="只处理聊天附件，不包含消息数据库；建议先退出微信。"
            "删除后聊天中的媒体文件将无法从盘析恢复，需要额外确认。"
            "如需连消息数据库一起删除，展开卡片使用“彻底删除微信数据”。",
            risk=CleanupRisk.RISK,
            icon="file",
            roots=_wechat_roots(),
            cleanable=True,
        ),
    ]
    return [category for category in categories if category.roots]


class CleanupDiscovery:
    """Read-only cache discovery with cancellation and progress."""

    def __init__(
        self,
        *,
        progress_callback: ProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
        max_samples: int = 20,
        progress_interval: float = 0.12,
        parallelism: int = 4,
    ) -> None:
        self._progress_callback = progress_callback
        self._pause = pause_event or threading.Event()
        self._cancel = cancel_event or threading.Event()
        self._max_samples = max(1, int(max_samples))
        self._progress_interval = max(0.03, float(progress_interval))
        self._parallelism = max(1, min(8, int(parallelism)))
        self._progress_lock = threading.Lock()
        self._files = 0
        self._bytes = 0
        self._errors = 0
        self._started = 0.0
        self._last_progress = 0.0
        self._current_target = ""
        self._current_target_path = ""
        self._entry_tick = 0
        self._child_counts: dict[str, tuple[int, int, int]] = {}

    def discover(
        self,
        categories: list[CleanupCategory] | None = None,
    ) -> CleanupReport:
        targets = list(categories) if categories is not None else build_default_categories()
        if self._parallelism > 1 and len(targets) > 1:
            return self._discover_parallel(targets)
        return self._discover_sequential(targets)

    def _discover_sequential(self, targets: list[CleanupCategory]) -> CleanupReport:
        self._started = time.monotonic()
        started_at = datetime.now()
        self._last_progress = 0.0
        scanned_paths = 0
        for category in targets:
            self._current_target = category.title
            category.total_size = 0
            category.file_count = 0
            category.errors = 0
            category.samples = []
            if category.key == "recycle_bin":
                self._collect_recycle_bin(category)
                scanned_paths += len(category.roots)
            else:
                for root in category.roots:
                    if not os.path.isdir(root):
                        continue
                    scanned_paths += 1
                    self._walk_category(category, root)
            if category.total_size > 0:
                category.samples.sort(key=lambda sample: sample.size, reverse=True)
            self._emit_progress(force=True)
        return CleanupReport(
            categories=[category for category in targets if category.file_count > 0],
            started_at=started_at,
            duration=max(0.0, time.monotonic() - self._started),
            files_scanned=self._files,
            errors=self._errors,
            scanned_paths=scanned_paths,
        )

    def _discover_parallel(self, targets: list[CleanupCategory]) -> CleanupReport:
        """Scan independent categories concurrently.

        The categories are independent read-only trees, so this overlaps
        metadata I/O without sharing mutable counters between workers.  A
        per-category child discovery object keeps cancellation, pause and
        sample collection identical to the sequential path.
        """

        self._started = time.monotonic()
        started_at = datetime.now()
        self._last_progress = 0.0
        self._files = 0
        self._bytes = 0
        self._errors = 0
        self._child_counts = {}
        for category in targets:
            category.total_size = 0
            category.file_count = 0
            category.errors = 0
            category.samples = []

        reports: list[CleanupReport] = []
        workers = min(self._parallelism, len(targets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="diskscope-clean") as pool:
            futures = {
                pool.submit(self._scan_one_category, category): category
                for category in targets
            }
            for future in as_completed(futures):
                category = futures[future]
                try:
                    reports.append(future.result())
                except ScanCancelled:
                    for pending in futures:
                        pending.cancel()
                    raise
        self._files = sum(report.files_scanned for report in reports)
        self._bytes = sum(category.total_size for category in targets)
        self._errors = sum(report.errors for report in reports)
        self._emit_progress(force=True)
        return CleanupReport(
            categories=[category for category in targets if category.file_count > 0],
            started_at=started_at,
            duration=max(0.0, time.monotonic() - self._started),
            files_scanned=self._files,
            errors=self._errors,
            scanned_paths=sum(report.scanned_paths for report in reports),
        )

    def _scan_one_category(self, category: CleanupCategory) -> CleanupReport:
        child = CleanupDiscovery(
            progress_callback=lambda progress: self._on_child_progress(category, progress),
            pause_event=self._pause,
            cancel_event=self._cancel,
            max_samples=self._max_samples,
            progress_interval=self._progress_interval,
            parallelism=1,
        )
        return child.discover([category])

    def _on_child_progress(self, category: CleanupCategory, progress: CleanupProgress) -> None:
        now = time.monotonic()
        emit = False
        with self._progress_lock:
            self._child_counts[category.key] = (
                progress.files_scanned,
                progress.bytes_found,
                progress.errors,
            )
            self._files = sum(item[0] for item in self._child_counts.values())
            self._bytes = sum(item[1] for item in self._child_counts.values())
            self._errors = sum(item[2] for item in self._child_counts.values())
            self._current_target = category.title
            self._current_target_path = progress.current_path
            if now - self._last_progress >= self._progress_interval:
                self._last_progress = now
                emit = True
        if not emit or self._progress_callback is None:
            return
        try:
            self._progress_callback(
                CleanupProgress(
                    current_path=progress.current_path,
                    files_scanned=self._files,
                    bytes_found=self._bytes,
                    errors=self._errors,
                    current_target=category.title,
                    completed_targets=0,
                    total_targets=0,
                    elapsed=max(0.0, now - self._started),
                )
            )
        except Exception:
            logger.exception("Cleanup progress callback failed")

    def _collect_recycle_bin(self, category: CleanupCategory) -> None:
        for root in category.roots:
            self._checkpoint()
            drive = Path(root).anchor or root
            result = query_recycle_bin_size(drive)
            if result is None:
                category.errors += 1
                self._errors += 1
                continue
            size, count = result
            category.total_size += size
            category.file_count += count

    def _walk_category(self, category: CleanupCategory, root: str) -> None:
        stack = [root]
        heap: list[tuple[int, str, float]] = []
        old_threshold = time.time() - _OLD_FILE_SECONDS
        while stack:
            self._checkpoint()
            current = stack.pop()
            self._maybe_progress(current)
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        self._entry_tick += 1
                        if (self._entry_tick & 0x7F) == 0:
                            self._checkpoint()
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            self._errors += 1
                            category.errors += 1
                            continue
                        if is_dir:
                            if not category.recursive:
                                continue
                            try:
                                dir_stat = entry.stat(follow_symlinks=False)
                            except OSError:
                                self._errors += 1
                                category.errors += 1
                                continue
                            if getattr(dir_stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                                continue
                            stack.append(entry.path)
                            continue
                        try:
                            stat_result = entry.stat(follow_symlinks=False)
                        except OSError:
                            self._errors += 1
                            category.errors += 1
                            continue
                        if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        self._files += 1
                        size = max(0, int(getattr(stat_result, "st_size", 0)))
                        self._bytes += size
                        modified: float | None = None
                        if category.key == "installers":
                            suffix = os.path.splitext(entry.name)[1].lower()
                            modified = float(getattr(stat_result, "st_mtime", 0.0))
                            if suffix not in INSTALLER_AND_ARCHIVE or modified > old_threshold:
                                continue
                        category.total_size += size
                        category.file_count += 1
                        if len(heap) < self._max_samples:
                            if modified is None:
                                modified = float(getattr(stat_result, "st_mtime", 0.0))
                            heapq.heappush(heap, (size, entry.path, modified))
                        elif size > heap[0][0]:
                            if modified is None:
                                modified = float(getattr(stat_result, "st_mtime", 0.0))
                            heapq.heapreplace(heap, (size, entry.path, modified))
            except (PermissionError, OSError) as exc:
                self._errors += 1
                category.errors += 1
                logger.info("Cleanup discovery skipped %s: %s", current, exc)
        category.samples = [
            CleanupSample(path=path, size=size, modified=modified)
            for size, path, modified in sorted(heap, reverse=True)
        ]

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
        if now - self._last_progress >= self._progress_interval:
            self._current_target_path = path
            self._emit_progress(force=True, path=path)

    def _emit_progress(self, *, force: bool = False, path: str = "") -> None:
        if self._progress_callback is None:
            return
        now = time.monotonic()
        if not force and now - self._last_progress < self._progress_interval:
            return
        self._last_progress = now
        try:
            self._progress_callback(
                CleanupProgress(
                    current_path=path or getattr(self, "_current_target_path", ""),
                    files_scanned=self._files,
                    bytes_found=self._bytes,
                    errors=self._errors,
                    current_target=self._current_target,
                    completed_targets=0,
                    total_targets=0,
                    elapsed=max(0.0, now - self._started),
                )
            )
        except Exception:
            logger.exception("Cleanup progress callback failed")