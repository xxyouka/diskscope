r"""DiskScope · 盘析

Run from the project root:

    .\.venv\Scripts\python.exe main.py
"""

from __future__ import annotations

import sys


def main() -> int:
    if sys.version_info < (3, 10):
        print("盘析需要 Python 3.10 或更高版本。", file=sys.stderr)
        return 1
    try:
        from app.application import run
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print(
                "缺少 PySide6。请先执行：\n"
                "  python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 1
        raise
    return run()


if __name__ == "__main__":
    raise SystemExit(main())