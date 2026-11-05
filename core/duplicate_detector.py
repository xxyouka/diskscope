"""Duplicate-file detection: size prefilter, quick hash, then full SHA-256.

The detector never deletes or modifies files.  It only opens files for reading
and is cancellation-aware so it can run from a background worker.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.scanner import FILE_ATTRIBUTE_REPARSE_POINT, ScanCancelled

logger = logging.getLogger(__name__)

_QUICK_CHUNK = 64 * 1024
_FULL_CHUNK = 1024 * 1024
_SYSTEM_DIR_NAMES = {"$recycle.bin", "system volume information", "recovery"}


@dataclass(slots=True)
class DuplicateFile:
    path: str
    size: int
    modified: float


@dataclass(slots=True)
class DuplicateGroup:
    digest: str
    size: int
    files: list[DuplicateFile] = field(default_factory=list)

    @property
    def wasted_size(self) -> int:
        return self.size * max(0, len(self.files) - 1)


@dataclass(slots=True)
class DuplicateProgress:
    stage: str
    current_path: str
    files_seen: int
    candidate_files: int
    hashed_files: int
    groups_found: int
    bytes_hashed: int
    elapsed: float


@dataclass(slots=True)
class DuplicateReport:
    root: str
    groups: list[DuplicateGroup]
    files_seen: int
    candidate_files: int
    hashed_files: int
    bytes_hashed: int
    errors: int
    started_at: datetime
    duration: float

    @property
    def total_files(self) -> int:
        return sum(len(group.files) for group in self.groups)

    @property
    def wasted_size(self) -> int:
        return sum(group.wasted_size for group in self.groups)


ProgressCallback = Callable[[DuplicateProgress], None]


def _normalised(path: str) -> str:
    return os.path.normcase(os.path.abspath(path)).rstrip("\\/")


class DuplicateDetector:
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
            _normalised(path) for path in (excluded_paths or []) if path
        )
        self._progress_callback = progress_callback
        self._pause = pause_event or threading.Event()
        self._cancel = cancel_event or threading.Event()
        self._progress_interval = max(0.03, float(progress_interval))
        self._started = 0.0
        self._last_progress = 0.0
        self._files_seen = 0
        self._candidate_files = 0
        self._hashed_files = 0
        self._bytes_hashed = 0
        self._errors = 0
        self._stage = "collect"
        self._current = ""

    def find(self, root: str | os.PathLike[str]) -> DuplicateReport:
        root_path = os.path.abspath(os.path.expanduser(os.fspath(root)))
        if not os.path.isdir(root_path):
            raise NotADirectoryError(root_path)
        self._started = time.monotonic()
        self._last_progress = 0.0
        started_at = datetime.now()
        by_size: dict[int, list[DuplicateFile]] = {}
        self._collect_files(root_path, by_size)
        groups: list[DuplicateGroup] = []
        size_groups = [files for files in by_size.values() if len(files) > 1]
        self._candidate_files = sum(len(files) for files in size_groups)
        self._stage = "quick"

        for files in size_groups:
            self._checkpoint()
            quick_buckets: dict[str, list[DuplicateFile]] = {}
            for file in files:
                self._checkpoint()
                self._current = file.path
                digest = self._quick_hash(file)
                if digest is not None:
                    quick_buckets.setdefault(digest, []).append(file)
                self._hashed_files += 1
                self._maybe_progress(file.path)
            self._stage = "full"
            for quick_files in quick_buckets.values():
                if len(quick_files) < 2:
                    continue
                full_buckets: dict[str, list[DuplicateFile]] = {}
                for file in quick_files:
                    self._checkpoint()
                    self._current = file.path
                    digest = self._full_hash(file)
                    if digest is not None:
                        full_buckets.setdefault(digest, []).append(file)
                    self._hashed_files += 1
                    self._maybe_progress(file.path)
                for digest, same_files in full_buckets.items():
                    if len(same_files) >= 2:
                        groups.append(
                            DuplicateGroup(
                                digest=digest,
                                size=same_files[0].size,
                                files=sorted(same_files, key=lambda item: item.path.casefold()),
                            )
                        )
        groups.sort(key=lambda group: group.wasted_size, reverse=True)
        self._stage = "done"
        self._emit_progress(force=True)
        return DuplicateReport(
            root=root_path,
            groups=groups,
            files_seen=self._files_seen,
            candidate_files=self._candidate_files,
            hashed_files=self._hashed_files,
            bytes_hashed=self._bytes_hashed,
            errors=self._errors,
            started_at=started_at,
            duration=max(0.0, time.monotonic() - self._started),
        )

    # ------------------------------------------------------------------
    def _collect_files(self, root: str, by_size: dict[int, list[DuplicateFile]]) -> None:
        stack = [root]
        while stack:
            self._checkpoint()
            current = stack.pop()
            self._current = current
            self._maybe_progress(current)
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        self._checkpoint()
                        try:
                            stat_result = entry.stat(follow_symlinks=False)
                        except OSError:
                            self._errors += 1
                            continue
                        if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                        except OSError:
                            self._errors += 1
                            continue
                        if is_dir:
                            if entry.name.casefold() in _SYSTEM_DIR_NAMES:
                                continue
                            if self._is_excluded(entry.path):
                                continue
                            stack.append(entry.path)
                            continue
                        size = int(getattr(stat_result, "st_size", 0))
                        self._files_seen += 1
                        if size <= 0:
                            continue
                        by_size.setdefault(size, []).append(
                            DuplicateFile(
                                path=entry.path,
                                size=size,
                                modified=float(getattr(stat_result, "st_mtime", 0.0)),
                            )
                        )
            except OSError as exc:
                self._errors += 1
                logger.debug("Duplicate scan skipped %s: %s", current, exc)

    def _quick_hash(self, file: DuplicateFile) -> str | None:
        try:
            digest = hashlib.sha256()
            digest.update(str(file.size).encode("ascii"))
            with open(file.path, "rb") as handle:
                head = handle.read(_QUICK_CHUNK)
                digest.update(head)
                self._bytes_hashed += len(head)
                if file.size > _QUICK_CHUNK:
                    handle.seek(max(0, file.size - _QUICK_CHUNK))
                    tail = handle.read(_QUICK_CHUNK)
                    digest.update(tail)
                    self._bytes_hashed += len(tail)
            return digest.hexdigest()
        except OSError as exc:
            self._errors += 1
            logger.debug("Quick hash failed for %s: %s", file.path, exc)
            return None

    def _full_hash(self, file: DuplicateFile) -> str | None:
        try:
            digest = hashlib.sha256()
            with open(file.path, "rb") as handle:
                while True:
                    self._checkpoint()
                    chunk = handle.read(_FULL_CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    self._bytes_hashed += len(chunk)
            return digest.hexdigest()
        except OSError as exc:
            self._errors += 1
            logger.debug("Full hash failed for %s: %s", file.path, exc)
            return None

    def _is_excluded(self, path: str) -> bool:
        if not self._excluded:
            return False
        normalised = _normalised(path)
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
        if now - self._last_progress >= self._progress_interval:
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
                DuplicateProgress(
                    stage=self._stage,
                    current_path=path or self._current,
                    files_seen=self._files_seen,
                    candidate_files=self._candidate_files,
                    hashed_files=self._hashed_files,
                    groups_found=0,
                    bytes_hashed=self._bytes_hashed,
                    elapsed=max(0.0, now - self._started),
                )
            )
        except Exception:
            logger.exception("Duplicate progress callback failed")