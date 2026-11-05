"""Small dialogs used by the cleanup preview flow."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, format_percent
from core.cleanup_engine import CleanupCategory
from core.file_types import category_label
from core.scanner import ScanResult
from services.history_service import CleanupHistoryRecord
from ui.components.common import Divider, IconLabel, Pill, SectionHeader, SurfaceCard, StatTile
from ui.components.icons import make_icon
from ui.components.usage_bar import UsageBar
from ui.styles.palette import Palette


class CleanupPreviewDialog(QDialog):
    def __init__(self, category: CleanupCategory, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{category.title} · 文件清单")
        self.setObjectName("cleanupPreviewDialog")
        self.setModal(True)
        self.resize(820, 620)
        self.setMinimumSize(660, 470)
        self.setMaximumSize(900, 720)
        self._size_settled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        head = SurfaceCard(variant="normal", margins=(20, 17, 20, 16), spacing=8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(IconLabel(category.icon, size=21, color=Palette.INK_SOFT))
        title = QLabel(category.title)
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        risk_variant = {"safe": "success", "review": "warning", "risk": "danger"}.get(
            category.risk, "muted"
        )
        title_row.addWidget(Pill(category.risk_label, variant=risk_variant))
        title_row.addStretch(1)
        title_row.addWidget(
            Pill(f"{format_capacity(category.total_size)} · {category.file_count:,} 个文件")
        )
        head.body.addLayout(title_row)
        reason = QLabel(category.reason)
        reason.setObjectName("mutedText")
        reason.setWordWrap(True)
        head.body.addWidget(reason)
        root_paths = "；".join(category.roots)
        paths = QLabel(root_paths)
        paths.setObjectName("subtleText")
        paths.setWordWrap(True)
        paths.setToolTip(root_paths)
        head.body.addWidget(paths)
        layout.addWidget(head)

        table_card = SurfaceCard(variant="raised", margins=(12, 12, 12, 12), spacing=6)
        subtitle = QLabel(
            "以下为扫描发现的最大文件示例。"
            + (
                f" 仅展示 {len(category.samples):,} / {category.file_count:,} 个文件。"
                if category.file_count > len(category.samples)
                else ""
            )
            + " 当前版本不会删除任何文件。"
        )
        subtitle.setObjectName("subtleText")
        subtitle.setWordWrap(True)
        table_card.body.addWidget(subtitle)

        table = QTableWidget(0, 3)
        table.setObjectName("fileTable")
        table.setHorizontalHeaderLabels(["文件", "大小", "修改时间"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 100)
        table.setColumnWidth(2, 140)
        for sample in category.samples:
            row = table.rowCount()
            table.insertRow(row)
            name_item = QTableWidgetItem(Path(sample.path).name)
            name_item.setIcon(make_icon("file", Palette.MUTED, 14))
            name_item.setToolTip(sample.path)
            table.setItem(row, 0, name_item)
            size_item = QTableWidgetItem(format_capacity(sample.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, 1, size_item)
            modified = "—"
            if sample.modified:
                try:
                    modified = datetime.fromtimestamp(sample.modified).strftime("%Y-%m-%d %H:%M")
                except (OSError, ValueError, OverflowError):
                    pass
            table.setItem(row, 2, QTableWidgetItem(modified))
        table_card.body.addWidget(table, 1)
        layout.addWidget(table_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        note = QLabel("清理执行将在后续版本开放，当前页面只做安全发现与预览。")
        note.setObjectName("subtleText")
        footer.addWidget(note, 1)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            # Some Windows/Qt DPI configurations enlarge a fresh dialog past
            # its maximum size.  Re-apply the intended preview size once the
            # native window exists and has settled.
            QTimer.singleShot(80, lambda: self.resize(820, 620))


class ScanReportDialog(QDialog):
    """Read-only summary of a completed scan, including category totals."""

    def __init__(self, result: ScanResult, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("扫描报告 · 盘析")
        self.setObjectName("scanReportDialog")
        self.setModal(True)
        self.resize(760, 600)
        self.setMinimumSize(620, 480)
        self.setMaximumSize(880, 720)
        self._size_settled = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        head = SurfaceCard(variant="normal", margins=(20, 17, 20, 16), spacing=8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(IconLabel("chart", size=21, color=Palette.INK_SOFT))
        title = QLabel("扫描报告")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(Pill(format_capacity(result.total_size)))
        head.body.addLayout(title_row)
        path = QLabel(result.root.path)
        path.setObjectName("mutedText")
        path.setWordWrap(True)
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.body.addWidget(path)
        meta = QLabel(
            f"扫描于 {result.started_at.strftime('%Y-%m-%d %H:%M:%S')}  ·  "
            f"耗时 {result.duration:.1f} 秒  ·  "
            f"读取 {result.files_scanned:,} 个文件 / {result.dirs_scanned:,} 个目录"
        )
        meta.setObjectName("subtleText")
        meta.setWordWrap(True)
        head.body.addWidget(meta)
        layout.addWidget(head)

        stats = SurfaceCard(variant="muted", margins=(18, 13, 18, 13), spacing=8)
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(18)
        for caption, value, unit, icon in (
            ("总大小", format_capacity(result.total_size).rsplit(" ", 1)[0], format_capacity(result.total_size).rsplit(" ", 1)[1], "database"),
            ("文件数量", f"{result.files_scanned:,}", "个", "file"),
            ("子目录", f"{max(0, result.dirs_scanned - 1):,}", "个", "folder"),
            ("权限/链接跳过", f"{result.errors:,}", "个", "shield"),
        ):
            tile = StatTile(caption, value, unit, icon=icon)
            stats_row.addWidget(tile, 1)
        stats.body.addLayout(stats_row)
        layout.addWidget(stats)

        category_card = SurfaceCard(variant="raised", margins=(20, 17, 20, 16), spacing=7)
        category_card.body.addWidget(
            SectionHeader(
                "文件类型构成",
                "按文件扩展名统计真实占用，仅供了解内容结构。",
            )
        )
        category_card.body.addWidget(Divider())
        categories = sorted(
            result.category_sizes.items(),
            key=lambda item: item[1],
            reverse=True,
        )
        if categories:
            for index, (key, size) in enumerate(categories):
                row = QHBoxLayout()
                row.setContentsMargins(0, 4, 0, 2)
                row.setSpacing(9)
                row.addWidget(
                    IconLabel(
                        {
                            "code": "code",
                            "image": "image",
                            "video": "video",
                            "archive": "zip",
                            "installer": "download",
                            "document": "file",
                            "database": "database",
                        }.get(key, "file"),
                        size=14,
                        color=Palette.MUTED,
                    )
                )
                label = QLabel(category_label(key))
                label.setObjectName("rowMeta")
                row.addWidget(label, 1)
                amount = QLabel(format_capacity(size))
                amount.setObjectName("subtleText")
                amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(amount, 0)
                percent = QLabel(format_percent(size / result.total_size if result.total_size else 0, 0))
                percent.setObjectName("subtleText")
                percent.setFixedWidth(40)
                percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(percent, 0)
                category_card.body.addLayout(row)
                bar = UsageBar(
                    height=3,
                    track_color="#E9E3D8",
                    fill_color=Palette.VOLUME_SHADES[min(index, len(Palette.VOLUME_SHADES) - 1)],
                    animated=False,
                )
                bar.set_value(size / result.total_size if result.total_size else 0, animated=False)
                category_card.body.addWidget(bar)
        else:
            empty = QLabel("本次扫描没有可统计的文件类型。")
            empty.setObjectName("mutedText")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            category_card.body.addWidget(empty)
        category_card.body.addStretch(1)
        layout.addWidget(category_card, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        note = QLabel("报告仅基于本次扫描的目录聚合，不会读取或上传文件内容。")
        note.setObjectName("subtleText")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(760, 600))


class HistoryDetailDialog(QDialog):
    def __init__(
        self,
        record: CleanupHistoryRecord,
        failures: list[tuple[str, str]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("清理记录详情 · 盘析")
        self.setObjectName("historyDetailDialog")
        self.setModal(True)
        self.resize(760, 560)
        self.setMinimumSize(640, 440)
        self.setMaximumSize(880, 700)
        self._size_settled = False
        self._build(record, failures)

    def _build(self, record: CleanupHistoryRecord, failures: list[tuple[str, str]]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        header = SurfaceCard(variant="normal", margins=(20, 17, 20, 15), spacing=8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(9)
        title_row.addWidget(IconLabel("history", size=21, color=Palette.INK_SOFT))
        title = QLabel("清理记录详情")
        title.setObjectName("sectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        if record.cancelled:
            status = "已取消"
        elif record.failed:
            status = "部分完成"
        elif record.delete_mode == "permanent":
            status = "永久删除"
        else:
            status = "完成"
        variant = (
            "muted"
            if record.cancelled
            else ("warning" if record.failed or record.delete_mode == "permanent" else "success")
        )
        title_row.addWidget(Pill(status, variant=variant))
        header.body.addLayout(title_row)
        mode_title = "永久删除" if record.delete_mode == "permanent" else "回收站"
        meta = QLabel(
            f"{record.started_at.strftime('%Y-%m-%d %H:%M:%S')}  ·  "
            f"{record.volume}  ·  {mode_title}  ·  耗时 {record.duration:.1f} 秒"
        )
        meta.setObjectName("mutedText")
        header.body.addWidget(meta)
        categories = QLabel(record.category_titles)
        categories.setObjectName("subtleText")
        categories.setWordWrap(True)
        header.body.addWidget(categories)
        layout.addWidget(header)

        stats_card = SurfaceCard(variant="muted", margins=(16, 12, 16, 12), spacing=8)
        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(15)
        number, unit = format_capacity(record.moved_size).rsplit(" ", 1)
        for caption, value, suffix, icon in (
            ("已处理文件", f"{record.moved:,}", "个", "file"),
            ("处理空间", number, unit, "database"),
            ("失败项", f"{record.failed:,}", "个", "warning"),
            ("可用空间变化", format_capacity(record.actual_released).rsplit(" ", 1)[0], format_capacity(record.actual_released).rsplit(" ", 1)[1], "chart"),
        ):
            stats.addWidget(StatTile(caption, value, suffix, icon=icon), 1)
        stats_card.body.addLayout(stats)
        layout.addWidget(stats_card)

        free_row = QHBoxLayout()
        free_row.setContentsMargins(2, 0, 2, 0)
        free_label = QLabel(
            f"清理前可用 {format_capacity(record.free_before)}  →  "
            f"清理后可用 {format_capacity(record.free_after)}"
        )
        free_label.setObjectName("mutedText")
        free_row.addWidget(free_label, 1)
        note = QLabel(
            "文件已永久删除，无法恢复。"
            if record.delete_mode == "permanent"
            else "文件进入回收站后，需清空回收站才会真正释放空间。"
        )
        note.setObjectName("subtleText")
        free_row.addWidget(note, 0)
        layout.addLayout(free_row)

        failure_title = QLabel(
            f"失败明细（{len(failures)}）" if failures else "失败明细"
        )
        failure_title.setObjectName("sectionCaption")
        layout.addWidget(failure_title)
        tree = QTreeWidget()
        tree.setObjectName("duplicateTree")
        tree.setColumnCount(2)
        tree.setHeaderLabels(["文件", "原因"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        if failures:
            for path, error in failures[:500]:
                item = QTreeWidgetItem([path, error])
                item.setToolTip(0, path)
                tree.addTopLevelItem(item)
            layout.addWidget(tree, 1)
        else:
            empty_label = QLabel("本次清理没有失败项。")
            empty_label.setObjectName("mutedText")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty_label, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._size_settled:
            self._size_settled = True
            QTimer.singleShot(80, lambda: self.resize(760, 560))