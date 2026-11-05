"""Expandable cleanup candidate card."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.formatting import format_capacity, split_size
from core.cleanup_engine import CleanupCategory
from ui.components.check_mark import CheckMark
from ui.components.common import Divider, IconLabel, Pill
from ui.components.elided_label import ElidedLabel
from ui.components.icons import make_icon
from ui.styles.palette import Palette


class CleanupItemCard(QFrame):
    selectionChanged = Signal(object, bool)  # CleanupCategory, selected
    previewRequested = Signal(object)
    dangerRequested = Signal(object)

    def __init__(
        self,
        category: CleanupCategory,
        *,
        selected: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.category = category
        self._selected = selected
        self._expanded = False
        self.setObjectName("cleanupCard")
        self.setProperty("selected", selected)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if category.cleanable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("点击卡片或左侧方框选择")
        else:
            self.setToolTip("该类仅识别，不提供自动清理")

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 13, 15, 12)
        root.setSpacing(7)

        main = QHBoxLayout()
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(11)
        self.check = CheckMark(checked=selected)
        self.check.setAccessibleName(f"选择 {category.title}")
        self.check.setEnabled(category.cleanable)
        if category.cleanable:
            self.check.setToolTip("点击选择该清理项")
        else:
            self.check.setToolTip("该类内容仅识别，当前版本不提供自动清理")
        self.check.toggled.connect(self._on_check)
        main.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)

        icon_box = QWidget()
        icon_box.setFixedSize(37, 37)
        icon_box.setStyleSheet("background: #EDE7DD; border-radius: 11px;")
        icon_layout = QVBoxLayout(icon_box)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(IconLabel(category.icon, size=18, color=Palette.INK_SOFT))
        main.addWidget(icon_box, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        title = QLabel(category.title)
        title.setObjectName("rowTitle")
        title_row.addWidget(title)
        risk_variant = {
            "safe": "success",
            "review": "warning",
            "risk": "danger",
        }.get(category.risk, "muted")
        title_row.addWidget(Pill(category.risk_label, variant=risk_variant))
        if not category.cleanable:
            title_row.addWidget(Pill("仅识别", variant="muted"))
        title_row.addStretch(1)
        text_col.addLayout(title_row)
        description = QLabel(category.description)
        description.setObjectName("rowMeta")
        description.setWordWrap(True)
        text_col.addWidget(description)
        main.addLayout(text_col, 1)

        size_col = QVBoxLayout()
        size_col.setContentsMargins(0, 0, 0, 0)
        size_col.setSpacing(0)
        number, unit = split_size(category.total_size)
        size_value = QLabel(number)
        size_value.setStyleSheet(
            "color: #292723; font-size: 20px; font-weight: 600;"
        )
        size_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_col.addWidget(size_value)
        size_unit = QLabel(f"{unit} 可释放")
        size_unit.setObjectName("subtleText")
        size_unit.setAlignment(Qt.AlignmentFlag.AlignRight)
        size_col.addWidget(size_unit)
        main.addLayout(size_col, 0)

        self.expand_button = QPushButton()
        self.expand_button.setObjectName("iconButton")
        self.expand_button.setFixedSize(25, 25)
        self.expand_button.setIcon(make_icon("chevron-down", Palette.MUTED, 14))
        self.expand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_button.setToolTip("展开详情")
        self.expand_button.clicked.connect(self._toggle_expanded)
        main.addWidget(self.expand_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(main)

        self.details = QWidget()
        details_layout = QVBoxLayout(self.details)
        details_layout.setContentsMargins(68, 0, 0, 0)
        details_layout.setSpacing(7)
        details_layout.addWidget(Divider())
        reason = QLabel(category.reason)
        reason.setObjectName("mutedText")
        reason.setWordWrap(True)
        details_layout.addWidget(reason)
        if category.samples:
            samples_title = QLabel("包含的文件示例")
            samples_title.setObjectName("subtleText")
            details_layout.addWidget(samples_title)
            for sample in category.samples[:4]:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(7)
                row.addWidget(IconLabel("file", size=12, color=Palette.MUTED_LIGHT))
                name = ElidedLabel(Path(sample.path).name, mode=Qt.TextElideMode.ElideMiddle)
                name.setObjectName("rowMeta")
                name.setToolTip(sample.path)
                row.addWidget(name, 1)
                sample_size = QLabel(format_capacity(sample.size))
                sample_size.setObjectName("subtleText")
                row.addWidget(sample_size, 0)
                details_layout.addLayout(row)
        else:
            summary_note = QLabel("此类别通过系统接口汇总，暂不列出文件明细。")
            summary_note.setObjectName("subtleText")
            summary_note.setWordWrap(True)
            details_layout.addWidget(summary_note)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(8)
        stats = QLabel(
            f"{category.file_count:,} 个文件"
            + (f"  ·  {category.errors:,} 个跳过" if category.errors else "")
        )
        stats.setObjectName("subtleText")
        footer.addWidget(stats, 1)
        preview = QPushButton("查看清单")
        preview.setObjectName("quietButton")
        preview.setCursor(Qt.CursorShape.PointingHandCursor)
        preview.clicked.connect(lambda: self.previewRequested.emit(self.category))
        preview.setVisible(bool(category.samples))
        footer.addWidget(preview, 0)
        details_layout.addLayout(footer)
        if category.key == "wechat":
            self.wipe_button = QPushButton("彻底删除微信数据…")
            self.wipe_button.setObjectName("dangerButton")
            self.wipe_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.wipe_button.setToolTip(
                "删除整个微信账号目录，包括消息数据库和聊天记录；需要微信完全退出"
            )
            self.wipe_button.clicked.connect(
                lambda: self.dangerRequested.emit(self.category)
            )
            details_layout.addWidget(self.wipe_button)
        self.details.setVisible(False)
        root.addWidget(self.details)

    # ------------------------------------------------------------------
    @property
    def is_selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self.check.blockSignals(True)
        self.check.setChecked(selected)
        self.check.blockSignals(False)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_check(self, checked: bool) -> None:
        self._selected = checked
        self.setProperty("selected", checked)
        self.style().unpolish(self)
        self.style().polish(self)
        self.selectionChanged.emit(self.category, checked)

    def _toggle_expanded(self) -> None:
        self._expanded = not self._expanded
        self.details.setVisible(self._expanded)
        self.expand_button.setIcon(
            make_icon(
                "chevron-down" if self._expanded else "chevron-right",
                Palette.MUTED,
                14,
            )
        )
        self.expand_button.setToolTip("收起详情" if self._expanded else "展开详情")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self.category.cleanable or event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        widget = self.childAt(event.position().toPoint())
        while widget is not None and widget is not self:
            if isinstance(widget, QAbstractButton):
                # The checkbox, expand toggle and preview button handle their
                # own clicks; do not toggle twice.
                super().mouseReleaseEvent(event)
                return
            widget = widget.parentWidget()
        self.check.toggle()
        event.accept()