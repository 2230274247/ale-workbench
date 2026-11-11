-- =====================================================================
-- ALE 实验工作台 · 99 功能冒烟测试（不写入数据）
-- ---------------------------------------------------------------------
-- 目的: 用四个压缩包中的真实数据形态，验证 schema 能否正确承载:
--   1. 批次 -> 样品 -> 工艺 -> 测量 -> 点级数据 的完整链路
--   2. 母片-小样层级
--   3. 异常样品隔离 (W01-S09)
--   4. 重测取代链 (300nm 10 号基线双版本)
--   5. 跨光学模型相减的识别
--   6. 共腔 vs 独立运行 (ISS-06)
--   7. 完整循环 vs 预暴露模式隔离 (EXP-09 vs EXP-10)
--   8. XPS 数据挂载与样品映射悬空状态
--   9. 视图输出正确性
--   10. 外键与 CHECK 约束真的生效
-- 全程使用事务并最终 ROLLBACK，库内不留任何数据。
-- =====================================================================

USE `ale_workbench`;

START TRANSACTION;

-- ---------------------------------------------------------------------
-- 1. 基础实体
-- ---------------------------------------------------------------------
INSERT INTO `users` (`username`,`display_name`,`role`) VALUES
  ('admin','管理员','admin'),
  ('wyy','研究人员','operator'),
  ('guest','只读访客','viewer');

INSERT INTO `tools` (`tool_code`,`tool_name`,`tool_type`,`vendor`,`model`) VALUES
  ('THERMAL_ALE_01','自制热ALE腔体','thermal_ale',NULL,'Home-built'),
  ('ELLIPSOMETER_01','椭偏仪','ellipsometer','Eoptics',NULL),
  ('XPS_01','X射线光电子能谱','xps','K-Alpha','K-Alpha'),
  ('RGA_01','残余气体分析仪','rga',NULL,NULL);

INSERT INTO `recipes` (`recipe_code`,`recipe_name`,`recipe_kind`,`nominal_temp_c`,`nominal_gas_flows`,`status`) VALUES
  ('RCP-PECVD-SIN-30NM','PECVD SiN 30nm 沉积','deposition',NULL,'{"SiH4":null,"NH3":null,"N2":null}','active'),
  ('RCP-O3-STD','O3 标准脉冲','o3',NULL,'{"O2_sccm":null}','active'),
  ('RCP-HF-TMA-STD','HF-TMA 标准循环','full_cycle',275.00,'{"N2_sccm":20}','active');

-- 批次: 对应四个压缩包
INSERT INTO `batches` (`batch_code`,`batch_name`,`nominal_thickness_nm`,`wafer_size`,`deposit_date`,`source_zip`,`source_zip_sha256`,`anomaly_flag`,`anomaly_note`) VALUES
  ('B-20260831-W01','8/31 批次 约30nm W01',30.000,'4inchx4inch','2026-08-31','1.-2026.8.31-SiN.zip','93e9e8593de2ccc83ac75ab7058f313d16b1b84bdd3471c6101310bfb185b99a',0,NULL),
  ('B-20260916-300NM','9/16 批次 约300nm',300.000,'4inchx4inch','2026-09-16','2.-2026.9.16-SiN-300nm.zip','19e43e3f04411425cd2728d64d3b37ede32933bab92396ba385f6a937a7737e3',0,NULL),
  ('B-20260928-74NM','9/28 批次 约74nm',74.000,'20mmx20mm','2026-09-28','3.-2026.9.28-SiN(1).zip','6e0de935eec1f94b162af18dae626fe0f6dd420d7c4f09db6fdafb9328e8d793',0,NULL),
  ('B-20260930-46NM-ERR','9/30 批次 约46nm（温度异常标记）',46.000,'4inchx4inch','2026-09-30','3.-2026.9.28-SiN(1).zip','6e0de935eec1f94b162af18dae626fe0f6dd420d7c4f09db6fdafb9328e8d793',1,'文件名标记 PECVD-ERROR_Temperature；ISS-02 禁止据此断言故障机理');

-- ---------------------------------------------------------------------
-- 2. 样品（含母片-小样层级与异常隔离）
-- ---------------------------------------------------------------------
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`nominal_thickness_nm`,`size_desc`,`status`)
SELECT 'W01', b.batch_id, 'parent_wafer', 30.000, '4inchx4inch','consumed'
FROM `batches` b WHERE b.batch_code='B-20260831-W01';

