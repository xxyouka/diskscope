"""Generate the raster application icon used by packaging and documentation.

Run from the project root:

    .\\.venv\\Scripts\\python.exe tools\\generate_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.components.branding import app_icon_pixmap  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication([])
    target = ROOT / "resources" / "app_icon.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap = app_icon_pixmap(512)
    if not pixmap.save(str(target), "PNG"):
        print(f"Could not save {target}", file=sys.stderr)
        return 1
    print(f"Wrote {target} ({pixmap.width()}x{pixmap.height()})")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())