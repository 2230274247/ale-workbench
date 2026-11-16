# ALE Workbench v1.0 — 数据备份与恢复

> 实验数据是科研资产。以下操作默认**只读/复制**，不删除、不覆盖、不重建生产数据库。

## 数据在哪里

| 数据 | 位置 |
|------|------|
| MySQL 全部数据库（含实验/样品/工艺/测量） | `%PROGRAMDATA%\ALE Workbench\mysql-data\`（MySQL 数据目录） |
| 数据库账号凭据 | `<项目根>\database\.dbcreds`（管理员）、`.appcreds`（应用账号） |
| 桌面壳配置 | `%APPDATA%\ALE Workbench Launcher\config.json` |
| 上传的原始数据/原件（若有独立原件目录） | 见后端配置的 `storage` / `storage-test` 目录 |

## 备份

**方式 A（推荐，逻辑备份，可跨版本恢复）：**

```
mysqldump --protocol=tcp -h 127.0.0.1 -P 3307 -u <管理员> -p \
  --single-transaction --routines --events --all-databases > ale_backup_YYYYMMDD.sql
```

管理员账号来自 `database\.dbcreds`（`user=` / `password=` 字段）。`--single-transaction` 保证 InnoDB 一致性快照，不锁表。

**方式 B（冷备份，物理文件）：**

1. 停止后端（桌面壳「停止工作站」）。
2. 停止 MySQL 服务 `ALEWorkbenchMySQL`（或在 `ale-ctl.ps1` 中确认）。
3. 整体复制 `%PROGRAMDATA%\ALE Workbench\mysql-data\` 到备份盘。
4. 重新启动服务。

> 物理备份必须连 MySQL 一起停，否则文件可能处于不一致状态。

**方式 C（自动每日备份）：** 项目已提供 `database/backup_db.py` 与 `database/install_daily_backup.ps1`（开发环境可用，安装版请先核对路径）。

## 恢复

**逻辑备份恢复（方式 A）：**

```
mysql --protocol=tcp -h 127.0.0.1 -P 3307 -u <管理员> -p < ale_backup_YYYYMMDD.sql
```

恢复前请确认目标实例是空库或你明确要覆盖的库——**绝不覆盖生产数据库**；测试请用独立的 `*_test` 数据库。

**物理备份恢复（方式 B）：**

1. 停止 MySQL 服务。
2. 将备份的 `mysql-data\` 整体覆盖回 `%PROGRAMDATA%\ALE Workbench\mysql-data\`（先保留原目录）。
3. 启动服务并核对 `GET /health` 返回 `database: ok`。

## 校验

- 恢复后用桌面壳「版本」或 `curl http://127.0.0.1:8001/health` 确认 `database: ok`。
- 抽查关键表行数与抽样记录，确认数据完整。

## 安全红线

- 不要在上传备份时包含 `.dbcreds` / `.appcreds` / `.env`（凭据）。
- 不要把备份文件发到公开位置；备份包含敏感科研数据。
- 不要在未确认目标实例状态时执行覆盖式恢复。