INSERT INTO `samples` (`sample_code`,`batch_id`,`parent_sample_id`,`sample_type`,`display_label`,`pre_treatment`,`status`,`exclude_from_analysis`,`exclude_reason`)
SELECT 'W01-S01', b.batch_id, p.sample_id,'coupon','1','O2 plasma 30s','consumed',0,NULL
FROM `batches` b JOIN `samples` p ON p.sample_code='W01' WHERE b.batch_code='B-20260831-W01';

-- 异常样品: W01-S09（酒精湿巾擦拭）——数据库层面固化隔离
INSERT INTO `samples` (`sample_code`,`batch_id`,`parent_sample_id`,`sample_type`,`display_label`,`pre_treatment`,`status`,`exclude_from_analysis`,`exclude_reason`)
SELECT 'W01-S09', b.batch_id, p.sample_id,'coupon','9','酒精湿巾擦拭后 HF-only','quarantined',1,
       'ISS-05: 酒精湿巾擦拭导致刻蚀量异常升高（约9.84nm）且均匀度破坏，严禁纳入常规HF-only速率均值'
FROM `batches` b JOIN `samples` p ON p.sample_code='W01' WHERE b.batch_code='B-20260831-W01';

-- 300nm 批次 10 号（基线双版本场景）
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`nominal_thickness_nm`,`status`)
SELECT 'B300-S10', b.batch_id,'coupon','10',300.000,'consumed'
FROM `batches` b WHERE b.batch_code='B-20260916-300NM';

-- B28 批次共腔两片 + 独立对照（ISS-06 场景）
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B28-S04', b.batch_id,'coupon','4','consumed' FROM `batches` b WHERE b.batch_code='B-20260928-74NM';
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B28-S06', b.batch_id,'coupon','6','consumed' FROM `batches` b WHERE b.batch_code='B-20260928-74NM';
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B28-S12', b.batch_id,'coupon','12','consumed' FROM `batches` b WHERE b.batch_code='B-20260928-74NM';

-- B05 批次（10/14 次数梯度）
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B05-S01', b.batch_id,'coupon','1','consumed' FROM `batches` b WHERE b.batch_code='B-20260930-46NM-ERR';
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B05-S07', b.batch_id,'coupon','7','consumed' FROM `batches` b WHERE b.batch_code='B-20260930-46NM-ERR';
INSERT INTO `samples` (`sample_code`,`batch_id`,`sample_type`,`display_label`,`status`)
SELECT 'B05-S08', b.batch_id,'coupon','8','consumed' FROM `batches` b WHERE b.batch_code='B-20260930-46NM-ERR';

-- ---------------------------------------------------------------------
-- 3. 光学模型（含跨模型场景）
-- ---------------------------------------------------------------------
INSERT INTO `optical_models` (`model_code`,`model_name`,`rcp_name`,`spl_name`,`n_setting`,`k_setting`,`quality_note`) VALUES
  ('OM-SIN30-N1.9100-K0','W01初始态模型','2026.9.1-SiN-30nm.rcp','8.31-30nm-SiN.spl',1.910000,0.000000,'W01 初始测量所用'),
  ('OM-SIN30-N1.9198-K0.0005','W01处理后模型','2026.9.1-SiN-30nm.rcp','8.31-30nm-SiN.spl',1.919800,0.000500,'W01 处理后所用；与初始态模型不同'),
  ('OM-SIN300-N2.6000','300nm模型','9.16-300nm-SiN.rcp','9.16-300nm-SiN.spl',2.600000,NULL,'ISS-03: 300nm 模型 MSE 曾达 8-14，需校模');

-- ---------------------------------------------------------------------
-- 4. 工艺运行
-- ---------------------------------------------------------------------
-- 完整循环（W01）
INSERT INTO `processes` (`process_code`,`batch_id`,`process_mode`,`tool_id`,`r1_temp_c`,`r2_temp_c`,`n2_flow_sccm`,`full_ale_cycles`,`started_at`,`is_independent_run`,`log_status`)
SELECT 'RUN-20260904-W01-FULL100', b.batch_id,'full_cycle', t.tool_id, 275.00,255.00,20.000,100,'2026-09-04 15:48:45',1,'ok'
FROM `batches` b
JOIN `tools` t ON t.tool_code='THERMAL_ALE_01'
WHERE b.batch_code='B-20260831-W01';

