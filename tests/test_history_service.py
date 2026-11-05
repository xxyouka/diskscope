from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core.cleanup_engine import CleanupCategory, CleanupRisk
from core.cleanup_executor import CleanupExecutionResult, CleanupFailure, CleanupPlan
from services.history_service import HistoryService


class HistoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".tmp") / "tests" / "history_case"
        shutil.rmtree(self.base, ignore_errors=True)
        self.base.mkdir(parents=True)
        self.service = HistoryService(self.base / "history.db")
        self.category = CleanupCategory(
            key="system_temp",
            title="测试缓存",
            description="test",
            reason="test",
            risk=CleanupRisk.SAFE,
            icon="broom",
            cleanable=True,
        )
        self.plan = CleanupPlan(
            items=[],
            categories=[self.category],
            allowed_roots=[str(self.base)],
            total_size=0,
            selected_keys=["system_temp"],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def _result(self, *, started: datetime, moved_size: int) -> CleanupExecutionResult:
        return CleanupExecutionResult(
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            duration=1.0,
            total=3,
            moved=2,
            failed=1,
            moved_size=moved_size,
            free_before=1000,
            free_after=1000,
            cancelled=False,
            failures=[
                CleanupFailure(path="C:\\locked.tmp", category_key="system_temp", error="文件被占用")
            ],
        )

    def test_record_stats_recent_and_failures(self) -> None:
        started = datetime(2026, 11, 5, 10, 0, 0)
        run_id = self.service.record(
            self._result(started=started, moved_size=2048),
            self.plan,
            volume="C:",
        )
        self.assertIsNotNone(run_id)
        stats = self.service.stats()
        self.assertEqual(stats.runs, 1)
        self.assertEqual(stats.moved_files, 2)
        self.assertEqual(stats.moved_size, 2048)
        self.assertEqual(stats.failed, 1)
        records = self.service.recent(6)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].category_titles, "测试缓存")
        self.assertEqual(records[0].volume, "C:")
        failures = self.service.failures_for(records[0].id)
        self.assertEqual(len(failures), 1)
        self.assertIn("占用", failures[0][1])

    def test_permanent_delete_mode_is_stored(self) -> None:
        started = datetime(2026, 11, 5, 11, 0, 0)
        self.service.record(
            self._result(started=started, moved_size=1024),
            self.plan,
            volume="C:",
            delete_mode="permanent",
        )
        record = self.service.recent(1)[0]
        self.assertEqual(record.delete_mode, "permanent")

    def test_chart_returns_chronological_runs(self) -> None:
        base_time = datetime(2026, 11, 1, 9, 0, 0)
        for index, size in enumerate((1024, 2048, 4096)):
            self.service.record(
                self._result(started=base_time + timedelta(days=index), moved_size=size),
                self.plan,
                volume="C:",
            )
        data = self.service.chart_data(6)
        self.assertEqual([value for _, value in data], [1024, 2048, 4096])

    def test_empty_database(self) -> None:
        self.assertEqual(self.service.stats().runs, 0)
        self.assertEqual(self.service.recent(), [])
        self.assertEqual(self.service.chart_data(), [])


if __name__ == "__main__":
    unittest.main()