-- Every resumable ADD is an individual statement, including its actual DDL in this checksum.
CREATE TABLE IF NOT EXISTS experiment_plan_steps (
 step_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 plan_id BIGINT UNSIGNED NOT NULL,
 step_index INT UNSIGNED NOT NULL,
 step_kind VARCHAR(32) NOT NULL,
 planned_parameters JSON NULL,
 step_note TEXT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uk_plan_steps_order(plan_id,step_index),
 CONSTRAINT fk_plan_steps_plan FOREIGN KEY(plan_id) REFERENCES experiment_plans(plan_id) ON DELETE RESTRICT,
 CONSTRAINT chk_plan_steps_index CHECK(step_index >= 1),
 CONSTRAINT chk_plan_steps_kind CHECK(step_kind IN ('o2_plasma','o3_purge','hf_purge','tma_purge','purge','wait','other'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
ALTER TABLE experiment_plans ADD COLUMN row_version INT UNSIGNED NOT NULL DEFAULT 1;
ALTER TABLE processes ADD COLUMN row_version INT UNSIGNED NOT NULL DEFAULT 1;
ALTER TABLE process_steps ADD COLUMN plan_step_id BIGINT UNSIGNED NULL;
ALTER TABLE process_steps ADD CONSTRAINT fk_steps_plan_step FOREIGN KEY(plan_step_id) REFERENCES experiment_plan_steps(step_id) ON DELETE RESTRICT;
ALTER TABLE sample_transitions ADD COLUMN step_id BIGINT UNSIGNED NULL;
ALTER TABLE sample_transitions ADD CONSTRAINT fk_transition_step FOREIGN KEY(step_id) REFERENCES process_steps(step_id) ON DELETE RESTRICT;