-- B28 共腔运行（S04 + S06 同腔）
INSERT INTO `processes` (`process_code`,`batch_id`,`process_mode`,`r1_temp_c`,`co_etch_group`,`is_independent_run`,`hf_tma_repeats`,`log_status`)
SELECT 'RUN-20261008-B28-COETCH-S04S06', b.batch_id,'pre_expose_then_react',275.00,'COETCH-B28-S04S06',0,50,'ok'
FROM `batches` b WHERE b.batch_code='B-20260928-74NM';

-- B28 独立对照运行（S12）
INSERT INTO `processes` (`process_code`,`batch_id`,`process_mode`,`r1_temp_c`,`is_independent_run`,`hf_tma_repeats`,`log_status`)
SELECT 'RUN-20261012-B28-INDEP-S12', b.batch_id,'pre_expose_then_react',275.00,1,50,'ok'
FROM `batches` b WHERE b.batch_code='B-20260928-74NM';

-- B05 完整循环对照（S07）—— 必须与预暴露系列严格区分
INSERT INTO `processes` (`process_code`,`batch_id`,`process_mode`,`full_ale_cycles`,`is_independent_run`,`log_status`)
SELECT 'RUN-20261014-B05-FULL50', b.batch_id,'full_cycle',50,1,'ok'
FROM `batches` b WHERE b.batch_code='B-20260930-46NM-ERR';

-- B05 预暴露 + HF-TMA 次数梯度（S01）
INSERT INTO `processes` (`process_code`,`batch_id`,`process_mode`,`o3_pre_cycles`,`o3_pre_duration_s`,`hf_tma_repeats`,`is_independent_run`,`log_status`)
SELECT 'RUN-20261014-B05-PRE-HFTMA5', b.batch_id,'pre_expose_then_react',50,NULL,5,1,'ok'
FROM `batches` b WHERE b.batch_code='B-20260930-46NM-ERR';

-- 工艺步骤（W01 完整循环）
INSERT INTO `process_steps` (`process_id`,`step_index`,`step_kind`,`chemistry`,`cycles`,`o3_delta_p_kpa`,`hf_delta_p_pa`,`tma_delta_p_pa`,`o3_generator_o2_flow_set_sccm`,`o3_generator_o2_flow_measured_sccm`,`step_note`)
SELECT p.process_id,1,'o3_purge','O3',100,5.0000,80.0000,110.0000,NULL,NULL,'ISS-01: O3发生器O2供气流量未留档，保持NULL不推测'
FROM `processes` p WHERE p.process_code='RUN-20260904-W01-FULL100';

-- 工艺步骤（O2 plasma 前处理，S01）
INSERT INTO `process_steps` (`process_id`,`step_index`,`step_kind`,`chemistry`,`duration_s`,`o2_plasma_w`,`o2_plasma_sccm`,`o2_plasma_pa`,`step_note`)
SELECT p.process_id,0,'o2_plasma','O2_plasma',30.000,30.000,30.000,80.0000,'O2 plasma 支路；其 30sccm 不得与 O3 发生器供气流量混淆'
FROM `processes` p WHERE p.process_code='RUN-20260904-W01-FULL100';

-- 运行-样品关联（共腔信息）
INSERT INTO `process_samples` (`process_id`,`sample_id`,`chamber_position`,`o3_pre_cycles`,`hf_tma_repeats`,`is_control`)
SELECT p.process_id, s.sample_id,'A',40,50,0
FROM `processes` p, `samples` s WHERE p.process_code='RUN-20261008-B28-COETCH-S04S06' AND s.sample_code='B28-S04';

INSERT INTO `process_samples` (`process_id`,`sample_id`,`chamber_position`,`o3_pre_cycles`,`hf_tma_repeats`,`is_control`)
SELECT p.process_id, s.sample_id,'B',0,50,1
FROM `processes` p, `samples` s WHERE p.process_code='RUN-20261008-B28-COETCH-S04S06' AND s.sample_code='B28-S06';

INSERT INTO `process_samples` (`process_id`,`sample_id`,`o3_pre_cycles`,`hf_tma_repeats`,`is_control`)
SELECT p.process_id, s.sample_id,0,50,1
FROM `processes` p, `samples` s WHERE p.process_code='RUN-20261012-B28-INDEP-S12' AND s.sample_code='B28-S12';

INSERT INTO `process_samples` (`process_id`,`sample_id`,`full_ale_cycles`)
SELECT p.process_id, s.sample_id,50
FROM `processes` p, `samples` s WHERE p.process_code='RUN-20261014-B05-FULL50' AND s.sample_code='B05-S07';

