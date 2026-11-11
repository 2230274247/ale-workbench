-- =====================================================================
-- ALE 实验工作台 · 06 补加约束与视图
-- 依赖: 05_findings_and_ext.sql
-- 说明: 前向引用约束在此补加(source_files 建成后)，
--       并建立常用查询视图供前后端直接调用。
-- 幂等: 用存储过程包裹，重复执行不报错。
-- =====================================================================

USE `ale_workbench`;

-- ---------------------------------------------------------------------
-- 补加前向引用外键
-- recipes.source_file_id / sample_transitions.measurement_id 在
-- 01/02 建表时其目标表尚不存在，故在此补加。
-- ---------------------------------------------------------------------
DROP PROCEDURE IF EXISTS `sp_add_fk_if_missing`;
DELIMITER $$
CREATE PROCEDURE `sp_add_fk_if_missing`()
BEGIN
  -- recipes.source_file_id -> source_files.file_id
  IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                 WHERE CONSTRAINT_SCHEMA='ale_workbench'
                   AND TABLE_NAME='recipes'
                   AND CONSTRAINT_NAME='fk_recipes_source_file') THEN
    ALTER TABLE `recipes`
      ADD CONSTRAINT `fk_recipes_source_file`
      FOREIGN KEY (`source_file_id`) REFERENCES `source_files` (`file_id`)
      ON DELETE SET NULL ON UPDATE CASCADE;
  END IF;

  -- sample_transitions.measurement_id -> measurements.measurement_id
  IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                 WHERE CONSTRAINT_SCHEMA='ale_workbench'
                   AND TABLE_NAME='sample_transitions'
                   AND CONSTRAINT_NAME='fk_trans_measurement') THEN
    ALTER TABLE `sample_transitions`
      ADD CONSTRAINT `fk_trans_measurement`
      FOREIGN KEY (`measurement_id`) REFERENCES `measurements` (`measurement_id`)
      ON DELETE SET NULL ON UPDATE CASCADE;
  END IF;
END$$
DELIMITER ;

CALL `sp_add_fk_if_missing`();
DROP PROCEDURE IF EXISTS `sp_add_fk_if_missing`;


-- =====================================================================
-- 视图层
-- 设计说明: 视图把「常用的、容易出错的」查询固化成可复用对象，
--   避免每个前端页面各写一遍 SQL 而出现口径不一致。
--   使用 CREATE OR REPLACE，保证幂等。
-- =====================================================================

-- ---------------------------------------------------------------------
-- v_sample_overview 样品总览
-- 前端「实验数据」模块的主列表。已排除被取代的测量与异常样品标记。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_sample_overview` AS
SELECT
  s.`sample_id`,
  s.`sample_code`,
  b.`batch_code`,
  b.`batch_name`,
  b.`nominal_thickness_nm`                    AS `batch_nominal_nm`,
  s.`sample_type`,
  s.`status`                                  AS `sample_status`,
  s.`exclude_from_analysis`,
  s.`exclude_reason`,
  s.`pre_treatment`,
  COUNT(DISTINCT m.`measurement_id`)          AS `measurement_count`,
  COUNT(DISTINCT mp.`point_id`)               AS `point_count_total`,
  MIN(m.`measured_at`)                        AS `first_measured_at`,
  MAX(m.`measured_at`)                        AS `last_measured_at`
FROM `samples` s
JOIN `batches` b            ON b.`batch_id` = s.`batch_id`
LEFT JOIN `measurements` m  ON m.`sample_id` = s.`sample_id` AND m.`is_current` = 1
LEFT JOIN `measurement_points` mp ON mp.`measurement_id` = m.`measurement_id`
GROUP BY s.`sample_id`, s.`sample_code`, b.`batch_code`, b.`batch_name`,
         b.`nominal_thickness_nm`, s.`sample_type`, s.`status`,
         s.`exclude_from_analysis`, s.`exclude_reason`, s.`pre_treatment`;


-- ---------------------------------------------------------------------
-- v_measurement_current 当前有效测量
-- 只暴露 is_current=1 的测量，避免统计时误用被取代的基线。
-- 这是 300nm 批次 10/11 号「基线双版本」问题的直接防护。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_measurement_current` AS
SELECT
  m.`measurement_id`,
  m.`measurement_code`,
  s.`sample_code`,
  b.`batch_code`,
  m.`stage`,
  m.`stage_seq`,
  m.`cumulative_cycles`,
  m.`measured_at`,
  m.`point_count`,
  m.`thickness_mean_nm`,
  m.`thickness_sd_nm`,
  m.`mse_mean`,
  m.`mse_max`,
  m.`gof_mean`,
  om.`model_code`,
  om.`n_setting`,
  om.`k_setting`,
  m.`quality_flag`,
  m.`is_current`
FROM `measurements` m
JOIN `samples` s              ON s.`sample_id` = m.`sample_id`
JOIN `batches` b              ON b.`batch_id` = s.`batch_id`
LEFT JOIN `optical_models` om ON om.`model_id` = m.`optical_model_id`
WHERE m.`is_current` = 1;


