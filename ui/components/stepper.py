"""Compact integer stepper used by settings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


class NumberStepper(QFrame):
    valueChanged = Signal(int)

    def __init__(
        self,
        *,
        minimum: int = 1,
        maximum: int = 16,
        value: int = 4,
        suffix: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stepper")
        self._minimum = minimum
        self._maximum = maximum
        self._value = max(minimum, min(maximum, value))
        self._suffix = suffix
        self.setFixedSize(116, 32)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        self.minus = QPushButton("−")
        self.minus.setObjectName("stepperButton")
        self.minus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.minus.setFixedSize(24, 24)
        self.minus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.minus.setAccessibleName("减少")
        self.plus = QPushButton("+")
        self.plus.setObjectName("stepperButton")
        self.plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.plus.setFixedSize(24, 24)
        self.plus.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plus.setAccessibleName("增加")

        self.value_label = QLabel()
        self.value_label.setObjectName("stepperValue")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setObjectName("stepperValue")

        layout.addWidget(self.minus)
        layout.addWidget(self.value_label, 1)
        layout.addWidget(self.plus)

        self.minus.clicked.connect(lambda: self.setValue(self._value - 1))
        self.plus.clicked.connect(lambda: self.setValue(self._value + 1))
        self._refresh()

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - mirrors QSpinBox API
        value = max(self._minimum, min(self._maximum, int(value)))
        if value == self._value:
            return
        self._value = value
        self._refresh()
        self.valueChanged.emit(value)

    def _refresh(self) -> None:
        self.value_label.setText(f"{self._value}{self._suffix}")
        self.minus.setEnabled(self._value > self._minimum)
        self.plus.setEnabled(self._value < self._maximum)
        self.setAccessibleName(f"扫描线程数 {self._value}")