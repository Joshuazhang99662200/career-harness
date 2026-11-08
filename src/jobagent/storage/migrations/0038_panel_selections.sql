BEGIN IMMEDIATE;

-- Each saved version of the panel's selection queue. A version lists the chosen
-- contacts with the verified execution item each had when chosen (or null), so a
-- later verified send takes it out while an earlier one does not.
CREATE TABLE panel_selection_versions (
    candidate_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    contacts_json TEXT NOT NULL CHECK (json_valid(contacts_json)),
    saved_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, version)
);
CREATE TRIGGER panel_selection_versions_no_update BEFORE UPDATE ON panel_selection_versions
BEGIN SELECT RAISE(ABORT, 'selection versions are append only'); END;
CREATE TRIGGER panel_selection_versions_no_delete BEFORE DELETE ON panel_selection_versions
BEGIN SELECT RAISE(ABORT, 'selection versions are append only'); END;

PRAGMA user_version = 38;
COMMIT;
