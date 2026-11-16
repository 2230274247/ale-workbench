# ALE Workbench v1.0 — 已知问题

## 1. WebView2 运行时（Windows 10）

- **现象**：Windows 10 未装 WebView2 Evergreen 运行时，桌面壳嵌入区可能空白。
- **影响**：仅影响嵌入前端展示；前端仍可用「浏览器打开」。
- **当前处理**：安装程序做注册表检测并提示；Win11 已内置无需处理。
- **后续**：内置 WebView2 固定版本运行时，或在安装程序里静默运行官方 Evergreen 引导程序。

## 2. 干净机一键安装尚未在 VM 验收

- **现象**：安装包已在开发机构建，但未在无 Python/Node/MySQL 的干净 Windows 上实装验证 MySQL 自动初始化与首启全流程。
- **处理**：见 [TEST_REPORT.md](TEST_REPORT.md)，需在有条件的环境补测。

## 3. MySQL 端口 3307 被占用

- **现象**：3307 被非工作台服务占用时，`deploy-mysql.ps1` 返回 `conflict` 且拒绝改动该服务。
- **处理**：属预期安全行为；请为工作台改用空闲端口（改脚本 `-Port` 并同步启动器/后端配置）。

## 4. 安装包体积较大

- **现象**：内置完整 MySQL 8.4（含 `bin/share/lib`）与完整便携 Python，安装包约 228 MB。
- **处理**：这是「无依赖一键安装」的代价。可后续裁剪 MySQL `docs/`、`include/` 与 Python 测试/构建目录以减小体积。

## 5. 卸载不删除数据（预期行为）

- **现象**：卸载后 `%PROGRAMDATA%\ALE Workbench\mysql-data` 与 `%APPDATA%\ALE Workbench Launcher` 仍保留。
- **处理**：这是保护科研数据的有意设计，不是 bug。彻底清除需手工删除（见 DATA_BACKUP_AND_RESTORE）。

## 6. 后端首次启动依赖数据库就绪

- **现象**：若数据库未部署完成即启动后端，`/health` 会报 `database` 非 ok，后端可能进入降级状态。
- **处理**：安装程序在文件复制后自动部署数据库；手动部署见 USER_GUIDE。
