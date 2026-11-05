"""The DiskScope visual language in code.

A warm, low-saturation paper palette.  The values here are also reflected in
``theme.qss``; keeping them typed makes custom-painted widgets share exactly
the same colors as styled Qt controls.
"""

from __future__ import annotations


class Palette:
    # Base surfaces
    BACKGROUND = "#F3F0EA"
    SURFACE = "#F8F6F1"
    SURFACE_RAISED = "#FCFAF6"
    SURFACE_MUTED = "#ECE7DD"
    SURFACE_DEEP = "#E5DFD4"

    # Ink
    INK = "#292723"
    INK_SOFT = "#4A463F"
    MUTED = "#88847C"
    MUTED_LIGHT = "#A7A198"
    INK_ON_DARK = "#F8F4EC"

    # Lines
    BORDER = "#DDD8CF"
    BORDER_SOFT = "#E8E3DA"
    BORDER_STRONG = "#CDC6BA"

    # States
    SUCCESS = "#758166"
    SUCCESS_BG = "#E8EBE0"
    WARNING = "#AE8152"
    WARNING_BG = "#F1E5D6"
    DANGER = "#A0625A"
    DANGER_BG = "#F1E1DD"
    INFO = "#6E7A7A"

    # Dark surfaces
    DARK = "#2C2A26"
    DARK_HOVER = "#3A3731"
    DARK_SOFT = "#4B473F"

    # Treemap / data visualization
    MAP_DARK = "#2E2B26"
    MAP_STONE = "#7E796D"
    MAP_TAUPE = "#A39B8C"
    MAP_SAND = "#CFC6B7"
    MAP_CREAM = "#E9E3D8"
    MAP_FREE = "#E7E1D6"

    # Chart shades, ordered by preference
    VOLUME_SHADES = ("#2F2C27", "#777267", "#A49C8D", "#C9C0B0", "#8E887B")

    WHITE = "#FFFDF9"
    BLACK = "#000000"


class Metrics:
    WINDOW_RADIUS = 22
    CARD_RADIUS = 18
    CONTROL_RADIUS = 11
    PAGE_MARGIN_H = 34
    PAGE_MARGIN_V = 28
    CARD_GAP = 20
    TITLEBAR_HEIGHT = 78