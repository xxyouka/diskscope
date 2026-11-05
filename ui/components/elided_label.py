"""A QLabel that paints an ellipsis instead of forcing the layout wider."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._full_text = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(24)
        self.setToolTip(text)
        self._apply_elision()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elision()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(16, self.width() - 2)
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, self._mode, width)
        super().setText(elided)