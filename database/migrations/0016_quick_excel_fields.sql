-- Explicit projections of the V2.2 payload for external SQL access.
-- payload JSON on quick_runs remains the authoritative snapshot; nothing here rewrites history.
-- Only additive: no DROP, no TRUNCATE, no backfill of scientific values.
ALTER TABLE quick_runs
 ADD COLUMN external_experiment_id VARCHAR(128) NULL,
 ADD COLUMN external_batch_id VARCHAR(128) NULL,
 ADD COLUMN process_type VARCHAR(64) NULL,
 ADD COLUMN rf_icp_power_w DECIMAL(18,4) NULL,
 ADD COLUMN bias_power_w DECIMAL(18,4) NULL,
 ADD COLUMN equipment VARCHAR(128) NULL,
 ADD COLUMN chamber_pressure_pa DECIMAL(18,4) NULL,
 ADD COLUMN r1_temp_c DECIMAL(10,2) NULL,
 ADD COLUMN r2_temp_c DECIMAL(10,2) NULL,
 ADD COLUMN n2_flow_sccm DECIMAL(12,3) NULL,
 ADD COLUMN started_at DATETIME NULL,
 ADD COLUMN ended_at DATETIME NULL,
 ADD COLUMN note TEXT NULL;

CREATE TABLE IF NOT EXISTS quick_results (
 run_id BIGINT UNSIGNED NOT NULL,
 result_id CHAR(36) CHARACTER SET ascii NOT NULL,
 ordinal INT UNSIGNED NOT NULL,
 alias VARCHAR(128) NULL,
 material_id CHAR(36) CHARACTER SET ascii NULL,
 thickness_before_nm DECIMAL(18,4) NULL,
 thickness_after_nm DECIMAL(18,4) NULL,
 effective_cycles INT UNSIGNED NULL,
 uniformity_pct DECIMAL(18,4) NULL,
 uniformity_definition VARCHAR(256) NULL,
 reported_epc DECIMAL(18,4) NULL,
 data_nature VARCHAR(32) NULL,
 quality_status VARCHAR(32) NULL,
 result_label VARCHAR(32) NULL,
 use_for_model_override TINYINT(1) NULL,
 before_origin VARCHAR(32) NULL,
 after_origin VARCHAR(32) NULL,
 PRIMARY KEY (run_id, result_id),
 KEY idx_quick_results_ordinal (run_id, ordinal),
 FOREIGN KEY (run_id) REFERENCES quick_runs(process_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS quick_steps (
 run_id BIGINT UNSIGNED NOT NULL,
 step_id CHAR(36) CHARACTER SET ascii NOT NULL,
 group_id CHAR(36) CHARACTER SET ascii NOT NULL,
 group_code VARCHAR(32) NULL,
 repeat_count INT UNSIGNED NULL,
 ordinal INT UNSIGNED NOT NULL,
 source_label VARCHAR(128) NULL,
 pulse_ms DECIMAL(18,4) NULL,
 purge_s DECIMAL(18,4) NULL,
 wait_s DECIMAL(18,4) NULL,
 delta_p_pa DECIMAL(18,4) NULL,
 delta_p_pa_min DECIMAL(18,4) NULL,
 delta_p_pa_max DECIMAL(18,4) NULL,
 enabled TINYINT(1) NOT NULL DEFAULT 0,
 PRIMARY KEY (run_id, step_id),
 KEY idx_quick_steps_ordinal (run_id, group_id, ordinal),
 FOREIGN KEY (run_id) REFERENCES quick_runs(process_id) ON DELETE CASCADE
) ENGINE=InnoDB;
