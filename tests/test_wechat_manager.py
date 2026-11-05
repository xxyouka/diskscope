from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from core.wechat_manager import (
    WeChatAccount,
    measure_account,
    validate_wipe_target,
    wipe_account,
)


class WeChatManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Path(".tmp") / "tests" / "wechat_base"
        shutil.rmtree(self.base, ignore_errors=True)
        self.account = self.base / "wxid_test"
        self.account.mkdir(parents=True)
        self.db = self.account / "db_storage" / "message"
        self.db.mkdir(parents=True)
        (self.db / "chat.db").write_bytes(b"x" * 512)
        self.media = self.account / "msg" / "attach"
        self.media.mkdir(parents=True)
        (self.media / "photo.dat").write_bytes(b"y" * 128)

    def tearDown(self) -> None:
        shutil.rmtree(self.base, ignore_errors=True)

    def test_validate_only_allows_direct_account_directory(self) -> None:
        resolved = validate_wipe_target(self.account, bases=[self.base])
        self.assertEqual(resolved, self.account.resolve())
        with self.assertRaises(ValueError):
            validate_wipe_target(self.base, bases=[self.base])
        with self.assertRaises(ValueError):
            validate_wipe_target(self.account / "db_storage", bases=[self.base])

    def test_measure_account_counts_database_and_media(self) -> None:
        account = WeChatAccount("wxid_test", str(self.account), "modern", has_message_db=True)
        measured = measure_account(account)
        self.assertEqual(measured.files, 2)
        self.assertEqual(measured.size, 640)
        self.assertGreater(measured.last_modified, 0)

    def test_permanent_wipe_removes_complete_account_directory(self) -> None:
        account = WeChatAccount("wxid_test", str(self.account), "modern", has_message_db=True)
        measure_account(account)
        result = wipe_account(
            account,
            mode="permanent",
            bases=[self.base],
            check_running=False,
        )
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.files_deleted, 2)
        self.assertEqual(result.size_deleted, 640)
        self.assertFalse(self.account.exists())
        self.assertEqual(result.mode, "permanent")


if __name__ == "__main__":
    unittest.main()