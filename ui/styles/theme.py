"""Stylesheet and application font setup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

_THEME_PATH = Path(__file__).with_name("theme.qss")

_PREFERRED_FONTS = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "Segoe UI Variable Text",
    "Segoe UI",
    "Noto Sans CJK SC",
)


def load_stylesheet() -> str:
    try:
        return _THEME_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def choose_font_family() -> str:
    try:
        families = set(QFontDatabase.families())
    except TypeError:  # older binding style
        families = set(QFontDatabase().families())
    for family in _PREFERRED_FONTS:
        if family in families:
            return family
    return "Segoe UI"


def build_app_font(point_size: float = 9.75) -> QFont:
    family = choose_font_family()
    font = QFont(family)
    font.setPointSizeF(point_size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font