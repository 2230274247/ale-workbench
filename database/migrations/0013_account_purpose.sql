-- Add account intent without moving owners or altering scientific records.
ALTER TABLE users ADD COLUMN account_purpose VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'research';
ALTER TABLE invitations ADD COLUMN account_purpose VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'research';
UPDATE users SET account_purpose = 'management', updated_at = updated_at WHERE role = 'admin' AND account_purpose <> 'management';
ALTER TABLE users ADD CONSTRAINT chk_users_account_purpose CHECK ((role = 'admin' AND account_purpose = 'management') OR (role IN ('operator','viewer') AND account_purpose IN ('research','testing')));
ALTER TABLE invitations ADD CONSTRAINT chk_invitations_account_purpose CHECK (account_purpose IN ('research','testing'));
