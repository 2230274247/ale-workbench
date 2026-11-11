-- Additive infrastructure only; scientific columns and rows are retained.
CREATE TABLE IF NOT EXISTS app_settings (
 setting_key VARCHAR(64) PRIMARY KEY, setting_value TEXT NULL,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT IGNORE INTO app_settings(setting_key,setting_value) VALUES ('initial_setup','pending');
CREATE TABLE IF NOT EXISTS auth_sessions (
 session_id CHAR(36) PRIMARY KEY, user_id BIGINT UNSIGNED NOT NULL,
 refresh_jti_hash CHAR(64) NOT NULL, expires_at DATETIME NOT NULL,
 revoked_at DATETIME NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_session_user(user_id), KEY ix_session_expires(expires_at),
 CONSTRAINT fk_session_user FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS invitations (
 invitation_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 code_hash CHAR(64) NOT NULL UNIQUE, role VARCHAR(32) NOT NULL DEFAULT 'viewer',
 created_by BIGINT UNSIGNED NOT NULL, expires_at DATETIME NOT NULL,
 used_by BIGINT UNSIGNED NULL, used_at DATETIME NULL, revoked_at DATETIME NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT chk_invitation_role CHECK(role IN ('operator','viewer')),
 CONSTRAINT fk_invitation_creator FOREIGN KEY(created_by) REFERENCES users(user_id) ON DELETE RESTRICT,
 CONSTRAINT fk_invitation_used FOREIGN KEY(used_by) REFERENCES users(user_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- Column additions are applied conditionally by migrate.py, making interrupted DDL resumable.
