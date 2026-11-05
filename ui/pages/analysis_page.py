"""File analysis powered by the real background directory scanner."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QModelIndex, QProcess, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.config import AppSettings, MIN_WINDOW_HEIGHT
from app.formatting import format_capacity, format_percent
from core.disk_manager import DiskManager, VolumeInfo
from core.file_analyzer import FileAnalyzer, FileEntry, human_node_date
from core.folder_knowledge import FolderInsight, describe_folder
from core.scanner import DirNode, ScanProgress, ScanResult
from services.scan_cache_service import ScanCacheMeta, ScanCacheService
from ui.components.common import Divider, IconLabel, Pill, SectionHeader, SurfaceCard
from ui.components.dialogs import ScanReportDialog
from ui.components.disk_row import DiskRow
from ui.components.duplicate_dialog import DuplicateFinderDialog
from ui.components.elided_label import ElidedLabel
from ui.components.file_table import FileTableView
from ui.components.folder_guide import CommonFoldersDialog, FolderGuideDialog
from ui.components.folder_tree import FolderTree
from ui.components.folder_treemap import FolderTreemap
from ui.components.icons import make_icon
from ui.components.usage_bar import UsageBar
from ui.pages.base_page import BasePage, page_heading
from ui.styles.palette import Palette
from workers.cache_worker import CacheLoadWorker
from workers.scan_worker import ScanWorker

logger = logging.getLogger(__name__)

_FILTERS = (
    ("all", "全部", "layers"),
    ("large", "大文件", "chart"),
    ("recent", "最近新增", "clock"),
    ("installer", "安装包", "download"),
    ("video", "视频", "video"),
    ("image", "图片", "image"),
    ("archive", "压缩包", "zip"),
    ("duplicates", "重复文件", "layers"),
)


class _EmptyTree(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            IconLabel("folder", size=26, color="#A19B91"),
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        label = QLabel("扫描后显示目录树")
        label.setObjectName("mutedText")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)


class AnalysisPage(BasePage):
    refreshRequested = Signal()
    overviewRequested = Signal()
    cleanupRequested = Signal()
    softwareRequested = Signal()

    def __init__(
        self,
        disk_manager: DiskManager,
        settings: AppSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._disk_manager = disk_manager
        self._settings = settings
        self._volumes: list[VolumeInfo] = []
        self._rows: list[DiskRow] = []
        self._selected_letter = ""
        self._scan_result: ScanResult | None = None
        self._current_node: DirNode | None = None
        self._current_insight: FolderInsight | None = None
        self._node_map: dict[str, DirNode] = {}
        self._worker: ScanWorker | None = None
        self._cache_worker: CacheLoadWorker | None = None
        self._cache_checked = False
        self._cache_meta: ScanCacheMeta | None = None
        self._scanning = False
        self._closing = False
        self._analyzer = FileAnalyzer()
        self._last_scan_root = ""
        self._filter_buttons: dict[str, QPushButton] = {}
        self._build()
        self.refresh_disks()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 27, 34, 28)
        outer.setSpacing(15)
        self._heading_pill = Pill("等待扫描", variant="muted")
        outer.addWidget(
            page_heading(
                "文件分析",
                "扫描真实目录、定位大文件与可整理内容，并通过空间地图逐层进入。",
                eyebrow="ANALYSIS",
                trailing=self._heading_pill,
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setMinimumHeight(655)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(0, 0, 2, 2)
        columns.setSpacing(15)
        columns.addWidget(self._build_left(), 0)
        columns.addWidget(self._build_center(), 1)
        columns.addWidget(self._build_right(), 0)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    # -- left ----------------------------------------------------------
    def _build_left(self) -> QWidget:
        card = SurfaceCard(variant="normal", margins=(12, 14, 12, 12), spacing=7)
        card.setFixedWidth(274)

        head = QHBoxLayout()
        head.setContentsMargins(4, 0, 4, 0)
        title = QLabel("磁盘")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)
        self.volume_pill = Pill("—")
        head.addWidget(self.volume_pill)
        card.body.addLayout(head)

        self.disk_list = QVBoxLayout()
        self.disk_list.setContentsMargins(0, 0, 0, 0)
        self.disk_list.setSpacing(3)
        card.body.addLayout(self.disk_list)
        card.body.addSpacing(2)
        card.body.addWidget(Divider())
        card.body.addSpacing(2)

        tree_head = QHBoxLayout()
        tree_head.setContentsMargins(4, 0, 4, 0)
        tree_title = QLabel("文件夹")
        tree_title.setObjectName("rowTitle")
        tree_head.addWidget(tree_title)
        tree_head.addStretch(1)
        self.tree_hint = QLabel("扫描后可用")
        self.tree_hint.setObjectName("subtleText")
        tree_head.addWidget(self.tree_hint)
        card.body.addLayout(tree_head)

        self.tree_stack = QStackedWidget()
        self.tree_empty = _EmptyTree()
        self.tree = FolderTree()
        self.tree.nodeSelected.connect(self._on_tree_node_selected)
        self.tree_stack.addWidget(self.tree_empty)
        self.tree_stack.addWidget(self.tree)
        card.body.addWidget(self.tree_stack, 1)

        card.body.addWidget(Divider())
        filter_head = QLabel("快捷筛选")
        filter_head.setObjectName("sectionCaption")
        filter_head.setContentsMargins(4, 0, 0, 0)
        card.body.addWidget(filter_head)

        filter_grid = QGridLayout()
        filter_grid.setContentsMargins(0, 0, 0, 0)
        filter_grid.setHorizontalSpacing(4)
        filter_grid.setVerticalSpacing(3)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for index, (key, text, icon) in enumerate(_FILTERS):
            button = QPushButton(text)
            button.setObjectName("filterChip")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(make_icon(icon, Palette.MUTED, 13))
            button.setProperty("filterKey", key)
            if key == "duplicates":
                button.setToolTip("按大小预筛并进行 SHA-256 完整校验")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._filter_group.addButton(button)
            self._filter_buttons[key] = button
            filter_grid.addWidget(button, index // 2, index % 2)
        self._filter_buttons["all"].setChecked(True)
        card.body.addLayout(filter_grid)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(5)
        self.scan_volume_button = QPushButton("扫描磁盘")
        self.scan_volume_button.setObjectName("secondaryButton")
        self.scan_volume_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_volume_button.setToolTip("扫描当前所选磁盘的完整目录")
        self.scan_volume_button.clicked.connect(self._scan_selected_volume)
        self.choose_button = QPushButton("选择文件夹")
        self.choose_button.setObjectName("primaryButton")
        self.choose_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.choose_button.clicked.connect(self._choose_folder)
        actions.addWidget(self.scan_volume_button, 1)
        actions.addWidget(self.choose_button, 1)
        card.body.addLayout(actions)
        self.common_guide_button = QPushButton("常见目录说明")
        self.common_guide_button.setObjectName("quietButton")
        self.common_guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.common_guide_button.setToolTip("先了解 Windows、软件、下载、微信等目录是什么")
        self.common_guide_button.clicked.connect(self._open_common_folders)
        card.body.addWidget(self.common_guide_button)
        return card

    # -- centre --------------------------------------------------------
    def _build_center(self) -> QWidget:
        card = SurfaceCard(variant="raised", margins=(16, 13, 16, 12), spacing=9)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)
        self.up_button = QPushButton()
        self.up_button.setObjectName("iconButton")
        self.up_button.setFixedSize(31, 31)
        self.up_button.setIcon(make_icon("arrow-up", Palette.INK_SOFT, 17))
        self.up_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.up_button.setToolTip("返回上级目录")
        self.up_button.setEnabled(False)
        self.up_button.clicked.connect(self._go_up)
        toolbar.addWidget(self.up_button)
        self.path_field = QLineEdit()
        self.path_field.setObjectName("pathField")
        self.path_field.setReadOnly(True)
        self.path_field.setPlaceholderText("尚未选择扫描位置")
        self.path_field.setClearButtonEnabled(False)
        toolbar.addWidget(self.path_field, 1)
        self.rescan_button = QPushButton()
        self.rescan_button.setObjectName("iconButton")
        self.rescan_button.setFixedSize(31, 31)
        self.rescan_button.setIcon(make_icon("refresh", Palette.INK_SOFT, 16))
        self.rescan_button.setToolTip("重新扫描当前根目录")
        self.rescan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rescan_button.setEnabled(False)
        self.rescan_button.clicked.connect(self._rescan_current_root)
        toolbar.addWidget(self.rescan_button)
        card.body.addLayout(toolbar)

        self.state_stack = QStackedWidget()
        self.state_stack.addWidget(self._build_empty_state())
        self.state_stack.addWidget(self._build_scanning_state())
        self.state_stack.addWidget(self._build_results_state())
        self.state_stack.addWidget(self._build_cache_state())
        card.body.addWidget(self.state_stack, 1)
        return card

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art = QWidget()
        art.setFixedSize(64, 64)
        art.setStyleSheet("background: #EAE4DA; border-radius: 20px;")
        art_layout = QVBoxLayout(art)
        art_layout.setContentsMargins(0, 0, 0, 0)
        art_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        art_layout.addWidget(IconLabel("folder", size=28, color="#827C72"))
        layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("从一个文件夹开始")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        body = QLabel(
            "盘析会在后台读取目录结构与真实大小，可随时暂停或取消。\n"
            "选择文件夹后可浏览目录树、排序文件并查看空间地图。"
        )
        body.setObjectName("emptyBody")
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)
        body.setMaximumWidth(460)
        layout.addWidget(body)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        default_button = QPushButton("扫描我的文档")
        default_button.setObjectName("primaryButton")
        default_button.setCursor(Qt.CursorShape.PointingHandCursor)
        default_button.clicked.connect(self._scan_default_documents)
        choose = QPushButton("选择文件夹")
        choose.setObjectName("secondaryButton")
        choose.setCursor(Qt.CursorShape.PointingHandCursor)
        choose.clicked.connect(self._choose_folder)
        buttons.addWidget(default_button)
        buttons.addWidget(choose)
        layout.addLayout(buttons)
        hint = QLabel("只读取元数据，不修改文件")
        hint.setObjectName("subtleText")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        return page

    def _build_cache_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_box = QWidget()
        icon_box.setFixedSize(58, 58)
        icon_box.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("database", size=25, color="#7D776C"))
        layout.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("正在恢复上次扫描…")
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.cache_path_label = QLabel("")
        self.cache_path_label.setObjectName("mutedText")
        self.cache_path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cache_path_label.setWordWrap(True)
        layout.addWidget(self.cache_path_label)
        progress = QProgressBar()
        progress.setObjectName("scanProgress")
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(6)
        progress.setMaximumWidth(400)
        layout.addWidget(progress, 0, Qt.AlignmentFlag.AlignHCenter)
        note = QLabel("从本地 SQLite 缓存读取目录结构，不会重新遍历磁盘。")
        note.setObjectName("subtleText")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        return page

    def _build_scanning_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(9)
        layout.addStretch(1)
        icon_box = QWidget()
        icon_box.setFixedSize(58, 58)
        icon_box.setStyleSheet("background: #E9E3D8; border-radius: 18px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel("search", size=25, color="#7D776C"))
        layout.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignHCenter)
        self.scan_title = QLabel("正在扫描…")
        self.scan_title.setObjectName("emptyTitle")
        self.scan_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.scan_title)
        self.scan_path = QLabel("")
        self.scan_path.setObjectName("mutedText")
        self.scan_path.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_path.setWordWrap(True)
        layout.addWidget(self.scan_path)
        self.scan_progress = QProgressBar()
        self.scan_progress.setObjectName("scanProgress")
        self.scan_progress.setRange(0, 0)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.setFixedHeight(6)
        self.scan_progress.setMaximumWidth(400)
        layout.addWidget(self.scan_progress, 0, Qt.AlignmentFlag.AlignHCenter)
        stats = QHBoxLayout()
        stats.setSpacing(26)
        stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scan_files = self._scan_stat("已扫描文件", "0")
        self.scan_dirs = self._scan_stat("已扫描目录", "0")
        self.scan_bytes = self._scan_stat("已统计空间", "0 B")
        self.scan_errors = self._scan_stat("跳过", "0")
        for stat in (self.scan_files, self.scan_dirs, self.scan_bytes, self.scan_errors):
            stats.addLayout(stat)
        layout.addLayout(stats)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pause_button = QPushButton("暂停")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.clicked.connect(self._toggle_pause)
        cancel = QPushButton("取消扫描")
        cancel.setObjectName("quietButton")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self._cancel_scan)
        buttons.addWidget(self.pause_button)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return page

    def _build_results_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(0)
        self.result_stats: list[tuple[QLabel, QLabel]] = []
        for caption in ("当前目录", "文件数量", "子文件夹", "扫描错误"):
            stat = QWidget()
            stat_layout = QVBoxLayout(stat)
            stat_layout.setContentsMargins(0, 0, 0, 0)
            stat_layout.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("subtleText")
            value = QLabel("—")
            value.setObjectName("strongText")
            stat_layout.addWidget(label)
            stat_layout.addWidget(value)
            stats_row.addWidget(stat, 1)
            self.result_stats.append((label, value))
        layout.addLayout(stats_row)
        layout.addWidget(Divider())

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(8)
        self.search_field = QLineEdit()
        self.search_field.setObjectName("searchField")
        self.search_field.setPlaceholderText("搜索当前文件夹…")
        self.search_field.setClearButtonEnabled(True)
        self.search_field.addAction(
            make_icon("search", Palette.MUTED, 15),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.search_field.textChanged.connect(self._on_search_changed)
        self.search_field.setEnabled(False)
        search_row.addWidget(self.search_field, 1)
        self.result_count = QLabel("—")
        self.result_count.setObjectName("subtleText")
        search_row.addWidget(self.result_count, 0)
        layout.addLayout(search_row)

        self.table = FileTableView()
        self.table.doubleClicked.connect(self._on_table_double_click)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_table_menu)
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self.selected_label = QLabel("未选择项目")
        self.selected_label.setObjectName("subtleText")
        footer.addWidget(self.selected_label, 1)
        self.scan_meta = QLabel("")
        self.scan_meta.setObjectName("subtleText")
        footer.addWidget(self.scan_meta, 0)
        self.report_button = QPushButton("扫描报告")
        self.report_button.setObjectName("linkButton")
        self.report_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.report_button.setEnabled(False)
        self.report_button.clicked.connect(self._show_scan_report)
        footer.addWidget(self.report_button, 0)
        layout.addLayout(footer)
        return page

    def _build_right(self) -> QWidget:
        card = SurfaceCard(variant="normal", margins=(17, 15, 17, 14), spacing=9)
        card.setFixedWidth(292)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(SectionHeader("空间占用", "点击色块进入子目录"), 1)
        self.map_pill = Pill("—")
        head.addWidget(self.map_pill, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(head)
        self.folder_map = FolderTreemap()
        self.folder_map.folderActivated.connect(self._navigate_to_node)
        card.body.addWidget(self.folder_map, 1)
        card.body.addWidget(Divider())

        self.detail_name = QLabel("未选择目录")
        self.detail_name.setObjectName("sectionTitle")
        self.detail_name.setWordWrap(True)
        card.body.addWidget(self.detail_name)
        self.detail_path = ElidedLabel("扫描完成后可查看目录详情", mode=Qt.TextElideMode.ElideMiddle)
        self.detail_path.setObjectName("subtleText")
        card.body.addWidget(self.detail_path)
        guide_row = QHBoxLayout()
        guide_row.setContentsMargins(0, 0, 0, 0)
        guide_row.setSpacing(7)
        self.guide_role = Pill("—", variant="muted")
        self.guide_role.setVisible(False)
        guide_row.addWidget(self.guide_role, 0)
        guide_row.addStretch(1)
        self.guide_button = QPushButton("这是什么？")
        self.guide_button.setObjectName("quietButton")
        self.guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guide_button.setToolTip("查看该目录的用途、删除风险和建议操作")
        self.guide_button.clicked.connect(self._open_folder_guide)
        self.guide_button.setVisible(False)
        guide_row.addWidget(self.guide_button, 0)
        card.body.addLayout(guide_row)
        card.body.addSpacing(2)
        details = QHBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(10)
        self.detail_size = self._detail_stat("总大小", "—")
        self.detail_files = self._detail_stat("文件", "—")
        self.detail_folders = self._detail_stat("子目录", "—")
        for layout in (self.detail_size, self.detail_files, self.detail_folders):
            details.addLayout(layout)
        card.body.addLayout(details)
        self.detail_modified = QLabel("—")
        self.detail_modified.setObjectName("subtleText")
        card.body.addWidget(self.detail_modified)
        card.body.addSpacing(5)
        self.top_folders_title = QLabel("主要子目录")
        self.top_folders_title.setObjectName("sectionCaption")
        card.body.addWidget(self.top_folders_title)
        self.top_folders = QWidget()
        self.top_folders_layout = QVBoxLayout(self.top_folders)
        self.top_folders_layout.setContentsMargins(0, 0, 0, 0)
        self.top_folders_layout.setSpacing(7)
        card.body.addWidget(self.top_folders)
        card.body.addStretch(1)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.open_button = QPushButton("打开位置")
        self.open_button.setObjectName("primaryButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setIcon(make_icon("external", "#F8F4EC", 14))
        self.open_button.clicked.connect(self._open_current_location)
        self.open_button.setEnabled(False)
        self.ignore_button = QPushButton("加入忽略")
        self.ignore_button.setObjectName("secondaryButton")
        self.ignore_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ignore_button.clicked.connect(self._ignore_current_folder)
        self.ignore_button.setEnabled(False)
        actions.addWidget(self.open_button, 1)
        actions.addWidget(self.ignore_button, 1)
        card.body.addLayout(actions)

        self.scan_footer = QLabel("尚未建立文件索引")
        self.scan_footer.setObjectName("subtleText")
        self.scan_footer.setWordWrap(True)
        card.body.addWidget(self.scan_footer)
        return card

    @staticmethod
    def _scan_stat(caption: str, value: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName("rowTitle")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption_label = QLabel(caption)
        caption_label.setObjectName("subtleText")
        caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        layout._value_label = value_label  # type: ignore[attr-defined]
        return layout

    @staticmethod
    def _detail_stat(caption: str, value: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName("rowTitle")
        caption_label = QLabel(caption)
        caption_label.setObjectName("subtleText")
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        layout._value_label = value_label  # type: ignore[attr-defined]
        return layout

    # ------------------------------------------------------------------
    # Volume selection
    # ------------------------------------------------------------------
    def refresh_disks(self) -> None:
        self._volumes = self._disk_manager.list_volumes()
        valid = {volume.drive_letter for volume in self._volumes}
        if self._selected_letter not in valid:
            default = self._disk_manager.default_volume(self._volumes)
            self._selected_letter = default.drive_letter if default else ""
        self._rebuild_volume_rows()
        self.volume_pill.setText(f"{len(self._volumes)} 个卷")
        self._update_scan_volume_button()

    def _rebuild_volume_rows(self) -> None:
        while self.disk_list.count():
            item = self.disk_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()
        shades = (Palette.DARK, "#7E796D", "#A39B8C", "#C7BDAC")
        for index, volume in enumerate(self._volumes):
            row = DiskRow(
                volume,
                accent=shades[min(index, len(shades) - 1)],
                compact=True,
            )
            row.clicked.connect(self._select_volume)
            self.disk_list.addWidget(row)
            self._rows.append(row)
            row.set_selected(volume.drive_letter.upper() == self._selected_letter.upper())

    def _select_volume(self, letter: str) -> None:
        if not letter:
            return
        self._selected_letter = letter.upper()
        for row in self._rows:
            row.set_selected(row.volume.drive_letter.upper() == self._selected_letter.upper())
        self._update_scan_volume_button()

    def _selected_volume(self) -> VolumeInfo | None:
        for volume in self._volumes:
            if volume.drive_letter.upper() == self._selected_letter.upper():
                return volume
        return None

    def _update_scan_volume_button(self) -> None:
        volume = self._selected_volume()
        if volume is None:
            self.scan_volume_button.setText("扫描磁盘")
            self.scan_volume_button.setEnabled(False)
            return
        self.scan_volume_button.setText(f"扫描 {volume.drive_letter}: 盘")
        self.scan_volume_button.setEnabled(not self._scanning)

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------
    def _choose_folder(self) -> None:
        if self._scanning:
            return
        if self._current_node is not None:
            start = self._current_node.path
        else:
            documents = Path.home() / "Documents"
            start = str(documents if documents.is_dir() else Path.home())
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择要分析的文件夹",
            start,
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self.start_scan(folder)

    def _scan_default_documents(self) -> None:
        documents = Path.home() / "Documents"
        if documents.is_dir():
            self.start_scan(str(documents))
        else:
            self._choose_folder()

    def _scan_selected_volume(self) -> None:
        if self._scanning:
            return
        volume = self._selected_volume()
        if volume is None:
            return
        answer = QMessageBox.question(
            self,
            f"扫描整个 {volume.drive_letter}: 盘？",
            f"盘析将读取 {volume.mount_point} 的完整目录结构，只读取元数据，不修改文件。\n\n"
            "整盘扫描可能需要几分钟，您可以随时暂停或取消。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_scan(volume.mount_point)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._cache_checked:
            self._cache_checked = True
            self._try_restore_cache()

    def _try_restore_cache(self) -> None:
        if self._scan_result is not None or self._scanning or self._cache_worker is not None:
            return
        path = (self._settings.last_analysis_path or "").strip()
        if not path or not os.path.isdir(path):
            return
        try:
            meta = ScanCacheService().metadata(path)
        except Exception:
            logger.exception("Could not inspect scan cache")
            return
        if meta is None:
            return
        self._cache_meta = meta
        self._last_scan_root = path
        self._heading_pill.setText("读取缓存")
        self._heading_pill.setObjectName("statusMuted")
        self._style_pill(self._heading_pill)
        self.path_field.setText(meta.root_path or path)
        self.path_field.setCursorPosition(0)
        self.cache_path_label.setText(meta.root_path or path)
        self.tree_hint.setText("读取缓存…")
        self.choose_button.setEnabled(False)
        self.scan_volume_button.setEnabled(False)
        self.rescan_button.setEnabled(False)
        self.state_stack.setCurrentIndex(3)
        worker = CacheLoadWorker(path, parent=self)
        self._cache_worker = worker
        worker.cacheLoaded.connect(self._on_cache_loaded)
        worker.cacheFailed.connect(self._on_cache_failed)
        worker.finished.connect(lambda w=worker: self._on_cache_finished(w))
        worker.start()

    def _on_cache_loaded(self, result: ScanResult) -> None:
        if self._closing:
            return
        self._scanning = False
        self._apply_scan_result(result, from_cache=True, cache_meta=self._cache_meta)
        self._show_toast("已恢复上次扫描缓存", icon="info")

    def _on_cache_failed(self, message: str) -> None:
        if self._closing:
            return
        logger.info("Scan cache restore failed: %s", message)
        self._heading_pill.setText("等待扫描")
        self._heading_pill.setObjectName("statusMuted")
        self._style_pill(self._heading_pill)
        self.tree_hint.setText("扫描后可用")
        self.choose_button.setEnabled(True)
        self.scan_volume_button.setEnabled(self._selected_volume() is not None)
        self.rescan_button.setEnabled(False)
        self.state_stack.setCurrentIndex(0)

    def _on_cache_finished(self, worker: CacheLoadWorker | None = None) -> None:
        finished = worker if worker is not None else self._cache_worker
        if self._cache_worker is finished:
            self._cache_worker = None
        if finished is not None:
            finished.deleteLater()

    def start_scan(self, path: str) -> None:
        if self._scanning or self._cache_worker is not None:
            return
        self._cache_checked = True
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(path):
            self._show_error("所选位置不是可访问的文件夹。")
            return

        self._last_scan_root = path
        self._scanning = True
        self._closing = False
        self.path_field.setText(path)
        self.path_field.setCursorPosition(0)
        self._heading_pill.setText("扫描中")
        self._heading_pill.setObjectName("statusWarning")
        self._style_pill(self._heading_pill)
        self.tree_hint.setText("扫描中…")
        self._set_filters_enabled(False)
        self._set_scan_buttons_enabled(False)
        self.rescan_button.setEnabled(False)
        self.up_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.state_stack.setCurrentIndex(1)
        self.scan_title.setText("正在扫描…")
        self.scan_path.setText(path)
        self.scan_progress.setRange(0, 0)
        self._set_scan_stat(self.scan_files, "0")
        self._set_scan_stat(self.scan_dirs, "0")
        self._set_scan_stat(self.scan_bytes, "0 B")
        self._set_scan_stat(self.scan_errors, "0")
        self.pause_button.setText("暂停")
        self._set_map_empty()

        worker = ScanWorker(
            path,
            excluded_paths=self._settings.excluded_paths,
            parent=self,
        )
        self._worker = worker
        worker.progress.connect(self._on_scan_progress)
        worker.scanFinished.connect(self._on_scan_finished)
        worker.scanFailed.connect(self._on_scan_failed)
        worker.scanCancelled.connect(self._on_scan_cancelled)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_scan_progress(self, progress: ScanProgress) -> None:
        self.scan_path.setText(self._elide_path(progress.current_path, 88))
        self._set_scan_stat(self.scan_files, f"{progress.files_scanned:,}")
        self._set_scan_stat(self.scan_dirs, f"{progress.dirs_scanned:,}")
        self._set_scan_stat(self.scan_bytes, format_capacity(progress.bytes_found))
        self._set_scan_stat(self.scan_errors, f"{progress.errors:,}")

    def _on_scan_finished(self, result: ScanResult) -> None:
        self._scanning = False
        self.pause_button.setEnabled(False)
        self._cache_meta = None
        self._apply_scan_result(result, from_cache=False)
        self._settings.last_analysis_path = result.root.path
        try:
            self._settings.save()
        except OSError:
            logger.warning("Could not remember the last analysis path", exc_info=True)
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast(
                f"扫描完成：{result.files_scanned:,} 个文件 · {format_capacity(result.total_size)}"
            )

    def _apply_scan_result(
        self,
        result: ScanResult,
        *,
        from_cache: bool,
        cache_meta: ScanCacheMeta | None = None,
    ) -> None:
        self._scan_result = result
        self._last_scan_root = result.root.path
        self._heading_pill.setText("缓存结果" if from_cache else "已扫描")
        self._heading_pill.setObjectName("statusSuccess")
        self._style_pill(self._heading_pill)
        self.tree_hint.setText(f"{result.dirs_scanned:,} 个目录")
        self._node_map = self._build_node_map(result.root)
        self.tree.set_root(result.root)
        self.tree_stack.setCurrentIndex(1)
        self._set_filters_enabled(True)
        self._set_scan_buttons_enabled(True)
        self.rescan_button.setEnabled(True)
        self.report_button.setEnabled(True)
        self.search_field.setEnabled(True)
        self.search_field.clear()
        self._filter_buttons["all"].setChecked(True)
        self.table.proxy.set_filter("all")
        self.state_stack.setCurrentIndex(2)
        if from_cache:
            cached_at = (
                cache_meta.scanned_at.strftime("%Y-%m-%d %H:%M")
                if cache_meta is not None
                else "未知时间"
            )
            self.scan_footer.setText(
                f"缓存于 {cached_at}  ·  "
                f"读取 {result.files_scanned:,} 个文件  ·  "
                f"{result.errors:,} 个跳过  ·  点击刷新重新扫描"
            )
            self.scan_meta.setText(
                f"缓存结果 · {result.files_scanned:,} 个文件 · 跳过 {result.errors:,}"
            )
        else:
            self.scan_footer.setText(
                f"耗时 {self._format_duration(result.duration)}  ·  "
                f"读取 {result.files_scanned:,} 个文件  ·  "
                f"{result.errors:,} 个跳过"
            )
            self.scan_meta.setText(
                f"已读取 {result.files_scanned:,} 个文件 · 跳过 {result.errors:,}"
            )
        self._navigate_to_node(result.root, reset_filters=True)

    def _on_scan_failed(self, message: str) -> None:
        self._scanning = False
        self.pause_button.setEnabled(False)
        self._heading_pill.setText("读取失败")
        self._heading_pill.setObjectName("statusDanger")
        self._style_pill(self._heading_pill)
        self.tree_hint.setText("读取失败")
        self.rescan_button.setEnabled(bool(self._last_scan_root))
        self.report_button.setEnabled(self._scan_result is not None)
        self._set_scan_buttons_enabled(True)
        self._set_filters_enabled(self._scan_result is not None)
        if self._scan_result is None or self._current_node is None:
            self.state_stack.setCurrentIndex(0)
        else:
            self._navigate_to_node(self._current_node)
            self.state_stack.setCurrentIndex(2)
        self._show_error(message)

    def _on_scan_cancelled(self) -> None:
        self._scanning = False
        self.pause_button.setEnabled(False)
        self._heading_pill.setText("已取消" if self._scan_result is None else "已扫描")
        self._heading_pill.setObjectName(
            "statusMuted" if self._scan_result is None else "statusSuccess"
        )
        self._style_pill(self._heading_pill)
        self.tree_hint.setText("已取消" if self._scan_result is None else "扫描结果")
        self.rescan_button.setEnabled(bool(self._last_scan_root))
        self.report_button.setEnabled(self._scan_result is not None)
        self._set_scan_buttons_enabled(True)
        self._set_filters_enabled(self._scan_result is not None)
        if self._scan_result is None or self._current_node is None:
            self.state_stack.setCurrentIndex(0)
        else:
            self._navigate_to_node(self._current_node)
            self.state_stack.setCurrentIndex(2)
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast("扫描已取消", icon="info")

    def _on_worker_finished(self, worker: ScanWorker | None = None) -> None:
        finished = worker if worker is not None else self._worker
        if self._worker is finished:
            self._worker = None
        if finished is not None:
            finished.deleteLater()

    def _toggle_pause(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if worker.is_paused:
            worker.resume()
            self.pause_button.setText("暂停")
            self.scan_title.setText("正在扫描…")
        else:
            worker.pause()
            self.pause_button.setText("继续")
            self.scan_title.setText("扫描已暂停")

    def _cancel_scan(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.cancel()
            self.scan_title.setText("正在取消…")
            self.pause_button.setEnabled(False)

    def _rescan_current_root(self) -> None:
        if not self._last_scan_root:
            return
        self.start_scan(self._last_scan_root)

    def _show_scan_report(self) -> None:
        if self._scan_result is None:
            return
        ScanReportDialog(self._scan_result, self).exec()

    def _set_scan_buttons_enabled(self, enabled: bool) -> None:
        self.choose_button.setEnabled(enabled)
        self.scan_volume_button.setEnabled(enabled and self._selected_volume() is not None)
        # Pause/cancel are only meaningful while a scan is active.
        self.pause_button.setEnabled(not enabled)
        self.up_button.setEnabled(enabled and self._current_node is not None)

    def _set_filters_enabled(self, enabled: bool) -> None:
        for button in self._filter_buttons.values():
            button.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Folder navigation
    # ------------------------------------------------------------------
    def _build_node_map(self, root: DirNode) -> dict[str, DirNode]:
        mapping: dict[str, DirNode] = {}
        stack = [root]
        while stack:
            node = stack.pop()
            mapping[os.path.normcase(node.path)] = node
            stack.extend(node.children)
        return mapping

    def _navigate_to_node(self, node: DirNode, *, reset_filters: bool = False) -> None:
        if node is None:
            return
        if self._scanning:
            return
        self._current_node = node
        entries = self._analyzer.list_entries(
            node, excluded_paths=self._settings.excluded_paths
        )
        self.table.set_entries(entries)
        if reset_filters:
            self.search_field.clear()
            self._filter_buttons["all"].setChecked(True)
            self.table.proxy.set_filter("all")
        self.path_field.setText(node.path)
        self.path_field.setCursorPosition(0)
        self.up_button.setEnabled(
            self._scan_result is not None
            and os.path.normcase(node.path) != os.path.normcase(self._scan_result.root.path)
        )
        self._update_result_stats(node, entries)
        self._update_right(node)
        self.tree.select_path(node)
        self._update_result_count()
        self._update_selection_label()
        self.ignore_button.setEnabled(
            self._scan_result is not None
            and os.path.normcase(node.path) != os.path.normcase(self._scan_result.root.path)
        )
        self.ignore_button.setToolTip(
            "将当前文件夹加入扫描排除列表"
            if self.ignore_button.isEnabled()
            else "扫描根目录不能加入忽略列表"
        )

    def _on_tree_node_selected(self, node: DirNode) -> None:
        if node is not None and node is not self._current_node:
            self._navigate_to_node(node)

    def _go_up(self) -> None:
        node = self._current_node
        result = self._scan_result
        if node is None or result is None:
            return
        if os.path.normcase(node.path) == os.path.normcase(result.root.path):
            return
        parent_path = os.path.dirname(node.path)
        parent = self._node_map.get(os.path.normcase(parent_path))
        if parent is None:
            return
        self._navigate_to_node(parent)

    def _update_result_stats(self, node: DirNode, entries: list[FileEntry]) -> None:
        self.result_stats[0][1].setText(node.name or node.path)
        self.result_stats[1][1].setText(f"{node.file_count:,}")
        self.result_stats[2][1].setText(f"{node.subfolder_count:,}")
        self.result_stats[3][1].setText(f"{node.errors:,}")

    def _update_result_count(self) -> None:
        total = self.table.proxy.rowCount()
        self.result_count.setText(f"{total} 项")
        if self.table.proxy.rowCount() == 0:
            self.search_field.setPlaceholderText("当前筛选没有匹配项")
        else:
            self.search_field.setPlaceholderText("搜索当前文件夹…")

    def _on_search_changed(self, text: str) -> None:
        self.table.proxy.set_search_text(text)
        self._update_result_count()

    def _set_filter(self, key: str) -> None:
        if key == "duplicates":
            # This is an action rather than a table predicate: duplicate
            # detection needs recursive hashing and grouped results.
            self._filter_buttons["all"].setChecked(True)
            self.table.proxy.set_filter("all")
            self._update_result_count()
            self._open_duplicate_dialog()
            return
        self.table.proxy.set_filter(key)
        self._update_result_count()

    def _open_duplicate_dialog(self) -> None:
        if self._current_node is None:
            return
        dialog = DuplicateFinderDialog(
            self._current_node.path,
            excluded_paths=self._settings.excluded_paths,
            parent=self,
        )
        dialog.exec()

    def _update_right(self, node: DirNode) -> None:
        self.detail_name.setText(node.name or node.path)
        self.detail_path.setText(node.path)
        self.detail_path.setToolTip(node.path)
        insight = describe_folder(node.path)
        self._current_insight = insight
        self.guide_role.setText(insight.category)
        variant = {
            "protected": "danger",
            "wechat": "danger",
            "personal": "warning",
            "caution": "warning",
            "project": "warning",
            "cache": "success",
        }.get(insight.tone, "muted")
        self.guide_role.setObjectName(
            {
                "danger": "statusDanger",
                "warning": "statusWarning",
                "success": "statusSuccess",
            }.get(variant, "statusMuted")
        )
        self.guide_role.style().unpolish(self.guide_role)
        self.guide_role.style().polish(self.guide_role)
        self.guide_role.setVisible(True)
        self.guide_button.setVisible(True)
        self.detail_name.setToolTip(insight.summary)
        self._set_detail_stat(self.detail_size, format_capacity(node.size))
        self._set_detail_stat(self.detail_files, f"{node.file_count:,}")
        self._set_detail_stat(self.detail_folders, f"{node.subfolder_count:,}")
        self.detail_modified.setText(
            f"修改时间 {human_node_date(node)}"
            + ("  ·  权限受限" if node.inaccessible else "")
        )
        self.map_pill.setText(format_capacity(node.size))
        self.folder_map.set_node(node)
        self.open_button.setEnabled(True)
        self._update_top_folders(node)

    def _open_folder_guide(self) -> None:
        node = self._current_node
        if node is None:
            return
        insight = self._current_insight or describe_folder(node.path)
        dialog = FolderGuideDialog(node.path, insight, self)
        dialog.exec()
        action = dialog.requested_action
        if action == "cleanup" or action == "wechat":
            self.cleanupRequested.emit()
        elif action == "software":
            self.softwareRequested.emit()

    def _open_common_folders(self) -> None:
        CommonFoldersDialog(self).exec()

    def _update_top_folders(self, node: DirNode) -> None:
        while self.top_folders_layout.count():
            item = self.top_folders_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        children = sorted(node.children, key=lambda child: child.size, reverse=True)[:4]
        self.top_folders_title.setVisible(bool(children))
        self.top_folders.setVisible(bool(children))
        if not children or node.size <= 0:
            return
        for child in children:
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(3)
            text_row = QHBoxLayout()
            text_row.setContentsMargins(0, 0, 0, 0)
            text_row.setSpacing(6)
            name = QLabel(child.name)
            name.setObjectName("rowMeta")
            name.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            percent = QLabel(format_percent(child.size / node.size, 0))
            percent.setObjectName("subtleText")
            percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text_row.addWidget(name, 1)
            text_row.addWidget(percent, 0)
            row_layout.addLayout(text_row)
            bar = UsageBar(
                height=3,
                track_color="#EAE4DA",
                fill_color="#6D675D",
                animated=False,
            )
            bar.set_value(child.size / node.size, animated=False)
            row_layout.addWidget(bar)
            self.top_folders_layout.addWidget(row)

    def _update_selection_label(self) -> None:
        entries = self.table.selected_entries()
        if not entries:
            self.selected_label.setText("未选择项目")
            return
        total_size = sum(entry.size for entry in entries)
        self.selected_label.setText(
            f"已选择 {len(entries)} 项  ·  {format_capacity(total_size)}"
        )

    def _on_table_selection(self, selected, deselected) -> None:
        del selected, deselected
        self._update_selection_label()

    def _on_table_double_click(self, index: QModelIndex) -> None:
        entry = self.table.entry_for_index(index)
        if entry is None:
            return
        if entry.is_dir:
            node = self._node_map.get(os.path.normcase(entry.path))
            if node is not None:
                self._navigate_to_node(node)
            else:
                self._show_error("此目录不可访问或未被扫描。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(entry.path))

    def _show_table_menu(self, pos) -> None:
        entries = self.table.selected_entries()
        menu = QMenu(self)
        open_action = menu.addAction("打开")
        open_action.setEnabled(bool(entries))
        reveal_action = menu.addAction("在资源管理器中显示")
        reveal_action.setEnabled(bool(entries))
        enter_action = menu.addAction("进入文件夹")
        directory_entries = [entry for entry in entries if entry.is_dir]
        enter_action.setEnabled(bool(directory_entries))
        menu.addSeparator()
        ignore_action = menu.addAction("将所在位置加入忽略列表")
        ignore_action.setEnabled(self._current_node is not None and self.ignore_button.isEnabled())

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == open_action:
            for entry in entries:
                QDesktopServices.openUrl(QUrl.fromLocalFile(entry.path))
        elif chosen == reveal_action:
            first = entries[0]
            self._reveal_in_explorer(first.path)
        elif chosen == enter_action:
            node = self._node_map.get(os.path.normcase(directory_entries[0].path))
            if node is not None:
                self._navigate_to_node(node)
        elif chosen == ignore_action:
            self._ignore_current_folder()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _open_current_location(self) -> None:
        if self._current_node is None:
            return
        QProcess.startDetached("explorer.exe", [os.path.normpath(self._current_node.path)])

    def _reveal_in_explorer(self, path: str) -> None:
        QProcess.startDetached("explorer.exe", [f"/select,{os.path.normpath(path)}"])

    def _ignore_current_folder(self) -> None:
        node = self._current_node
        result = self._scan_result
        if node is None or result is None:
            return
        if os.path.normcase(node.path) == os.path.normcase(result.root.path):
            return
        existing = {
            os.path.normcase(os.path.abspath(path))
            for path in self._settings.excluded_paths
        }
        normalised = os.path.normcase(os.path.abspath(node.path))
        if normalised in existing:
            self._show_toast("此文件夹已在忽略列表中", icon="info")
            return
        answer = QMessageBox.question(
            self,
            "加入忽略列表",
            f"扫描与后续清理将跳过：\n{node.path}\n\n确定要加入吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._settings.excluded_paths.append(node.path)
        try:
            self._settings.save()
        except OSError as exc:
            self._show_error(f"无法保存忽略列表：{exc}")
            return
        self._show_toast("已加入忽略列表，下次扫描生效")

    def shutdown(self) -> None:
        """Stop a running worker cleanly when the app is actually exiting."""

        self._closing = True
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            worker.wait(1800)
        cache_worker = self._cache_worker
        if cache_worker is not None and cache_worker.isRunning():
            cache_worker.wait(1800)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "文件分析", message, QMessageBox.StandardButton.Ok)

    def _show_toast(self, text: str, *, icon: str = "check") -> None:
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast(text, icon=icon)

    def _set_map_empty(self) -> None:
        self.folder_map.clear()
        self.detail_name.setText("正在扫描")
        self.detail_path.setText("目录结构与空间会在扫描完成后显示。")
        self._set_detail_stat(self.detail_size, "—")
        self._set_detail_stat(self.detail_files, "—")
        self._set_detail_stat(self.detail_folders, "—")
        self.detail_modified.setText("—")
        self.map_pill.setText("—")
        self.open_button.setEnabled(False)
        self.ignore_button.setEnabled(False)
        self.guide_role.setVisible(False)
        self.guide_button.setVisible(False)
        self._current_insight = None

    @staticmethod
    def _set_scan_stat(layout: QVBoxLayout, value: str) -> None:
        label = getattr(layout, "_value_label", None)
        if label is not None:
            label.setText(value)

    @staticmethod
    def _set_detail_stat(layout: QVBoxLayout, value: str) -> None:
        label = getattr(layout, "_value_label", None)
        if label is not None:
            label.setText(value)

    @staticmethod
    def _style_pill(pill: Pill) -> None:
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    @staticmethod
    def _elide_path(path: str, limit: int) -> str:
        if len(path) <= limit:
            return path
        return path[: max(10, limit // 2 - 2)] + "…" + path[-(limit // 2 - 1):]

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 1:
            return "不到 1 秒"
        if seconds < 60:
            return f"{seconds:.1f} 秒"
        minutes = int(seconds // 60)
        remaining = int(seconds % 60)
        return f"{minutes} 分 {remaining} 秒"