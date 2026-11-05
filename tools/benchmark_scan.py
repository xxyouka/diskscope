"""Development benchmark for the scanner and optional scan cache.

Examples::

    .\\.venv\\Scripts\\python.exe tools\\benchmark_scan.py --path "E:\\项目"
    .\\.venv\\Scripts\\python.exe tools\\benchmark_scan.py --path "E:\\项目" --cache

The tool is read-only and only writes a cache database when ``--cache`` is set.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.scanner import DirectoryScanner  # noqa: E402
from services.scan_cache_service import ScanCacheService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="DiskScope scanner benchmark")
    parser.add_argument("--path", required=True, help="directory to scan")
    parser.add_argument("--cache", action="store_true", help="also test SQLite cache")
    args = parser.parse_args()
    target = Path(args.path).expanduser().resolve()
    if not target.is_dir():
        print(f"Not a directory: {target}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    result = DirectoryScanner().scan(target)
    scan_seconds = time.perf_counter() - started
    print(
        f"scan: {scan_seconds:.2f}s | files={result.files_scanned:,} | "
        f"dirs={result.dirs_scanned:,} | size={result.total_size / 1024**3:.2f} GiB | "
        f"errors={result.errors:,}"
    )
    if args.cache:
        db_path = ROOT / ".tmp" / "benchmark-cache.db"
        service = ScanCacheService(db_path)
        started = time.perf_counter()
        saved = service.save(result)
        save_seconds = time.perf_counter() - started
        started = time.perf_counter()
        loaded = service.load(target)
        load_seconds = time.perf_counter() - started
        print(
            f"cache: save={'ok' if saved else 'failed'} {save_seconds:.2f}s | "
            f"load={'ok' if loaded is not None else 'failed'} {load_seconds:.2f}s | "
            f"db={db_path.stat().st_size / 1024**2:.2f} MiB"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())