"""Installed-software page: discover Windows programs, launch official uninstallers."""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, split_size
from core.software_manager import (
    InstalledSoftware,
    launch_uninstall,
    open_install_location,
    open_windows_apps,
    read_installed_software,
)
from ui.components.common import (
    Divider,
    IconLabel,
    Pill,
    SectionHeader,
    StatTile,
    SurfaceCard,
)
from ui.components.icons import make_icon
from ui.pages.base_page import BasePage, page_heading
from ui.styles.palette import Palette

logger = logging.getLogger(__name__)

_LARGE_SOFTWARE = 100 * 1024 * 1024


class SoftwareTableModel(QAbstractTableModel):
    COLUMNS = ("软件", "发布者", "大小")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._all: list[InstalledSoftware] = []
        self._items: list[InstalledSoftware] = []
        self._search = ""
        self._filter = "all"

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section] if 0 <= section < 3 else ""
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return item.name
            if column == 1:
                return item.publisher
            if column == 2:
                return format_capacity(item.estimated_size) if item.estimated_size else "—"
        elif role == Qt.ItemDataRole.ToolTipRole:
            return f"{item.name}\n{item.publisher}\n版本 {item.version}"
        elif role == Qt.ItemDataRole.TextAlignmentRole and column == 2:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif role == Qt.ItemDataRole.FontRole and column == 0:
            font = QFont()
            font.setWeight(QFont.Weight.DemiBold)
            return font
        return None

    def set_items(self, items: list[InstalledSoftware]) -> None:
        self._all = list(items)
        self._apply()

    def set_search(self, text: str) -> None:
        self._search = text.strip().casefold()
        self._apply()

    def set_filter(self, key: str) -> None:
        self._filter = key
        self._apply()

    def item_at(self, row: int) -> InstalledSoftware | None:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    @property
    def visible_count(self) -> int:
        return len(self._items)

    @property
    def total_count(self) -> int:
        return len(self._all)

    def _apply(self) -> None:
        items = self._all
        if self._search:
            items = [
                item
                for item in items
                if self._search in item.name.casefold()
                or self._search in item.publisher.casefold()
            ]
        if self._filter == "uninstallable":
            items = [item for item in items if item.can_uninstall]
        elif self._filter == "large":
            items = [item for item in items if item.estimated_size >= _LARGE_SOFTWARE]
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()


