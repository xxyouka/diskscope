"""Small composable building blocks shared by pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.components.icons import IconLabel, make_icon
from ui.styles.palette import Palette


class SurfaceCard(QFrame):
    """The one card surface used throughout the app.

    ``variant`` selects between the normal elevated paper card and the muted
    inset panel.  Avoids a proliferation of one-off QSS rules.
    """

    def __init__(
        self,
        parent=None,
        *,
        variant: str = "normal",
        margins: tuple[int, int, int, int] = (22, 20, 22, 20),
        spacing: int = 14,
    ) -> None:
        super().__init__(parent)
        object_name = {
            "normal": "surfaceCard",
            "raised": "surfaceCardRaised",
            "muted": "mutedCard",
            "dark": "darkCard",
        }.get(variant, "surfaceCard")
        self.setObjectName(object_name)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class Divider(QFrame):
    def __init__(self, horizontal: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("hairline" if horizontal else "verticalHairline")
        if horizontal:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        else:
            self.setFixedWidth(1)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)


class SectionHeader(QWidget):
    """Title / supporting caption / optional trailing widget."""

    def __init__(
        self,
        title: str,
        caption: str = "",
        *,
        trailing: QWidget | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        text_col.addWidget(title_label)
        if caption:
            caption_label = QLabel(caption)
            caption_label.setObjectName("sectionCaption")
            caption_label.setWordWrap(True)
            text_col.addWidget(caption_label)
        row.addLayout(text_col, 1)
        if trailing is not None:
            row.addWidget(trailing, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class Pill(QLabel):
    def __init__(self, text: str, *, variant: str = "muted", parent=None) -> None:
        super().__init__(text, parent)
        object_name = {
            "success": "statusSuccess",
            "warning": "statusWarning",
            "danger": "statusDanger",
            "muted": "statusMuted",
        }.get(variant, "statusMuted")
        self.setObjectName(object_name)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class KeyValueRow(QWidget):
    """A restrained two-column stat line."""

    def __init__(self, key: str, value: str, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.key_label = QLabel(key)
        self.key_label.setObjectName("mutedText")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("strongText")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.key_label, 1)
        row.addWidget(self.value_label, 0)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class StatTile(QWidget):
    """Compact metric block used in summary rows."""

    def __init__(
        self,
        caption: str,
        value: str = "—",
        unit: str = "",
        *,
        icon: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        caption_row = QHBoxLayout()
        caption_row.setContentsMargins(0, 0, 0, 0)
        caption_row.setSpacing(6)
        if icon:
            caption_row.addWidget(IconLabel(icon, size=14, color=Palette.MUTED))
        self.caption_label = QLabel(caption)
        self.caption_label.setObjectName("sectionCaption")
        caption_row.addWidget(self.caption_label)
        caption_row.addStretch(1)
        col.addLayout(caption_row)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)
        value_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.unit_label = QLabel(unit)
        self.unit_label.setObjectName("metricUnit")
        self.unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.unit_label.setContentsMargins(0, 0, 0, 3)
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label)
        value_row.addStretch(1)
        col.addLayout(value_row)

    def set_value(self, value: str, unit: str = "") -> None:
        self.value_label.setText(value)
        self.unit_label.setText(unit)


def icon_button(name: str, tooltip: str, parent=None, color: str = Palette.MUTED):
    from PySide6.QtWidgets import QPushButton

    button = QPushButton(parent)
    button.setObjectName("iconButton")
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setIcon(make_icon(name, color, 17))
    button.setFixedSize(31, 31)
    button.setToolTip(tooltip)
    return button