-- Additive lifecycle metadata only. Preserve status, codes and all scientific rows.
ALTER TABLE samples ADD COLUMN voided_at DATETIME NULL;
ALTER TABLE samples ADD COLUMN void_reason VARCHAR(2000) NULL;
ALTER TABLE samples ADD COLUMN voided_by_user_id BIGINT UNSIGNED NULL;
ALTER TABLE samples ADD CONSTRAINT fk_samples_void_actor FOREIGN KEY (voided_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE samples ADD CONSTRAINT chk_samples_void_metadata CHECK (
 (voided_at IS NULL AND void_reason IS NULL AND voided_by_user_id IS NULL)
 OR (voided_at IS NOT NULL AND void_reason IS NOT NULL AND CHAR_LENGTH(TRIM(void_reason)) > 0 AND voided_by_user_id IS NOT NULL)
);
