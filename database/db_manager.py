"""Local SQLite database for scan cache and future cleanup history."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import DATABASE_PATH

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3


class DatabaseManager:
    """Small connection factory with explicit, conservative pragmas."""

    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = Path(path)
        self._initialised = False

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=12.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._initialised:
            return
        with self.connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS scan_sessions (
                    root_key TEXT PRIMARY KEY,
                    root_path TEXT NOT NULL,
                    scanned_at TEXT NOT NULL,
                    files_scanned INTEGER NOT NULL,
                    dirs_scanned INTEGER NOT NULL,
                    total_size INTEGER NOT NULL,
                    errors INTEGER NOT NULL,
                    duration REAL NOT NULL,
                    schema_version INTEGER NOT NULL,
                    app_version TEXT NOT NULL,
                    category_sizes TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS scan_dirs (
                    root_key TEXT NOT NULL,
                    dir_id INTEGER NOT NULL,
                    parent_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    own_file_size INTEGER NOT NULL,
                    file_count INTEGER NOT NULL,
                    dir_count INTEGER NOT NULL,
                    errors INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    inaccessible INTEGER NOT NULL,
                    PRIMARY KEY (root_key, dir_id),
                    FOREIGN KEY (root_key) REFERENCES scan_sessions(root_key)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scan_dirs_parent
                    ON scan_dirs(root_key, parent_id);

                CREATE TABLE IF NOT EXISTS cleanup_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration REAL NOT NULL,
                    volume TEXT NOT NULL,
                    total INTEGER NOT NULL,
                    moved INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    moved_size INTEGER NOT NULL,
                    free_before INTEGER NOT NULL,
                    free_after INTEGER NOT NULL,
                    cancelled INTEGER NOT NULL,
                    categories_json TEXT NOT NULL DEFAULT '[]',
                    delete_mode TEXT NOT NULL DEFAULT 'recycle'
                );

                CREATE TABLE IF NOT EXISTS cleanup_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    category_key TEXT NOT NULL,
                    error TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES cleanup_runs(id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_cleanup_failures_run
                    ON cleanup_failures(run_id);
                """
            )
            run_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(cleanup_runs)").fetchall()
            }
            if "delete_mode" not in run_columns:
                # v2 -> v3: keep existing history and mark old runs as recycle.
                connection.execute(
                    "ALTER TABLE cleanup_runs "
                    "ADD COLUMN delete_mode TEXT NOT NULL DEFAULT 'recycle'"
                )
            if version != SCHEMA_VERSION:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._initialised = True

    def close(self) -> None:
        self._initialised = False