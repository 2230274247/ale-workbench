-- =====================================================================
-- ALE 实验工作台 · 04 溯源与派生结果层
-- 依赖: 03_measurement_schema.sql
-- 内容: source_files -> derived_results
-- 设计主线: 原始文件 + 分析结果
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- source_files 原始文件登记
-- 设计说明: 数据溯源的核心。三条设计:
--   (1) SHA-256 是主溯源键。SRC-A 的 file_inventory.csv 已经存好了每个
--       原始文件的哈希，直接沿用，不重算。哈希使「文件是否被改动过」
--       成为可验证事实——这对科研数据至关重要。
--   (2) 原始文件只读。本表只登记路径与指纹，不存文件内容，
--       也不允许通过本系统修改原始文件。所有分析写入新版本目录。
--   (3) file_role 区分文件在数据链中的位置(仪器原始导出/派生汇总/
--       点级派生/分析产出/元数据)，因为四批数据里这六种性质完全不同，
--       混为一类会导致 schema 设计错误。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `source_files` (
  `file_id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `file_sha256`    CHAR(64)            NOT NULL                COMMENT 'SHA-256 主溯源键',
  `file_name`      VARCHAR(512)        NOT NULL                COMMENT '文件名(可能含 n/k 编码，如 1-n1.9198-k0.0005-ALE.xlsx)',
  `rel_path`       VARCHAR(1024)       NULL                COMMENT '相对于压缩包根或项目根的路径',
  `source_zip`     VARCHAR(255)        NULL                COMMENT '来源压缩包文件名',
  `file_role`      VARCHAR(32)     NOT NULL                COMMENT 'instrument_raw=仪器原始导出 / derived_summary=派生汇总 / point_derived=点级派生 / analysis_output=分析产出 / metadata=元数据 / xps_raw=其他表征原始',
  `file_ext`       VARCHAR(16)         NULL,
  `size_bytes`     BIGINT UNSIGNED     NULL,
  `mtime_epoch`    BIGINT              NULL                COMMENT '文件修改时间(epoch 秒)',
  `batch_id`       BIGINT UNSIGNED     NULL,
  `sample_id`      BIGINT UNSIGNED     NULL                COMMENT '若该文件可唯一归属某样品',
  `is_readonly`    TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '原始文件只读，恒为 1',
  `is_duplicate_of` BIGINT UNSIGNED    NULL                COMMENT '重复文件的原始版本；SRC-D 内嵌 SRC-A/SRC-C 副本',
  `parse_status`   VARCHAR(24)     NOT NULL DEFAULT 'pending' COMMENT 'pending/parsed/failed/ignored',
  `parse_note`     TEXT                NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`file_id`),
  UNIQUE KEY `uk_source_files_sha` (`file_sha256`),
  KEY `ix_source_files_batch` (`batch_id`),
  KEY `ix_source_files_sample` (`sample_id`),
  KEY `ix_source_files_role` (`file_role`),
  KEY `ix_source_files_status` (`parse_status`),
  KEY `ix_source_files_dup` (`is_duplicate_of`),
  CONSTRAINT `fk_sf_batch`  FOREIGN KEY (`batch_id`)        REFERENCES `batches`      (`batch_id`)  ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_sf_sample` FOREIGN KEY (`sample_id`)       REFERENCES `samples`      (`sample_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_sf_dup`    FOREIGN KEY (`is_duplicate_of`) REFERENCES `source_files` (`file_id`)   ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_sf_role`   CHECK (`file_role` IN ('instrument_raw','derived_summary','point_derived','analysis_output','metadata','xps_raw')),
  CONSTRAINT `chk_sf_status` CHECK (`parse_status` IN ('pending','parsed','failed','ignored'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='原始文件登记与溯源。SHA-256 为主键，原始文件只读。';


-- ---------------------------------------------------------------------
-- derived_results 派生分析结果
-- 设计说明: 所有「计算出来的结论」都落在这里，而不是手填字段。
--   关键原则: 减薄量 R = before - after 必须是可追溯的派生对象，
--   指向两次具体测量，而不是人工录入的数字。这样:
--     - 任何结论都能回溯到源测量；
--     - 测量被取代时，依赖它的派生结果可被识别为「需重算」；
--     - 换光学模型重算后，新旧结果并存可对比。
--   result_kind 覆盖四批数据中出现的全部派生量:
--     R(表观减薄) / delta_d(表观增厚) / apparent_epc / rate
--     / paired_point_delta(点级配对差) / uniformity / fit_quality
--   配对方式(pairing_method)必须记录，因为「同坐标配对」与
--   「按行号相减」会给出不同答案，SRC-D 明确采用前者。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `derived_results` (
  `result_id`        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `result_code`      VARCHAR(128)    NOT NULL                COMMENT '结果编码，如 RES-B05-S01-R',
  `result_kind`      VARCHAR(32)     NOT NULL                COMMENT 'apparent_removal_R / delta_d / apparent_epc / rate / paired_point_delta / uniformity / fit_quality / other',
  `sample_id`        BIGINT UNSIGNED NOT NULL,
  `before_measurement_id` BIGINT UNSIGNED NULL                COMMENT '前一次测量',
  `after_measurement_id`  BIGINT UNSIGNED NULL                COMMENT '后一次测量',
  `process_id`       BIGINT UNSIGNED     NULL                COMMENT '所评估的工艺运行',
  `value_nm`         DECIMAL(16,8)       NULL                COMMENT '数值(单位见 value_unit)',
  `value_unit`       VARCHAR(16)         NULL                COMMENT 'nm / A_per_cycle / pct',
  `value_sd_nm`      DECIMAL(16,8)       NULL                COMMENT '空间 SD(非独立重复误差)',
  `cycles_basis`     INT UNSIGNED        NULL                COMMENT '计算速率所用的循环基数',
  `pairing_method`   VARCHAR(64)         NULL                COMMENT 'same_xy_coordinate=同坐标配对 / row_index / mean_difference',
  `paired_point_count` INT UNSIGNED      NULL,
  `model_consistent` TINYINT(1)          NULL                COMMENT '1=前后测量用同一光学模型；0=跨模型相减，需谨慎',
  `is_valid`         TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '0=因源测量被取代而失效，需重算',
  `evidence_level`   VARCHAR(32)     NOT NULL DEFAULT 'measured' COMMENT 'measured=实测观察 / hypothesis=机理假设 / unverified',
  `computation_note` TEXT                NULL                COMMENT '计算说明与限制',
  `computed_at`      DATETIME            NULL,
  `computed_by`      VARCHAR(128)        NULL                COMMENT '计算者或脚本标识',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`result_id`),
  UNIQUE KEY `uk_derived_code` (`result_code`),
  KEY `ix_derived_sample` (`sample_id`),
  KEY `ix_derived_kind` (`result_kind`),
  KEY `ix_derived_before` (`before_measurement_id`),
  KEY `ix_derived_after` (`after_measurement_id`),
  KEY `ix_derived_process` (`process_id`),
  KEY `ix_derived_valid` (`is_valid`),
  KEY `ix_derived_evidence` (`evidence_level`),
  CONSTRAINT `fk_dr_sample`  FOREIGN KEY (`sample_id`)               REFERENCES `samples`      (`sample_id`)      ON DELETE CASCADE  ON UPDATE CASCADE,
  CONSTRAINT `fk_dr_before`  FOREIGN KEY (`before_measurement_id`)   REFERENCES `measurements` (`measurement_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_dr_after`   FOREIGN KEY (`after_measurement_id`)    REFERENCES `measurements` (`measurement_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_dr_process` FOREIGN KEY (`process_id`)              REFERENCES `processes`    (`process_id`)     ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_dr_kind`     CHECK (`result_kind` IN ('apparent_removal_R','delta_d','apparent_epc','rate','paired_point_delta','uniformity','fit_quality','other')),
  CONSTRAINT `chk_dr_evidence` CHECK (`evidence_level` IN ('measured','hypothesis','unverified'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='派生分析结果。所有结论可追溯到源测量，禁止手填。';