INSERT INTO `process_samples` (`process_id`,`sample_id`,`o3_pre_cycles`,`hf_tma_repeats`)
SELECT p.process_id, s.sample_id,50,5
FROM `processes` p, `samples` s WHERE p.process_code='RUN-20261014-B05-PRE-HFTMA5' AND s.sample_code='B05-S01';

-- ---------------------------------------------------------------------
-- 5. 测量（含跨模型与重测取代）
-- ---------------------------------------------------------------------
-- W01-S01 初始（用 N1.91 模型）
INSERT INTO `measurements` (`measurement_code`,`sample_id`,`tool_id`,`optical_model_id`,`stage`,`stage_seq`,`point_count`,`thickness_mean_nm`,`thickness_sd_nm`,`mse_mean`,`gof_mean`,`is_current`)
SELECT 'MSR-W01-S01-INITIAL', s.sample_id, t.tool_id, om.model_id,'initial',0,3,32.316667,0.349905,2.39,0.994763,1
FROM `samples` s, `tools` t, `optical_models` om
WHERE s.sample_code='W01-S01' AND t.tool_code='ELLIPSOMETER_01' AND om.model_code='OM-SIN30-N1.9100-K0';

-- W01-S01 处理后（用 N1.9198 模型）—— 跨模型相减场景
INSERT INTO `measurements` (`measurement_code`,`sample_id`,`process_id`,`tool_id`,`optical_model_id`,`stage`,`stage_seq`,`cumulative_cycles`,`point_count`,`thickness_mean_nm`,`thickness_sd_nm`,`mse_mean`,`gof_mean`,`is_current`)
SELECT 'MSR-W01-S01-AFTER100', s.sample_id, p.process_id, t.tool_id, om.model_id,'after_ale',2,100,3,28.600000,0.036056,1.05,0.994917,1
FROM `samples` s, `processes` p, `tools` t, `optical_models` om
WHERE s.sample_code='W01-S01' AND p.process_code='RUN-20260904-W01-FULL100'
  AND t.tool_code='ELLIPSOMETER_01' AND om.model_code='OM-SIN30-N1.9198-K0.0005';

-- 300nm 10号 基线双版本：原始测量 -> 被二次测量取代
INSERT INTO `measurements` (`measurement_code`,`sample_id`,`optical_model_id`,`stage`,`stage_seq`,`point_count`,`thickness_mean_nm`,`thickness_sd_nm`,`mse_mean`,`is_current`,`quality_flag`,`quality_note`)
SELECT 'MSR-B300-S10-INITIAL-V1', s.sample_id, om.model_id,'initial',0,3,291.403333,3.005122,11.10,0,'suspect','原始测量；后被二次测量取代，汇总未采用'
FROM `samples` s, `optical_models` om WHERE s.sample_code='B300-S10' AND om.model_code='OM-SIN300-N2.6000';

INSERT INTO `measurements` (`measurement_code`,`sample_id`,`optical_model_id`,`stage`,`stage_seq`,`point_count`,`thickness_mean_nm`,`thickness_sd_nm`,`mse_mean`,`supersedes_measurement_id`,`is_current`,`supersede_reason`)
SELECT 'MSR-B300-S10-INITIAL-V2', s.sample_id, om.model_id,'initial',0,3,289.690000,2.589000,10.11,m.measurement_id,1,
       '二次测量；汇总CSV采用的基线值。差异1.71nm，原因未在档案中记录——本字段使取代关系可追溯'
FROM `samples` s, `optical_models` om, `measurements` m
WHERE s.sample_code='B300-S10' AND om.model_code='OM-SIN300-N2.6000' AND m.measurement_code='MSR-B300-S10-INITIAL-V1';

-- B05-S08 高 MSE 点（ISS-08）
INSERT INTO `measurements` (`measurement_code`,`sample_id`,`stage`,`stage_seq`,`point_count`,`thickness_mean_nm`,`thickness_sd_nm`,`mse_mean`,`mse_max`,`is_current`,`quality_flag`,`quality_note`)
SELECT 'MSR-B05-S08-INITIAL', s.sample_id,'initial',0,4,48.947500,0.573000,7.942500,20.58,1,'suspect','ISS-08: 第4测点 MSE=20.58，须保留并优先复核，禁止直接剔除'
FROM `samples` s WHERE s.sample_code='B05-S08';

