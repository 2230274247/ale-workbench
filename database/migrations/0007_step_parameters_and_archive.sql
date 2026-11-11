-- Phase 5: independent archive metadata and copied generic step parameters.
-- No scientific row, status, legacy JSON or file is rewritten.
ALTER TABLE batches ADD COLUMN archived_at DATETIME NULL;
ALTER TABLE processes ADD COLUMN archived_at DATETIME NULL;
ALTER TABLE experiment_plan_steps ADD COLUMN parameter_snapshot JSON NULL;
ALTER TABLE process_steps ADD COLUMN parameter_snapshot JSON NULL;
CREATE TABLE IF NOT EXISTS step_parameter_templates (
 template_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 template_name VARCHAR(128) NOT NULL,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 definition JSON NOT NULL,
 row_version INT UNSIGNED NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 KEY ix_step_parameter_templates_owner(owner_user_id),
 CONSTRAINT fk_step_parameter_templates_owner FOREIGN KEY(owner_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
ALTER TABLE audit_log DROP CHECK chk_audit_entity,
 ADD CONSTRAINT chk_audit_entity CHECK (entity_type IN
 ('experiment_plan','experiment_plan_step','process','process_step','process_sample','sample','sample_transition','measurement','measurement_point','derived_result','instrument_dataset','finding','issue','batch','recipe','user','source_file','chemistry_system','chemistry_species','chemistry_step_template','step_parameter_template'));
