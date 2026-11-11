-- User-managed precursor/gas labels. Existing recipe values are never rewritten.
CREATE TABLE IF NOT EXISTS quick_sources (
 source_id CHAR(36) CHARACTER SET ascii PRIMARY KEY,
 owner_user_id BIGINT UNSIGNED NOT NULL,
 canonical_name VARCHAR(128) NOT NULL,
 UNIQUE KEY uq_quick_source (owner_user_id, canonical_name),
 FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
) ENGINE=InnoDB;
