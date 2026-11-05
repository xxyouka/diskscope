"""Disk overview — the visual centrepiece of DiskScope.

This page intentionally uses only real capacity counters for its numbers and
composition.  File-level categories arrive with the scanner in a later stage;
nothing here is a fabricated placeholder value.
"""

from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, format_percent, split_size
from core.disk_manager import DiskManager, VolumeInfo
from ui.components.common import (
    Divider,
    IconLabel,
    KeyValueRow,
    Pill,
    SectionHeader,
    StatTile,
    SurfaceCard,
)
from ui.components.disk_row import DiskRow
from ui.components.folder_guide import CommonFoldersDialog
from ui.components.icons import icon_pixmap, make_icon
from ui.components.storage_map import StorageMapWidget
from ui.components.usage_bar import UsageBar
from ui.pages.base_page import BasePage
from ui.styles.palette import Palette

logger = logging.getLogger(__name__)


class _Legend(QWidget):
    def __init__(self, items: tuple[tuple[str, str], ...], parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)
        for color, label in items:
            item = QWidget()
            item_row = QHBoxLayout(item)
            item_row.setContentsMargins(0, 0, 0, 0)
            item_row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(7, 7)
            dot.setStyleSheet(f"background: {color}; border-radius: 3px;")
            text = QLabel(label)
            text.setObjectName("sectionCaption")
            item_row.addWidget(dot)
            item_row.addWidget(text)
            row.addWidget(item)


