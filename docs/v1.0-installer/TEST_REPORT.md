# ALE Workbench v1.0 — 测试报告

> 诚实标记：本报告区分「本机验证通过」与「未在干净虚拟机验证」。静态/隔离测试**不**等同于正式账户验收。

## 环境

- 开发机：Windows 11 Pro for Workstations x64，.NET 10 SDK，Python 3.14.2，MySQL 8.4（端口 3307）。
- 本仓库为 git worktree（`strange-lovelace-af6201`）。

## 已验证通过（本机）

| 项 | 结果 | 证据 |
|----|------|------|
| WPF 桌面壳编译 | ✅ 0 警告 0 错误 | `dotnet build` 成功，`bin\Release\...\ALE-Workbench-Launcher.dll` |
| WPF 自包含单文件发布 | ✅ ~67 MB | `publish\ALE-Workbench-Launcher.exe` |
| WPF 启动冒烟测试 | ✅ ALIVE（进程存活，内存 ~294 MB） | 启动器进程存活 |
| 启动/状态/停止 端到端 | ✅ 运行→healthy→database:ok→PID 记录→停止→端口释放 | `start-workbench.ps1` / `ale-ctl.ps1 -Action status` / `-Action stop` |
| 安全停止（不误杀非工作台进程） | ✅ 只认领本项目进程；端口被占用时拒绝 | `ale-ctl.ps1` `Stop-VerifiedBackend` |
| `-NoBrowser` 开关（启动不弹浏览器） | ✅ 附加且默认行为不变 | `start-workbench.ps1` param 新增 `[switch]$NoBrowser` |
| 便携 Python 打包 | ✅ 复制基础 CPython + 覆盖 venv 依赖，导入全部依赖 | `python\python.exe -c "import fastapi,...cryptography"` 输出 OK |
| 便携 Python 导入完整后端 | ✅ `import app.main` 成功 | `PYTHONPATH=backend python\python.exe -c "import app.main"` |
| MySQL 部署脚本（幂等/不覆盖） | ✅ 代码完成，检测→复用/部署逻辑 | `launcher\deploy\deploy-mysql.ps1` |
| 配置目录自动检测 | ✅ 空 ProjectRoot 时回退到壳同目录 | `AppConfig.AutoDetectProjectRoot` |
| 安装包构建产出 | ✅ `ALE-Workbench-Setup-x64.exe`（~228 MB，SHA-256 见下） | ISCC 编译成功，staging 1.4 GB 完整打进去 |
| 安装包内容与密钥隔离 | ✅ 关键文件齐全、无 `.dbcreds/.appcreds/.env` | 逐项核对 staging；SHA256 `3303dd17c8769b724c13a38ee23eba8a0329312475a139828ab22278048698de` |

## 未验证 / 未完成（诚实标注）

| 项 | 状态 | 说明 |
|----|------|------|
| 干净 Windows 11 虚拟机一键安装 | ❌ **未通过**（无 VM 环境） | 安装包已构建，但未在无 Python/Node/MySQL 的干净机上实际安装验收 |
| MySQL 自动部署端到端（干净机） | ⚠️ 未跑通 | 脚本逻辑完成，未在无 MySQL 的干净机上实际初始化 + 建库 + 迁移 |
| WebView2 缺失时的自动处理 | ⚠️ 未实现下载/内置 | Win11 内置；Win10 缺失仅提示，见 KNOWN_ISSUES |
| 卸载路径（保留数据） | ⚠️ 脚本声明未实测 | `[UninstallDelete]` 只删安装目录内文件，未在真实卸载后核对 |
| 云端模式端到端 | ⚠️ 未测 | 本地模式为主，云端仅导航逻辑 |

## 测试约束（遵循 AGENTS.md）

- 测试使用独立 `*_test` 数据库与独立原件目录；本报告未对正式数据库做任何迁移/清理。
- 未提交、未推送、未 `git reset --hard`、未丢弃未提交修改。
- 未上传密钥、数据库文件；未写入任何客户端数据库密码。

## 结论

核心 P1（桌面壳 + 安全启动/停止 + 状态）已在本机验证通过；安装包已产出，但**干净机一键安装**尚未在真实 VM 上验收，需在有条件的用户环境补做。