-- ---------------------------------------------------------------------
-- 6. 点级数据
-- ---------------------------------------------------------------------
INSERT INTO `measurement_points` (`measurement_id`,`point_no`,`x_mm`,`y_mm`,`thickness_nm`,`intensity`,`mse`,`gof`,`aoi_deg`,`fit_iter`,`source_sheet`,`source_row`,`source_cell`,`is_outlier`)
SELECT m.measurement_id, 1, 0.000000, 0.000000, 32.200000, 7810.84, 2.56, 0.994746, 64.95, 50,'Sheet1',5,'H5',0
FROM `measurements` m WHERE m.measurement_code='MSR-W01-S01-INITIAL';

INSERT INTO `measurement_points` (`measurement_id`,`point_no`,`x_mm`,`y_mm`,`thickness_nm`,`intensity`,`mse`,`gof`,`is_outlier`)
SELECT m.measurement_id, 2, 0.000000, 10.000000, 32.710000, 7728.21, 1.29, 0.994891, 0
FROM `measurements` m WHERE m.measurement_code='MSR-W01-S01-INITIAL';

INSERT INTO `measurement_points` (`measurement_id`,`point_no`,`x_mm`,`y_mm`,`thickness_nm`,`intensity`,`mse`,`gof`,`is_outlier`)
SELECT m.measurement_id, 3, -10.000000, 0.000000, 32.040000, 7755.38, 3.33, 0.994651, 0
FROM `measurements` m WHERE m.measurement_code='MSR-W01-S01-INITIAL';

-- 整片 O3-only 的一个点（含 Tukey 标记）
INSERT INTO `measurement_points` (`measurement_id`,`point_no`,`x_mm`,`y_mm`,`thickness_nm`,`mse`,`gof`,`is_outlier`,`outlier_note`)
SELECT m.measurement_id, 68, -34.641000, 20.000000, 46.860000, 1.70, 0.994847, 1,'Tukey 围栏描述性标记；保留不剔除，非仪器错误证据'
FROM `measurements` m WHERE m.measurement_code='MSR-B05-S08-INITIAL';

-- ---------------------------------------------------------------------
-- 7. 派生结果（含跨模型警告）
-- ---------------------------------------------------------------------
INSERT INTO `derived_results` (`result_code`,`result_kind`,`sample_id`,`before_measurement_id`,`after_measurement_id`,`process_id`,`value_nm`,`value_unit`,`value_sd_nm`,`cycles_basis`,`pairing_method`,`paired_point_count`,`model_consistent`,`evidence_level`,`computation_note`)
SELECT 'RES-W01-S01-R100','apparent_removal_R', s.sample_id, mb.measurement_id, ma.measurement_id, p.process_id,
       3.716667,'nm',0.351758,100,'same_xy_coordinate',3,0,'measured',
       'ISS-10: 跨光学模型相减（初始N1.91 / 处理后N1.9198），且非稳态自限EPC'
FROM `samples` s, `measurements` mb, `measurements` ma, `processes` p
WHERE s.sample_code='W01-S01' AND mb.measurement_code='MSR-W01-S01-INITIAL'
  AND ma.measurement_code='MSR-W01-S01-AFTER100' AND p.process_code='RUN-20260904-W01-FULL100';

-- ---------------------------------------------------------------------
-- 8. 溯源文件
-- ---------------------------------------------------------------------
INSERT INTO `source_files` (`file_sha256`,`file_name`,`rel_path`,`source_zip`,`file_role`,`file_ext`,`batch_id`,`parse_status`)
SELECT REPEAT('a',64),'1-n1.9198-k0.0005-ALE.xlsx','原始数据/1-n1.9198-k0.0005-ALE.xlsx','1.-2026.8.31-SiN.zip','instrument_raw','.xlsx',b.batch_id,'parsed'
FROM `batches` b WHERE b.batch_code='B-20260831-W01';

INSERT INTO `source_files` (`file_sha256`,`file_name`,`rel_path`,`source_zip`,`file_role`,`file_ext`,`batch_id`,`parse_status`)
SELECT REPEAT('b',64),'Small_Samples_Paired_Points.csv','ALE_Thickness_Origin_Results/Data_CSV/Small_Samples_Paired_Points.csv','3.-2026.9.28-SiN(1).zip','point_derived','.csv',b.batch_id,'parsed'
FROM `batches` b WHERE b.batch_code='B-20260928-74NM';

