# ALE Workbench v1.0 — 最终交付报告

## 一、架构问题逐条答复

**Q1. WPF 是否只做壳、不重写业务逻辑？**
是。全部业务逻辑留在 Python FastAPI 后端；WPF 只做进程管理、状态展示、嵌入前端、设置。WPF 不实现任何业务规则。

**Q2. 前后端/壳与后端如何通信？**
HTTP/HTTPS + JSON。壳通过 `/health`（`{code:0,data:{status,database}}`）与 `/openapi.json`（版本对齐）与后端交互；前端页面由后端同一进程服务。

**Q3. 客户端是否直连 MySQL、是否存数据库密码？**
否。数据库访问只发生在后端；客户端从不直连 MySQL，从不保存数据库密码或云端凭据。数据库密码只存在于后端 `.dbcreds`/`.appcreds`，不进入安装包、不进入版本库。

**Q4. 是否使用 Python.NET？**
否。后端是独立 Python 进程，壳与后端仅经 HTTP 通信，无进程内嵌入。

**Q5. 目标框架与运行时？**
`net10.0-windows`（.NET 10 LTS，WPF + WinForms 托盘），自包含单文件 `win-x64` 发布，目标机无需 .NET SDK/运行时。

**Q6. 本地模式与云端模式？**
双模式。`Mode=local` 管理本机后端/MySQL；`Mode=remote` 仅保存 HTTPS 地址并导航。由 `%APPDATA%\ALE Workbench Launcher\config.json` 控制。

**Q7. 安装/配置/日志/数据是否分离？**
是。安装目录 `C:\Program Files\ALE Workbench`、配置 `%APPDATA%\ALE Workbench Launcher`、日志同配置目录、MySQL 数据 `%PROGRAMDATA%\ALE Workbench\mysql-data` 四者分离，卸载保留数据与配置。

**Q8. 版本管理如何做？**
壳版本 1.0.0；后端兼容 API 版本 1.8.0（从 `/openapi.json` 读取对齐，不匹配则提示）。安装包附带 SHA-256 校验。

**Q9. 测试如何保证不污染生产数据？**
测试使用独立 `*_test` 数据库与独立原件目录；不重建数据库、不自动清理生产数据；静态/隔离测试不冒称正式账户验收。

## 二、P1 桌面启动与管理系统答复

**Q1. 是否审计了现有启动机制？**
是。现有 `start-workbench.ps1` 是单进程 uvicorn（`app.main:app`，127.0.0.1:8001），前端由后端服务；已确认 venv 重定向器→基础解释器的进程链。

**Q2. 是否提供一键启动/停止/重启与状态？**
是。桌面壳提供启动/打开/停止/重启，2.5 秒轮询后端/数据库/前端/地址四项状态。

**Q3. 是否无 CMD 窗口、且安全停止？**
是。WPF 用隐藏窗口启动脚本，不弹 CMD；`ale-ctl.ps1` 只停被工作台认领的进程，端口被非工作台进程占用时拒绝停止，绝不误杀所有 Python/Node。

**Q4. 是否提供日志、快捷方式与测试？**
是。桌面壳「查看日志」+ `%APPDATA%\ALE Workbench Launcher\logs`（轮转、脱敏）；安装包创建桌面/开始菜单快捷方式；测试结果见 [TEST_REPORT.md](TEST_REPORT.md)。

## 三、交付物清单

- 安装包：`launcher\dist\ALE-Workbench-Setup-x64.exe`
- 校验：`SHA256SUMS.txt`
- 文档：`docs\v1.0-installer\`（ARCHITECTURE / INSTALLATION_GUIDE / USER_GUIDE / DATA_BACKUP_AND_RESTORE / TEST_REPORT / KNOWN_ISSUES / RELEASE_NOTES / 本报告）
- 脚本：`start-workbench.ps1`、`ale-ctl.ps1`、`stop-workbench.ps1`、`launcher\deploy\deploy-mysql.ps1`、`launcher\deploy\provision-python.ps1`、`launcher\installer\build-installer.ps1`、`ale-workbench.iss`

## 四、尚未完成（诚实声明）

干净 Windows VM 上的一键安装、MySQL 在无库机器的自动初始化全流程、WebView2 缺失自动处理、卸载保留数据实测，均**未通过**（本机无 VM 环境）。详见 [TEST_REPORT.md](TEST_REPORT.md) 与 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。
