from __future__ import annotations

import os
import unittest
from pathlib import Path

from core.folder_knowledge import common_folder_examples, describe_folder


@unittest.skipUnless(os.name == "nt", "Windows folder guidance")
class FolderKnowledgeTests(unittest.TestCase):
    def test_system_and_cache_paths(self) -> None:
        system = describe_folder(r"C:\Windows\System32")
        self.assertEqual(system.category, "系统目录")
        self.assertEqual(system.tone, "protected")
        self.assertEqual(system.action, "none")

        temp = describe_folder(Path.home() / "AppData" / "Local" / "Temp" / "x")
        self.assertEqual(temp.tone, "cache")
        self.assertEqual(temp.action, "cleanup")

    def test_personal_project_and_wechat_paths(self) -> None:
        downloads = describe_folder(Path.home() / "Downloads")
        self.assertEqual(downloads.category, "个人文件")
        self.assertEqual(downloads.tone, "personal")

        appdata = describe_folder(Path.home() / "AppData")
        self.assertEqual(appdata.category, "应用目录")
        self.assertEqual(appdata.tone, "app")

        node_modules = describe_folder(Path.home() / "project" / "node_modules")
        self.assertEqual(node_modules.tone, "project")

        wechat = describe_folder(Path.home() / "Documents" / "xwechat_files" / "wxid")
        self.assertEqual(wechat.tone, "wechat")
        self.assertEqual(wechat.action, "wechat")

    def test_generic_folder_has_actionable_fallback(self) -> None:
        insight = describe_folder(Path("D:/SomeUnknownFolder"))
        self.assertEqual(insight.category, "普通目录")
        self.assertEqual(insight.tone, "caution")
        self.assertTrue(insight.advice)

    def test_detects_project_folder_from_markers(self) -> None:
        import shutil

        root = Path(".tmp") / "tests" / "project_guide"
        shutil.rmtree(root, ignore_errors=True)
        (root / "src").mkdir(parents=True)
        (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        try:
            insight = describe_folder(root / "src")
            self.assertEqual(insight.category, "项目文件")
            self.assertEqual(insight.tone, "project")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_common_examples_are_explained(self) -> None:
        examples = common_folder_examples()
        self.assertTrue(examples)
        for label, path in examples:
            insight = describe_folder(path)
            self.assertTrue(label)
            self.assertTrue(insight.summary)
            self.assertTrue(insight.category)


if __name__ == "__main__":
    unittest.main()