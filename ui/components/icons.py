"""A tiny, dependency-free line-icon set rendered through QtSvg.

Icons are stored as monochrome SVG templates and tinted at runtime.  This
keeps the interface crisp at any DPI without shipping dozens of colored PNGs.
"""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel

_SVG: dict[str, str] = {
    "refresh": """
        <path d="M20.2 11.2a8.2 8.2 0 1 0-.7 4.8"/>
        <path d="M20.4 5.7v5.7h-5.7"/>
    """,
    "disk": """
        <rect x="3.4" y="5.3" width="17.2" height="13.4" rx="3.0"/>
        <circle cx="12" cy="12" r="2.1"/>
        <path d="M16.7 9.4h.01"/>
    """,
    "folder": """
        <path d="M3.5 8.2a2 2 0 0 1 2-2h4l2 2.1h7a2 2 0 0 1 2 2v6.2a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>
        <path d="M3.9 10.3h16.2"/>
    """,
    "chart": """
        <path d="M4 19.2h16"/>
        <path d="M6.2 16V11"/>
        <path d="M10.9 16V7.2"/>
        <path d="M15.6 16v-3.4"/>
        <path d="M20.1 16V5.2"/>
    """,
    "history": """
        <path d="M4.2 10.2A8 8 0 1 1 5 15.9"/>
        <path d="M4.1 4.9v5.4h5.4"/>
        <path d="M12 7.9v4.5l2.9 1.7"/>
    """,
    "settings": """
        <path d="M4 7.2h10.2"/>
        <path d="M18.1 7.2H20"/>
        <circle cx="16.2" cy="7.2" r="2.0"/>
        <path d="M4 16.8h4.4"/>
        <path d="M12.4 16.8H20"/>
        <circle cx="10.4" cy="16.8" r="2.0"/>
        <path d="M4 12h5.3"/>
        <path d="M13.3 12H20"/>
        <circle cx="11.3" cy="12" r="2.0"/>
    """,
    "broom": """
        <path d="M14.6 4.4 10.2 9"/>
        <path d="M9.1 8.2l6.7 6.6"/>
        <path d="M8.2 11.5c-2.4 2.3-2.9 5-2.1 8.1 2.6-1.2 5.5-2.4 8.2-2.1"/>
        <path d="M8.4 11.6 4.9 15c1.4 1.4 3 2.7 4.4 4.2l3.1-3.3"/>
    """,
    "sparkles": """
        <path d="M12 3.4c.5 4.1 2.2 5.8 6.2 6.3-4 .5-5.7 2.2-6.2 6.3-.5-4.1-2.2-5.8-6.2-6.3 4-.5 5.7-2.2 6.2-6.3Z"/>
        <path d="M18.6 15.1c.2 1.8 1 2.6 2.8 2.8-1.8.2-2.6 1-2.8 2.8-.2-1.8-1-2.6-2.8-2.8 1.8-.2 2.6-1 2.8-2.8Z"/>
    """,
    "shield": """
        <path d="M12 3.3 19 6v5.4c0 4.3-2.8 7.7-7 9.3-4.2-1.6-7-5-7-9.3V6Z"/>
        <path d="m8.9 12 2.1 2.1 4.2-4.3"/>
    """,
    "info": """
        <circle cx="12" cy="12" r="8.5"/>
        <path d="M12 10.8v5"/>
        <path d="M12 7.7h.01"/>
    """,
    "chevron-right": """
        <path d="m9.7 6.2 5.8 5.8-5.8 5.8"/>
    """,
    "chevron-down": """
        <path d="m6.2 9.7 5.8 5.8 5.8-5.8"/>
    """,
    "arrow-up": """
        <path d="M12 19V5"/>
        <path d="m6.3 10.7 5.7-5.7 5.7 5.7"/>
    """,
    "arrow-right": """
        <path d="M5 12h14"/>
        <path d="m13.3 6.3 5.7 5.7-5.7 5.7"/>
    """,
    "search": """
        <circle cx="10.8" cy="10.8" r="6.3"/>
        <path d="m15.5 15.5 4.1 4.1"/>
    """,
    "database": """
        <ellipse cx="12" cy="5.8" rx="7.2" ry="2.7"/>
        <path d="M4.8 5.8v6.1c0 1.5 3.2 2.7 7.2 2.7s7.2-1.2 7.2-2.7V5.8"/>
        <path d="M4.8 11.9v6.1c0 1.5 3.2 2.7 7.2 2.7s7.2-1.2 7.2-2.7v-6.1"/>
    """,
    "layers": """
        <path d="m12 3.8 8 4.1-8 4.1-8-4.1Z"/>
        <path d="m4 12.2 8 4.1 8-4.1"/>
        <path d="m4 16.3 8 4.1 8-4.1"/>
    """,
    "warning": """
        <path d="M12 3.9 21 19.7H3Z"/>
        <path d="M12 9.1v4.6"/>
        <path d="M12 16.8h.01"/>
    """,
    "trash": """
        <path d="M4.8 7.1h14.4"/>
        <path d="M9 7.1V4.8h6v2.3"/>
        <path d="m6.7 7.1.8 12.1h9l.8-12.1"/>
        <path d="M10.2 10.6v5.4"/>
        <path d="M13.8 10.6v5.4"/>
    """,
    "external": """
        <path d="M14.2 4.6h5.2v5.2"/>
        <path d="M19.4 4.6 11 13"/>
        <path d="M18.9 13.7v4.2a2 2 0 0 1-2 2H5.6a2 2 0 0 1-2-2V6.6a2 2 0 0 1 2-2h4.2"/>
    """,
    "check": """
        <path d="m5.2 12.5 4.2 4.2 9.4-9.5"/>
    """,
    "download": """
        <path d="M12 4.2v10.6"/>
        <path d="m7.4 10.3 4.6 4.6 4.6-4.6"/>
        <path d="M4.5 19.5h15"/>
    """,
    "clock": """
        <circle cx="12" cy="12" r="8.4"/>
        <path d="M12 7.4v5l3.2 1.9"/>
    """,
    "bell": """
        <path d="M6.5 10.2a5.5 5.5 0 0 1 11 0v4.3l1.4 2.1H5.1l1.4-2.1Z"/>
        <path d="M9.8 19.1a2.4 2.4 0 0 0 4.4 0"/>
    """,
    "file": """
        <path d="M6 3.6h7.2L18 8.4v12H6Z"/>
        <path d="M13.1 3.7v4.9h4.8"/>
    """,
    "code": """
        <path d="m8.2 8.2-4 3.8 4 3.8"/>
        <path d="m15.8 8.2 4 3.8-4 3.8"/>
        <path d="m13.4 5.8-2.8 12.4"/>
    """,
    "image": """
        <rect x="3.8" y="4.6" width="16.4" height="14.8" rx="2.2"/>
        <circle cx="9" cy="9.6" r="1.5"/>
        <path d="m5.5 17 4.4-4.3 3.1 3 2.5-2.2 3.1 3.5"/>
    """,
    "video": """
        <rect x="3.8" y="5.3" width="12.5" height="13.4" rx="2.2"/>
        <path d="m16.3 10 4-2.2v8.4l-4-2.2"/>
    """,
    "zip": """
        <path d="M6 3.6h7.2L18 8.4v12H6Z"/>
        <path d="M13.1 3.7v4.9h4.8"/>
        <path d="M9.7 5.5h2"/>
        <path d="M9.7 8h2"/>
        <path d="M9.7 10.5h2"/>
        <path d="M9.7 13h2v2h-2Z"/>
    """,
    "recycle": """
        <path d="m9.3 4.7 2.7-1.5 2.7 1.5"/>
        <path d="M5.4 8.5 3.8 11l2.7 4.6"/>
        <path d="M18.6 8.5 20.2 11l-2.7 4.6"/>
        <path d="M7.3 18.8h9.4"/>
        <path d="m12 16 2.8 2.8L12 21"/>
    """,
    "browser": """
        <circle cx="12" cy="12" r="8.4"/>
        <path d="M4 9.7h16"/>
        <path d="M4 14.3h16"/>
        <path d="M12 3.6c2.1 2.4 3.1 5.2 3.1 8.4s-1 6-3.1 8.4c-2.1-2.4-3.1-5.2-3.1-8.4s1-6 3.1-8.4Z"/>
    """,
}


def available_icons() -> tuple[str, ...]:
    return tuple(sorted(_SVG))


@lru_cache(maxsize=256)
def _render(name: str, size: int, color: str, scale: int) -> QPixmap:
    template = _SVG.get(name)
    if not template:
        template = _SVG["info"]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="{color}" '
        'stroke-width="1.55" stroke-linecap="round" stroke-linejoin="round">'
        + template
        + "</svg>"
    ).format(color=color)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixel_size = max(1, size * scale)
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def icon_pixmap(name: str, size: int = 18, color: str = "#88847C") -> QPixmap:
    """Return a high-DPI-aware pixmap for a named icon."""

    return _render(name, int(size), color, 2)


def make_icon(name: str, color: str = "#88847C", size: int = 18) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_render(name, int(size), color, 2))
    icon.addPixmap(_render(name, int(size), color, 1))
    return icon


class IconLabel(QLabel):
    """A compact, non-interactive icon label."""

    def __init__(
        self,
        name: str,
        *,
        size: int = 18,
        color: str = "#88847C",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(size, size))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setPixmap(icon_pixmap(name, size, color))
        self.setScaledContents(False)
        self.setStyleSheet("background: transparent; border: none;")