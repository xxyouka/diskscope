"""On-demand folder listing and file classification for the analysis page.

The full scan is directory-only.  File records are read lazily for the folder
currently in view, which is both faster and more memory-efficient than storing
every file path for a multi-hundred-thousand-file volume.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from core.file_types import (
    ARCHIVE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    CODE_EXTENSIONS,
    DATABASE_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    IMAGE_EXTENSIONS,
    INSTALLER_EXTENSIONS,
    VIDEO_EXTENSIONS,
    WEB_EXTENSIONS,
    category_label,
    classify_extension,
)
from core.scanner import DirNode, FILE_ATTRIBUTE_REPARSE_POINT

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FileEntry:
    name: str
    path: str
    is_dir: bool
    size: int
    modified: float
    extension: str
    type_label: str
    category: str
    inaccessible: bool = False
    is_link: bool = False
    ignored: bool = False


_SHORT_TYPE_LABELS = {
    "code": "代码",
    "document": "文档",
    "image": "图片",
    "video": "视频",
    "audio": "音频",
    "archive": "压缩包",
    "installer": "安装包",
    "web": "网页",
    "database": "数据库",
    "other": "文件",
}


def category_for_extension(extension: str) -> str:
    if not extension:
        return "文件"
    return _SHORT_TYPE_LABELS.get(classify_extension(extension), "文件")


def icon_for_file(entry: FileEntry) -> str:
    if entry.is_dir:
        return "folder"
    mapping = {
        "code": "code",
        "image": "image",
        "video": "video",
        "archive": "zip",
        "installer": "download",
        "document": "file",
        "database": "database",
    }
    return mapping.get(entry.category, "file")


def extension_label(entry: FileEntry) -> str:
    if entry.is_dir:
        return "文件夹"
    if entry.extension:
        return entry.extension.lstrip(".").upper()
    return "文件"


class FileAnalyzer:
    """List a folder on demand and enrich it with scan tree aggregates."""

    def list_entries(
        self,
        node: DirNode,
        *,
        excluded_paths: list[str] | tuple[str, ...] | None = None,
    ) -> list[FileEntry]:
        child_map = {child.name.casefold(): child for child in node.children}
        excluded = tuple(
            os.path.normcase(os.path.abspath(path))
            for path in (excluded_paths or [])
            if path
        )
        entries: list[FileEntry] = []
        try:
            scandir_entries = os.scandir(node.path)
        except OSError as exc:
            logger.info("Cannot list folder %s: %s", node.path, exc)
            return entries

        with scandir_entries:
            for entry in scandir_entries:
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                except OSError:
                    entries.append(
                        FileEntry(
                            name=entry.name,
                            path=entry.path,
                            is_dir=False,
                            size=0,
                            modified=0.0,
                            extension=Path(entry.name).suffix,
                            type_label="不可访问",
                            category="other",
                            inaccessible=True,
                        )
                    )
                    continue

                is_link = bool(
                    getattr(stat_result, "st_file_attributes", 0)
                    & FILE_ATTRIBUTE_REPARSE_POINT
                )
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False

                extension = Path(entry.name).suffix
                ignored = False
                if is_dir:
                    child = child_map.get(entry.name.casefold())
                    size = int(child.size) if child is not None else 0
                    category = "folder"
                    normalised = os.path.normcase(os.path.abspath(entry.path))
                    ignored = any(
                        normalised == path or normalised.startswith(path + os.sep)
                        for path in excluded
                    )
                    if ignored:
                        type_label = "已忽略"
                    elif child is None:
                        type_label = "未扫描"
                    else:
                        type_label = "文件夹"
                else:
                    size = max(0, int(getattr(stat_result, "st_size", 0)))
                    category = classify_extension(extension)
                    type_label = category_for_extension(extension)

                entries.append(
                    FileEntry(
                        name=entry.name,
                        path=entry.path,
                        is_dir=is_dir,
                        size=size,
                        modified=float(getattr(stat_result, "st_mtime", 0.0)),
                        extension=extension,
                        type_label=type_label,
                        category=category,
                        is_link=is_link,
                        ignored=ignored,
                    )
                )

        entries.sort(key=lambda item: (not item.is_dir, -item.size, item.name.casefold()))
        return entries


def human_node_date(node: DirNode) -> str:
    if not node.mtime:
        return "—"
    try:
        return datetime.fromtimestamp(node.mtime).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "—"