"""Cleanup history read from the persistent local SQLite database."""

from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, split_size
from services.history_service import CleanupHistoryRecord, HistoryService, HistoryStats
from ui.components.dialogs import HistoryDetailDialog
from ui.components.common import Divider, IconLabel, Pill, SectionHeader, SurfaceCard, StatTile
from ui.pages.base_page import BasePage, page_heading
from ui.styles.palette import Palette

logger = logging.getLogger(__name__)


class _HistoryChart(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self.setMinimumHeight(220)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self._data = list(data)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        left_margin = 46
        right_margin = 16
        top = 22
        bottom = 31
        plot = QRectF(
            left_margin,
            top,
            max(10, self.width() - left_margin - right_margin),
            max(10, self.height() - top - bottom),
        )
        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        if not self._data:
            for index in range(5):
                y = plot.top() + plot.height() * index / 4
                painter.setPen(QPen(QColor(224, 218, 208, 180), 1, Qt.PenStyle.DashLine))
                painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            painter.setPen(QColor(Palette.MUTED))
            painter.drawText(
                plot,
                Qt.AlignmentFlag.AlignCenter,
                "首次清理完成后，这里会生成真实的处理趋势",
            )
            painter.end()
            return

        max_value = max((value for _, value in self._data), default=0)
        max_value = max(1, max_value)
        levels = 4
        for index in range(levels + 1):
            ratio = index / levels
            y = plot.bottom() - plot.height() * ratio
            painter.setPen(QPen(QColor(224, 218, 208, 180), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(plot.left()), int(y), int(plot.right()), int(y))
            painter.setPen(QColor(Palette.MUTED_LIGHT))
            painter.drawText(
                QRectF(0, y - 8, left_margin - 10, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_capacity(max_value * ratio),
            )

        count = len(self._data)
        step = plot.width() / max(1, count - 1) if count > 1 else 0
        points = []
        for index, (label, value) in enumerate(self._data):
            x = plot.left() + step * index if count > 1 else plot.center().x()
            y = plot.bottom() - (value / max_value) * plot.height()
            points.append((x, y, label, value))

        path = QPainterPath()
        if points:
            path.moveTo(points[0][0], plot.bottom())
            for x, y, _label, _value in points:
                path.lineTo(x, y)
            path.lineTo(points[-1][0], plot.bottom())
            path.closeSubpath()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(206, 196, 180, 55))
            painter.drawPath(path)

        line = QPainterPath()
        for index, (x, y, _label, _value) in enumerate(points):
            if index == 0:
                line.moveTo(x, y)
            else:
                line.lineTo(x, y)
        pen = QPen(QColor(Palette.INK), 1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(line)

        for index, (x, y, label, value) in enumerate(points):
            painter.setPen(QPen(QColor(Palette.SURFACE), 1.5))
            painter.setBrush(QColor(Palette.INK))
            painter.drawEllipse(QRectF(x - 3.2, y - 3.2, 6.4, 6.4))
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(font)
            painter.drawText(
                QRectF(x - 34, plot.bottom() + 7, 68, 15),
                Qt.AlignmentFlag.AlignHCenter,
                label,
            )
            if index == len(points) - 1 or value == max_value:
                painter.setPen(QColor(Palette.INK_SOFT))
                painter.drawText(
                    QRectF(x - 44, y - 22, 88, 16),
                    Qt.AlignmentFlag.AlignHCenter,
                    format_capacity(value),
                )
        painter.end()


class _HistoryRow(QWidget):
    clicked = Signal(object)

    def __init__(self, record: CleanupHistoryRecord, parent=None) -> None:
        super().__init__(parent)
        self.record = record
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(59)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        date = record.started_at.strftime("%m-%d %H:%M")
        date_label = QLabel(date)
        date_label.setObjectName("subtleText")
        top.addWidget(date_label)
        top.addStretch(1)
        if record.cancelled:
            status = "已取消"
        elif record.failed:
            status = "部分完成"
        elif record.delete_mode == "permanent":
            status = "永久删除"
        else:
            status = "完成"
        pill = Pill(
            status,
            variant=(
                "muted"
                if record.cancelled
                else ("warning" if record.failed or record.delete_mode == "permanent" else "success")
            ),
        )
        top.addWidget(pill)
        text.addLayout(top)
        title = QLabel(record.category_titles)
        title.setObjectName("rowMeta")
        title.setWordWrap(False)
        text.addWidget(title)
        layout.addLayout(text, 1)
        size_col = QVBoxLayout()
        size_col.setContentsMargins(0, 0, 0, 0)
        size_col.setSpacing(1)
        number, unit = split_size(record.moved_size)
        amount = QLabel(f"{number} {unit}")
        amount.setObjectName("strongText")
        amount.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_col.addWidget(amount)
        files = QLabel(f"{record.moved:,} 个文件")
        files.setObjectName("subtleText")
        files.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_col.addWidget(files)
        layout.addLayout(size_col, 0)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit(self.record)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F3EEE6"))
            painter.drawRoundedRect(self.rect().adjusted(0, 1, -1, -1), 9, 9)
        painter.setPen(QPen(QColor("#E8E2D8"), 1.0))
        painter.drawLine(10, self.height() - 1, self.width() - 10, self.height() - 1)
        painter.end()


class HistoryPage(BasePage):
    overviewRequested = Signal()
    cleanupRequested = Signal()

    def __init__(self, history_service: HistoryService, parent=None) -> None:
        super().__init__(parent)
        self._service = history_service
        self._records: list[CleanupHistoryRecord] = []
        self._build()
        self.refresh_history()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(34, 27, 34, 28)
        outer.setSpacing(20)
        self.heading_pill = Pill("0 条记录", variant="muted")
        outer.addWidget(
            page_heading(
                "历史记录",
                "每次清理的清单、处理结果和容量变化保存在本地 SQLite 数据库。",
                eyebrow="HISTORY",
                trailing=self.heading_pill,
            )
        )

        stats = QHBoxLayout()
        stats.setContentsMargins(0, 0, 0, 0)
        stats.setSpacing(14)
        self.stat_size = StatTile("累计处理空间", "0", "B")
        self.stat_count = StatTile("清理次数", "0", "次")
        self.stat_average = StatTile("平均每次处理", "0", "B")
        for caption, tile, icon in (
            ("累计处理空间", self.stat_size, "database"),
            ("清理次数", self.stat_count, "broom"),
            ("平均每次处理", self.stat_average, "chart"),
        ):
            card = SurfaceCard(variant="normal", margins=(20, 16, 20, 15), spacing=4)
            card.setMinimumHeight(108)
            card.body.addWidget(IconLabel(icon, size=17, color=Palette.MUTED))
            card.body.addWidget(tile)
            stats.addWidget(card, 1)
        outer.addLayout(stats)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)

        chart_card = SurfaceCard(variant="normal", margins=(22, 19, 22, 16), spacing=9)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(
            SectionHeader(
                "历史处理空间",
                "记录每次清理实际移入回收站的文件容量。",
            ),
            1,
        )
        chart_card.body.addLayout(head)
        self.chart = _HistoryChart()
        chart_card.body.addWidget(self.chart, 1)
        chart_card.body.addWidget(Divider())
        self.chart_note = QLabel(
            "文件默认移入 Windows 回收站；清空回收站后才会真正释放空间。"
        )
        self.chart_note.setObjectName("subtleText")
        chart_card.body.addWidget(self.chart_note)
        content.addWidget(chart_card, 1)

        recent = SurfaceCard(variant="normal", margins=(18, 18, 18, 15), spacing=8)
        recent.setFixedWidth(370)
        recent_head = QHBoxLayout()
        recent_head.setContentsMargins(0, 0, 0, 0)
        recent_head.addWidget(SectionHeader("最近清理", "点击记录查看失败明细"), 1)
        recent.body.addLayout(recent_head)
        recent.body.addWidget(Divider())
        self.recent_scroll = QScrollArea()
        self.recent_scroll.setWidgetResizable(True)
        self.recent_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.recent_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.recent_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.recent_container = QWidget()
        self.recent_layout = QVBoxLayout(self.recent_container)
        self.recent_layout.setContentsMargins(0, 0, 3, 0)
        self.recent_layout.setSpacing(0)
        self.recent_layout.addStretch(1)
        self.recent_scroll.setWidget(self.recent_container)
        recent.body.addWidget(self.recent_scroll, 1)
        self.cleanup_button = QPushButton("前往清理建议")
        self.cleanup_button.setObjectName("secondaryButton")
        self.cleanup_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cleanup_button.clicked.connect(self.cleanupRequested)
        recent.body.addWidget(self.cleanup_button)
        content.addWidget(recent, 0)

        outer.addLayout(content, 1)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.refresh_history()

    def refresh_history(self) -> None:
        try:
            stats = self._service.stats()
            records = self._service.recent(6)
            chart_data = self._service.chart_data(6)
        except Exception:
            logger.exception("Could not refresh cleanup history")
            return
        self._records = records
        self.heading_pill.setText(f"{stats.runs} 条记录")
        number, unit = split_size(stats.moved_size)
        self.stat_size.set_value(number, unit)
        self.stat_count.set_value(str(stats.runs), "次")
        number, unit = split_size(stats.average_size)
        self.stat_average.set_value(number, unit)
        self.chart.set_data(chart_data)
        self._rebuild_recent(records)
        if stats.runs:
            self.chart_note.setText(
                f"已处理 {stats.moved_files:,} 个文件；累计移入回收站 "
                f"{format_capacity(stats.moved_size)}，失败 {stats.failed:,} 个。"
            )
        else:
            self.chart_note.setText(
                "文件默认移入 Windows 回收站；清空回收站后才会真正释放空间。"
            )

    def _rebuild_recent(self, records: list[CleanupHistoryRecord]) -> None:
        while self.recent_layout.count():
            item = self.recent_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not records:
            empty = QWidget()
            empty_layout = QVBoxLayout(empty)
            empty_layout.setContentsMargins(18, 22, 18, 22)
            empty_layout.setSpacing(8)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(
                IconLabel("broom", size=26, color="#918B82"),
                0,
                Qt.AlignmentFlag.AlignHCenter,
            )
            title = QLabel("暂无清理记录")
            title.setObjectName("emptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(title)
            body = QLabel("清理结果会记录清理前后容量、实际处理空间和失败原因。")
            body.setObjectName("emptyBody")
            body.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.setWordWrap(True)
            empty_layout.addWidget(body)
            self.recent_layout.addWidget(empty)
            self.recent_layout.addStretch(1)
            return
        for record in records:
            row = _HistoryRow(record)
            row.clicked.connect(self._open_record)
            self.recent_layout.addWidget(row)
        self.recent_layout.addStretch(1)

    def _open_record(self, record: CleanupHistoryRecord) -> None:
        failures = self._service.failures_for(record.id)
        HistoryDetailDialog(record, failures, self).exec()