-- Atomic ALTER can be replayed after interruption before the migration ledger insert.
ALTER TABLE audit_log DROP CHECK chk_audit_entity,
 ADD CONSTRAINT chk_audit_entity CHECK (entity_type IN
 ('experiment_plan','experiment_plan_step','process','process_step','process_sample','sample','sample_transition','measurement','measurement_point','derived_result','instrument_dataset','finding','issue','batch','recipe','user','source_file'));
