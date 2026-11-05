from __future__ import annotations

import unittest
from datetime import datetime

from core.cleanup_executor import (
    DELETE_MODE_PERMANENT,
    DELETE_MODE_RECYCLE,
    CleanupExecutionResult,
    CleanupFailure,
)
from ui.components.cleanup_workflow import CleanupWorkflowDialog


def _result(*, moved: int, mode: str, errors: list[str]) -> CleanupExecutionResult:
    return CleanupExecutionResult(
        started_at=datetime.now(),
        finished_at=datetime.now(),
        duration=1.0,
        total=len(errors) + moved,
        moved=moved,
        failed=len(errors),
        moved_size=0,
        free_before=1,
        free_after=1,
        cancelled=False,
        failures=[
            CleanupFailure(path=f"C:\\x\\{index}.tmp", category_key="browser_cache", error=error)
            for index, error in enumerate(errors)
        ],
        delete_mode=mode,
    )


class CleanupFallbackTests(unittest.TestCase):
    def test_offers_permanent_after_all_recycle_access_failures(self) -> None:
        result = _result(
            moved=0,
            mode=DELETE_MODE_RECYCLE,
            errors=[
                "[WinError -2144927711] OLE error 0x80270021",
                "[WinError 5] 拒绝访问。",
            ],
        )
        self.assertTrue(
            CleanupWorkflowDialog._should_offer_permanent_fallback(result)
        )

    def test_does_not_offer_when_files_were_already_moved(self) -> None:
        result = _result(
            moved=1,
            mode=DELETE_MODE_RECYCLE,
            errors=["[WinError -2144927711] OLE error 0x80270021"],
        )
        self.assertFalse(
            CleanupWorkflowDialog._should_offer_permanent_fallback(result)
        )
        self.assertFalse(
            CleanupWorkflowDialog._should_offer_permanent_fallback(
                _result(moved=0, mode=DELETE_MODE_PERMANENT, errors=["[WinError 5] 拒绝访问。"])
            )
        )


if __name__ == "__main__":
    unittest.main()