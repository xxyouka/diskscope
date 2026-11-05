from __future__ import annotations

import unittest

from core.treemap_layout import squarify


class SquarifyTests(unittest.TestCase):
    def test_rectangles_stay_inside_bounds(self) -> None:
        rects = squarify(
            [("a", 50), ("b", 30), ("c", 20), ("d", 5)],
            1000,
            600,
            padding=12,
        )
        self.assertEqual(len(rects), 4)
        for item in rects:
            rect = item.rect
            self.assertGreater(rect.width, 0)
            self.assertGreater(rect.height, 0)
            self.assertGreaterEqual(rect.x, 12 - 1e-6)
            self.assertGreaterEqual(rect.y, 12 - 1e-6)
            self.assertLessEqual(rect.right, 988 + 1e-6)
            self.assertLessEqual(rect.bottom, 588 + 1e-6)

    def test_area_is_proportional_to_value(self) -> None:
        items = [("a", 60), ("b", 25), ("c", 15)]
        rects = squarify(items, 900, 500)
        covered = sum(item.rect.area for item in rects)
        total = 900 * 500
        self.assertAlmostEqual(covered, total, delta=total * 0.001)
        by_key = {item.key: item for item in rects}
        for key, value in items:
            self.assertAlmostEqual(
                by_key[key].rect.area / total,
                value / 100,
                delta=0.002,
            )

    def test_rectangles_do_not_overlap(self) -> None:
        rects = [item.rect for item in squarify([("a", 4), ("b", 3), ("c", 2), ("d", 1)], 800, 500)]
        for index, first in enumerate(rects):
            for second in rects[index + 1 :]:
                overlap_w = max(0.0, min(first.right, second.right) - max(first.x, second.x))
                overlap_h = max(0.0, min(first.bottom, second.bottom) - max(first.y, second.y))
                self.assertLess(overlap_w * overlap_h, 1e-6)

    def test_empty_and_invalid_values(self) -> None:
        self.assertEqual(squarify([], 400, 300), [])
        self.assertEqual(squarify([("a", 0), ("b", -3)], 400, 300), [])
        self.assertEqual(squarify([("a", 10)], 0, 300), [])

    def test_single_item_fills_canvas(self) -> None:
        result = squarify([("only", 42)], 640, 480)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].rect.width, 640, places=5)
        self.assertAlmostEqual(result[0].rect.height, 480, places=5)


if __name__ == "__main__":
    unittest.main()