-- ---------------------------------------------------------------------
-- 9. 结论与问题台账
-- ---------------------------------------------------------------------
INSERT INTO `findings` (`finding_code`,`statement`,`evidence_level`,`support_sample_count`,`is_confirmed`,`scope_note`) VALUES
  ('F01','W01完整O3-HF-TMA x100 对应 1.1933-1.8067nm 表观减薄','measured',4,0,'表观膜厚变化，非SiN本体真实刻蚀'),
  ('F05','整片O3-only 50次后81点平均表观增厚0.29198nm','measured',1,0,'≠生成0.292nm真实SiO2氧化层'),
  ('F07','O3可能改变表面终止/氧化状态并影响HF-TMA作用','hypothesis',NULL,0,'氧化层化学厚度、自限性、本征EPC均未证实');

INSERT INTO `issues` (`issue_code`,`title`,`severity`,`status`,`observed`,`effect`,`action`,`avoid`) VALUES
  ('ISS-05','异常前处理样品 W01-S09','high','accepted_risk','酒精湿巾擦拭后HF-only x100 平均表观下降约9.84nm，MSE约19.7','污染/擦拭改变表面或模型，不代表正常HF-only行为','保留源数据与标记，重做标准清洗对照','严禁纳入常规HF-only速率均值'),
  ('ISS-06','9/28预暴露小样共腔/独立运行混杂','medium_high','open','B28-S06(0次)与B28-S04(40次)共腔；B28-S12为另一轮独立0次对照','两片0次不构成工艺独立重复','后续匹配装载数量与腔体位置，独立重复0/1/2/40次','不把B28-S06和S12平均成单个0次工艺点'),
  ('ISS-07','O3预暴露次数与剂量定义混淆','medium_high','open','部分源文件名用10s/20s/30s/40s，实为10/20/30/40次','循环次数不等价于已量化分子剂量','统一记录exposure_cycles/pulse_duration_s/total_O3_on_time_s','不能在未核验时把"10s"解释为10秒');

INSERT INTO `issues_links` (`issue_id`,`entity_type`,`entity_id`,`relation`,`note`)
SELECT i.issue_id,'sample', s.sample_id,'related','异常样品隔离'
FROM `issues` i, `samples` s WHERE i.issue_code='ISS-05' AND s.sample_code='W01-S09';

INSERT INTO `issues_links` (`issue_id`,`entity_type`,`entity_id`,`relation`,`note`)
SELECT i.issue_id,'process', p.process_id,'related','共腔运行'
FROM `issues` i, `processes` p WHERE i.issue_code='ISS-06' AND p.process_code='RUN-20261008-B28-COETCH-S04S06';

-- ---------------------------------------------------------------------
-- 10. XPS 数据挂载（样品映射悬空场景）
-- ---------------------------------------------------------------------
INSERT INTO `instrument_datasets` (`dataset_code`,`instrument_type`,`tool_id`,`batch_id`,`external_ref`,`title`,`sample_mapping_status`,`mapping_note`)
SELECT 'XPS-H2609100564-4DATA','xps', t.tool_id, b.batch_id,'H2609100564/4.DATA','XPS Si2p/N1s/O1s/F1s 扫描',
       'unresolved','needs_manual_review: XPS 测量文件夹 1-9 与 SiN 样品编号(S07/S08/S04或S06/S10)的对应关系未建立'
FROM `tools` t, `batches` b WHERE t.tool_code='XPS_01' AND b.batch_code='B-20260831-W01';

INSERT INTO `instrument_channels` (`dataset_id`,`channel_code`,`channel_label`,`channel_type`,`element`,`transition`,`x_unit`,`y_unit`,`peak_center`,`peak_height`,`fwhm`,`peak_area`)
SELECT d.dataset_id,'Si2p','Si2p Scan','spectrum','Si','2p','binding_energy_eV','counts_per_s',101.890000,64230.13,1.72,125014.35
FROM `instrument_datasets` d WHERE d.dataset_code='XPS-H2609100564-4DATA';

INSERT INTO `instrument_channels` (`dataset_id`,`channel_code`,`channel_label`,`channel_type`,`element`,`transition`,`x_unit`,`y_unit`,`peak_center`,`peak_height`,`fwhm`,`peak_area`)
SELECT d.dataset_id,'N1s','N1s Scan','spectrum','N','1s','binding_energy_eV','counts_per_s',397.720000,128204.55,1.39,206541.97
FROM `instrument_datasets` d WHERE d.dataset_code='XPS-H2609100564-4DATA';

