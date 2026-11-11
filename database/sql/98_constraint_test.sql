-- =====================================================================
-- ALE 实验工作台 · 98 约束生效性测试
-- ---------------------------------------------------------------------
-- 目的: 证明约束不是装饰——非法数据必须被拒绝。
-- 覆盖: 6 类 CHECK、4 类 UNIQUE、2 类 FOREIGN KEY
-- 用法: 需在种子数据存在的情况下执行（见 run_constraint_test.py）
-- 注意: 全部用 SAVEPOINT 隔离，最终 ROLLBACK，不留数据。
-- =====================================================================

USE `ale_workbench`;

START TRANSACTION;

-- 种子数据
INSERT INTO `users` (`username`,`role`) VALUES ('ct_admin','admin');
INSERT INTO `batches` (`batch_code`,`batch_name`) VALUES ('CT-BATCH','constraint test batch');
INSERT INTO `samples` (`sample_code`,`batch_id`,`status`)
  SELECT 'CT-SAMPLE', batch_id, 'available' FROM `batches` WHERE batch_code='CT-BATCH';
INSERT INTO `measurements` (`measurement_code`,`sample_id`,`stage`)
  SELECT 'CT-MSR', sample_id, 'initial' FROM `samples` WHERE sample_code='CT-SAMPLE';
INSERT INTO `measurement_points` (`measurement_id`,`point_no`,`x_mm`,`y_mm`,`thickness_nm`)
  SELECT measurement_id, 1, 0, 0, 30.0 FROM `measurements` WHERE measurement_code='CT-MSR';

SAVEPOINT base;

-- ---------------------------------------------------------------------
-- 以下每条都应被数据库拒绝。脚本本身会因错误中断是正常的，
-- 故实际测试由 run_constraint_test.py 逐条执行并捕获异常。
-- 这里列出预期被拒的语句作为文档与手工测试清单。
-- ---------------------------------------------------------------------
-- [1] CHECK samples.status  (预期 3819)
--     UPDATE samples SET status='melted' WHERE sample_code='CT-SAMPLE';
-- [2] CHECK measurements.stage  (预期 3819)
--     UPDATE measurements SET stage='before_after' WHERE measurement_code='CT-MSR';
-- [3] CHECK measurements.quality_flag  (预期 3819)
--     UPDATE measurements SET quality_flag='weird' WHERE measurement_code='CT-MSR';
-- [4] CHECK instrument_datasets.instrument_type  (预期 3819)
--     INSERT INTO instrument_datasets(dataset_code,instrument_type) VALUES('D-X','nmr');
-- [5] CHECK source_files.file_role  (预期 3819)
--     INSERT INTO source_files(file_sha256,file_name,file_role) VALUES(REPEAT('c',64),'x.xlsx','bogus');
-- [6] CHECK issues_links.entity_type  (预期 3819)
--     INSERT INTO issues_links(issue_id,entity_type,entity_id) VALUES(1,'spaceship',1);
-- [7] UNIQUE samples.sample_code  (预期 1062)
--     INSERT INTO samples(sample_code,batch_id) SELECT sample_code,batch_id FROM samples WHERE sample_code='CT-SAMPLE';
-- [8] UNIQUE users.username  (预期 1062)
--     INSERT INTO users(username) VALUES('ct_admin');
-- [9] UNIQUE measurements.measurement_code  (预期 1062)
--     INSERT INTO measurements(measurement_code,sample_id,stage) SELECT measurement_code,sample_id,'final' FROM measurements WHERE measurement_code='CT-MSR';
-- [10] UNIQUE measurement_points(measurement_id,point_no)  (预期 1062)
--     INSERT INTO measurement_points(measurement_id,point_no,x_mm,y_mm) SELECT measurement_id,1,0,0 FROM measurements WHERE measurement_code='CT-MSR';
-- [11] FK batches 被引用时删除  (预期 1451)
--     DELETE FROM batches WHERE batch_code='CT-BATCH';
-- [12] FK measurements.sample_id  (预期 1452)
--     INSERT INTO measurements(measurement_code,sample_id,stage) VALUES('M-BAD',999999,'initial');

ROLLBACK TO SAVEPOINT base;

-- 复核约束数量
SELECT
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA='ale_workbench' AND CONSTRAINT_TYPE='FOREIGN KEY') AS fk_total,
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE CONSTRAINT_SCHEMA='ale_workbench' AND CONSTRAINT_TYPE='CHECK')       AS check_total,
  (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA='ale_workbench' AND NON_UNIQUE=0 AND INDEX_NAME<>'PRIMARY') AS unique_index_total;

ROLLBACK;
