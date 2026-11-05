"""Immutable product-level constants.

Keeping these values in one place avoids magic strings leaking through the UI
and the storage engine.  Anything that may change at runtime belongs in
``app.config`` instead.
"""

from __future__ import annotations

from enum import IntEnum

APP_NAME = "盘析"
APP_NAME_EN = "DiskScope"
APP_VERSION = "0.7.0"
APP_ORGANIZATION = "DiskScope"
APP_DESCRIPTION = "一款专注于磁盘空间可视化、文件分析与安全清理的 Windows 桌面工具。"


class Page(IntEnum):
    """Top-level navigation destinations."""

    DASHBOARD = 0
    CLEANUP = 1
    ANALYSIS = 2
    SOFTWARE = 3
    HISTORY = 4
    SETTINGS = 5


PAGE_TITLES: dict[Page, str] = {
    Page.DASHBOARD: "磁盘概览",
    Page.CLEANUP: "清理建议",
    Page.ANALYSIS: "文件分析",
    Page.SOFTWARE: "软件卸载",
    Page.HISTORY: "历史记录",
    Page.SETTINGS: "设置",
}

# Friendly, deterministic names for the common Windows volume layouts.  The
# real volume label is still shown when it adds useful information.
DRIVE_ROLE_NAMES: dict[str, str] = {
    "C": "系统盘",
    "D": "软件盘",
    "E": "数据盘",
    "F": "备份盘",
}

# Reserved system folders that the scanner must never descend into by
# default.  They are either reparse points or protected OS components.
SYSTEM_SCAN_EXCLUSIONS: tuple[str, ...] = (
    "System Volume Information",
    "$Recycle.Bin",
    "Recovery",
    "Windows\\CSC",
    "Windows\\WinSxS",
    "Windows\\System32\\driverstore",
)

# File operations in this product are deliberately conservative.  The
# current stage ships the policy as data so later cleanup stages cannot
# accidentally default to permanent deletion.
DEFAULT_DELETE_MODE = "recycle_bin"