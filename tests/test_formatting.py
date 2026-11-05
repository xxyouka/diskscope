from __future__ import annotations

import unittest

from app.formatting import format_capacity, format_percent, split_size


class FormattingTests(unittest.TestCase):
    def test_trailing_zero_precision_is_not_lost(self) -> None:
        # Regression: 550.37 KB used to be rendered as "55 KB" because the
        # decimal-stripping logic also removed a significant trailing zero.
        self.assertEqual(split_size(563_578), ("550", "KB"))
        self.assertEqual(format_capacity(563_578), "550 KB")
        self.assertEqual(format_capacity(1024 * 100), "100 KB")

    def test_decimal_trimming(self) -> None:
        self.assertEqual(format_capacity(1024 * 10), "10 KB")
        self.assertEqual(format_capacity(1024 * 1024 * 42.6), "42.6 MB")
        self.assertEqual(format_capacity(1024), "1 KB")
        self.assertEqual(format_capacity(0), "0 B")

    def test_percent(self) -> None:
        self.assertEqual(format_percent(0.894), "89%")
        self.assertEqual(format_percent(0.894, 1), "89.4%")
        self.assertEqual(format_percent(1.8), "100%")


if __name__ == "__main__":
    unittest.main()