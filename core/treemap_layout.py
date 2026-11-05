"""Squarified treemap layout.

The layout is intentionally UI-independent so it can be reused by the
dashboard and, later, by directory-level analysis views.  Values are rendered
with rounded corners and gutters by the widget; this module only computes
geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class MapRect:
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class LayoutItem:
    key: str
    value: float
    rect: MapRect


@dataclass(slots=True)
class _Entry:
    key: str
    area: float


def _worst_ratio(row: Sequence[_Entry], side: float) -> float:
    if not row or side <= 0:
        return float("inf")
    total = sum(entry.area for entry in row)
    if total <= 0:
        return float("inf")
    largest = max(entry.area for entry in row)
    smallest = min(entry.area for entry in row)
    if smallest <= 0:
        return float("inf")
    return max((side * side * largest) / (total * total), (total * total) / (side * side * smallest))


def squarify(
    items: Iterable[tuple[str, float]],
    width: float,
    height: float,
    *,
    padding: float = 0.0,
) -> list[LayoutItem]:
    """Lay out weighted items as a squarified treemap.

    ``padding`` is applied to the outside of the resulting map.  Keys must be
    unique; zero/negative values are ignored.
    """

    width = max(0.0, float(width) - padding * 2)
    height = max(0.0, float(height) - padding * 2)
    offset_x = float(padding)
    offset_y = float(padding)

    valid = [(str(key), float(value)) for key, value in items if float(value) > 0]
    if not valid or width <= 0 or height <= 0:
        return []

    valid.sort(key=lambda pair: pair[1], reverse=True)
    total = sum(value for _, value in valid)
    scale = (width * height) / total
    entries = [_Entry(key, value * scale) for key, value in valid]

    x = offset_x
    y = offset_y
    w = width
    h = height
    result: list[LayoutItem] = []

    while entries:
        side = min(w, h)
        row: list[_Entry] = [entries[0]]
        remaining = entries[1:]

        while remaining:
            current_worst = _worst_ratio(row, side)
            candidate_worst = _worst_ratio(row + [remaining[0]], side)
            if candidate_worst > current_worst:
                break
            row.append(remaining.pop(0))

        row_area = sum(entry.area for entry in row)
        if row_area <= 0:
            break

        if w >= h:
            # Vertical strip along the left edge.
            strip_width = row_area / h
            strip_width = min(strip_width, w)
            cursor = y
            for entry in row:
                item_height = (entry.area / strip_width) if strip_width > 0 else 0.0
                item_height = min(item_height, max(0.0, offset_y + height - cursor))
                result.append(
                    LayoutItem(
                        entry.key,
                        entry.area / scale,
                        MapRect(x, cursor, strip_width, item_height),
                    )
                )
                cursor += item_height
            x += strip_width
            w -= strip_width
        else:
            # Horizontal strip along the top edge.
            strip_height = row_area / w
            strip_height = min(strip_height, h)
            cursor = x
            for entry in row:
                item_width = (entry.area / strip_height) if strip_height > 0 else 0.0
                item_width = min(item_width, max(0.0, offset_x + width - cursor))
                result.append(
                    LayoutItem(
                        entry.key,
                        entry.area / scale,
                        MapRect(cursor, y, item_width, strip_height),
                    )
                )
                cursor += item_width
            y += strip_height
            h -= strip_height

        entries = remaining
        if w <= 0.01 or h <= 0.01:
            break

    return result