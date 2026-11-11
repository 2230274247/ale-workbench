-- Optional AI service; no scientific data or account changes.
CREATE TABLE IF NOT EXISTS ai_config (
 config_id INT UNSIGNED NOT NULL PRIMARY KEY,
 settings JSON NOT NULL,
 key_ciphertext TEXT NULL,
 discovered_models JSON NULL,
 revision INT UNSIGNED NOT NULL DEFAULT 1,
 updated_by BIGINT UNSIGNED NULL,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CONSTRAINT fk_ai_config_actor FOREIGN KEY (updated_by) REFERENCES users(user_id) ON DELETE RESTRICT,
 CONSTRAINT chk_ai_config_singleton CHECK (config_id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS ai_budget_periods (
 period CHAR(7) NOT NULL PRIMARY KEY,
 charged_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 reserved_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 charged_cost DECIMAL(24,8) NOT NULL DEFAULT 0,
 reserved_cost DECIMAL(24,8) NOT NULL DEFAULT 0,
 CONSTRAINT chk_ai_budget_cost CHECK (charged_cost >= 0 AND reserved_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS ai_conversations (
 conversation_id CHAR(36) NOT NULL PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 busy_request_id CHAR(36) NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_ai_conversations_owner (owner_user_id),
 CONSTRAINT fk_ai_conversations_owner FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS ai_requests (
 request_id CHAR(36) NOT NULL PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 conversation_id CHAR(36) NULL,
 request_hash CHAR(64) NOT NULL,
 purpose VARCHAR(12) NOT NULL,
 status VARCHAR(12) NOT NULL,
 period CHAR(7) NOT NULL,
 reserved_tokens BIGINT UNSIGNED NOT NULL,
 reserved_cost DECIMAL(24,8) NOT NULL,
 prompt_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 completion_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 cache_hit_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 cache_miss_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 charged_tokens BIGINT UNSIGNED NOT NULL DEFAULT 0,
 charged_cost DECIMAL(24,8) NOT NULL DEFAULT 0,
 usage_estimated TINYINT UNSIGNED NOT NULL DEFAULT 0,
 provider_calls INT UNSIGNED NOT NULL DEFAULT 0,
 result JSON NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 finished_at DATETIME NULL,
 KEY ix_ai_requests_owner_day (owner_user_id, created_at),
 KEY ix_ai_requests_period (period),
 KEY ix_ai_requests_conversation (conversation_id),
 CONSTRAINT fk_ai_requests_owner FOREIGN KEY (owner_user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
 CONSTRAINT fk_ai_requests_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations(conversation_id) ON DELETE RESTRICT,
 CONSTRAINT fk_ai_requests_period FOREIGN KEY (period) REFERENCES ai_budget_periods(period) ON DELETE RESTRICT,
 CONSTRAINT chk_ai_requests_status CHECK (status IN ('pending','completed','failed')),
 CONSTRAINT chk_ai_requests_purpose CHECK (purpose IN ('chat','test','models')),
 CONSTRAINT chk_ai_requests_cost CHECK (reserved_cost >= 0 AND charged_cost >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS ai_messages (
 message_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 conversation_id CHAR(36) NOT NULL,
 request_id CHAR(36) NOT NULL,
 role VARCHAR(12) NOT NULL,
 content TEXT NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_ai_messages_conversation (conversation_id, message_id),
 KEY ix_ai_messages_request (request_id),
 CONSTRAINT fk_ai_messages_conversation FOREIGN KEY (conversation_id) REFERENCES ai_conversations(conversation_id) ON DELETE RESTRICT,
 CONSTRAINT fk_ai_messages_request FOREIGN KEY (request_id) REFERENCES ai_requests(request_id) ON DELETE RESTRICT,
 CONSTRAINT chk_ai_messages_role CHECK (role IN ('user','assistant'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS ai_tool_traces (
 trace_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 request_id CHAR(36) NOT NULL,
 tool_name VARCHAR(64) NOT NULL,
 status VARCHAR(12) NOT NULL,
 sources JSON NOT NULL,
 result_bytes INT UNSIGNED NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY ix_ai_tool_traces_request (request_id),
 CONSTRAINT fk_ai_tool_traces_request FOREIGN KEY (request_id) REFERENCES ai_requests(request_id) ON DELETE RESTRICT,
 CONSTRAINT chk_ai_tool_traces_status CHECK (status IN ('completed','denied'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
