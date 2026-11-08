BEGIN IMMEDIATE;

-- A panel execution list of already-approved first greetings, as created. Item
-- statuses are not stored here: they are derived from send audits and readbacks.
CREATE TABLE execution_batches (
    batch_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    batch_json TEXT NOT NULL CHECK (json_valid(batch_json)),
    refs_json TEXT NOT NULL CHECK (json_valid(refs_json)),
    created_at TEXT NOT NULL
);
-- The person's one confirmation of a list: which items to hand to the host.
CREATE TABLE execution_confirmations (
    event_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    batch_id TEXT NOT NULL UNIQUE REFERENCES execution_batches(batch_id),
    request_digest TEXT NOT NULL,
    item_ids_json TEXT NOT NULL CHECK (json_valid(item_ids_json)),
    actor_id TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    UNIQUE (candidate_id, operation_key)
);
CREATE TRIGGER execution_batches_no_update BEFORE UPDATE ON execution_batches
BEGIN SELECT RAISE(ABORT, 'execution batches are append only'); END;
CREATE TRIGGER execution_batches_no_delete BEFORE DELETE ON execution_batches
BEGIN SELECT RAISE(ABORT, 'execution batches are append only'); END;
CREATE TRIGGER execution_confirmations_no_update BEFORE UPDATE ON execution_confirmations
BEGIN SELECT RAISE(ABORT, 'execution confirmations are append only'); END;
CREATE TRIGGER execution_confirmations_no_delete BEFORE DELETE ON execution_confirmations
BEGIN SELECT RAISE(ABORT, 'execution confirmations are append only'); END;

PRAGMA user_version = 37;
COMMIT;
