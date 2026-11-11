-- Version 0001. Single atomic ALTER preserves existing rows and enforcement.
ALTER TABLE issues_links
  DROP CHECK chk_il_entity,
  ADD CONSTRAINT chk_il_entity CHECK (entity_type IN
    ('experiment_plan','process','sample','measurement','source_file','finding','batch','derived_result','instrument_dataset'));
