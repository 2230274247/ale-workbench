-- Additive sample lifecycle metadata only. Existing status, void metadata, codes and all scientific rows stay unchanged.
-- Each statement is independently resumable through migrate.py (column/constraint existence is checked first).
ALTER TABLE samples ADD COLUMN archived_at DATETIME NULL;
ALTER TABLE samples ADD COLUMN archived_by_user_id BIGINT UNSIGNED NULL;
ALTER TABLE samples ADD CONSTRAINT fk_samples_archive_actor FOREIGN KEY (archived_by_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
