-- =====================================================================
-- ALE 实验工作台 · 00 数据库创建
-- 目标实例: MySQL 8.4.11 @ 127.0.0.1:3307  (datadir H:\ALE_AI\mysql_data)
-- 说明: 本脚本幂等，可重复执行。
-- 字符集: utf8mb4 / utf8mb4_0900_ai_ci (与 my.ini 的 character-set-server=utf8mb4 一致)
-- =====================================================================

CREATE DATABASE IF NOT EXISTS `ale_workbench`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_0900_ai_ci;

-- 说明: 本项目不修改任何既有库。建库前已核实 datadir 下仅有
-- mysql / performance_schema / sys 三个系统库，无用户库，无覆盖风险。
