"""Frameless-window title bar with the primary navigation."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.constants import APP_NAME, APP_NAME_EN, PAGE_TITLES, Page
from ui.components.common import Divider
from ui.components.icons import IconLabel, make_icon
from ui.components.logo import LogoMark
from ui.styles.palette import Palette


class WindowControlButton(QAbstractButton):
    """Minimize / maximize / close control painted with the app's line style."""

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._maximized = False
        self.setFixedSize(43, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        labels = {"minimize": "最小化", "maximize": "最大化", "close": "关闭"}
        self.setToolTip(labels.get(kind, kind))
        self.setAccessibleName(labels.get(kind, kind))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_maximized(self, maximized: bool) -> None:
        self._maximized = maximized
        self.setToolTip("还原" if maximized else "最大化")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hovered = self.underMouse()
        pressed = self.isDown()

        if hovered or pressed:
            if self.kind == "close":
                background = QColor("#E9D8D3") if not pressed else QColor("#E1CCC6")
                foreground = QColor("#8D4D44")
            else:
                background = QColor("#EAE4DA") if not pressed else QColor("#DFD8CC")
                foreground = QColor(Palette.INK_SOFT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 9, 9)
        else:
            foreground = QColor("#6F6A61")

        pen = QPen(foreground)
        pen.setWidthF(1.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        if self.kind == "minimize":
            painter.drawLine(QPoint(int(cx - 5), int(cy + 1)), QPoint(int(cx + 5), int(cy + 1)))
        elif self.kind == "maximize":
            if self._maximized:
                painter.drawRoundedRect(int(cx - 5), int(cy - 4), 8, 8, 1.2, 1.2)
                painter.drawRoundedRect(int(cx - 3), int(cy - 6), 8, 8, 1.2, 1.2)
            else:
                painter.drawRoundedRect(int(cx - 5), int(cy - 5), 10, 10, 1.4, 1.4)
        else:
            painter.drawLine(QPoint(int(cx - 5), int(cy - 5)), QPoint(int(cx + 5), int(cy + 5)))
            painter.drawLine(QPoint(int(cx + 5), int(cy - 5)), QPoint(int(cx - 5), int(cy + 5)))
        painter.end()


class TitleBar(QWidget):
    pageRequested = Signal(int)
    refreshRequested = Signal()
    minimizeRequested = Signal()
    maximizeRequested = Signal()
    closeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(26, 0, 14, 0)
        row.setSpacing(0)

        row.addWidget(LogoMark(34), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(11)
        brand_col = QVBoxLayout()
        brand_col.setContentsMargins(0, 0, 0, 0)
        brand_col.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brandName")
        brand_sub = QLabel(APP_NAME_EN.upper())
        brand_sub.setObjectName("brandSub")
        brand_col.addWidget(brand)
        brand_col.addWidget(brand_sub)
        row.addLayout(brand_col)
        row.addSpacing(23)

        divider = Divider(horizontal=False)
        divider.setFixedHeight(22)
        row.addWidget(divider, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(21)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[int, QPushButton] = {}
        nav_row = QHBoxLayout()
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(3)
        for page in Page:
            button = QPushButton(PAGE_TITLES[page])
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAccessibleName(f"打开{PAGE_TITLES[page]}")
            button.clicked.connect(lambda checked=False, p=page: self.pageRequested.emit(int(p)))
            self._nav_group.addButton(button, int(page))
            self._nav_buttons[int(page)] = button
            nav_row.addWidget(button)
        row.addLayout(nav_row)
        row.addStretch(1)

        local_badge = QWidget()
        local_layout = QHBoxLayout(local_badge)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(5)
        local_layout.addWidget(IconLabel("shield", size=14, color="#969087"))
        local_text = QLabel("仅本地处理")
        local_text.setObjectName("subtleText")
        local_layout.addWidget(local_text)
        local_badge.setToolTip("所有扫描与清理数据仅保存在本机，不上传云端")
        row.addWidget(local_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(13)

        divider2 = Divider(horizontal=False)
        divider2.setFixedHeight(20)
        row.addWidget(divider2, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(8)

        self.refresh_button = QPushButton("刷新磁盘")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.refresh_button.setIcon(make_icon("refresh", Palette.MUTED, 16))
        self.refresh_button.setToolTip("重新读取本机磁盘容量（F5）")
        self.refresh_button.clicked.connect(self.refreshRequested)
        row.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(10)

        controls = QWidget()
        controls_row = QHBoxLayout(controls)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(2)
        self.minimize_button = WindowControlButton("minimize")
        self.maximize_button = WindowControlButton("maximize")
        self.close_button = WindowControlButton("close")
        self.minimize_button.clicked.connect(self.minimizeRequested)
        self.maximize_button.clicked.connect(self.maximizeRequested)
        self.close_button.clicked.connect(self.closeRequested)
        controls_row.addWidget(self.minimize_button)
        controls_row.addWidget(self.maximize_button)
        controls_row.addWidget(self.close_button)
        row.addWidget(controls, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_active_page(Page.DASHBOARD)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    # ------------------------------------------------------------------
    def set_active_page(self, page: int) -> None:
        button = self._nav_buttons.get(int(page))
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.set_maximized(maximized)

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setText("读取中…" if refreshing else "刷新磁盘")
        if refreshing:
            self.refresh_button.setIcon(make_icon("refresh", "#B6B0A6", 16))
        else:
            self.refresh_button.setIcon(make_icon("refresh", Palette.MUTED, 16))

    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None:
                handle.startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximizeRequested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)