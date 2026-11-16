# ALE Workbench v1.0 — 安装指南

## 适用对象

在**全新 Windows 11 x64 机器**（无需预装 Python、Node.js、.NET SDK、MySQL）上安装的用户。

## 前置条件

- Windows 11 x64（或 Windows 10 x64）。
- **WebView2 运行时**：Windows 11 已内置；Windows 10 上若缺失，安装程序会提示（详见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)）。
- 安装过程需要**管理员权限**（用于注册本地 MySQL 服务与写入 `%PROGRAMDATA%`）。

## 安装步骤

1. 双击 `ALE-Workbench-Setup-x64.exe`，允许「用户账户控制」提示。
2. 选择安装目录（默认 `C:\Program Files\ALE Workbench`）。
3. 勾选「创建桌面快捷方式」（可选）。
4. 完成文件复制后，安装程序会**自动部署本地数据库**：
   - 若本机 3307 端口已有可用 MySQL → 检测并复用，不做任何改动。
   - 否则 → 用内置 MySQL 在 `%PROGRAMDATA%\ALE Workbench\mysql-data` 初始化实例、创建数据库与账号、执行迁移。
5. 安装完成后勾选「启动 ALE Workbench」即可打开桌面壳。

## 安装后布局

```
C:\Program Files\ALE Workbench\
  ALE-Workbench-Launcher.exe      # 桌面壳（自包含）
  start-workbench.ps1             # 启动脚本（带启动溯源）
  ale-ctl.ps1 / stop-workbench.ps1# 安全状态/停止
  backend\app\ + requirements.txt # 后端源码
  frontend\dist\                  # Vue 构建产物
  api\openapi\                    # OpenAPI
  database\sql\ + migrations\     # 建库/迁移
  python\                         # 便携 Python 3.14
  mysql-server\                   # 内置 MySQL 8.4
  launcher\deploy\deploy-mysql.ps1
```

数据不在这里：MySQL 数据在 `%PROGRAMDATA%\ALE Workbench\mysql-data`，配置在 `%APPDATA%\ALE Workbench Launcher\`。

## 静默安装（可选）

```
ALE-Workbench-Setup-x64.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

## 卸载

控制面板 → 卸载 ALE Workbench。**不会**删除 MySQL 数据目录与用户配置；如需彻底清除请手工删除 `%PROGRAMDATA%\ALE Workbench\mysql-data`（见 [DATA_BACKUP_AND_RESTORE.md](DATA_BACKUP_AND_RESTORE.md)）。

## 从源码构建安装包

在开发机（已装 .NET 10 SDK、Inno Setup 6、已有 `.venv-win` 与 `frontend/dist`、`mysql-server`）上：

```
powershell -NoProfile -ExecutionPolicy Bypass -File launcher\installer\build-installer.ps1
```

产物：`launcher\dist\ALE-Workbench-Setup-x64.exe`。
