# ALE Workbench v1.0 — 架构说明

## 1. 总览

ALE Workbench 是一个热原子层刻蚀（Thermal ALE）科研数据工作台，包含三部分：

| 层 | 技术 | 职责 |
|----|------|------|
| 桌面壳 | C# / .NET 10 LTS / WPF + WebView2 | 启动/停止/状态/日志、嵌入 Vue 前端、本地与云端两种模式 |
| 后端 | Python 3.14 / FastAPI / uvicorn | 全部业务逻辑、数据库访问、鉴权、单进程同时服务 API + 前端静态资源 |
| 数据 | MySQL 8.4（端口 3307） | 结构化实验/样品/工艺数据 |

**核心原则：WPF 只是壳。** 任何业务逻辑都在 Python 后端里实现；WPF 绝不直连 MySQL、绝不在客户端保存数据库密码、绝不使用 Python.NET。

## 2. 进程与通信

- 后端是**单进程**：`python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001`，同时服务 `/api/*` 与 `frontend/dist` 静态页。
- 桌面壳通过 **HTTP/HTTPS + JSON** 与后端通信。
- 健康检查 `GET /health` 返回信封：`{"code":0,"data":{"status":"ok","database":"ok"}}`。
- 兼容 API 版本：`1.8.0`（启动器从 `/openapi.json` 读取并对齐）。

## 3. 本地模式 vs 云端模式

- **本地模式（默认）**：启动器管理本机 Python 后端与 MySQL；地址 `http://127.0.0.1:8001/login`。
- **云端模式**：启动器只保存一个 HTTPS 地址，不运行本地 Python / MySQL，直接导航到云端地址。
- 模式由 `%APPDATA%\ALE Workbench Launcher\config.json` 的 `Mode` 字段决定（`local` / `remote`）。

## 4. 目录与安装/数据分离

| 内容 | 位置 | 说明 |
|------|------|------|
| 安装目录（程序 + 后端 + 前端 + 运行时） | `C:\Program Files\ALE Workbench`（默认 `{autopf}`） | 可整体重装/升级，不保存用户数据 |
| 桌面壳配置 | `%APPDATA%\ALE Workbench Launcher\config.json` | 与安装目录分离 |
| 桌面壳日志 | `%APPDATA%\ALE Workbench Launcher\logs` | 轮转（2MB × 5），脱敏凭据 |
| MySQL 数据目录 | `%PROGRAMDATA%\ALE Workbench\mysql-data` | 卸载**不会**删除 |
| 数据库凭据 | `<项目根>\database\.dbcreds` / `.appcreds` | 由 `apply_schema.py` 在目标机生成，从不进入安装包 |

## 5. 便携运行时（不依赖开发机）

- **便携 Python**：由 `launcher/deploy/provision-python.ps1` 生成 `python\`，复制基础 CPython（python.exe + python314.dll + 标准库），再覆盖开发虚拟环境已校验的 wheel（排除测试用 `playwright`）。同 ABI（3.14.x）使原生扩展可重定位。`start-workbench.ps1` 优先使用 `python\python.exe`，其次回退 `backend\.venv-win`。
- **MySQL**：安装包内置 `mysql-server\`（8.4，bin 完整），由 `launcher/deploy/deploy-mysql.ps1` 幂等部署；数据目录保持在安装目录之外。
- **桌面壳**：自包含单文件 `ALE-Workbench-Launcher.exe`（win-x64），无需目标机安装 .NET SDK/运行时。

## 6. 安全约束（启动/停止）

- `start-workbench.ps1` 使用 schema v2 启动溯源记录（launchNonce、SHA-256 指纹、进程身份），只认领本项目、本端口、本命令行的后端进程。
- `ale-ctl.ps1` / `stop-workbench.ps1` 做「安全停止」：只停被工作台认领的进程，若端口被非工作台进程占用则拒绝停止，绝不 `kill` 所有 Python/Node 进程。
- 数据库密码只存在于后端与 `.dbcreds`/`.appcreds`，绝不下发到客户端、不进入安装包、不进入版本库。

## 7. 版本管理

- 桌面壳 `Version=1.0.0`；后端兼容 API 版本 `1.8.0`。
- 启动器在连接后端后校验 `openapi.json` 版本，不匹配时给出明确提示。
- 安装包输出 `ALE-Workbench-Setup-x64.exe`，附带 `SHA256SUMS.txt` 校验。
