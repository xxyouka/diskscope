"""Projected disk-impact donut built from real capacity counters."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.formatting import format_percent
from ui.styles.palette import Palette


class ImpactGauge(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._drive = "C:"
        self._total = 0
        self._used_before = 0
        self._release = 0
        self.setMinimumSize(190, 190)

    def set_values(
        self,
        *,
        drive: str,
        total: int,
        used_before: int,
        release: int,
    ) -> None:
        self._drive = drive
        self._total = max(0, int(total))
        self._used_before = max(0, int(used_before))
        self._release = max(0, int(release))
        self.update()

    def _font(self, px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(px)
        font.setWeight(weight)
        return font

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height()) - 18
        if side <= 20:
            painter.end()
            return
        rect = QRectF(
            (self.width() - side) / 2.0,
            (self.height() - side) / 2.0,
            side,
            side,
        )
        stroke = max(13.0, side * 0.075)
        ring = rect.adjusted(stroke / 2, stroke / 2, -stroke / 2, -stroke / 2)

        track = QPen(QColor("#EAE4DA"), stroke)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(ring, 90 * 16, -360 * 16)

        if self._total > 0:
            used_after = max(0, self._used_before - self._release)
            used_fraction = max(0.0, min(1.0, used_after / self._total))
            before_fraction = max(0.0, min(1.0, self._used_before / self._total))
            after_fraction = max(0.0, min(1.0, (self._total - used_after) / self._total))

            # A soft outer mark shows the pre-cleanup boundary; the dark arc
            # shows the projected used share after the selected items.
            if self._release > 0:
                outer = ring.adjusted(-stroke * 0.68, -stroke * 0.68, stroke * 0.68, stroke * 0.68)
                painter.setPen(QPen(QColor("#C9C0B1"), 2.0))
                painter.drawArc(
                    outer,
                    90 * 16,
                    int(-360 * 16 * before_fraction),
                )
                # Reclaimed segment in warm cream.
                inner = ring.adjusted(stroke * 0.37, stroke * 0.37, -stroke * 0.37, -stroke * 0.37)
                painter.setPen(QPen(QColor("#F6F1E7"), max(3.0, stroke * 0.20)))
                start = 90 - int(360 * after_fraction)
                span = -int(360 * (before_fraction - after_fraction))
                painter.drawArc(inner, start * 16, span * 16)

            arc = QPen(QColor(Palette.DARK), stroke)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            painter.drawArc(ring, 90 * 16, -int(360 * 16 * used_fraction))

            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(10, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(rect.x(), rect.center().y() - 36, rect.width(), 16),
                Qt.AlignmentFlag.AlignCenter,
                f"{self._drive} 盘",
            )
            painter.setPen(QColor(Palette.INK))
            painter.setFont(self._font(max(24, int(side * 0.16)), QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(rect.x(), rect.center().y() - 18, rect.width(), 38),
                Qt.AlignmentFlag.AlignCenter,
                format_percent(used_fraction),
            )
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(10))
            painter.drawText(
                QRectF(rect.x(), rect.center().y() + 21, rect.width(), 16),
                Qt.AlignmentFlag.AlignCenter,
                "清理后已用（预计）",
            )
        else:
            painter.setPen(QColor(Palette.MUTED))
            painter.setFont(self._font(12))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "等待扫描")
        painter.end()