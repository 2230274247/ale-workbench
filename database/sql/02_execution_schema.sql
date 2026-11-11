-- =====================================================================
-- ALE 实验工作台 · 02 执行层
-- 依赖: 01_core_schema.sql
-- 内容: optical_models -> processes -> process_steps -> process_samples
--       -> sample_transitions
-- 设计主线: 实验计划 -> 实验执行 -> 工艺步骤 -> 样品流转
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- optical_models 光学模型
-- 设计说明: 这是本项目最关键的设计决策之一。
--   原始椭偏文件名把 n/k 编码在文件名里(如 1-n1.9198-k0.0005-ALE.xlsx)，
--   文件内容中并无 n/k 字段，WaferID 一栏恒为空。
--   更严重的是：同一样品的「初始态」与「处理后」使用了不同的 n/k
--   (1-n1.91-k0.xlsx  vs  1-n1.9198-k0.0005-ALE.xlsx)。
--   因此 n/k 不是可选元数据，而是决定结论的变量，必须提升为独立实体，
--   由每次测量显式引用，使「跨模型相减」这一事实在库中可见、可审计。
--   ISS-03(300nm 模型 MSE 偏高) 也通过本表统一管理模型版本。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `optical_models` (
  `model_id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `model_code`       VARCHAR(64)     NOT NULL                COMMENT '模型编码，如 OM-SIN-30NM-N1.9198-K0.0005',
  `model_name`       VARCHAR(255)    NOT NULL,
  `rcp_name`         VARCHAR(255)        NULL                COMMENT '仪器配方名，如 2026.9.1-SiN-30nm.rcp',
  `spl_name`         VARCHAR(255)        NULL                COMMENT 'Profile 名，如 8.31-30nm-SiN.spl',
  `n_setting`        DECIMAL(10,6)       NULL                COMMENT '折射率 n 设定值',
  `k_setting`        DECIMAL(10,6)       NULL                COMMENT '消光系数 k 设定值',
  `layer_structure`  JSON                NULL                COMMENT '层结构定义，如 [{"layer":1,"material":"SiNx:H"}]',
  `aoi_deg`          DECIMAL(8,3)        NULL                COMMENT '入射角 AOI',
  `valid_range_nm`   VARCHAR(64)         NULL                COMMENT '适用厚度范围，如 20-50nm',
  `applicable_batch_id` BIGINT UNSIGNED  NULL                COMMENT '若模型仅适用于特定批次',
  `quality_note`     TEXT                NULL                COMMENT '模型质量备注；如 300nm 模型 MSE 偏高记录',
  `status`           VARCHAR(24)     NOT NULL DEFAULT 'active' COMMENT 'active/superseded/experimental',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`model_id`),
  UNIQUE KEY `uk_optical_models_code` (`model_code`),
  KEY `ix_optical_models_batch` (`applicable_batch_id`),
  CONSTRAINT `fk_optical_models_batch` FOREIGN KEY (`applicable_batch_id`) REFERENCES `batches` (`batch_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_optical_models_status` CHECK (`status` IN ('active','superseded','experimental'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='椭偏光学模型(n/k 设定)。把跨模型相减的事实显式化，是结论可信度的前提。';


-- ---------------------------------------------------------------------
-- processes 工艺运行
-- 设计说明: 一次实际执行的工艺事件。粒度选择说明:
--   本表表示「一次装入样品、按一组步骤跑完」的过程。
--   例: 9/16 对 300nm 的 10、11 号只通 HF；
--       9/28 对 B28 系列做 O3 预暴露 + HF-TMA 50 次；
--       10/14 对 B05 系列做固定预暴露 + HF-TMA 次数梯度。
--   process_mode 区分「完整循环」与「预暴露后 HF-TMA」——
--   交接文档明确警告二者绝不可混为一组(EXP-09 vs EXP-10)。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `processes` (
  `process_id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `process_code`      VARCHAR(64)     NOT NULL                COMMENT '运行编码，如 RUN-20261014-B05-HFTMA-SERIES',
  `plan_id`           BIGINT UNSIGNED     NULL                COMMENT '所属实验计划；可为空(临时加做)',
  `batch_id`          BIGINT UNSIGNED     NULL,
  `process_mode`      VARCHAR(32)     NOT NULL                COMMENT 'full_cycle=逐循环完整O3-HF-TMA / pre_expose_then_react=固定预暴露后HF-TMA / hf_only / o3_only / tma_only / plasma / deposition / other',
  `tool_id`           BIGINT UNSIGNED     NULL                COMMENT '执行设备(热ALE腔体)',
  `r1_temp_c`         DECIMAL(8,2)        NULL                COMMENT 'R1 实际温度；与标称配方分开',
  `r2_temp_c`         DECIMAL(8,2)        NULL                COMMENT 'R2 实际温度',
  `n2_flow_sccm`      DECIMAL(10,3)       NULL,
  `o3_pre_cycles`     INT UNSIGNED        NULL                COMMENT 'O3 预暴露次数；ISS-07 明确次数不等于已标定剂量',
  `o3_pre_duration_s` DECIMAL(10,3)       NULL                COMMENT '单次预暴露时长；与次数分开记录，避免 10s/10次 混淆',
  `full_ale_cycles`   INT UNSIGNED        NULL                COMMENT '完整 O3-HF-TMA 循环数',
  `hf_tma_repeats`    INT UNSIGNED        NULL                COMMENT '预暴露后 HF-TMA 重复次数',
  `started_at`        DATETIME            NULL,
  `ended_at`          DATETIME            NULL,
  `operator_user_id`  BIGINT UNSIGNED     NULL,
  `co_etch_group`     VARCHAR(64)         NULL                COMMENT '共腔/同批运行分组；ISS-06 要求共腔与独立运行不得合并',
  `is_independent_run` TINYINT(1)     NOT NULL DEFAULT 1      COMMENT '0=与其他样品共腔，1=独立运行',
  `log_status`        VARCHAR(24)     NOT NULL DEFAULT 'ok'   COMMENT 'ok/partial/aborted/unknown',
  `notes`             TEXT                NULL,
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`process_id`),
  UNIQUE KEY `uk_processes_code` (`process_code`),
  KEY `ix_processes_plan` (`plan_id`),
  KEY `ix_processes_batch` (`batch_id`),
  KEY `ix_processes_mode` (`process_mode`),
  KEY `ix_processes_started` (`started_at`),
  KEY `ix_processes_coetch` (`co_etch_group`),
  CONSTRAINT `fk_processes_plan`     FOREIGN KEY (`plan_id`)          REFERENCES `experiment_plans` (`plan_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_processes_batch`    FOREIGN KEY (`batch_id`)         REFERENCES `batches` (`batch_id`)         ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_processes_tool`     FOREIGN KEY (`tool_id`)          REFERENCES `tools` (`tool_id`)            ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_processes_operator` FOREIGN KEY (`operator_user_id`) REFERENCES `users` (`user_id`)            ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_processes_mode`   CHECK (`process_mode` IN ('full_cycle','pre_expose_then_react','hf_only','o3_only','tma_only','plasma','deposition','other')),
  CONSTRAINT `chk_processes_status` CHECK (`log_status`  IN ('ok','partial','aborted','unknown'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='工艺运行(一次执行事件)。process_mode 强制区分完整循环与预暴露两种模式。';


-- ---------------------------------------------------------------------
-- process_steps 工艺步骤
-- 设计说明: 一次运行内的有序步骤。对应 SRC-A 中已存在的
--   experiment_relations.csv 原型字段(chemistry/cycles/cumulative_cycles/
--   O3_dP_kPa/pulse/purge/wait/...)，在其基础上补全实际运行参数。
--   关键: 每一步都记录「实际」参数，而非引用配方标称值——
--   因为设备日志缺失，实际值常常是 NULL，NULL 本身就是重要信息
--   (表示未知)，不得用配方标称值填充。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `process_steps` (
  `step_id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `process_id`        BIGINT UNSIGNED NOT NULL,
  `step_index`        INT UNSIGNED    NOT NULL                COMMENT '步骤序号，从 1 开始',
  `step_kind`         VARCHAR(32)     NOT NULL                COMMENT 'o2_plasma/o3_purge/hf_purge/tma_purge/purge/wait/other',
  `chemistry`         VARCHAR(64)         NULL                COMMENT 'O2_plasma/O3/HF_pyridine/TMA/none',
  `recipe_id`         BIGINT UNSIGNED     NULL                COMMENT '所依据配方(标称)',
  `cycles`            INT UNSIGNED        NULL                COMMENT '本步骤重复次数',
  `cumulative_cycles` INT UNSIGNED        NULL                COMMENT '累计循环数',
  `duration_s`        DECIMAL(10,3)       NULL,
  `pulse_s`           DECIMAL(10,3)       NULL,
  `purge_s`           DECIMAL(10,3)       NULL,
  `wait_s`            DECIMAL(10,3)       NULL,
  `actual_temp_c`     DECIMAL(8,2)        NULL                COMMENT '实测温度(区别于配方标称)',
  `delta_p`           DECIMAL(12,4)       NULL                COMMENT '腔体压力增量',
  `delta_p_unit`      VARCHAR(16)         NULL                COMMENT 'kPa/Pa',
  `o3_delta_p_kpa`    DECIMAL(12,4)       NULL                COMMENT 'O3 脉冲 ΔP，历史典型约 5kPa',
  `hf_delta_p_pa`     DECIMAL(12,4)       NULL                COMMENT 'HF 脉冲 ΔP，历史典型约 80Pa',
  `tma_delta_p_pa`    DECIMAL(12,4)       NULL                COMMENT 'TMA 脉冲 ΔP，历史典型约 110Pa',
  `o3_generator_o2_flow_set_sccm`      DECIMAL(10,3) NULL     COMMENT 'O3发生器O2供气设定流量；ISS-01 与plasma的30sccm严格区分',
  `o3_generator_o2_flow_measured_sccm` DECIMAL(10,3) NULL     COMMENT 'O3发生器O2实测流量(常为NULL=未记录)',
  `o3_concentration`  DECIMAL(12,6)       NULL                COMMENT 'O3 浓度(常为NULL)',
  `o2_plasma_w`       DECIMAL(10,3)       NULL                COMMENT 'O2 plasma 功率(30W)',
  `o2_plasma_sccm`    DECIMAL(10,3)       NULL                COMMENT 'O2 plasma 流量(30sccm)；不得与O3发生器流量混记',
  `o2_plasma_pa`      DECIMAL(12,4)       NULL                COMMENT 'O2 plasma 腔压(80Pa)',
  `step_note`         TEXT                NULL,
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`step_id`),
  UNIQUE KEY `uk_process_steps_order` (`process_id`, `step_index`),
  KEY `ix_process_steps_kind` (`step_kind`),
  KEY `ix_process_steps_recipe` (`recipe_id`),
  CONSTRAINT `fk_steps_process` FOREIGN KEY (`process_id`) REFERENCES `processes` (`process_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_steps_recipe`  FOREIGN KEY (`recipe_id`)  REFERENCES `recipes`   (`recipe_id`)  ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_steps_kind` CHECK (`step_kind` IN ('o2_plasma','o3_purge','hf_purge','tma_purge','purge','wait','other'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='工艺步骤。记录实际运行参数，未知值保持 NULL 而非用标称值填充。';


-- ---------------------------------------------------------------------
-- process_samples 运行-样品关联
-- 设计说明: 多对多。承载「同一次运行里哪些样品共腔」这一关键信息，
--   以及每个样品在该次运行中的独立参数(O3预暴露次数、HF-TMA次数)——
--   因为 10/14 实验中同一批样品每片的 HF-TMA 次数各不相同。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `process_samples` (
  `process_sample_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `process_id`        BIGINT UNSIGNED NOT NULL,
  `sample_id`         BIGINT UNSIGNED NOT NULL,
  `chamber_position`  VARCHAR(64)         NULL                COMMENT '腔体位置/装载位',
  `o3_pre_cycles`     INT UNSIGNED        NULL                COMMENT '本片在该次运行的 O3 预暴露次数(可逐片不同)',
  `hf_tma_repeats`    INT UNSIGNED        NULL                COMMENT '本片的 HF-TMA 重复次数(可逐片不同)',
  `full_ale_cycles`   INT UNSIGNED        NULL                COMMENT '本片的完整循环数',
  `is_control`        TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '1=对照样(如 0 次 O3)',
  `sample_role_note`  TEXT                NULL,
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`process_sample_id`),
  UNIQUE KEY `uk_process_sample` (`process_id`, `sample_id`),
  KEY `ix_process_samples_sample` (`sample_id`),
  CONSTRAINT `fk_ps_process` FOREIGN KEY (`process_id`) REFERENCES `processes` (`process_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_ps_sample`  FOREIGN KEY (`sample_id`)  REFERENCES `samples`   (`sample_id`)  ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='工艺运行与样品的关联。承载共腔信息与逐片工艺参数。';


-- ---------------------------------------------------------------------
-- sample_transitions 样品流转记录
-- 设计说明: 直接对应需求中的「支持样品流转」。
--   记录样品状态每一次变化(切割、装入、取出、测量、废弃、隔离)，
--   形成完整的时间线审计轨迹。这是「样品为中心」得以成立的关键——
--   任何一个样品当前为何处于此状态，都能沿本表回溯。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `sample_transitions` (
  `transition_id`   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `sample_id`       BIGINT UNSIGNED NOT NULL,
  `from_status`     VARCHAR(24)         NULL                COMMENT '变更前状态',
  `to_status`       VARCHAR(24)     NOT NULL                COMMENT '变更后状态',
  `event_type`      VARCHAR(32)     NOT NULL                COMMENT 'cut=切割 / load=装入 / unload=取出 / measure=测量 / process=工艺 / quarantine=隔离 / dispose=废弃 / receive=接收',
  `process_id`      BIGINT UNSIGNED     NULL                COMMENT '若因某次工艺运行而变更',
  `measurement_id`  BIGINT UNSIGNED     NULL                COMMENT '若因某次测量而变更(FK 于 03 中补加)',
  `event_at`        DATETIME            NULL,
  `operator_user_id` BIGINT UNSIGNED    NULL,
  `location`        VARCHAR(128)        NULL                COMMENT '物理位置',
  `note`            TEXT                NULL,
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`transition_id`),
  KEY `ix_transitions_sample` (`sample_id`),
  KEY `ix_transitions_event_at` (`event_at`),
  KEY `ix_transitions_type` (`event_type`),
  CONSTRAINT `fk_trans_sample` FOREIGN KEY (`sample_id`)  REFERENCES `samples`   (`sample_id`)   ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_trans_proc`   FOREIGN KEY (`process_id`) REFERENCES `processes` (`process_id`)  ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_trans_user`   FOREIGN KEY (`operator_user_id`) REFERENCES `users` (`user_id`)   ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_trans_event` CHECK (`event_type` IN ('cut','load','unload','measure','process','quarantine','dispose','receive'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='样品流转时间线。支持样品全生命周期追溯。';
