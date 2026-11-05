# Contributing to DiskScope

感谢对盘析（DiskScope）的兴趣。这个项目首先是一个**安全工具**，其次才是一个磁盘清理工具。提交代码前请先阅读下面的边界。

## Safety invariants

以下规则属于项目不可协商的安全边界，请不要在 PR 中绕过：

1. **不静默删除**。任何删除动作都必须由用户主动触发，并展示清单和确认步骤。
2. **优先回收站**。永久删除只能作为回收站不可用时的显式兜底，不能默认启用。
3. **逐文件校验**。清理执行不能只信任 UI 的选择状态，必须继续经过 `core/safety_guard.py` 的根目录、类型、reparse point、数据目录等检查。
4. **不自动清理个人文件、项目源码、Windows 系统组件**。
5. **软件卸载只调用官方卸载入口**，不直接删除安装目录。
6. **微信消息数据库**只能通过独立的“彻底删除微信数据”高风险流程处理，并且需要微信完全退出、回收站/永久删除选择、二次确认和短语确认。
7. **不引入云端、遥测、远程扫描**。所有数据留在本机。
8. 不要在仓库、测试夹具、截图中提交真实用户目录、已安装软件列表、聊天内容或数据库。

如果发现安全设计有问题，请不要公开提交 issue 中的利用细节，按 [SECURITY.md](SECURITY.md) 私下报告。

## Development setup

环境：Windows 10/11 + Python 3.10+（推荐 3.12）。

```powershell
git clone https://github.com/xxyouka/diskscope.git
cd diskscope
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Pull requests

- 一个 PR 聚焦一件事，避免顺手格式化整个仓库。
- 保持数据真实：不要引入伪造的容量、扫描结果或历史记录。
- 涉及删除、权限、路径解析的改动必须补测试，并说明为什么不会扩大删除范围。
- UI 文案优先使用中文，语气克制；代码标识符和注释可使用英文。
- 不要提交 `.venv/`、`data/`、`.tmp/`、日志、SQLite 数据库或未脱敏截图。

## Good first issues

- 增加更多目录说明规则；
- 改进文件分析的右键菜单；
- 增加 Windows 打包与安装器；
- 补充端到端 UI 测试；
- 改进多磁盘和大目录扫描性能。

## License

提交贡献即表示你同意以 [MIT License](LICENSE) 发布你的贡献。