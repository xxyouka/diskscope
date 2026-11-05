"""Shared page chrome and stage-safe empty states."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.components.common import Pill
from ui.components.icons import IconLabel


class BasePage(QWidget):
    """Base class for pages: transparent background and a common padding grid."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)


def page_heading(
    title: str,
    subtitle: str,
    *,
    eyebrow: str = "",
    trailing: QWidget | None = None,
) -> QWidget:
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(16)

    col = QVBoxLayout()
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(4)
    if eyebrow:
        eyebrow_label = QLabel(eyebrow)
        eyebrow_label.setObjectName("pageEyebrow")
        col.addWidget(eyebrow_label)
    title_label = QLabel(title)
    title_label.setObjectName("pageTitle")
    col.addWidget(title_label)
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("pageSubtitle")
    subtitle_label.setWordWrap(True)
    col.addWidget(subtitle_label)
    row.addLayout(col, 1)
    if trailing is not None:
        row.addWidget(trailing, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    return wrapper


def stage_notice(icon: str, title: str, body: str, *, badge: str = "下一阶段接入") -> QWidget:
    """A deliberate, honest placeholder used while a module is being built."""

    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(30, 30, 30, 30)
    layout.setSpacing(10)
    icon_row = QHBoxLayout()
    icon_row.setSpacing(10)
    icon_row.addWidget(IconLabel(icon, size=18, color="#817B71"))
    label = QLabel(title)
    label.setObjectName("emptyTitle")
    icon_row.addWidget(label)
    icon_row.addStretch(1)
    icon_row.addWidget(Pill(badge))
    layout.addLayout(icon_row)
    body_label = QLabel(body)
    body_label.setObjectName("emptyBody")
    body_label.setWordWrap(True)
    body_label.setMaximumWidth(620)
    layout.addWidget(body_label)
    layout.addStretch(1)
    return panel