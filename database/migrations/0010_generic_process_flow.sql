-- Generic classifications and parent-owned, ID-anchored flow. Existing values remain intact.
ALTER TABLE experiment_plans ADD COLUMN process_flow JSON NULL;
ALTER TABLE processes ADD COLUMN process_flow JSON NULL;
ALTER TABLE experiment_plan_steps MODIFY COLUMN step_kind VARCHAR(128) NOT NULL;
ALTER TABLE process_steps MODIFY COLUMN step_kind VARCHAR(128) NOT NULL;
ALTER TABLE experiment_plan_steps DROP CHECK chk_plan_steps_kind;
ALTER TABLE process_steps DROP CHECK chk_steps_kind;