class DashboardPage(BasePage):
    refreshRequested = Signal()

    def __init__(self, disk_manager: DiskManager, parent=None) -> None:
        super().__init__(parent)
        self._disk_manager = disk_manager
        self._volumes: list[VolumeInfo] = []
        self._selected_letter = ""
        self._rows: list[DiskRow] = []
        self._last_refresh: datetime | None = None
        self._build()
        self.refresh_disks()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        # The dashboard scrolls vertically on shorter displays while keeping
        # the title bar and window chrome fixed.  On normal desktop sizes the
        # scrollbar stays hidden.
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("dashboardScrollContent")
        outer = QHBoxLayout(content)
        outer.setContentsMargins(34, 27, 34, 28)
        outer.setSpacing(25)

        outer.addWidget(self._build_left_column(), 0)
        outer.addWidget(self._build_right_column(), 1)
        scroll.setWidget(content)
        wrap.addWidget(scroll)

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(332)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title = QLabel("存储概览")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.live_pill = Pill("实时读数", variant="success")
        header.addWidget(self.live_pill)
        col.addLayout(header)
        col.addSpacing(19)

        caption = QLabel("当前可用空间")
        caption.setObjectName("metricCaption")
        col.addWidget(caption)
        col.addSpacing(1)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(7)
        value_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.hero_number = QLabel("—")
        self.hero_number.setObjectName("heroNumber")
        self.hero_unit = QLabel("")
        self.hero_unit.setObjectName("heroUnit")
        self.hero_unit.setContentsMargins(0, 0, 0, 9)
        self.hero_unit.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        )
        value_row.addWidget(self.hero_number)
        value_row.addWidget(self.hero_unit)
        value_row.addStretch(1)
        col.addLayout(value_row)

        self.hero_meta = QLabel("正在读取磁盘信息…")
        self.hero_meta.setObjectName("pageSubtitle")
        self.hero_meta.setWordWrap(False)
        col.addWidget(self.hero_meta)
        col.addSpacing(14)

        self.capacity_bar = UsageBar(height=7, fill_color=Palette.DARK)
        col.addWidget(self.capacity_bar)
        bar_legend = QHBoxLayout()
        bar_legend.setContentsMargins(0, 7, 0, 0)
        bar_legend.setSpacing(0)
        self.used_legend = QLabel("")
        self.used_legend.setObjectName("subtleText")
        self.free_legend = QLabel("")
        self.free_legend.setObjectName("subtleText")
        self.free_legend.setAlignment(Qt.AlignmentFlag.AlignRight)
        bar_legend.addWidget(self.used_legend, 1)
        bar_legend.addWidget(self.free_legend, 0)
        col.addLayout(bar_legend)
        col.addSpacing(22)

        divider = Divider()
        col.addWidget(divider)
        col.addSpacing(17)

        disks_header = QHBoxLayout()
        disks_header.setContentsMargins(0, 0, 0, 0)
        disks_header.setSpacing(8)
        disks_title = QLabel("本机磁盘")
        disks_title.setObjectName("rowTitle")
        disks_header.addWidget(disks_title)
        self.disk_count_label = QLabel("—")
        self.disk_count_label.setObjectName("subtleText")
        disks_header.addWidget(self.disk_count_label)
        disks_header.addStretch(1)
        hint = QLabel("点击切换")
        hint.setObjectName("subtleText")
        disks_header.addWidget(hint)
        col.addLayout(disks_header)
        col.addSpacing(9)

        self.disk_list = QVBoxLayout()
        self.disk_list.setContentsMargins(0, 0, 0, 0)
        self.disk_list.setSpacing(4)
        col.addLayout(self.disk_list)
        col.addSpacing(13)

        facts = SurfaceCard(variant="normal", margins=(16, 13, 16, 13), spacing=5)
        facts_header = QHBoxLayout()
        facts_header.setContentsMargins(0, 0, 0, 0)
        facts_header.setSpacing(8)
        facts_title = QLabel("当前卷信息")
        facts_title.setObjectName("sectionCaption")
        facts_header.addWidget(facts_title)
        facts_header.addStretch(1)
        facts_header.addWidget(IconLabel("database", size=13, color=Palette.MUTED_LIGHT))
        facts.body.addLayout(facts_header)
        facts.body.addSpacing(2)
        self.fact_label = KeyValueRow("卷标", "—")
        self.fact_mount = KeyValueRow("挂载点", "—")
        self.fact_filesystem = KeyValueRow("文件系统", "—")
        self.fact_ratio = KeyValueRow("可用比例", "—")
        for row in (self.fact_label, self.fact_mount, self.fact_filesystem, self.fact_ratio):
            facts.body.addWidget(row)
        col.addWidget(facts)
        col.addStretch(1)

        note = SurfaceCard(variant="muted", margins=(16, 13, 16, 13), spacing=8)
        note_row = QHBoxLayout()
        note_row.setContentsMargins(0, 0, 0, 0)
        note_row.setSpacing(9)
        note_row.addWidget(IconLabel("shield", size=15, color=Palette.MUTED))
        note_text = QLabel("Windows 实时读取容量，全程本地处理。")
        note_text.setObjectName("mutedText")
        note_text.setWordWrap(True)
        note_row.addWidget(note_text, 1)
        note.body.addLayout(note_row)
        col.addWidget(note)
        col.addSpacing(10)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.open_button = QPushButton("打开磁盘")
        self.open_button.setObjectName("secondaryButton")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setIcon(make_icon("external", Palette.MUTED, 15))
        self.open_button.setToolTip("在资源管理器中打开当前选中的磁盘")
        self.open_button.clicked.connect(self._open_selected_volume)
        self.copy_button = QPushButton("复制摘要")
        self.copy_button.setObjectName("quietButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("将当前磁盘容量摘要复制到剪贴板")
        self.copy_button.clicked.connect(self._copy_summary)
        actions.addWidget(self.open_button, 1)
        actions.addWidget(self.copy_button, 0)
        col.addLayout(actions)
        self.guide_button = QPushButton("看不懂文件夹？看看常见目录说明")
        self.guide_button.setObjectName("quietButton")
        self.guide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.guide_button.setToolTip("解释 Windows、软件、下载、微信等常见目录的用途与删除建议")
        self.guide_button.clicked.connect(self._show_common_folders)
        col.addWidget(self.guide_button)

        return column

    def _build_right_column(self) -> QWidget:
        column = QWidget()
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(17)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)
        header = SectionHeader(
            "空间地图",
            "面积与真实已用容量成正比，点击磁盘块可切换查看。",
        )
        header_row.addWidget(header, 1)
        self.refresh_note = QLabel("")
        self.refresh_note.setObjectName("subtleText")
        self.refresh_note.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        header_row.addWidget(self.refresh_note, 0, Qt.AlignmentFlag.AlignBottom)
        col.addLayout(header_row)

        map_card = SurfaceCard(variant="normal", margins=(19, 17, 19, 15), spacing=8)
        map_top = QHBoxLayout()
        map_top.setContentsMargins(0, 0, 0, 0)
        map_top.setSpacing(10)
        map_caption = QLabel("按容量构成")
        map_caption.setObjectName("eyebrowLike")
        map_caption.setStyleSheet(
            "color: #918B82; font-size: 11px; font-weight: 600;"
        )
        map_top.addWidget(map_caption)
        map_top.addStretch(1)
        map_top.addWidget(
            _Legend(
                (
                    (Palette.MAP_DARK, "已使用"),
                    (Palette.MAP_FREE, "可用空间"),
                )
            )
        )
        map_card.body.addLayout(map_top)

        self.storage_map = StorageMapWidget()
        self.storage_map.volumeActivated.connect(self._select_volume)
        self.storage_map.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        map_card.body.addWidget(self.storage_map, 1)
        col.addWidget(map_card, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(14)

        self.current_card = SurfaceCard(
            variant="normal", margins=(18, 16, 18, 15), spacing=9
        )
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(11)
        top.addWidget(IconLabel("disk", size=18, color=Palette.INK_SOFT))
        current_caption = QLabel("当前磁盘")
        current_caption.setObjectName("sectionCaption")
        top.addWidget(current_caption)
        top.addStretch(1)
        self.current_pill = Pill("—")
        top.addWidget(self.current_pill)
        self.current_card.body.addLayout(top)
        self.current_name = QLabel("—")
        self.current_name.setObjectName("sectionTitle")
        self.current_card.body.addWidget(self.current_name)
        self.current_meta = QLabel("—")
        self.current_meta.setObjectName("mutedText")
        self.current_card.body.addWidget(self.current_meta)
        self.current_bar = UsageBar(height=5)
        self.current_card.body.addWidget(self.current_bar)
        bottom.addWidget(self.current_card, 4)

        summary_card = SurfaceCard(
            variant="muted", margins=(17, 15, 17, 14), spacing=8
        )
        summary_title = QLabel("全部容量")
        summary_title.setObjectName("sectionCaption")
        summary_card.body.addWidget(summary_title)
        self.summary_total = StatTile("总容量", "—")
        summary_card.body.addWidget(self.summary_total)
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(16)
        self.summary_used = StatTile("已使用", "—")
        self.summary_free = StatTile("可用", "—")
        summary_row.addWidget(self.summary_used)
        summary_row.addWidget(self.summary_free)
        summary_card.body.addLayout(summary_row)
        bottom.addWidget(summary_card, 3)

        health_card = SurfaceCard(
            variant="normal", margins=(18, 15, 18, 14), spacing=7
        )
        health_top = QHBoxLayout()
        health_top.setContentsMargins(0, 0, 0, 0)
        health_top.setSpacing(8)
        self.health_icon = IconLabel("shield", size=17, color=Palette.SUCCESS)
        health_top.addWidget(self.health_icon)
        health_caption = QLabel("空间状态")
        health_caption.setObjectName("sectionCaption")
        health_top.addWidget(health_caption)
        health_top.addStretch(1)
        self.health_pill = Pill("—", variant="success")
        health_top.addWidget(self.health_pill)
        health_card.body.addLayout(health_top)
        self.health_title = QLabel("—")
        self.health_title.setObjectName("rowTitle")
        health_card.body.addWidget(self.health_title)
        self.health_body = QLabel("")
        self.health_body.setObjectName("mutedText")
        self.health_body.setWordWrap(True)
        health_card.body.addWidget(self.health_body, 1)
        bottom.addWidget(health_card, 4)

        col.addLayout(bottom)
        return column

    # ------------------------------------------------------------------
    def refresh_disks(self) -> None:
        volumes = self._disk_manager.list_volumes()
        self._last_refresh = self._disk_manager.last_refresh
        previous = self._selected_letter
        self._volumes = volumes

        default = self._disk_manager.default_volume(volumes)
        valid_letters = {volume.drive_letter for volume in volumes}
        if previous not in valid_letters:
            self._selected_letter = default.drive_letter if default else ""
        self._rebuild_disk_rows()
        self._update_selection()
        self._update_timestamp()
        if not volumes:
            self._show_empty_state()

    def _show_empty_state(self) -> None:
        self.hero_number.setText("—")
        self.hero_unit.setText("")
        self.hero_meta.setText("未读取到可用的本地磁盘")
        self.capacity_bar.set_value(0.0, animated=False)
        self.used_legend.setText("")
        self.free_legend.setText("")
        self.storage_map.set_data([], "")
        self.current_name.setText("暂无磁盘")
        self.current_meta.setText("请检查磁盘连接后重试")
        self.current_pill.setText("不可用")
        self.current_bar.set_value(0.0, animated=False)
        self.fact_label.set_value("—")
        self.fact_mount.set_value("—")
        self.fact_filesystem.set_value("—")
        self.fact_ratio.set_value("—")
        self.summary_total.set_value("—", "")
        self.summary_used.set_value("—", "")
        self.summary_free.set_value("—", "")
        self.health_title.setText("无法读取容量")
        self.health_body.setText("没有可用于分析的本地磁盘。")
        self.health_pill.setText("待检查")
        self.health_pill.setObjectName("statusMuted")
        self.health_pill.style().unpolish(self.health_pill)
        self.health_pill.style().polish(self.health_pill)

    def _update_timestamp(self) -> None:
        if self._last_refresh is None:
            self.refresh_note.setText("")
            return
        self.refresh_note.setText(
            f"读取于 {self._last_refresh.strftime('%H:%M:%S')}"
        )

    def _rebuild_disk_rows(self) -> None:
        while self.disk_list.count():
            item = self.disk_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows.clear()

        shades = (Palette.DARK, "#7E796D", "#A39B8C", "#C7BDAC")
        for index, volume in enumerate(self._volumes):
            row = DiskRow(volume, accent=shades[min(index, len(shades) - 1)])
            row.clicked.connect(self._select_volume)
            self.disk_list.addWidget(row)
            self._rows.append(row)

        self.disk_count_label.setText(f"{len(self._volumes)} 个本地卷")

    def _select_volume(self, letter: str) -> None:
        if not letter:
            return
        letter = letter.upper()
        if letter == self._selected_letter:
            return
        if letter not in {volume.drive_letter for volume in self._volumes}:
            return
        self._selected_letter = letter
        self._update_selection()

    def _selected_volume(self) -> VolumeInfo | None:
        for volume in self._volumes:
            if volume.drive_letter.upper() == self._selected_letter.upper():
                return volume
        return None

    def _update_selection(self) -> None:
        selected = self._selected_volume()
        for row in self._rows:
            row.set_selected(row.volume.drive_letter.upper() == self._selected_letter.upper())

        self.storage_map.set_data(self._volumes, self._selected_letter)
        if selected is None:
            return

        number, unit = split_size(selected.free)
        self.hero_number.setText(number)
        self.hero_unit.setText(unit)
        if selected.label:
            self.hero_meta.setText(
                f"{selected.display_name} · 卷标「{selected.label}」 · 共 {format_capacity(selected.total)}"
            )
        else:
            self.hero_meta.setText(
                f"{selected.display_name} · 共 {format_capacity(selected.total)}"
            )
        self.capacity_bar.set_value(selected.used_fraction)
        self.used_legend.setText(
            f"已用 {format_capacity(selected.used)}  ·  {format_percent(selected.used_fraction)}"
        )
        self.free_legend.setText(f"可用 {format_capacity(selected.free)}")

        self.current_name.setText(selected.display_name)
        self.current_meta.setText(
            f"{selected.mount_point}  ·  {selected.filesystem}  ·  "
            f"{format_capacity(selected.used)} / {format_capacity(selected.total)}"
        )
        self.current_bar.set_value(selected.used_fraction)
        self.current_pill.setText(format_percent(selected.used_fraction))
        self.fact_label.set_value(selected.label or "未命名卷")
        self.fact_mount.set_value(selected.mount_point)
        self.fact_filesystem.set_value(selected.filesystem or "—")
        self.fact_ratio.set_value(format_percent(selected.free_fraction))

        total = sum(volume.total for volume in self._volumes)
        used = sum(volume.used for volume in self._volumes)
        free = sum(volume.free for volume in self._volumes)
        total_number, total_unit = split_size(total)
        used_number, used_unit = split_size(used)
        free_number, free_unit = split_size(free)
        self.summary_total.set_value(total_number, total_unit)
        self.summary_used.set_value(used_number, used_unit)
        self.summary_free.set_value(free_number, free_unit)

        if selected.used_fraction >= 0.90:
            self.health_pill.setText("空间偏紧")
            self.health_pill.setObjectName("statusDanger")
            self.health_icon.setPixmap(icon_pixmap("warning", 17, Palette.DANGER))
            self.health_title.setText(f"{selected.drive_letter}: 盘剩余空间较低")
            self.health_body.setText(
                f"仅剩 {format_capacity(selected.free)}，低于总容量的 10%。"
                "建议优先关注系统缓存、浏览器缓存与下载目录。"
            )
        elif selected.used_fraction >= 0.80:
            self.health_pill.setText("建议关注")
            self.health_pill.setObjectName("statusWarning")
            self.health_icon.setPixmap(icon_pixmap("warning", 17, Palette.WARNING))
            self.health_title.setText(f"{selected.drive_letter}: 盘空间需要关注")
            self.health_body.setText(
                f"当前剩余 {format_capacity(selected.free)}（{format_percent(selected.free_fraction)}）。"
                "建议留意缓存和下载目录，避免空间继续下降。"
            )
        else:
            self.health_pill.setText("状态良好")
            self.health_pill.setObjectName("statusSuccess")
            self.health_icon.setPixmap(icon_pixmap("shield", 17, Palette.SUCCESS))
            self.health_title.setText(f"{selected.drive_letter}: 盘空间充足")
            self.health_body.setText(
                f"当前仍有 {format_percent(selected.free_fraction)} 可用。"
                "磁盘读取正常，未发现连接异常。"
            )
        self.health_pill.style().unpolish(self.health_pill)
        self.health_pill.style().polish(self.health_pill)

    # ------------------------------------------------------------------
    def _open_selected_volume(self) -> None:
        selected = self._selected_volume()
        if selected is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(selected.mount_point))

    def _show_common_folders(self) -> None:
        CommonFoldersDialog(self).exec()

    def _copy_summary(self) -> None:
        selected = self._selected_volume()
        if selected is None:
            return
        text = (
            f"盘析 · {selected.display_name}\n"
            f"总容量：{format_capacity(selected.total)}\n"
            f"已使用：{format_capacity(selected.used)}（{format_percent(selected.used_fraction)}）\n"
            f"可用：{format_capacity(selected.free)}\n"
            f"文件系统：{selected.filesystem}  挂载点：{selected.mount_point}"
        )
        QApplication.clipboard().setText(text)
        window = self.window()
        if hasattr(window, "show_toast"):
            window.show_toast("容量摘要已复制到剪贴板")