"""Last-line safety checks for the cleanup executor.

The planner only emits files from known cache roots, but deletion is
irreversible enough that every file is validated again immediately before it
is handed to the Windows recycle bin.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from app.config import DATA_DIR
from core.cleanup_engine import INSTALLER_AND_ARCHIVE, _OLD_FILE_SECONDS
from core.scanner import FILE_ATTRIBUTE_REPARSE_POINT

logger = logging.getLogger(__name__)


class SafetyViolation(Exception):
    """Raised when a cleanup path fails a safety invariant."""


def _normalise(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).rstrip("\\/")


class SafetyGuard:
    def __init__(
        self,
        *,
        data_dir: str | os.PathLike[str] = DATA_DIR,
        protected_paths: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self._data_dir = _normalise(data_dir)
        self._protected = tuple(
            _normalise(path) for path in (protected_paths or []) if path
        )

    def validate(
        self,
        path: str | os.PathLike[str],
        *,
        allowed_roots: list[str] | tuple[str, ...],
        category_key: str,
    ) -> Path:
        candidate = Path(os.path.abspath(os.fspath(path)))
        normalised = _normalise(candidate)

        if category_key not in {
            "system_temp",
            "browser_cache",
            "installers",
            "dev_cache",
            "wechat",
        }:
            raise SafetyViolation(f"不允许的清理类别：{category_key}")

        if not self._is_under_any(normalised, allowed_roots):
            raise SafetyViolation("文件不在本次清理的允许根目录内")

        if normalised == self._data_dir or normalised.startswith(self._data_dir + os.sep):
            raise SafetyViolation("不允许清理盘析自身的数据目录")

        if any(
            normalised == protected or normalised.startswith(protected + os.sep)
            for protected in self._protected
        ):
            raise SafetyViolation("文件位于受保护目录")

        try:
            stat_result = os.stat(candidate, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise SafetyViolation("文件已不存在") from exc
        except OSError as exc:
            raise SafetyViolation(f"无法读取文件信息：{exc}") from exc

        if not os.path.isfile(candidate):
            raise SafetyViolation("只允许清理文件，不允许清理目录")
        if os.path.islink(candidate):
            raise SafetyViolation("不允许清理符号链接")
        if getattr(stat_result, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise SafetyViolation("不允许清理 reparse point")

        if category_key == "installers":
            suffix = candidate.suffix.lower()
            if suffix not in INSTALLER_AND_ARCHIVE:
                raise SafetyViolation("不是允许清理的安装包或压缩包类型")
            if float(getattr(stat_result, "st_mtime", 0.0)) > time.time() - _OLD_FILE_SECONDS:
                raise SafetyViolation("安装包尚未达到 30 天的整理阈值")

        return candidate

    @staticmethod
    def _is_under_any(normalised: str, roots: list[str] | tuple[str, ...]) -> bool:
        for root in roots:
            if not root:
                continue
            normalised_root = _normalise(root)
            if normalised.startswith(normalised_root + os.sep):
                return True
        return False