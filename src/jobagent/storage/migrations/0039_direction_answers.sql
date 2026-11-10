BEGIN IMMEDIATE;

-- A skip proposal from the direction gate, and the person's one answer to it. The
-- answer is owner feedback on the jobs rules the proposal cited, so the preference
-- memory can widen or narrow them.
CREATE TABLE direction_proposals (
    proposal_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    proposal_json TEXT NOT NULL CHECK (json_valid(proposal_json)),
    proposed_at TEXT NOT NULL
);
CREATE TABLE direction_answers (
    answer_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES direction_proposals(proposal_id),
    candidate_id TEXT NOT NULL,
    answer_json TEXT NOT NULL CHECK (json_valid(answer_json)),
    answered_at TEXT NOT NULL
);
CREATE TRIGGER direction_proposals_no_update BEFORE UPDATE ON direction_proposals
BEGIN SELECT RAISE(ABORT, 'direction proposals are append only'); END;
CREATE TRIGGER direction_proposals_no_delete BEFORE DELETE ON direction_proposals
BEGIN SELECT RAISE(ABORT, 'direction proposals are append only'); END;
CREATE TRIGGER direction_answers_no_update BEFORE UPDATE ON direction_answers
BEGIN SELECT RAISE(ABORT, 'direction answers are append only'); END;
CREATE TRIGGER direction_answers_no_delete BEFORE DELETE ON direction_answers
BEGIN SELECT RAISE(ABORT, 'direction answers are append only'); END;

PRAGMA user_version = 39;
COMMIT;
