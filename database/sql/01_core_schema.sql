-- =====================================================================
-- ALE 实验工作台 · 01 核心实体层
-- 依赖: 00_create_database.sql
-- 幂等: 全部使用 CREATE TABLE IF NOT EXISTS
-- 顺序: users -> tools -> recipes -> batches -> samples -> experiment_plans
--       (被引用者必须先建)
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- users 用户
-- 设计说明: 现阶段不接入认证 UI，password_hash 允许为 NULL，
--           使「先建用户占位、后补密码」成为可能。role 用 VARCHAR+CHECK
--           而非 ENUM，便于日后增加角色而不改表结构。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `user_id`       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(64)     NOT NULL                COMMENT '登录名，唯一',
  `display_name`  VARCHAR(128)        NULL                COMMENT '显示名，如「王某某」',
  `email`         VARCHAR(255)        NULL,
  `password_hash` VARCHAR(255)        NULL                COMMENT 'bcrypt/argon2 哈希；未接入认证前为 NULL',
  `role`          VARCHAR(32)     NOT NULL DEFAULT 'viewer' COMMENT 'admin=管理员 operator=普通用户 viewer=只读用户',
  `status`        VARCHAR(16)     NOT NULL DEFAULT 'active' COMMENT 'active/disabled',
  `notes`         TEXT                NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uk_users_username` (`username`),
  KEY `ix_users_role_status` (`role`, `status`),
  CONSTRAINT `chk_users_role`   CHECK (`role`   IN ('admin','operator','viewer')),
  CONSTRAINT `chk_users_status` CHECK (`status` IN ('active','disabled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='用户与角色。为后续多用户、数据隔离与共享预留。';


-- ---------------------------------------------------------------------
-- tools 仪器设备
-- 设计说明: 把「椭偏仪」「热ALE腔体」「XPS」「RGA」统一抽象为 tool，
--           使 measurements / processes 都能指向具体设备，
--           也为日后增加新仪器提供挂载点。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `tools` (
  `tool_id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tool_code`    VARCHAR(64)     NOT NULL                COMMENT '设备编码，如 THERMAL_ALE_01 / ELLIPSOMETER_01',
  `tool_name`    VARCHAR(255)    NOT NULL,
  `tool_type`    VARCHAR(64)     NOT NULL                COMMENT 'ellipsometer/thermal_ale/xps/rga/xrr/afm/sem/other',
  `vendor`       VARCHAR(128)        NULL                COMMENT '如 Eoptics / K-Alpha',
  `model`        VARCHAR(128)        NULL,
  `location`     VARCHAR(255)        NULL,
  `status`       VARCHAR(24)     NOT NULL DEFAULT 'active' COMMENT 'active/maintenance/retired',
  `notes`        TEXT                NULL,
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`tool_id`),
  UNIQUE KEY `uk_tools_code` (`tool_code`),
  KEY `ix_tools_type` (`tool_type`),
  CONSTRAINT `chk_tools_status` CHECK (`status` IN ('active','maintenance','retired'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='仪器设备台账。';


-- ---------------------------------------------------------------------
-- recipes 工艺配方
-- 设计说明: 关键决策——「标称配方」与「实际运行」分离。
--           交接文档反复强调 R1≈275C/R2≈255C 属历史典型值，不能推定每次一致。
--           因此本表只存配方定义(标称)，真实运行参数存在 process_steps。
--           recipe_kind 区分沉积配方与各化学步配方。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `recipes` (
  `recipe_id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `recipe_code`      VARCHAR(64)     NOT NULL                COMMENT '配方编码，如 RCP-PECVD-SIN-30NM / RCP-O3-STD',
  `recipe_name`      VARCHAR(255)    NOT NULL                COMMENT '原始配方名，如 2026.9.1-SiN-30nm.rcp',
  `recipe_kind`      VARCHAR(32)     NOT NULL                COMMENT 'deposition/o3/hf/tma/plasma/full_cycle/purge',
  `material`         VARCHAR(128)        NULL,
  `nominal_temp_c`   DECIMAL(8,2)        NULL                COMMENT '标称温度(如 275.00)，非实测',
  `nominal_pressure` DECIMAL(12,4)       NULL,
  `pressure_unit`    VARCHAR(16)         NULL                COMMENT 'kPa/Pa/mTorr',
  `nominal_gas_flows` JSON               NULL                COMMENT '如 {"N2_sccm":20,"O2_sccm":30}；结构化存流量',
  `pulse_s`          DECIMAL(10,3)       NULL,
  `purge_s`          DECIMAL(10,3)       NULL,
  `wait_s`           DECIMAL(10,3)       NULL,
  `version`          VARCHAR(32)     NOT NULL DEFAULT 'v1',
  `status`           VARCHAR(24)     NOT NULL DEFAULT 'active' COMMENT 'active/superseded/obsolete',
  `source_file_id`   BIGINT UNSIGNED     NULL                COMMENT '配方来源文件，FK 于 03_provenance 中补加',
  `notes`            TEXT                NULL,
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`recipe_id`),
  UNIQUE KEY `uk_recipes_code_version` (`recipe_code`, `version`),
  KEY `ix_recipes_kind` (`recipe_kind`),
  CONSTRAINT `chk_recipes_kind`   CHECK (`recipe_kind` IN ('deposition','o3','hf','tma','plasma','full_cycle','purge')),
  CONSTRAINT `chk_recipes_status` CHECK (`status` IN ('active','superseded','obsolete'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='工艺配方(标称定义)。实际运行参数见 process_steps。';


-- ---------------------------------------------------------------------
-- batches 批次
-- 设计说明: 对应四个原始压缩包所代表的沉积批次。
--           交接文档明确「不同批次初始厚度约 30/300/74/47-49nm，不应合并拟合」，
--           因此批次是强制隔离边界，几乎所有样品都挂在某个批次下。
--           source_zip_sha256 直接沿用 file_inventory.csv 中已有的哈希，不重算。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `batches` (
  `batch_id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `batch_code`            VARCHAR(64)     NOT NULL                COMMENT '批次编码，如 B-20260831-W01 / B-20260916-300NM',
  `batch_name`            VARCHAR(255)    NOT NULL,
  `material`              VARCHAR(128)    NOT NULL DEFAULT 'PECVD SiNx:H',
  `wafer_size`            VARCHAR(32)         NULL                COMMENT '如 4inchx4inch / 20mmx20mm',
  `nominal_thickness_nm`  DECIMAL(12,3)       NULL                COMMENT '标称厚度(30/300/74/47nm)',
  `deposit_recipe_id`     BIGINT UNSIGNED     NULL                COMMENT '沉积配方',
  `deposit_date`          DATE                NULL,
  `deposit_set_temp_c`    DECIMAL(8,2)        NULL                COMMENT 'PECVD 设定温度',
  `deposit_actual_temp_c` DECIMAL(8,2)        NULL                COMMENT 'PECVD 实测温度；ISS-02 要求与设定值分开',
  `deposit_gas_flows`     JSON                NULL                COMMENT 'SiH4/NH3/N2 流量',
  `source_zip`            VARCHAR(255)        NULL                COMMENT '原始压缩包文件名',
  `source_zip_sha256`     CHAR(64)            NULL                COMMENT '压缩包 SHA-256，溯源用',
  `anomaly_flag`          TINYINT(1)      NOT NULL DEFAULT 0     COMMENT '1=已知异常批次(如 PECVD-ERROR_Temperature)',
  `anomaly_note`          TEXT                NULL                COMMENT '异常描述；ISS-02 禁止据文件名断言故障机理',
  `owner_user_id`         BIGINT UNSIGNED     NULL,
  `status`                VARCHAR(24)     NOT NULL DEFAULT 'active' COMMENT 'active/archived/quarantined',
  `notes`                 TEXT                NULL,
  `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`batch_id`),
  UNIQUE KEY `uk_batches_code` (`batch_code`),
  KEY `ix_batches_status` (`status`),
  KEY `ix_batches_anomaly` (`anomaly_flag`),
  CONSTRAINT `fk_batches_recipe` FOREIGN KEY (`deposit_recipe_id`) REFERENCES `recipes` (`recipe_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_batches_owner`  FOREIGN KEY (`owner_user_id`)     REFERENCES `users`   (`user_id`)   ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_batches_status` CHECK (`status` IN ('active','archived','quarantined'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='沉积批次。批次是数据可比性的强制隔离边界。';


-- ---------------------------------------------------------------------
-- samples 样品
-- 设计说明: 工作台的中心实体。三点关键设计:
--   1) sample_code 全局唯一，格式 批次前缀-Sxx（W01-S01 / B28-S06 / B05-S01）。
--      交接文档警告「W01-S01、B28-S01、B05-S01 不是一片样品」，
--      故唯一约束建在全局编码上，而非批次内序号。
--   2) parent_sample_id 自引用，表达「母片切出小样」的层级。
--   3) exclude_from_analysis + exclude_reason：把 W01-S09(酒精湿巾异常)
--      这类「必须隔离、严禁纳入常规均值」的样品在数据库层面固化，
--      而不是只写在文档里靠人记住。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `samples` (
  `sample_id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `sample_code`           VARCHAR(64)     NOT NULL                COMMENT '全局唯一样品编码，如 W01-S09',
  `batch_id`              BIGINT UNSIGNED NOT NULL,
  `parent_sample_id`      BIGINT UNSIGNED     NULL                COMMENT '母片/上级样品，自引用',
  `sample_type`           VARCHAR(32)     NOT NULL DEFAULT 'coupon' COMMENT 'parent_wafer=母片 full_wafer=整片 coupon=小样',
  `display_label`         VARCHAR(128)        NULL                COMMENT '原始文件中的编号，如 "1" / "9"',
  `nominal_thickness_nm`  DECIMAL(12,3)       NULL,
  `size_desc`             VARCHAR(64)         NULL                COMMENT '如 20mmx20mm / 4inchx4inch',
  `cut_position`          VARCHAR(128)        NULL                COMMENT '切割位置描述',
  `surface_state`         VARCHAR(128)        NULL                COMMENT '表面状态备注(未处理/plasma/擦拭等)',
  `pre_treatment`         VARCHAR(255)        NULL                COMMENT '前处理描述；ISS-05 要求记录前处理',
  `status`                VARCHAR(24)     NOT NULL DEFAULT 'available' COMMENT 'available/in_process/consumed/lost/quarantined',
  `exclude_from_analysis` TINYINT(1)      NOT NULL DEFAULT 0     COMMENT '1=排除出常规统计(如 W01-S09)',
  `exclude_reason`        TEXT                NULL                COMMENT '排除理由，如「酒精湿巾擦拭，刻蚀量异常升高」',
  `owner_user_id`         BIGINT UNSIGNED     NULL,
  `notes`                 TEXT                NULL,
  `created_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`            DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`sample_id`),
  UNIQUE KEY `uk_samples_code` (`sample_code`),
  KEY `ix_samples_batch` (`batch_id`),
  KEY `ix_samples_status` (`status`),
  KEY `ix_samples_exclude` (`exclude_from_analysis`),
  KEY `ix_samples_parent` (`parent_sample_id`),
  CONSTRAINT `fk_samples_batch`  FOREIGN KEY (`batch_id`)         REFERENCES `batches` (`batch_id`) ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_samples_parent` FOREIGN KEY (`parent_sample_id`) REFERENCES `samples` (`sample_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_samples_owner`  FOREIGN KEY (`owner_user_id`)    REFERENCES `users`   (`user_id`)   ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_samples_type`   CHECK (`sample_type` IN ('parent_wafer','full_wafer','coupon')),
  CONSTRAINT `chk_samples_status` CHECK (`status` IN ('available','in_process','consumed','lost','quarantined'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='样品。工作台中心实体，支持母片-小样层级与异常样品隔离。';


-- ---------------------------------------------------------------------
-- experiment_plans 实验计划
-- 设计说明: 对应工作台「实验计划」模块，位于执行之前。
--           一个计划可派生多个 process(执行)，形成 计划->执行 的链路。
--           单独建表而非塞进 processes，是为了让「先计划后执行」
--           与「执行中临时加做」都能表达。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `experiment_plans` (
  `plan_id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `plan_code`       VARCHAR(64)     NOT NULL                COMMENT '计划编码，如 PLAN-2026-10-14-HFTMA-SERIES',
  `title`           VARCHAR(255)    NOT NULL,
  `objective`       TEXT                NULL                COMMENT '实验目的',
  `hypothesis`      TEXT                NULL                COMMENT '待验证假设',
  `design_note`     TEXT                NULL                COMMENT '变量设计、对照组设置',
  `planned_start`   DATE                NULL,
  `planned_end`     DATE                NULL,
  `priority`        VARCHAR(16)     NOT NULL DEFAULT 'normal' COMMENT 'high/normal/low',
  `status`          VARCHAR(24)     NOT NULL DEFAULT 'draft'  COMMENT 'draft/approved/running/completed/abandoned',
  `owner_user_id`   BIGINT UNSIGNED     NULL,
  `batch_id`        BIGINT UNSIGNED     NULL                COMMENT '若计划绑定单一批次',
  `notes`           TEXT                NULL,
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`plan_id`),
  UNIQUE KEY `uk_plans_code` (`plan_code`),
  KEY `ix_plans_status` (`status`),
  KEY `ix_plans_owner` (`owner_user_id`),
  CONSTRAINT `fk_plans_owner` FOREIGN KEY (`owner_user_id`) REFERENCES `users`   (`user_id`)   ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_plans_batch` FOREIGN KEY (`batch_id`)      REFERENCES `batches` (`batch_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_plans_status`   CHECK (`status`   IN ('draft','approved','running','completed','abandoned')),
  CONSTRAINT `chk_plans_priority` CHECK (`priority` IN ('high','normal','low'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='实验计划。位于实验执行之前，一个计划可派生多个执行。';
