from datetime import UTC, datetime, timedelta

import pytest

from jobagent.bridge.preference_memory import load_direction_answers
from jobagent.errors import ContractValidationError
from jobagent.schemas.preference_memory import DirectionAnswer, DirectionProposal
from jobagent.storage.database import Database
from jobagent.storage.direction_repository import (
    SqliteDirectionRepository,
    answer_id_for,
    proposal_id_for,
)

NOW = datetime(2026, 11, 10, tzinfo=UTC)


def setup(tmp_path):
    database = Database(tmp_path / "db.sqlite3")
    database.migrate()
    repo = SqliteDirectionRepository(database)
    proposal = DirectionProposal(
        proposal_id=proposal_id_for("CAND_TEST", "JOB_ONE", "PMEM_V1", ["RULE_SALES"], NOW),
        candidate_id="CAND_TEST", job_id="JOB_ONE", memory_version="PMEM_V1",
        rule_ids=["RULE_SALES"], reason="synthetic", proposed_at=NOW,
    )
    repo.save_proposal(proposal)
    return database, repo, proposal


def answer(proposal, **changes):
    at = changes.pop("occurred_at", NOW + timedelta(minutes=1))
    base = DirectionAnswer(
        answer_id=answer_id_for(proposal.proposal_id, "confirm_skip", "跳过。", "商务岗", at),
        proposal_id=proposal.proposal_id, candidate_id="CAND_TEST", job_id="JOB_ONE",
        rule_ids=["RULE_SALES"], action="confirm_skip", words="跳过。", free_text="商务岗",
        job_title="Synthetic", company="Synthetic", jd_text="Synthetic JD.", occurred_at=at,
    )
    return base.model_copy(update=changes)


def test_an_answer_must_restate_its_proposal_and_comes_once(tmp_path):
    _, repo, proposal = setup(tmp_path)
    for wrong in ({"rule_ids": ["RULE_OTHER"]}, {"job_id": "JOB_TWO"},
                  {"candidate_id": "CAND_OTHER"}, {"occurred_at": NOW - timedelta(minutes=1)}):
        with pytest.raises(ContractValidationError, match="does not match"):
            repo.record_answer(answer(proposal, **wrong))
    repo.record_answer(answer(proposal))
    with pytest.raises(ContractValidationError, match="already"):
        repo.record_answer(answer(proposal, occurred_at=NOW + timedelta(minutes=2)))


def test_answers_without_a_stored_real_jd_are_not_read_as_feedback(tmp_path):
    database, repo, proposal = setup(tmp_path)
    repo.record_answer(answer(proposal))
    assert load_direction_answers(database.path, "CAND_TEST") == []
