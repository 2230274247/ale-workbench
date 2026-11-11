-- Each additive ALTER is separate so interrupted execution can resume safely.
-- source_files remains unchanged: file_id PK, file_sha256 globally unique.
-- User-specific names and associations belong to occurrences, never dedup metadata.
CREATE TABLE IF NOT EXISTS import_jobs (
 job_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'draft',
 row_version INT UNSIGNED NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_import_jobs_owner(owner_user_id),
 CONSTRAINT fk_import_jobs_owner FOREIGN KEY(owner_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION,
 CONSTRAINT chk_import_jobs_status CHECK(status IN ('draft','completed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS import_items (
 item_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 job_id BIGINT UNSIGNED NOT NULL,
 filename VARCHAR(255) NOT NULL,
 sha256 CHAR(64) NOT NULL,
 storage_key VARCHAR(255) NOT NULL,
 parse_result JSON NOT NULL,
 confirmation JSON NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'pending',
 result JSON NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_import_items_job(job_id),
 CONSTRAINT fk_import_items_job FOREIGN KEY(job_id) REFERENCES import_jobs(job_id) ON DELETE RESTRICT ON UPDATE NO ACTION,
 CONSTRAINT chk_import_items_status CHECK(status IN ('pending','imported','original_only','skipped'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS import_confirmations (
 job_id BIGINT UNSIGNED NOT NULL,
 confirmation_hash CHAR(64) NOT NULL,
 result JSON NOT NULL,
 PRIMARY KEY(job_id,confirmation_hash),
 CONSTRAINT fk_import_confirmations_job FOREIGN KEY(job_id) REFERENCES import_jobs(job_id) ON DELETE RESTRICT ON UPDATE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS source_file_occurrences (
 occurrence_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 source_file_id BIGINT UNSIGNED NOT NULL,
 import_item_id BIGINT UNSIGNED NOT NULL,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 sample_id BIGINT UNSIGNED NULL,
 filename VARCHAR(255) NOT NULL,
 notes TEXT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uk_source_occurrence_item(import_item_id),
 KEY ix_source_occurrences_source(source_file_id),
 KEY ix_source_occurrences_owner(owner_user_id),
 KEY ix_source_occurrences_sample(sample_id),
 CONSTRAINT fk_source_occurrences_source FOREIGN KEY(source_file_id) REFERENCES source_files(file_id) ON DELETE RESTRICT ON UPDATE NO ACTION,
 CONSTRAINT fk_source_occurrences_item FOREIGN KEY(import_item_id) REFERENCES import_items(item_id) ON DELETE RESTRICT ON UPDATE NO ACTION,
 CONSTRAINT fk_source_occurrences_owner FOREIGN KEY(owner_user_id) REFERENCES users(user_id) ON DELETE RESTRICT ON UPDATE NO ACTION,
 CONSTRAINT fk_source_occurrences_sample FOREIGN KEY(sample_id) REFERENCES samples(sample_id) ON DELETE RESTRICT ON UPDATE NO ACTION
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE measurements ADD COLUMN source_file_id BIGINT UNSIGNED NULL;
ALTER TABLE measurements ADD COLUMN import_item_id BIGINT UNSIGNED NULL;
ALTER TABLE measurements ADD COLUMN import_locator VARCHAR(255) NULL;
ALTER TABLE measurements ADD COLUMN row_version INT UNSIGNED NOT NULL DEFAULT 1;
ALTER TABLE measurements ADD COLUMN provenance JSON NULL;
ALTER TABLE measurements ADD CONSTRAINT fk_msr_source_file FOREIGN KEY(source_file_id) REFERENCES source_files(file_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE measurements ADD CONSTRAINT fk_msr_import_item FOREIGN KEY(import_item_id) REFERENCES import_items(item_id) ON DELETE RESTRICT ON UPDATE NO ACTION;
ALTER TABLE measurements ADD CONSTRAINT uk_msr_import_locator UNIQUE(import_item_id,import_locator);
ALTER TABLE measurement_points ADD COLUMN raw_values JSON NULL;
