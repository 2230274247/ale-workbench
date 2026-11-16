# ALE Workbench v1.0 — 发布说明

## 版本 1.0.0

首次交付 Windows 一键安装包 `ALE-Workbench-Setup-x64.exe`。

### 新特性

- **桌面壳（C# / .NET 10 / WPF + WebView2）**：一键启动/停止/重启，实时状态（后端/数据库/前端/地址），托盘最小化，嵌入式前端。
- **本地 + 云端双模式**：本地管理本机后端与 MySQL；云端仅导航到 HTTPS 地址。
- **便携 Python 3.14**：内置 CPython + 已校验依赖，目标机无需 Python。
- **内置 MySQL 8.4**：自动检测复用或部署独立实例，数据目录独立于安装目录。
- **安全启动/停止**：schema v2 启动溯源，只认领本项目进程，不误杀、不弹 CMD。
- **安装/配置/数据分离**：安装目录、`%APPDATA%` 配置、`%PROGRAMDATA%` 数据三者分离，卸载保留数据。

### 兼容性

- 后端兼容 API 版本：`1.8.0`。
- 目标平台：Windows 11 x64（Windows 10 x64 需 WebView2）。

### 已知限制

见 [KNOWN_ISSUES.md](KNOWN_ISSUES.md)。干净虚拟机一键安装尚未验收（见 TEST_REPORT.md）。

### 校验

安装包：`ALE-Workbench-Setup-x64.exe`（约 228 MB）。

```
SHA-256: 3303dd17c8769b724c13a38ee23eba8a0329312475a139828ab22278048698de
```

完整校验见同目录 `SHA256SUMS.txt`。
