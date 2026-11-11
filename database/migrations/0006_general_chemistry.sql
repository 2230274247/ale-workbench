-- Phase 4 general chemistry systems, batch endpoints and step extensions.
-- Additive only: every new object is CREATE IF NOT EXISTS or a separate
-- resumable ADD, and both CHECK changes are single atomic ALTER statements so
-- an interrupted run can be replayed without weakening the contract.
-- `role` is a MySQL 8 reserved word and stays backticked.
CREATE TABLE IF NOT EXISTS chemistry_systems (
 system_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 system_code VARCHAR(64) NOT NULL,
 system_name VARCHAR(255) NOT NULL,
 description TEXT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'active',
 owner_user_id BIGINT UNSIGNED NULL,
 row_version INT UNSIGNED NOT NULL DEFAULT 1,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 UNIQUE KEY uk_chemistry_systems_code(system_code),
 KEY ix_chemistry_systems_owner(owner_user_id),
 CONSTRAINT fk_chemistry_systems_owner FOREIGN KEY(owner_user_id) REFERENCES users(user_id) ON DELETE SET NULL ON UPDATE CASCADE,
 CONSTRAINT chk_chemistry_systems_status CHECK(status IN ('active','superseded','experimental'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chemistry_species (
 species_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 system_id BIGINT UNSIGNED NOT NULL,
 species_code VARCHAR(64) NOT NULL,
 species_name VARCHAR(255) NOT NULL,
 formula VARCHAR(64) NULL,
 `role` VARCHAR(24) NOT NULL,
 default_unit VARCHAR(24) NULL,
 notes TEXT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uk_species_code(system_id,species_code),
 CONSTRAINT fk_species_system FOREIGN KEY(system_id) REFERENCES chemistry_systems(system_id) ON DELETE CASCADE ON UPDATE CASCADE,
 CONSTRAINT chk_species_role CHECK(`role` IN ('precursor','reactant','purge','carrier','other'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS chemistry_step_templates (
 template_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
 system_id BIGINT UNSIGNED NOT NULL,
 template_code VARCHAR(64) NOT NULL,
 template_name VARCHAR(255) NOT NULL,
 description TEXT NULL,
 steps JSON NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 UNIQUE KEY uk_templates_code(system_id,template_code),
 CONSTRAINT fk_templates_system FOREIGN KEY(system_id) REFERENCES chemistry_systems(system_id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

ALTER TABLE experiment_plans DROP CHECK chk_plans_status,
 ADD CONSTRAINT chk_plans_status CHECK (status IN ('draft','approved','running','completed','abandoned','archived'));

ALTER TABLE processes ADD COLUMN chemistry_system_id BIGINT UNSIGNED NULL;
ALTER TABLE processes ADD CONSTRAINT fk_processes_chemistry FOREIGN KEY(chemistry_system_id) REFERENCES chemistry_systems(system_id) ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE experiment_plan_steps ADD COLUMN step_name VARCHAR(128) NULL;
ALTER TABLE experiment_plan_steps ADD COLUMN custom_parameters JSON NULL;
ALTER TABLE process_steps ADD COLUMN step_name VARCHAR(128) NULL;
ALTER TABLE process_steps ADD COLUMN custom_parameters JSON NULL;

ALTER TABLE audit_log DROP CHECK chk_audit_entity,
 ADD CONSTRAINT chk_audit_entity CHECK (entity_type IN
 ('experiment_plan','experiment_plan_step','process','process_step','process_sample','sample','sample_transition','measurement','measurement_point','derived_result','instrument_dataset','finding','issue','batch','recipe','user','source_file','chemistry_system','chemistry_species','chemistry_step_template'));
