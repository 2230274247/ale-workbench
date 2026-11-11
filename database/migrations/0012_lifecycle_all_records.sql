-- Additive lifecycle metadata. No scientific values, status values or history are rewritten.
ALTER TABLE batches ADD COLUMN voided_at DATETIME NULL;
ALTER TABLE batches ADD COLUMN void_reason VARCHAR(2000) NULL;
ALTER TABLE batches ADD COLUMN voided_by_user_id BIGINT UNSIGNED NULL;
ALTER TABLE batches ADD CONSTRAINT fk_batches_void_actor FOREIGN KEY (voided_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE batches ADD CONSTRAINT chk_batches_void_metadata CHECK ((voided_at IS NULL AND void_reason IS NULL AND voided_by_user_id IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND CHAR_LENGTH(TRIM(void_reason)) > 0 AND voided_by_user_id IS NOT NULL));
ALTER TABLE experiment_plans ADD COLUMN voided_at DATETIME NULL;
ALTER TABLE experiment_plans ADD COLUMN void_reason VARCHAR(2000) NULL;
ALTER TABLE experiment_plans ADD COLUMN voided_by_user_id BIGINT UNSIGNED NULL;
ALTER TABLE experiment_plans ADD CONSTRAINT fk_experiment_plans_void_actor FOREIGN KEY (voided_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE experiment_plans ADD CONSTRAINT chk_experiment_plans_void_metadata CHECK ((voided_at IS NULL AND void_reason IS NULL AND voided_by_user_id IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND CHAR_LENGTH(TRIM(void_reason)) > 0 AND voided_by_user_id IS NOT NULL));
ALTER TABLE processes ADD COLUMN voided_at DATETIME NULL;
ALTER TABLE processes ADD COLUMN void_reason VARCHAR(2000) NULL;
ALTER TABLE processes ADD COLUMN voided_by_user_id BIGINT UNSIGNED NULL;
ALTER TABLE processes ADD CONSTRAINT fk_processes_void_actor FOREIGN KEY (voided_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE processes ADD CONSTRAINT chk_processes_void_metadata CHECK ((voided_at IS NULL AND void_reason IS NULL AND voided_by_user_id IS NULL) OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND CHAR_LENGTH(TRIM(void_reason)) > 0 AND voided_by_user_id IS NOT NULL));
ALTER TABLE experiment_plans ADD COLUMN archive_previous_status VARCHAR(24) NULL;
