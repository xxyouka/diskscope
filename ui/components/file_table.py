"""Virtualized file table with real search, filtering and sorting."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QTableView

from app.formatting import format_size
from core.file_analyzer import (
    ARCHIVE_EXTENSIONS,
    IMAGE_EXTENSIONS,
    INSTALLER_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FileEntry,
    icon_for_file,
)
from ui.components.icons import icon_pixmap
from ui.styles.palette import Palette

_SORT_ROLE = Qt.ItemDataRole.UserRole + 21


class FileTableModel(QAbstractTableModel):
    COLUMNS = ("名称", "路径", "类型", "大小", "修改时间")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: list[FileEntry] = []
        self._icons: dict[str, QIcon] = {}
        colors = {
            "folder": "#7D776C",
            "code": "#6B7264",
            "image": "#8B7D68",
            "video": "#7D7465",
            "audio": "#7E7568",
            "archive": "#7B7164",
            "installer": "#857A69",
            "document": "#726D64",
            "database": "#74786E",
            "other": "#938D83",
        }
        for kind, color in colors.items():
            self._icons[kind] = QIcon(
                icon_pixmap(icon_for_file_name(kind), 16, color)
            )
        self._folder_font = QFont(QApplication.font())
        self._folder_font.setWeight(QFont.Weight.DemiBold)

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section] if 0 <= section < len(self.COLUMNS) else ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if section in (3, 4):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return entry.name
            if column == 1:
                return entry.path
            if column == 2:
                return entry.type_label
            if column == 3:
                return format_size(entry.size)
            if column == 4:
                return self._format_time(entry.modified)
        elif role == Qt.ItemDataRole.DecorationRole and column == 0:
            return self._icons.get(entry.category, self._icons["other"])
        elif role == Qt.ItemDataRole.ToolTipRole:
            if entry.inaccessible:
                return f"{entry.path}\n无法读取此文件的信息"
            if entry.ignored:
                return f"{entry.path}\n已在忽略列表中，因此未统计大小"
            if entry.is_link:
                return f"{entry.path}\n链接目录（扫描时不会跟随）"
            return entry.path
        elif role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.ForegroundRole and column == 1:
            return QColor(Palette.MUTED)
        elif role == Qt.ItemDataRole.FontRole and column == 0 and entry.is_dir:
            return self._folder_font
        elif role == _SORT_ROLE:
            if column == 0:
                return entry.name.casefold()
            if column == 1:
                return entry.path.casefold()
            if column == 2:
                return entry.type_label
            if column == 3:
                return entry.size
            if column == 4:
                return entry.modified
        return None

    def set_entries(self, entries: list[FileEntry]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> FileEntry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    @staticmethod
    def _format_time(timestamp: float) -> str:
        if not timestamp:
            return "—"
        try:
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return "—"


class FileFilterProxy(QSortFilterProxyModel):
    FILTER_ALL = "all"
    FILTER_LARGE = "large"
    FILTER_RECENT = "recent"
    FILTER_INSTALLER = "installer"
    FILTER_VIDEO = "video"
    FILTER_IMAGE = "image"
    FILTER_ARCHIVE = "archive"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setSortRole(_SORT_ROLE)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._search = ""
        self._filter = self.FILTER_ALL
        self._now = datetime.now().timestamp()

    def set_search_text(self, text: str) -> None:
        self._search = (text or "").strip().casefold()
        self.invalidateFilter()

    def set_filter(self, key: str) -> None:
        self._filter = key
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, FileTableModel):
            return True
        entry = model.entry_at(source_row)
        if entry is None:
            return False
        if self._search:
            haystack = f"{entry.name}\n{entry.path}".casefold()
            if self._search not in haystack:
                return False

        key = self._filter
        if key == self.FILTER_ALL:
            return True
        if key == self.FILTER_LARGE:
            return entry.size >= 100 * 1024 * 1024
        if key == self.FILTER_RECENT:
            return entry.modified >= self._now - 7 * 24 * 3600
        if entry.is_dir:
            return False
        extension = entry.extension.lower()
        if key == self.FILTER_INSTALLER:
            return extension in INSTALLER_EXTENSIONS
        if key == self.FILTER_VIDEO:
            return extension in VIDEO_EXTENSIONS
        if key == self.FILTER_IMAGE:
            return extension in IMAGE_EXTENSIONS
        if key == self.FILTER_ARCHIVE:
            return extension in ARCHIVE_EXTENSIONS
        return True


def icon_for_file_name(kind: str) -> str:
    return {
        "folder": "folder",
        "code": "code",
        "image": "image",
        "video": "video",
        "archive": "zip",
        "installer": "download",
        "document": "file",
        "database": "database",
    }.get(kind, "file")


class FileTableView(QTableView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fileTable")
        self._source_model = FileTableModel(self)
        self._proxy = FileFilterProxy(self)
        self._proxy.setSourceModel(self._source_model)
        self.setModel(self._proxy)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(33)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(54)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(2, 64)
        self.setColumnWidth(3, 84)
        self.setColumnWidth(4, 126)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    @property
    def proxy(self) -> FileFilterProxy:
        return self._proxy

    @property
    def source_model(self) -> FileTableModel:
        return self._source_model

    def set_entries(self, entries: list[FileEntry]) -> None:
        self._source_model.set_entries(entries)

    def selected_entries(self) -> list[FileEntry]:
        rows = sorted({index.row() for index in self.selectionModel().selectedRows()})
        entries: list[FileEntry] = []
        for proxy_row in rows:
            source_index = self._proxy.mapToSource(self._proxy.index(proxy_row, 0))
            entry = self._source_model.entry_at(source_index.row())
            if entry is not None:
                entries.append(entry)
        return entries

    def entry_for_index(self, index: QModelIndex) -> FileEntry | None:
        if not index.isValid():
            return None
        source_index = self._proxy.mapToSource(index)
        return self._source_model.entry_at(source_index.row())