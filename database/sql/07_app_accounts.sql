-- =====================================================================
-- ALE 实验工作台 · 07 应用专用账号
-- 依赖: 06_constraints_and_views.sql
-- ---------------------------------------------------------------------
-- 安全说明:
--   本脚本使用占位符 __ALE_APP_PASSWORD__ / __ALE_RO_PASSWORD__，
--   真实密码由 apply_accounts.py 在运行时随机生成并注入，
--   不写入本文件、不进入版本控制、不出现在设计报告中。
--   生成后的密码保存在 H:\ALE_AI\database\.appcreds（本地文件）。
--
-- 权限设计（最小权限原则）:
--   ale_app : 应用读写账号，供 FastAPI 后端使用。
--             具备 SELECT/INSERT/UPDATE/DELETE，无 DROP/ALTER。
--   ale_ro  : 只读账号，供图表渲染、数据导出、AI 分析使用。
--             仅 SELECT，杜绝任何写入路径。
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- ale_app 应用读写账号
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'ale_app'@'localhost' IDENTIFIED BY '__ALE_APP_PASSWORD__';
CREATE USER IF NOT EXISTS 'ale_app'@'127.0.0.1' IDENTIFIED BY '__ALE_APP_PASSWORD__';
ALTER USER 'ale_app'@'localhost' IDENTIFIED BY '__ALE_APP_PASSWORD__';
ALTER USER 'ale_app'@'127.0.0.1' IDENTIFIED BY '__ALE_APP_PASSWORD__';

GRANT SELECT, INSERT, UPDATE, DELETE ON `ale_workbench`.* TO 'ale_app'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON `ale_workbench`.* TO 'ale_app'@'127.0.0.1';

-- ---------------------------------------------------------------------
-- ale_ro 只读账号
-- ---------------------------------------------------------------------
CREATE USER IF NOT EXISTS 'ale_ro'@'localhost' IDENTIFIED BY '__ALE_RO_PASSWORD__';
CREATE USER IF NOT EXISTS 'ale_ro'@'127.0.0.1' IDENTIFIED BY '__ALE_RO_PASSWORD__';
ALTER USER 'ale_ro'@'localhost' IDENTIFIED BY '__ALE_RO_PASSWORD__';
ALTER USER 'ale_ro'@'127.0.0.1' IDENTIFIED BY '__ALE_RO_PASSWORD__';

GRANT SELECT ON `ale_workbench`.* TO 'ale_ro'@'localhost';
GRANT SELECT ON `ale_workbench`.* TO 'ale_ro'@'127.0.0.1';

FLUSH PRIVILEGES;
