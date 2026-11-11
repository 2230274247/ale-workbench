-- =====================================================================
-- ALE 实验工作台 · 05 结论台账与仪器扩展层
-- 依赖: 04_provenance_schema.sql
-- 内容: findings / issues / issues_links -> instruments_datasets
--       -> instrument_channels -> instrument_datapoints
--       -> attachments / audit_log
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- findings 研究结论
-- 设计说明: 直接对应交接文档中的 F01-F07。
--   evidence_level 是核心字段，强制区分「实测观察」与「机理假设」——
--   例如 F01「W01完整O3-HF-TMA x100对应1.1933-1.8067nm表观减薄」是
--   measured；F07「O3可能改变表面终止状态」是 hypothesis。
--   support_sample_count 记录支撑样品数，使「这条结论只有一个样片支撑」
--   成为可查询事实，而不是靠人记住。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `findings` (
  `finding_id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `finding_code`    VARCHAR(32)     NOT NULL                COMMENT '结论编号，如 F01',
  `statement`       TEXT            NOT NULL                COMMENT '结论陈述',
  `evidence_level`  VARCHAR(32)     NOT NULL DEFAULT 'measured' COMMENT 'measured=实测观察 / hypothesis=机理假设 / unverified',
  `support_sample_count` INT UNSIGNED   NULL                COMMENT '支撑样品数',
  `is_confirmed`    TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '是否已确认；多数当前为 0',
  `scope_note`      TEXT                NULL                COMMENT '适用边界与禁止外推说明',
  `created_by`      BIGINT UNSIGNED     NULL,
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`finding_id`),
  UNIQUE KEY `uk_findings_code` (`finding_code`),
  KEY `ix_findings_level` (`evidence_level`),
  CONSTRAINT `fk_findings_user` FOREIGN KEY (`created_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_findings_level` CHECK (`evidence_level` IN ('measured','hypothesis','unverified'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='研究结论台账。强制区分实测观察与机理假设。';


-- ---------------------------------------------------------------------
-- issues 问题台账
-- 设计说明: 对应交接文档 ISS-01 至 ISS-10。
--   avoid 字段(「禁止误用」)是这批数据最有价值的部分之一——
--   它是前人踩过的坑的固化。把它建成独立字段而非混在描述里，
--   使其可以被查询、可以在录入数据时被引用提醒。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `issues` (
  `issue_id`       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `issue_code`     VARCHAR(32)     NOT NULL                COMMENT '问题编号，如 ISS-01',
  `title`          VARCHAR(255)    NOT NULL,
  `severity`       VARCHAR(16)     NOT NULL DEFAULT 'medium' COMMENT 'high/medium_high/medium/medium_low/low',
  `status`         VARCHAR(32)     NOT NULL DEFAULT 'open'   COMMENT 'open/investigating/resolved/accepted_risk/deferred',
  `observed`       TEXT                NULL                COMMENT '现象与证据',
  `effect`         TEXT                NULL                COMMENT '对结论的影响',
  `action`         TEXT                NULL                COMMENT '交接处理措施',
  `avoid`          TEXT                NULL                COMMENT '禁止误用条款',
  `opened_at`      DATE                NULL,
  `closed_at`      DATE                NULL,
  `owner_user_id`  BIGINT UNSIGNED     NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`issue_id`),
  UNIQUE KEY `uk_issues_code` (`issue_code`),
  KEY `ix_issues_severity` (`severity`),
  KEY `ix_issues_status` (`status`),
  CONSTRAINT `fk_issues_user` FOREIGN KEY (`owner_user_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_issues_severity` CHECK (`severity` IN ('high','medium_high','medium','medium_low','low')),
  CONSTRAINT `chk_issues_status`   CHECK (`status`   IN ('open','investigating','resolved','accepted_risk','deferred'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='问题台账。固化前人踩过的坑与禁止误用条款。';


-- ---------------------------------------------------------------------
-- issues_links 问题-实体关联
-- 设计说明: 多态关联表。一个 ISS 可能关联实验、样品、测量或文件，
--   用 entity_type + entity_id 表达，避免为每种关联建一张表。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `issues_links` (
  `link_id`      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `issue_id`     BIGINT UNSIGNED NOT NULL,
  `entity_type`  VARCHAR(32)     NOT NULL                COMMENT 'experiment_plan/process/sample/measurement/source_file/finding/batch',
  `entity_id`    BIGINT UNSIGNED NOT NULL,
  `relation`     VARCHAR(32)     NOT NULL DEFAULT 'related' COMMENT 'related/caused_by/blocked_by/evidence_for',
  `note`         TEXT                NULL,
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`link_id`),
  UNIQUE KEY `uk_issue_entity` (`issue_id`, `entity_type`, `entity_id`, `relation`),
  KEY `ix_issues_links_entity` (`entity_type`, `entity_id`),
  CONSTRAINT `fk_il_issue` FOREIGN KEY (`issue_id`) REFERENCES `issues` (`issue_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_il_entity` CHECK (`entity_type` IN ('experiment_plan','process','sample','measurement','source_file','finding','batch')),
  CONSTRAINT `chk_il_relation` CHECK (`relation` IN ('related','caused_by','blocked_by','evidence_for'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='问题与实体的多态关联。';


-- =====================================================================
-- 仪器数据扩展层 (RGA / XPS / 未来新仪器)
-- ---------------------------------------------------------------------
-- 设计思路: 不预判每种仪器的具体字段。XPS 有结合能/峰面积，
--   RGA 有 m/z 与离子流，未来 XRR 有角度与反射率——
--   为每种仪器建一张专属表会导致表数量随仪器线性增长。
--   采用「数据集 + 通道 + 数据点」三层通用模型:
--     instruments_datasets  一次测量产生的一个数据集
--     instrument_channels   数据集内的信号通道(如 Si2p 扫描、m/z=18)
--     instrument_datapoints 通道内的实际数据点
--   仪器特有字段放 extra_json，既能存又不必改表结构。
--   本层与 measurements 通过 sample_id / process_id 关联，
--   使「同一片样品的椭偏、XPS、RGA 结果」可以在样品视图下汇总。
-- =====================================================================

-- ---------------------------------------------------------------------
-- instrument_datasets 仪器数据集
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `instrument_datasets` (
  `dataset_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `dataset_code`   VARCHAR(96)     NOT NULL,
  `instrument_type` VARCHAR(32)    NOT NULL                COMMENT 'xps/rga/xrr/afm/sem/sims/other',
  `tool_id`        BIGINT UNSIGNED     NULL,
  `sample_id`      BIGINT UNSIGNED     NULL,
  `process_id`     BIGINT UNSIGNED     NULL,
  `measurement_id` BIGINT UNSIGNED     NULL                COMMENT '若与某次椭偏测量对应同一阶段',
  `batch_id`       BIGINT UNSIGNED     NULL,
  `title`          VARCHAR(255)        NULL,
  `external_ref`   VARCHAR(128)        NULL                COMMENT '仪器侧编号，如 XPS 文件夹 H2609100564 / 1.DATA',
  `acquired_at`    DATETIME            NULL,
  `operator_user_id` BIGINT UNSIGNED   NULL,
  `source_file_id` BIGINT UNSIGNED     NULL,
  `acquisition_params` JSON            NULL                COMMENT '采集参数：通能/阳极电压/束流等',
  `sample_mapping_status` VARCHAR(24) NOT NULL DEFAULT 'unresolved' COMMENT 'resolved/unresolved/ambiguous；XPS 9文件夹 vs 4组样品的对应关系当前悬空',
  `mapping_note`   TEXT                NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`dataset_id`),
  UNIQUE KEY `uk_dataset_code` (`dataset_code`),
  KEY `ix_ds_instrument` (`instrument_type`),
  KEY `ix_ds_sample` (`sample_id`),
  KEY `ix_ds_process` (`process_id`),
  KEY `ix_ds_measurement` (`measurement_id`),
  KEY `ix_ds_batch` (`batch_id`),
  KEY `ix_ds_mapping` (`sample_mapping_status`),
  CONSTRAINT `fk_ds_tool`   FOREIGN KEY (`tool_id`)        REFERENCES `tools`        (`tool_id`)        ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_sample` FOREIGN KEY (`sample_id`)      REFERENCES `samples`      (`sample_id`)      ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_proc`   FOREIGN KEY (`process_id`)     REFERENCES `processes`    (`process_id`)     ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_msr`    FOREIGN KEY (`measurement_id`) REFERENCES `measurements` (`measurement_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_batch`  FOREIGN KEY (`batch_id`)       REFERENCES `batches`      (`batch_id`)       ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_user`   FOREIGN KEY (`operator_user_id`) REFERENCES `users`      (`user_id`)        ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_ds_file`   FOREIGN KEY (`source_file_id`) REFERENCES `source_files` (`file_id`)        ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_ds_instrument` CHECK (`instrument_type` IN ('xps','rga','xrr','afm','sem','sims','other')),
  CONSTRAINT `chk_ds_mapping`    CHECK (`sample_mapping_status` IN ('resolved','unresolved','ambiguous'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='仪器数据集(XPS/RGA/未来仪器通用)。';


-- ---------------------------------------------------------------------
-- instrument_channels 仪器信号通道
-- 设计说明: 一个数据集内的独立信号通道。
--   XPS: 每个元素扫描是一个通道(Si2p Scan / N1s Scan / O1s Scan ...)
--   RGA: 每个 m/z 是一个通道
--   峰拟合结果(peak_BE/fwhm/area)作为通道级属性存储。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `instrument_channels` (
  `channel_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `dataset_id`     BIGINT UNSIGNED NOT NULL,
  `channel_code`   VARCHAR(64)     NOT NULL                COMMENT '通道编码，如 Si2p / N1s / mz_18',
  `channel_label`  VARCHAR(128)        NULL                COMMENT '显示名，如 "Si2p Scan"',
  `channel_type`   VARCHAR(32)     NOT NULL DEFAULT 'spectrum' COMMENT 'spectrum=谱图 / survey / peak / ion_current / image',
  `element`        VARCHAR(16)         NULL                COMMENT '元素符号，如 Si / N / O / F',
  `transition`     VARCHAR(32)         NULL                COMMENT '轨道，如 2p / 1s / 3d',
  `mass_charge`    DECIMAL(12,5)       NULL                COMMENT 'RGA 的 m/z',
  `x_unit`         VARCHAR(24)         NULL                COMMENT '横轴单位：binding_energy_eV / mz / angle_deg',
  `y_unit`         VARCHAR(24)         NULL                COMMENT '纵轴单位：counts_per_s / ion_current_A',
  `peak_center`    DECIMAL(14,6)       NULL                COMMENT '峰位',
  `peak_height`    DECIMAL(18,6)       NULL,
  `fwhm`           DECIMAL(14,6)       NULL,
  `peak_area`      DECIMAL(18,6)       NULL,
  `extra_json`     JSON                NULL                COMMENT '仪器特有属性',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`channel_id`),
  UNIQUE KEY `uk_channel` (`dataset_id`, `channel_code`),
  KEY `ix_ch_ds` (`dataset_id`),
  KEY `ix_ch_element` (`element`),
  KEY `ix_ch_mz` (`mass_charge`),
  CONSTRAINT `fk_ch_ds` FOREIGN KEY (`dataset_id`) REFERENCES `instrument_datasets` (`dataset_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_ch_type` CHECK (`channel_type` IN ('spectrum','survey','peak','ion_current','image'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='仪器信号通道。XPS 元素扫描 / RGA m/z 通道。';


-- ---------------------------------------------------------------------
-- instrument_datapoints 仪器数据点
-- 设计说明: 谱图实际数据点。XPS 的 Si2p 扫描 604 点、
--   N1s 1267 点、O1s 1809 点、F1s 1005 点——
--   全部来自 VGD(VAMAS)文件解析结果。数据量对 MySQL 完全可控。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `instrument_datapoints` (
  `datapoint_id`  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `channel_id`    BIGINT UNSIGNED NOT NULL,
  `point_index`   INT UNSIGNED    NOT NULL,
  `x_value`       DECIMAL(18,8)       NULL                COMMENT '横轴值',
  `y_value`       DECIMAL(24,8)       NULL                COMMENT '纵轴值',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`datapoint_id`),
  UNIQUE KEY `uk_datapoint` (`channel_id`, `point_index`),
  KEY `ix_dp_channel` (`channel_id`),
  CONSTRAINT `fk_dp_channel` FOREIGN KEY (`channel_id`) REFERENCES `instrument_channels` (`channel_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='仪器数据点。XPS/RGA 谱图原始点。';


-- ---------------------------------------------------------------------
-- attachments 附件
-- 设计说明: 图、Origin 工程、PDF、QA 报告等非结构化产出的登记。
--   不存文件内容，只存路径与指纹，与 source_files 分工一致。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `attachments` (
  `attachment_id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `file_sha256`   CHAR(64)            NULL,
  `file_name`     VARCHAR(512)        NOT NULL,
  `rel_path`      VARCHAR(1024)       NULL,
  `attachment_type` VARCHAR(32)     NOT NULL DEFAULT 'other' COMMENT 'figure=图 / origin_project / pdf / report / script / table / other',
  `entity_type`   VARCHAR(32)         NULL                COMMENT '所属实体类型',
  `entity_id`     BIGINT UNSIGNED     NULL                COMMENT '所属实体 ID',
  `mime_type`     VARCHAR(128)        NULL,
  `size_bytes`    BIGINT UNSIGNED     NULL,
  `description`   TEXT                NULL,
  `uploaded_by`   BIGINT UNSIGNED     NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`attachment_id`),
  KEY `ix_att_entity` (`entity_type`, `entity_id`),
  KEY `ix_att_type` (`attachment_type`),
  KEY `ix_att_sha` (`file_sha256`),
  CONSTRAINT `fk_att_user` FOREIGN KEY (`uploaded_by`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_att_type`   CHECK (`attachment_type` IN ('figure','origin_project','pdf','report','script','table','other')),
  CONSTRAINT `chk_att_entity` CHECK (`entity_type` IS NULL OR `entity_type` IN ('experiment_plan','process','sample','measurement','derived_result','instrument_dataset','finding','issue','batch'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='附件登记。图/工程/报告等产出的路径与指纹。';


-- ---------------------------------------------------------------------
-- audit_log 操作审计
-- 设计说明: 为多用户环境准备。记录谁在何时改了什么，
--   对科研数据尤其重要——「这个数值是谁改的、什么时候改的」
--   必须能回答。应用层写入，数据库不自动填充。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `audit_log` (
  `audit_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`      BIGINT UNSIGNED     NULL,
  `action`       VARCHAR(32)     NOT NULL                COMMENT 'insert/update/delete/login/export',
  `entity_type`  VARCHAR(32)     NOT NULL,
  `entity_id`    BIGINT UNSIGNED     NULL,
  `field_name`   VARCHAR(128)        NULL,
  `old_value`    TEXT                NULL,
  `new_value`    TEXT                NULL,
  `client_info`  VARCHAR(255)        NULL                COMMENT 'IP/客户端标识',
  `occurred_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`audit_id`),
  KEY `ix_audit_user` (`user_id`),
  KEY `ix_audit_entity` (`entity_type`, `entity_id`),
  KEY `ix_audit_time` (`occurred_at`),
  KEY `ix_audit_action` (`action`),
  CONSTRAINT `fk_audit_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_audit_action`  CHECK (`action` IN ('insert','update','delete','login','export')),
  CONSTRAINT `chk_audit_entity`  CHECK (`entity_type` IN ('experiment_plan','process','process_step','sample','sample_transition','measurement','measurement_point','derived_result','instrument_dataset','finding','issue','batch','recipe','user','source_file'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='操作审计日志。为多用户协作与数据可信度提供追溯。';