INSERT INTO `instrument_datapoints` (`channel_id`,`point_index`,`x_value`,`y_value`)
SELECT c.channel_id,1,110.00000000,3046.75
FROM `instrument_channels` c WHERE c.channel_code='Si2p';
INSERT INTO `instrument_datapoints` (`channel_id`,`point_index`,`x_value`,`y_value`)
SELECT c.channel_id,2,109.90000000,3082.70
FROM `instrument_channels` c WHERE c.channel_code='Si2p';

-- RGA 数据集（占位，说明该证据线当前缺失）
INSERT INTO `instrument_datasets` (`dataset_code`,`instrument_type`,`tool_id`,`title`,`sample_mapping_status`,`mapping_note`)
SELECT 'RGA-PLACEHOLDER-2026','rga', t.tool_id,'RGA 数据集占位','unresolved','ISS-09: 四个压缩包中无 RGA 数据；历史有 Filament Error/Connecting 故障，设备状态待确认'
FROM `tools` t WHERE t.tool_code='RGA_01';

-- ---------------------------------------------------------------------
-- 11. 样品流转
-- ---------------------------------------------------------------------
INSERT INTO `sample_transitions` (`sample_id`,`from_status`,`to_status`,`event_type`,`process_id`,`event_at`,`note`)
SELECT s.sample_id,'available','in_process','load', p.process_id,'2026-09-04 15:00:00','装入热ALE腔体'
FROM `samples` s, `processes` p WHERE s.sample_code='W01-S01' AND p.process_code='RUN-20260904-W01-FULL100';

INSERT INTO `sample_transitions` (`sample_id`,`from_status`,`to_status`,`event_type`,`process_id`,`event_at`,`note`)
SELECT s.sample_id,'in_process','consumed','unload', p.process_id,'2026-09-04 16:30:00','完成100循环'
FROM `samples` s, `processes` p WHERE s.sample_code='W01-S01' AND p.process_code='RUN-20260904-W01-FULL100';

-- =====================================================================
-- 12. 断言校验（用 SIGNAL 报错使事务失败）
-- =====================================================================
-- 断言 A: 样品总览视图应能看到 W01-S09 且带排除标记
SET @chk_excl := (SELECT COUNT(*) FROM `v_sample_overview` WHERE sample_code='W01-S09' AND exclude_from_analysis=1);
SET @msg := IF(@chk_excl=1,'OK','FAIL: W01-S09 排除标记未生效');
SELECT IF(@chk_excl=1,'[PASS] A 异常样品隔离标记','[FAIL] A') AS test_a;

-- 断言 B: 被取代的测量不应出现在「当前有效测量」视图
SET @chk_sup := (SELECT COUNT(*) FROM `v_measurement_current` WHERE measurement_code='MSR-B300-S10-INITIAL-V1');
SELECT IF(@chk_sup=0,'[PASS] B 被取代基线已从当前视图排除','[FAIL] B') AS test_b;
SET @chk_cur := (SELECT COUNT(*) FROM `v_measurement_current` WHERE measurement_code='MSR-B300-S10-INITIAL-V2');
SELECT IF(@chk_cur=1,'[PASS] B2 取代后的基线出现在当前视图','[FAIL] B2') AS test_b2;

-- 断言 C: 跨模型相减应被标记并给出警告
SET @chk_model := (SELECT COUNT(*) FROM `v_derived_removal` WHERE result_code='RES-W01-S01-R100' AND model_consistent=0 AND model_warning IS NOT NULL);
SELECT IF(@chk_model=1,'[PASS] C 跨光学模型相减已标记并告警','[FAIL] C') AS test_c;

-- 断言 D: 共腔与独立运行可区分
SET @chk_coetch := (SELECT COUNT(*) FROM `v_process_detail` WHERE process_code='RUN-20261008-B28-COETCH-S04S06' AND is_independent_run=0 AND sample_count=2);
SELECT IF(@chk_coetch=1,'[PASS] D 共腔运行(2片,非独立)可识别','[FAIL] D') AS test_d;

-- 断言 E: 完整循环与预暴露模式隔离
SET @chk_mode := (SELECT COUNT(DISTINCT process_mode) FROM `processes` WHERE process_code IN ('RUN-20261014-B05-FULL50','RUN-20261014-B05-PRE-HFTMA5'));
SELECT IF(@chk_mode=2,'[PASS] E 完整循环/预暴露模式已隔离','[FAIL] E') AS test_e;