class SoftwarePage(BasePage):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._software: list[InstalledSoftware] = []
        self._selected: InstalledSoftware | None = None
        self._last_refresh = 0.0
        self._loading = False
        self._build()
        QTimer.singleShot(80, self.refresh)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 27, 34, 28)
        outer.setSpacing(18)
        self.heading_pill = Pill("读取中", variant="muted")
        outer.addWidget(
            page_heading(
                "软件卸载",
                "读取 Windows 已安装程序，调用软件自带的卸载程序；不直接删除安装目录。",
                eyebrow="SOFTWARE",
                trailing=self.heading_pill,
            )
        )

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(14)
        self.stat_total = StatTile("已安装程序", "0", "个")
        self.stat_uninstallable = StatTile("可启动卸载", "0", "个")
        self.stat_size = StatTile("估算占用", "0", "B")
        for caption, tile, icon in (
            ("已安装程序", self.stat_total, "layers"),
            ("可启动卸载", self.stat_uninstallable, "broom"),
            ("估算占用", self.stat_size, "database"),
        ):
            card = SurfaceCard(variant="normal", margins=(20, 15, 20, 14), spacing=4)
            card.setMinimumHeight(102)
            card.body.addWidget(IconLabel(icon, size=17, color=Palette.MUTED))
            card.body.addWidget(tile)
            stats.addWidget(card, 1)
        outer.addLayout(stats)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)

        listing = SurfaceCard(variant="normal", margins=(18, 17, 18, 15), spacing=9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(9)
        head.addWidget(
            SectionHeader(
                "已安装软件",
                "数据来自 Windows 卸载注册表，按估算占用空间排序。",
            ),
            1,
        )
        self.refresh_button = QPushButton("刷新列表")
        self.refresh_button.setObjectName("quietButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        head.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        listing.body.addLayout(head)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_field = QLineEdit()
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("搜索软件或发布者…")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.addAction(
            make_icon("search", Palette.MUTED, 15),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_field.textChanged.connect(self._on_search)
        search_row.addWidget(self.search_field, 1)
        self.result_count = QLabel("0 / 0")
        self.result_count.setObjectName("subtleText")
        search_row.addWidget(self.result_count, 0)
        listing.body.addLayout(search_row)

        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setSpacing(4)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for key, label in (("all", "全部"), ("uninstallable", "可卸载"), ("large", "大体积")):
            button = QPushButton(label)
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._filter_group.addButton(button)
            filters.addWidget(button)
            if key == "all":
                button.setChecked(True)
        filters.addStretch(1)
        listing.body.addLayout(filters)

        self.model = SoftwareTableModel(self)
        self.table = QTableView()
        self.table.setObjectName("fileTable")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(39)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(2, 94)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_changed)
        listing.body.addWidget(self.table, 1)

        note = QLabel(
            "卸载由厂商或 Windows 卸载程序完成；盘析不会直接删除安装目录。"
            "Microsoft Store 应用请使用「打开 Windows 应用列表」。"
        )
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        listing.body.addWidget(note)
        content.addWidget(listing, 1)

        detail = SurfaceCard(variant="normal", margins=(19, 17, 19, 16), spacing=10)
        detail.setFixedWidth(350)
        detail_head = QHBoxLayout()
        detail_head.setContentsMargins(0, 0, 0, 0)
        detail_head.addWidget(SectionHeader("软件详情", "确认发布者与卸载方式"), 1)
        detail.body.addLayout(detail_head)
        detail.body.addWidget(Divider())
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self._build_detail_empty())
        self.detail_stack.addWidget(self._build_detail_view())
        detail.body.addWidget(self.detail_stack, 1)
        self.windows_apps_button = QPushButton("打开 Windows 应用列表")
        self.windows_apps_button.setObjectName("quietButton")
        self.windows_apps_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.windows_apps_button.clicked.connect(self._open_windows_apps)
        detail.body.addWidget(self.windows_apps_button)
        content.addWidget(detail, 0)

        outer.addLayout(content, 1)

    def _build_detail_empty(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 28, 12, 28)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            IconLabel("layers", size=28, color="#9A9389"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        title = QLabel("选择一个软件")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        body = QLabel("左侧列表中选择软件后，可查看发布者、版本、安装位置并启动官方卸载程序。")
        body.setObjectName("emptyBody")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch(1)
        return page

    def _build_detail_view(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        icon = QWidget()
        icon.setFixedSize(42, 42)
        icon.setStyleSheet("background: #EDE7DD; border-radius: 12px;")
        icon_layout = QVBoxLayout(icon)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("layers", size=20, color=Palette.INK_SOFT))
        head.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        self.detail_name = QLabel("—")
        self.detail_name.setObjectName("sectionTitle")
        self.detail_name.setWordWrap(True)
        head.addWidget(self.detail_name, 1)
        layout.addLayout(head)
        self.detail_publisher = QLabel("—")
        self.detail_publisher.setObjectName("mutedText")
        self.detail_publisher.setWordWrap(True)
        layout.addWidget(self.detail_publisher)
        layout.addWidget(Divider())
        self.detail_version = self._detail_row(layout, "版本")
        self.detail_size = self._detail_row(layout, "占用空间")
        self.detail_date = self._detail_row(layout, "安装日期")
        self.detail_location = self._detail_row(layout, "安装位置")
        warning = QLabel(
            "卸载会打开软件自带的卸载向导，可能需要管理员权限。"
            "请按向导完成，盘析不会直接删除安装目录。"
        )
        warning.setObjectName("subtleText")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addStretch(1)
        self.uninstall_button = QPushButton("启动卸载程序")
        self.uninstall_button.setObjectName("primaryButton")
        self.uninstall_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_button.clicked.connect(self._confirm_uninstall)
        layout.addWidget(self.uninstall_button)
        self.location_button = QPushButton("打开安装位置")
        self.location_button.setObjectName("secondaryButton")
        self.location_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.location_button.clicked.connect(self._open_location)
        layout.addWidget(self.location_button)
        return page

    @staticmethod
    def _detail_row(layout: QVBoxLayout, caption: str) -> QLabel:
        row = QVBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(1)
        label = QLabel(caption)
        label.setObjectName("subtleText")
        row.addWidget(label)
        value = QLabel("—")
        value.setObjectName("rowMeta")
        value.setWordWrap(True)
        row.addWidget(value)
        layout.addLayout(row)
        return value

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._loading and time.monotonic() - self._last_refresh > 20:
            QTimer.singleShot(0, self.refresh)

    def refresh(self) -> None:
        if self._loading:
            return
        self._loading = True
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("读取中…")
        try:
            software = read_installed_software()
        except Exception:
            logger.exception("Could not read installed software")
            software = []
        self._software = software
        self._last_refresh = time.monotonic()
        self.model.set_items(software)
        total_size = sum(item.estimated_size for item in software)
        self.stat_total.set_value(str(len(software)), "个")
        uninstallable = sum(1 for item in software if item.can_uninstall)
        self.stat_uninstallable.set_value(str(uninstallable), "个")
        number, unit = split_size(total_size)
        self.stat_size.set_value(number, unit)
        self.heading_pill.setText(f"{len(software)} 个程序")
        self.result_count.setText(f"{self.model.visible_count} / {len(software)}")
        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("刷新列表")
        self._loading = False
        if software:
            self.table.selectRow(0)
            self._show_detail(self.model.item_at(0))
        else:
            self._show_detail(None)
            self.detail_stack.setCurrentIndex(0)

    def _on_search(self, text: str) -> None:
        self.model.set_search(text)
        self.result_count.setText(f"{self.model.visible_count} / {self.model.total_count}")
        self._select_first()

    def _set_filter(self, key: str) -> None:
        self.model.set_filter(key)
        self.result_count.setText(f"{self.model.visible_count} / {self.model.total_count}")
        self._select_first()

    def _select_first(self) -> None:
        if self.model.rowCount() > 0:
            self.table.selectRow(0)
            self._show_detail(self.model.item_at(0))
        else:
            self._show_detail(None)
            self.detail_stack.setCurrentIndex(0)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        self._show_detail(self.model.item_at(current.row()) if current.isValid() else None)

    def _show_detail(self, software: InstalledSoftware | None) -> None:
        self._selected = software
        if software is None:
            self.detail_stack.setCurrentIndex(0)
            return
        self.detail_stack.setCurrentIndex(1)
        self.detail_name.setText(software.name)
        self.detail_publisher.setText(software.publisher)
        self.detail_version.setText(software.version)
        self.detail_size.setText(
            format_capacity(software.estimated_size) if software.estimated_size else "未知"
        )
        self.detail_date.setText(software.install_date_display)
        self.detail_location.setText(software.install_location or "未记录")
        self.detail_location.setToolTip(software.install_location)
        self.location_button.setEnabled(
            bool(software.install_location) and os.path.isdir(software.install_location)
        )
        self.uninstall_button.setEnabled(software.can_uninstall)
        self.uninstall_button.setToolTip(software.uninstall_string)
        self.uninstall_button.setText(
            "启动卸载程序" if software.can_uninstall else "没有可用卸载命令"
        )

    def _confirm_uninstall(self) -> None:
        software = self._selected
        if software is None or not software.can_uninstall:
            return
        box = QMessageBox(self)
        box.setWindowTitle("启动卸载程序")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"卸载「{software.name}」？")
        box.setInformativeText(
            f"发布者：{software.publisher}\n"
            f"版本：{software.version}\n"
            f"估算占用："
            f"{format_capacity(software.estimated_size) if software.estimated_size else '未知'}\n\n"
            "将打开该软件注册的官方卸载程序，可能需要管理员权限。"
            "盘析不会直接删除安装目录、注册表或用户数据。"
        )
        launch = box.addButton("启动卸载程序", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        if box.clickedButton() is not launch:
            return
        ok, error = launch_uninstall(software)
        if not ok:
            QMessageBox.critical(self, "无法启动卸载程序", error)
            return
        self._show_toast(f"已启动「{software.name}」的卸载程序")
        QTimer.singleShot(2500, self.refresh)

    def _open_location(self) -> None:
        software = self._selected
        if software is not None and open_install_location(software.install_location):
            return
        self._show_toast("没有找到该软件的安装目录", icon="warning")

    def _open_windows_apps(self) -> None:
        if not open_windows_apps():
            self._show_toast("无法打开 Windows 应用列表", icon="warning")

    def _show_toast(self, text: str, *, icon: str = "check") -> None:
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast(text, icon=icon)