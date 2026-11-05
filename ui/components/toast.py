"""Non-blocking in-window status toast."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from ui.components.icons import IconLabel, icon_pixmap


class Toast(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setObjectName("toast")
        self.setStyleSheet(
            """
            QWidget#toast {
                background-color: #2E2B26;
                border-radius: 12px;
            }
            QLabel#toastText {
                color: #F8F3E9;
                font-size: 12px;
                font-weight: 500;
            }
            """
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(15, 9, 17, 9)
        row.setSpacing(8)
        self._icon = IconLabel("check", size=15, color="#C9D2BB")
        row.addWidget(self._icon)
        self._label = QLabel("")
        self._label.setObjectName("toastText")
        row.addWidget(self._label)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self.hide()

    def show_message(self, text: str, *, duration: int = 2400, icon: str = "check") -> None:
        self._label.setText(text)
        self._icon.setPixmap(icon_pixmap(icon, 15, "#C9D2BB"))
        self.adjustSize()
        if self.parentWidget() is not None:
            parent_rect = self.parentWidget().rect()
            x = parent_rect.center().x() - self.width() // 2
            y = parent_rect.bottom() - self.height() - 28
            self.move(max(16, x), max(16, y))
        self.raise_()
        self.show()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._hide_timer.start(duration)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish_hide_once)
        self._fade.start()

    def _finish_hide_once(self) -> None:
        try:
            self._fade.finished.disconnect(self._finish_hide_once)
        except (RuntimeError, TypeError):
            pass
        self.hide()