"""Real directory scanner.

The scanner deliberately stores directory aggregates only, not every file
record.  This keeps memory bounded on directories with hundreds of thousands
of files while still giving the analysis UI exact folder sizes and counts.
The file table reads the current folder on demand from disk.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from core.file_types import classify_extension

logger = logging.getLogger(__name__)

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_MAX_DEPTH = 512
_SYSTEM_DIRECTORY_NAMES = {
    "$recycle.bin",
    "system volume information",
    "recovery",
    "config.msi",
}


class ScanCancelled(Exception):
    """Raised internally when the user cancels an active scan."""


@dataclass(slots=True)
class ScanProgress:
    current_path: str
    files_scanned: int
    dirs_scanned: int
    bytes_found: int
    errors: int
    elapsed: float


@dataclass(slots=True)
class DirNode:
    """A directory in the scanned tree.

    ``size`` and the counts include descendants.  ``own_file_size`` contains
    only files directly inside this directory.
    """

    name: str
    path: str
    size: int = 0
    own_file_size: int = 0
    file_count: int = 0
    dir_count: int = 0
    errors: int = 0
    mtime: float = 0.0
    inaccessible: bool = False
    children: list["DirNode"] = field(default_factory=list)

    @property
    def subfolder_count(self) -> int:
        return len(self.children)

    def child_by_name(self, name: str) -> "DirNode | None":
        lowered = name.casefold()
        for child in self.children:
            if child.name.casefold() == lowered:
                return child
        return None


@dataclass(slots=True)
class ScanResult:
    root: DirNode
    files_scanned: int
    dirs_scanned: int
    total_size: int
    errors: int
    started_at: datetime
    duration: float
    cancelled: bool = False
    category_sizes: dict[str, int] = field(default_factory=dict)

    @property
    def root_path(self) -> str:
        return self.root.path


ProgressCallback = Callable[[ScanProgress], None]


def _is_reparse_point(stat_result: os.stat_result) -> bool:
    attributes = getattr(stat_result, "st_file_attributes", 0)
    return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _normalise_for_exclusion(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


class DirectoryScanner:
    """Recursive, cancellable, non-symlink-following directory scanner."""

    def __init__(
        self,
        *,
        excluded_paths: list[str] | tuple[str, ...] | None = None,
        progress_callback: ProgressCallback | None = None,
        pause_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
        progress_interval: float = 0.12,
    ) -> None:
        self._excluded = tuple(
            _normalise_for_exclusion(path)
            for path in (excluded_paths or [])
            if path
        )
        self._progress_callback = progress_callback
        self._pause_event = pause_event or threading.Event()
        self._cancel_event = cancel_event or threading.Event()
        self._progress_interval = max(0.03, float(progress_interval))

        self._files = 0
        self._dirs = 0
        self._bytes = 0
        self._errors = 0
        self._skipped_reparse = 0
        self._category_sizes: dict[str, int] = {}
        self._current_path = ""
        self._started_monotonic = 0.0
        self._last_progress_at = 0.0
        self._entry_tick = 0

    @property
    def skipped_reparse(self) -> int:
        return self._skipped_reparse

    def scan(self, root: str | os.PathLike[str]) -> ScanResult:
        root_path = os.path.abspath(os.path.expanduser(os.fspath(root)))
        if not os.path.isdir(root_path):
            raise NotADirectoryError(root_path)

        self._started_monotonic = time.monotonic()
        self._last_progress_at = 0.0
        started_at = datetime.now()
        self._current_path = root_path
        root_name = os.path.basename(root_path.rstrip("\\/")) or root_path
        root_node = DirNode(name=root_name, path=root_path)

        self._scan_directory(root_node, depth=0)
        self._sort_tree(root_node)
        self._emit_progress(root_path, force=True)

        return ScanResult(
            root=root_node,
            files_scanned=self._files,
            dirs_scanned=self._dirs,
            total_size=self._bytes,
            errors=self._errors + self._skipped_reparse,
            started_at=started_at,
            duration=max(0.0, time.monotonic() - self._started_monotonic),
            category_sizes=dict(self._category_sizes),
        )

    # ------------------------------------------------------------------
    def _scan_directory(self, node: DirNode, *, depth: int) -> None:
        self._checkpoint()
        if self._is_excluded(node.path):
            return
        if depth > _MAX_DEPTH:
            node.inaccessible = True
            self._errors += 1
            return

        self._dirs += 1
        self._current_path = node.path
        node.mtime = self._mtime(node.path)
        self._maybe_emit_progress(node.path)

        try:
            with os.scandir(node.path) as entries:
                for entry in entries:
                    self._entry_tick += 1
                    if (self._entry_tick & 0x7F) == 0:
                        self._checkpoint()
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        node.errors += 1
                        self._errors += 1
                        logger.debug("Cannot stat %s: %s", entry.path, exc)
                        continue

                    if _is_reparse_point(stat_result):
                        self._skipped_reparse += 1
                        continue

                    try:
                        is_directory = entry.is_dir(follow_symlinks=False)
                    except OSError as exc:
                        node.errors += 1
                        self._errors += 1
                        logger.debug("Cannot classify %s: %s", entry.path, exc)
                        continue

                    if is_directory:
                        if self._is_excluded(entry.path):
                            continue
                        if entry.name.casefold() in _SYSTEM_DIRECTORY_NAMES:
                            continue
                        child = DirNode(name=entry.name, path=entry.path)
                        self._scan_directory(child, depth=depth + 1)
                        node.children.append(child)
                        node.size += child.size
                        node.file_count += child.file_count
                        node.dir_count += 1 + child.dir_count
                        node.errors += child.errors
                    else:
                        size = max(0, int(getattr(stat_result, "st_size", 0)))
                        node.size += size
                        node.own_file_size += size
                        node.file_count += 1
                        self._files += 1
                        self._bytes += size
                        extension = os.path.splitext(entry.name)[1]
                        category = classify_extension(extension)
                        self._category_sizes[category] = (
                            self._category_sizes.get(category, 0) + size
                        )
        except PermissionError as exc:
            node.inaccessible = True
            node.errors += 1
            self._errors += 1
            logger.info("Permission denied while scanning %s: %s", node.path, exc)
        except OSError as exc:
            node.inaccessible = True
            node.errors += 1
            self._errors += 1
            logger.info("Cannot scan directory %s: %s", node.path, exc)

        self._current_path = node.path
        self._maybe_emit_progress(node.path)

    # ------------------------------------------------------------------
    def _checkpoint(self) -> None:
        if self._cancel_event.is_set():
            raise ScanCancelled()
        while self._pause_event.is_set():
            if self._cancel_event.is_set():
                raise ScanCancelled()
            time.sleep(0.05)
        if self._cancel_event.is_set():
            raise ScanCancelled()

    def _is_excluded(self, path: str) -> bool:
        if not self._excluded:
            return False
        normalised = _normalise_for_exclusion(path)
        for excluded in self._excluded:
            if normalised == excluded or normalised.startswith(excluded + os.sep):
                return True
        return False

    @staticmethod
    def _mtime(path: str) -> float:
        try:
            return float(os.stat(path, follow_symlinks=False).st_mtime)
        except OSError:
            return 0.0

    def _maybe_emit_progress(self, path: str) -> None:
        now = time.monotonic()
        if now - self._last_progress_at >= self._progress_interval:
            self._emit_progress(path)

    def _emit_progress(self, path: str, *, force: bool = False) -> None:
        if self._progress_callback is None:
            return
        now = time.monotonic()
        if not force and now - self._last_progress_at < self._progress_interval:
            return
        self._last_progress_at = now
        try:
            self._progress_callback(
                ScanProgress(
                    current_path=path,
                    files_scanned=self._files,
                    dirs_scanned=self._dirs,
                    bytes_found=self._bytes,
                    errors=self._errors + self._skipped_reparse,
                    elapsed=max(0.0, now - self._started_monotonic),
                )
            )
        except Exception:
            # A consumer-side error must never abort a filesystem scan.
            logger.exception("Progress callback failed")

    @staticmethod
    def _sort_tree(node: DirNode) -> None:
        node.children.sort(key=lambda child: (-child.size, child.name.casefold()))
        for child in node.children:
            DirectoryScanner._sort_tree(child)


def flatten_tree(root: DirNode, *, limit: int | None = None) -> list[DirNode]:
    """Depth-first list of directories, useful for search and tests."""

    result: list[DirNode] = []
    stack = [root]
    while stack:
        node = stack.pop()
        result.append(node)
        if limit is not None and len(result) >= limit:
            break
        stack.extend(reversed(node.children))
    return result