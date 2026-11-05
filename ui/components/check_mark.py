"""A small custom check control used by cleanup candidate cards."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton

from ui.styles.palette import Palette


class CheckMark(QAbstractButton):
    def __init__(self, parent=None, *, checked: bool = False) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("选择清理项目")

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        body = QRectF(1.0, 1.0, 20.0, 20.0)
        enabled = self.isEnabled()

        if self.isChecked():
            border = QColor(Palette.DARK if enabled else "#BEB8AE")
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(border)
            painter.drawRoundedRect(body, 7.0, 7.0)
            pen = QPen(QColor("#FBF7EF"))
            pen.setWidthF(1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(6.2, 11.3)
            path.lineTo(9.4, 14.4)
            path.lineTo(16.0, 7.5)
            painter.drawPath(path)
        else:
            border_color = QColor("#AFA698" if enabled else "#DDD7CE")
            painter.setPen(QPen(border_color, 1.2))
            painter.setBrush(QColor("#FCFAF6" if enabled else "#F1ECE4"))
            painter.drawRoundedRect(body, 7.0, 7.0)
            if self.underMouse() and enabled:
                painter.setPen(QPen(QColor("#A49C90"), 1.2))
                painter.drawRoundedRect(body.adjusted(0.4, 0.4, -0.4, -0.4), 6.6, 6.6)

        if self.hasFocus():
            painter.setPen(QPen(QColor("#938B7E"), 1.0, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(body.adjusted(-0.6, -0.6, 0.6, 0.6), 8.0, 8.0)
        painter.end()