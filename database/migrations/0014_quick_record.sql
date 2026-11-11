-- V2.2 additive extension: existing process identity and ownership remain authoritative.
CREATE TABLE IF NOT EXISTS quick_materials (
 material_id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 canonical_name VARCHAR(128) NOT NULL,
 aliases JSON NOT NULL,
 UNIQUE KEY uq_quick_material (owner_user_id, canonical_name),
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS quick_runs (
 process_id BIGINT UNSIGNED PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 experiment_date DATE NOT NULL,
 daily_no INT UNSIGNED NOT NULL,
 sequence_id CHAR(36) CHARACTER SET ascii NOT NULL,
 previous_process_id BIGINT UNSIGNED NULL,
 payload JSON NOT NULL,
 request_key CHAR(36) CHARACTER SET ascii NOT NULL,
 request_hash CHAR(64) CHARACTER SET ascii NOT NULL,
 UNIQUE KEY uq_quick_request (owner_user_id, request_key),
 UNIQUE KEY uq_quick_daily (owner_user_id, experiment_date, daily_no),
 KEY ix_quick_sequence (sequence_id),
 FOREIGN KEY (process_id) REFERENCES processes(process_id),
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
 FOREIGN KEY (previous_process_id) REFERENCES processes(process_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS quick_revisions (
 revision_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 process_id BIGINT UNSIGNED NOT NULL,
 actor_user_id BIGINT UNSIGNED NOT NULL,
 version INT UNSIGNED NOT NULL,
 snapshot JSON NOT NULL,
 reason VARCHAR(255) NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_quick_revision (process_id, version),
 FOREIGN KEY (process_id) REFERENCES processes(process_id),
 FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS quick_templates (
 template_id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 name VARCHAR(128) NOT NULL,
 snapshot JSON NOT NULL,
 version INT NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS quick_imports (
 token CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 process_id BIGINT UNSIGNED NOT NULL,
 sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
 filename VARCHAR(255) NOT NULL,
 preview JSON NOT NULL,
 confirmation JSON NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
 FOREIGN KEY (process_id) REFERENCES processes(process_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS quick_exports (
 export_id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 manifest JSON NOT NULL,
 sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;