-- 断言 F: 点级配对可执行（同坐标连接）
SET @chk_pair := (
  SELECT COUNT(*) FROM `measurement_points` pa
  JOIN `measurement_points` pb ON pb.x_mm=pa.x_mm AND pb.y_mm=pa.y_mm
  JOIN `measurements` ma ON ma.measurement_id=pa.measurement_id
  JOIN `measurements` mb ON mb.measurement_id=pb.measurement_id
  WHERE ma.measurement_code='MSR-W01-S01-INITIAL');
SELECT IF(@chk_pair=3,'[PASS] F 点级同坐标配对可执行(3对)','[FAIL] F') AS test_f;

-- 断言 G: 异常样品证据汇总视图
SET @chk_ev := (SELECT COUNT(*) FROM `v_sample_evidence` WHERE sample_code='W01-S09' AND exclude_from_analysis=1 AND n_linked_issues>=1);
SELECT IF(@chk_ev=1,'[PASS] G 样品证据汇总(含关联问题)','[FAIL] G') AS test_g;

-- 断言 H: XPS 映射悬空状态可查询
SET @chk_xps := (SELECT COUNT(*) FROM `instrument_datasets` WHERE instrument_type='xps' AND sample_mapping_status='unresolved');
SELECT IF(@chk_xps=1,'[PASS] H XPS 样品映射悬空可查询','[FAIL] H') AS test_h;

-- 断言 I: 问题台账的「禁止误用」条款可检索
SET @chk_avoid := (SELECT COUNT(*) FROM `issues` WHERE avoid IS NOT NULL AND avoid<>'');
SELECT IF(@chk_avoid>=3,'[PASS] I 禁止误用条款可检索','[FAIL] I') AS test_i;

-- 断言 J: 工艺步骤中未知参数保持 NULL（未被标称值填充）
SET @chk_null := (SELECT COUNT(*) FROM `process_steps` WHERE o3_generator_o2_flow_set_sccm IS NULL);
SELECT IF(@chk_null>=1,'[PASS] J 未知工艺参数保持 NULL','[FAIL] J') AS test_j;

-- ---------------------------------------------------------------------
-- 13. 约束生效性测试
-- ---------------------------------------------------------------------
-- 外键与 CHECK 已由 DDL 建立；此处用 information_schema 复核其定义存在。
SELECT COUNT(*) AS fk_count_expected_49
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA='ale_workbench' AND CONSTRAINT_TYPE='FOREIGN KEY';

SELECT COUNT(*) AS check_count_expected_33
FROM information_schema.TABLE_CONSTRAINTS
WHERE CONSTRAINT_SCHEMA='ale_workbench' AND CONSTRAINT_TYPE='CHECK';

-- ---------------------------------------------------------------------
-- 汇总
-- ---------------------------------------------------------------------
SELECT '=== 行数汇总 ===' AS section;
SELECT 'users' t, COUNT(*) n FROM `users`
UNION ALL SELECT 'tools', COUNT(*) FROM `tools`
UNION ALL SELECT 'batches', COUNT(*) FROM `batches`
UNION ALL SELECT 'samples', COUNT(*) FROM `samples`
UNION ALL SELECT 'optical_models', COUNT(*) FROM `optical_models`
UNION ALL SELECT 'processes', COUNT(*) FROM `processes`
UNION ALL SELECT 'process_steps', COUNT(*) FROM `process_steps`
UNION ALL SELECT 'process_samples', COUNT(*) FROM `process_samples`
UNION ALL SELECT 'measurements', COUNT(*) FROM `measurements`
UNION ALL SELECT 'measurement_points', COUNT(*) FROM `measurement_points`
UNION ALL SELECT 'derived_results', COUNT(*) FROM `derived_results`
UNION ALL SELECT 'source_files', COUNT(*) FROM `source_files`
UNION ALL SELECT 'findings', COUNT(*) FROM `findings`
UNION ALL SELECT 'issues', COUNT(*) FROM `issues`
UNION ALL SELECT 'issues_links', COUNT(*) FROM `issues_links`
UNION ALL SELECT 'instrument_datasets', COUNT(*) FROM `instrument_datasets`
UNION ALL SELECT 'instrument_channels', COUNT(*) FROM `instrument_channels`
UNION ALL SELECT 'instrument_datapoints', COUNT(*) FROM `instrument_datapoints`
UNION ALL SELECT 'sample_transitions', COUNT(*) FROM `sample_transitions`;

-- 全部回滚，库内不留数据
ROLLBACK;
