from __future__ import annotations

import os
import time
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from core.cleanup_engine import CleanupCategory, CleanupRisk
from core.cleanup_executor import (
    DELETE_MODE_PERMANENT,
    CleanupExecutionResult,
    CleanupExecutor,
    CleanupPermissionError,
    CleanupPlan,
    CleanupPlanItem,
    CleanupPlanner,
)
from core.safety_guard import SafetyGuard, SafetyViolation


class _FakeTrash:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.batch_calls: list[list[str]] = []

    def __call__(self, path) -> None:
        paths = list(path) if isinstance(path, (list, tuple)) else [path]
        self.batch_calls.append(paths)
        for item in paths:
            self.paths.append(item)
            os.remove(item)


class SafetyGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".tmp") / "tests" / "safety_case"
        shutil.rmtree(self.base, ignore_errors=True)
        self.allowed = self.base / "allowed"
        self.allowed.mkdir(parents=True)
        self.outside = self.base / "outside"
        self.outside.mkdir()
        self.file = self.allowed / "cache.bin"
        self.file.write_bytes(b"x" * 10)
        self.guard = SafetyGuard(data_dir=self.base / "appdata")

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_allows_file_under_known_root(self) -> None:
        validated = self.guard.validate(
            self.file,
            allowed_roots=[str(self.allowed)],
            category_key="system_temp",
        )
        self.assertEqual(validated, self.file.resolve())

    def test_rejects_file_outside_allowed_roots(self) -> None:
        other = self.outside / "keep.txt"
        other.write_bytes(b"x")
        with self.assertRaises(SafetyViolation):
            self.guard.validate(
                other,
                allowed_roots=[str(self.allowed)],
                category_key="system_temp",
            )

    def test_rejects_directory_and_unknown_category(self) -> None:
        with self.assertRaises(SafetyViolation):
            self.guard.validate(
                self.allowed,
                allowed_roots=[str(self.allowed)],
                category_key="system_temp",
            )
        with self.assertRaises(SafetyViolation):
            self.guard.validate(
                self.file,
                allowed_roots=[str(self.allowed)],
                category_key="unknown_category",
            )
        self.guard.validate(
            self.file,
            allowed_roots=[str(self.allowed)],
            category_key="wechat",
        )

    def test_rejects_app_data_directory(self) -> None:
        app_data = self.base / "appdata"
        app_data.mkdir()
        secret = app_data / "diskscope.db"
        secret.write_bytes(b"db")
        with self.assertRaises(SafetyViolation):
            self.guard.validate(
                secret,
                allowed_roots=[str(app_data)],
                category_key="system_temp",
            )

    def test_installer_rules_are_enforced(self) -> None:
        setup = self.allowed / "setup.exe"
        setup.write_bytes(b"x")
        with self.assertRaises(SafetyViolation):
            self.guard.validate(
                setup,
                allowed_roots=[str(self.allowed)],
                category_key="installers",
            )
        old = time.time() - 40 * 24 * 3600
        os.utime(setup, (old, old))
        self.guard.validate(
            setup,
            allowed_roots=[str(self.allowed)],
            category_key="installers",
        )


class PlannerAndExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".tmp") / "tests" / "executor_case"
        shutil.rmtree(self.base, ignore_errors=True)
        self.root = self.base / "cache"
        self.root.mkdir(parents=True)
        self.one = self.root / "one.bin"
        self.two = self.root / "two.bin"
        self.one.write_bytes(b"a" * 100)
        self.two.write_bytes(b"b" * 200)
        self.category = CleanupCategory(
            key="system_temp",
            title="测试缓存",
            description="test",
            reason="test",
            risk=CleanupRisk.SAFE,
            icon="broom",
            roots=[str(self.root)],
            cleanable=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_planner_collects_real_files(self) -> None:
        with patch("core.cleanup_executor.build_default_categories", return_value=[self.category]):
            plan = CleanupPlanner().build(["system_temp"])
        self.assertEqual(plan.total_files, 2)
        self.assertEqual(plan.total_size, 300)
        self.assertEqual({Path(item.path).name for item in plan.items}, {"one.bin", "two.bin"})

    def test_executor_moves_files_and_reports_failures(self) -> None:
        missing = self.root / "gone.bin"
        plan = CleanupPlan(
            items=[
                CleanupPlanItem(str(self.one), 100, time.time(), "system_temp", "测试缓存", "safe"),
                CleanupPlanItem(str(self.two), 200, time.time(), "system_temp", "测试缓存", "safe"),
                CleanupPlanItem(str(missing), 50, time.time(), "system_temp", "测试缓存", "safe"),
            ],
            categories=[self.category],
            allowed_roots=[str(self.root)],
            total_size=350,
            selected_keys=["system_temp"],
        )
        trash = _FakeTrash()
        result = CleanupExecutor(
            plan,
            volume_mount=str(self.root),
            guard=SafetyGuard(data_dir=self.base / "appdata"),
            trash_function=trash,
            probe_recycle_bin=False,
        ).execute()
        self.assertEqual(result.moved, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.moved_size, 300)
        self.assertEqual(len(trash.paths), 2)
        self.assertEqual(len(trash.batch_calls), 1)
        self.assertFalse(self.one.exists())
        self.assertFalse(self.two.exists())
        self.assertEqual(len(result.failures), 1)
        self.assertIn("不存在", result.failures[0].error)

    def test_executor_can_cancel_before_any_file(self) -> None:
        import threading

        plan = CleanupPlan(
            items=[
                CleanupPlanItem(str(self.one), 100, time.time(), "system_temp", "测试缓存", "safe")
            ],
            categories=[self.category],
            allowed_roots=[str(self.root)],
            total_size=100,
            selected_keys=["system_temp"],
        )
        cancel = threading.Event()
        cancel.set()
        fake = _FakeTrash()
        result = CleanupExecutor(
            plan,
            volume_mount=str(self.root),
            guard=SafetyGuard(data_dir=self.base / "appdata"),
            trash_function=fake,
            cancel_event=cancel,
            probe_recycle_bin=False,
        ).execute()
        self.assertTrue(result.cancelled)
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.total, 1)
        self.assertFalse(fake.paths)
        self.assertTrue(self.one.exists())

    def test_permanent_mode_deletes_files_directly(self) -> None:
        plan = CleanupPlan(
            items=[
                CleanupPlanItem(str(self.one), 100, time.time(), "system_temp", "测试缓存", "safe")
            ],
            categories=[self.category],
            allowed_roots=[str(self.root)],
            total_size=100,
            selected_keys=["system_temp"],
        )
        result = CleanupExecutor(
            plan,
            volume_mount=str(self.root),
            guard=SafetyGuard(data_dir=self.base / "appdata"),
            probe_recycle_bin=False,
            delete_mode=DELETE_MODE_PERMANENT,
        ).execute()
        self.assertEqual(result.delete_mode, DELETE_MODE_PERMANENT)
        self.assertEqual(result.moved, 1)
        self.assertFalse(self.one.exists())

    def test_preflight_aborts_when_recycle_bin_is_denied(self) -> None:
        def deny(_path: str) -> None:
            raise PermissionError(13, "Access denied")

        plan = CleanupPlan(
            items=[
                CleanupPlanItem(str(self.one), 100, time.time(), "system_temp", "测试缓存", "safe")
            ],
            categories=[self.category],
            allowed_roots=[str(self.root)],
            total_size=100,
            selected_keys=["system_temp"],
        )
        with self.assertRaises(CleanupPermissionError):
            CleanupExecutor(
                plan,
                volume_mount=str(self.root),
                guard=SafetyGuard(data_dir=self.base / "appdata"),
                trash_function=deny,
            ).execute()
        self.assertTrue(self.one.exists())

    def test_executor_rejects_outside_plan_file(self) -> None:
        outside = self.base / "outside.bin"
        outside.write_bytes(b"x" * 10)
        plan = CleanupPlan(
            items=[
                CleanupPlanItem(str(outside), 10, time.time(), "system_temp", "测试缓存", "safe")
            ],
            categories=[self.category],
            allowed_roots=[str(self.root)],
            total_size=10,
            selected_keys=["system_temp"],
        )
        fake = _FakeTrash()
        result = CleanupExecutor(
            plan,
            volume_mount=str(self.root),
            guard=SafetyGuard(data_dir=self.base / "appdata"),
            trash_function=fake,
            probe_recycle_bin=False,
        ).execute()
        self.assertEqual(result.moved, 0)
        self.assertEqual(result.failed, 1)
        self.assertTrue(outside.exists())


if __name__ == "__main__":
    unittest.main()