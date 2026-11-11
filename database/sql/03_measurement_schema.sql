-- =====================================================================
-- ALE 实验工作台 · 03 测量层
-- 依赖: 02_execution_schema.sql
-- 内容: measurements -> measurement_points
-- 设计主线: 测量数据(点级膜厚)
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- measurements 测量记录
-- 设计说明: 一次仪器测量事件。三条关键设计:
--
--   (1) 显式引用 optical_model_id。同一样品的初始态与处理后可能用不同
--       n/k 模型(1-n1.91-k0 对比 1-n1.9198-k0.0005)，若不记录模型，
--       「表观减薄」就是跨模型相减而不可知。查询时可据此提示风险。
--
--   (2) supersedes_measurement_id 自引用 + is_current。
--       实测发现的真实问题: 300nm 批次 10 号样品的「初始膜厚」有两个版本——
--         10.xlsx        -> 均值 291.40 nm
--         10二次测量.xlsx -> 均值 289.69 nm  (汇总采用此值)
--       11 号差异更大: 287.67 -> 282.25，相差 5.42 nm，
--       而 11 号最终表观减薄仅 0.79 nm——基线选择影响是结果的近 7 倍。
--       若允许两个值并存而无取代关系，结论就不可复现。
--       本设计强制: 被取代的测量保留(is_current=0)但不参与统计，
--       取代链可完整回溯，取代原因必须填写。
--
--   (3) stage 字段区分测量处于工艺链的哪个阶段(初始/plasma后/预暴露后/
--       最终)。ISS-07 与 EXP-07 都强调「没有中间测厚，净差值不能全部
--       归于 HF-TMA」，本字段使中间测厚的缺失成为可查询的事实。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `measurements` (
  `measurement_id`     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `measurement_code`   VARCHAR(96)     NOT NULL                COMMENT '测量编码，如 MSR-W01-S01-INITIAL',
  `sample_id`          BIGINT UNSIGNED NOT NULL,
  `process_id`         BIGINT UNSIGNED     NULL                COMMENT '该测量所评估的工艺运行；初始测量为 NULL',
  `tool_id`            BIGINT UNSIGNED     NULL                COMMENT '测量设备(椭偏仪)',
  `optical_model_id`   BIGINT UNSIGNED     NULL                COMMENT '所用光学模型(n/k)。跨模型相减的风险由此暴露',
  `stage`              VARCHAR(48)     NOT NULL                COMMENT 'initial=初始 / after_o2_plasma / after_o3_pre / after_ale / after_hf_only / after_o3_only / intermediate / final / other',
  `stage_seq`          INT UNSIGNED        NULL                COMMENT '阶段序号，便于排序',
  `cumulative_cycles`  INT UNSIGNED        NULL                COMMENT '该阶段累计循环数',
  `measured_at`        DATETIME            NULL,
  `operator_user_id`   BIGINT UNSIGNED     NULL,
  `point_count`        INT UNSIGNED        NULL                COMMENT '测点数(3/4/41/81)',
  `thickness_mean_nm`  DECIMAL(14,6)       NULL                COMMENT '平均膜厚(派生值，可由点级重算)',
  `thickness_sd_nm`    DECIMAL(14,6)       NULL                COMMENT '空间标准差(非独立重复的统计误差)',
  `thickness_min_nm`   DECIMAL(14,6)       NULL,
  `thickness_max_nm`   DECIMAL(14,6)       NULL,
  `mse_mean`           DECIMAL(14,6)       NULL                COMMENT '拟合 MSE 均值；ISS-03/ISS-08 关键质量指标',
  `mse_max`            DECIMAL(14,6)       NULL                COMMENT '最大单点 MSE；如 B05-S08 处理前 20.58',
  `gof_mean`           DECIMAL(14,8)       NULL                COMMENT '拟合 GOF 均值',
  `wafer_size`         VARCHAR(32)         NULL                COMMENT '4inchx4inch / 20mmx20mm',
  `grid_desc`          VARCHAR(128)        NULL                COMMENT '测点布局描述，如 4点 / 81点圆周分布',
  `supersedes_measurement_id` BIGINT UNSIGNED NULL             COMMENT '本测量取代了哪次测量(重测场景)',
  `is_current`         TINYINT(1)      NOT NULL DEFAULT 1      COMMENT '1=当前有效参与统计；0=已被取代',
  `supersede_reason`   TEXT                NULL                COMMENT '取代原因；被取代时必填(应用层约束)',
  `quality_flag`       VARCHAR(24)     NOT NULL DEFAULT 'ok'   COMMENT 'ok/suspect/abnormal/excluded',
  `quality_note`       TEXT                NULL,
  `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`measurement_id`),
  UNIQUE KEY `uk_measurements_code` (`measurement_code`),
  KEY `ix_measurements_sample` (`sample_id`),
  KEY `ix_measurements_process` (`process_id`),
  KEY `ix_measurements_model` (`optical_model_id`),
  KEY `ix_measurements_stage` (`sample_id`, `stage`, `stage_seq`),
  KEY `ix_measurements_current` (`is_current`),
  KEY `ix_measurements_time` (`measured_at`),
  KEY `ix_measurements_quality` (`quality_flag`),
  KEY `ix_measurements_supersedes` (`supersedes_measurement_id`),
  CONSTRAINT `fk_msr_sample`  FOREIGN KEY (`sample_id`)        REFERENCES `samples`         (`sample_id`)        ON DELETE CASCADE  ON UPDATE CASCADE,
  CONSTRAINT `fk_msr_process` FOREIGN KEY (`process_id`)       REFERENCES `processes`       (`process_id`)       ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_msr_tool`    FOREIGN KEY (`tool_id`)          REFERENCES `tools`           (`tool_id`)          ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_msr_model`   FOREIGN KEY (`optical_model_id`) REFERENCES `optical_models`  (`model_id`)         ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_msr_user`    FOREIGN KEY (`operator_user_id`) REFERENCES `users`           (`user_id`)          ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_msr_super`   FOREIGN KEY (`supersedes_measurement_id`) REFERENCES `measurements` (`measurement_id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `chk_msr_stage`   CHECK (`stage` IN ('initial','after_o2_plasma','after_o3_pre','after_ale','after_hf_only','after_o3_only','intermediate','final','other')),
  CONSTRAINT `chk_msr_quality` CHECK (`quality_flag` IN ('ok','suspect','abnormal','excluded'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='测量记录。显式绑定光学模型，支持重测取代链，区分测量阶段。';


-- ---------------------------------------------------------------------
-- measurement_points 点级测量数据
-- 设计说明: 原始椭偏 xlsx 的每一行测点。
--   为什么必须存点级(而非只存均值)：
--     - 配对计算 R = before - after 依赖 (x,y) 坐标一一对应。
--       SRC-D 的分析记录明确「按数值 X、Y 做精确一一连接，
--       没有按 Excel 行号直接相减」。只存均值则失去配对能力。
--     - 换光学模型重算时，必须回到点级。
--     - 整片空间分布图(Mapping)只能由点级数据生成。
--   数据量评估: 四批合计约 2000-3000 行，对 MySQL 微不足道。
--   坐标用 DECIMAL 而非 FLOAT，因为配对是精确相等匹配，浮点误差会导致漏配。
--   溯源字段(source_file_id/source_sheet/excel_row/thickness_cell)沿用
--   SRC-D 派生 CSV 中已有的单元格级溯源粒度。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `measurement_points` (
  `point_id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `measurement_id`    BIGINT UNSIGNED NOT NULL,
  `point_no`          INT UNSIGNED        NULL                COMMENT '原始 No 列',
  `x_mm`              DECIMAL(12,6)       NULL                COMMENT 'X 坐标(mm)，配对键',
  `y_mm`              DECIMAL(12,6)       NULL                COMMENT 'Y 坐标(mm)，配对键',
  `thickness_nm`      DECIMAL(14,6)       NULL                COMMENT 'layer_1_thickness(nm)',
  `intensity`         DECIMAL(16,6)       NULL,
  `height_mm`         DECIMAL(12,6)       NULL                COMMENT 'Height(mm) 列，非膜厚',
  `mse`               DECIMAL(14,6)       NULL,
  `gof`               DECIMAL(16,10)      NULL,
  `aoi_deg`           DECIMAL(8,3)        NULL                COMMENT 'AOI',
  `fit_iter`          INT UNSIGNED        NULL,
  `lbh`               DECIMAL(12,6)       NULL,
  `fit_time_ms`       DECIMAL(12,3)       NULL,
  `dispersion_params` JSON                NULL                COMMENT '24 个色散模型参数(1#M_0@Einf ... 1#M_7@En)',
  `source_file_id`    BIGINT UNSIGNED     NULL                COMMENT '来源原始文件',
  `source_sheet`      VARCHAR(128)        NULL                COMMENT '来源工作表名',
  `source_row`        INT UNSIGNED        NULL                COMMENT '来源 Excel 行号',
  `source_cell`       VARCHAR(32)         NULL                COMMENT '厚度单元格引用，如 H5',
  `is_outlier`        TINYINT(1)      NOT NULL DEFAULT 0      COMMENT '标记但保留，不自动剔除',
  `outlier_note`      TEXT                NULL                COMMENT '如 Tukey 围栏标记说明',
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`point_id`),
  UNIQUE KEY `uk_point_coord` (`measurement_id`, `point_no`),
  KEY `ix_points_measurement` (`measurement_id`),
  KEY `ix_points_xy` (`measurement_id`, `x_mm`, `y_mm`)       COMMENT '配对连接用',
  KEY `ix_points_thickness` (`thickness_nm`),
  KEY `ix_points_outlier` (`is_outlier`),
  CONSTRAINT `fk_pt_measurement` FOREIGN KEY (`measurement_id`) REFERENCES `measurements` (`measurement_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='点级膜厚数据。配对计算、空间 Mapping、换模型重算的原始依据。';