-- ---------------------------------------------------------------------
-- v_derived_removal 表观减薄结果
-- 供「实验分析」「图表中心」使用。带 model_consistent 提示，
-- 使跨模型相减的结果一眼可见。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_derived_removal` AS
SELECT
  dr.`result_id`,
  dr.`result_code`,
  dr.`result_kind`,
  s.`sample_code`,
  b.`batch_code`,
  dr.`value_nm`,
  dr.`value_unit`,
  dr.`value_sd_nm`,
  dr.`cycles_basis`,
  dr.`pairing_method`,
  dr.`paired_point_count`,
  dr.`model_consistent`,
  CASE WHEN dr.`model_consistent` = 0
       THEN '⚠ 前后测量使用了不同光学模型，该差值为跨模型相减'
       ELSE NULL END                            AS `model_warning`,
  dr.`evidence_level`,
  dr.`is_valid`,
  mb.`stage`                                    AS `before_stage`,
  ma.`stage`                                    AS `after_stage`,
  mb.`thickness_mean_nm`                        AS `before_mean_nm`,
  ma.`thickness_mean_nm`                        AS `after_mean_nm`,
  dr.`computation_note`
FROM `derived_results` dr
JOIN `samples` s              ON s.`sample_id` = dr.`sample_id`
JOIN `batches` b              ON b.`batch_id` = s.`batch_id`
LEFT JOIN `measurements` mb   ON mb.`measurement_id` = dr.`before_measurement_id`
LEFT JOIN `measurements` ma   ON ma.`measurement_id` = dr.`after_measurement_id`
WHERE dr.`is_valid` = 1;


-- ---------------------------------------------------------------------
-- v_process_detail 工艺运行明细
-- 前端「实验执行」模块。带共腔标记与工艺模式。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_process_detail` AS
SELECT
  p.`process_id`,
  p.`process_code`,
  p.`process_mode`,
  b.`batch_code`,
  pl.`plan_code`,
  p.`r1_temp_c`,
  p.`r2_temp_c`,
  p.`n2_flow_sccm`,
  p.`o3_pre_cycles`,
  p.`o3_pre_duration_s`,
  p.`full_ale_cycles`,
  p.`hf_tma_repeats`,
  p.`started_at`,
  p.`ended_at`,
  p.`co_etch_group`,
  p.`is_independent_run`,
  p.`log_status`,
  COUNT(DISTINCT ps.`sample_id`)               AS `sample_count`,
  COUNT(DISTINCT st.`step_id`)                 AS `step_count`
FROM `processes` p
LEFT JOIN `batches` b             ON b.`batch_id` = p.`batch_id`
LEFT JOIN `experiment_plans` pl   ON pl.`plan_id` = p.`plan_id`
LEFT JOIN `process_samples` ps    ON ps.`process_id` = p.`process_id`
LEFT JOIN `process_steps` st      ON st.`process_id` = p.`process_id`
GROUP BY p.`process_id`, p.`process_code`, p.`process_mode`, b.`batch_code`,
         pl.`plan_code`, p.`r1_temp_c`, p.`r2_temp_c`, p.`n2_flow_sccm`,
         p.`o3_pre_cycles`, p.`o3_pre_duration_s`, p.`full_ale_cycles`,
         p.`hf_tma_repeats`, p.`started_at`, p.`ended_at`,
         p.`co_etch_group`, p.`is_independent_run`, p.`log_status`;


-- ---------------------------------------------------------------------
-- v_issue_dashboard 问题看板
-- 前端「首页」用。按严重度排序，显示未关闭问题。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_issue_dashboard` AS
SELECT
  i.`issue_id`,
  i.`issue_code`,
  i.`title`,
  i.`severity`,
  i.`status`,
  i.`observed`,
  i.`effect`,
  i.`action`,
  i.`avoid`,
  COUNT(il.`link_id`)                          AS `linked_entity_count`
FROM `issues` i
LEFT JOIN `issues_links` il ON il.`issue_id` = i.`issue_id`
GROUP BY i.`issue_id`, i.`issue_code`, i.`title`, i.`severity`, i.`status`,
         i.`observed`, i.`effect`, i.`action`, i.`avoid`;


-- ---------------------------------------------------------------------
-- v_sample_evidence 样品证据汇总
-- 把一片样品的全部证据线(椭偏/衍生结果/XPS/RGA/异常标记)汇总，
-- 回答「这片样品的结论有多少证据支撑」。
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW `v_sample_evidence` AS
SELECT
  s.`sample_id`,
  s.`sample_code`,
  b.`batch_code`,
  s.`exclude_from_analysis`,
  (SELECT COUNT(*) FROM `measurements` m
     WHERE m.`sample_id` = s.`sample_id` AND m.`is_current` = 1)          AS `n_measurements`,
  (SELECT COUNT(*) FROM `derived_results` dr
     WHERE dr.`sample_id` = s.`sample_id` AND dr.`is_valid` = 1)          AS `n_derived_results`,
  (SELECT COUNT(*) FROM `instrument_datasets` ds
     WHERE ds.`sample_id` = s.`sample_id`)                                AS `n_instrument_datasets`,
  (SELECT COUNT(*) FROM `issues_links` il
     WHERE il.`entity_type` = 'sample' AND il.`entity_id` = s.`sample_id`) AS `n_linked_issues`
FROM `samples` s
JOIN `batches` b ON b.`batch_id` = s.`batch_id`;
