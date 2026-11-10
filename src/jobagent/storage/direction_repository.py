"""Skip proposals from the direction gate and the person's one answer to each."""

import sqlite3
from datetime import datetime

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.preference_memory import DirectionAnswer, DirectionProposal
from jobagent.storage.database import Database


def proposal_id_for(
    candidate_id: str, job_id: str, memory_version: str, rule_ids: list[str], at: datetime,
) -> str:
    digest = canonical_digest([candidate_id, job_id, memory_version, sorted(rule_ids),
                               at.isoformat()])
    return "ODIRP_" + digest[7:27].upper()


def answer_id_for(proposal_id: str, action: str, words: str, free_text: str,
                  at: datetime) -> str:
    return "ODIR_" + canonical_digest([proposal_id, action, words, free_text,
                                       at.isoformat()])[7:27].upper()


class SqliteDirectionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_proposal(self, proposal: DirectionProposal) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO direction_proposals VALUES (?, ?, ?, ?, ?)",
                (proposal.proposal_id, proposal.candidate_id, proposal.job_id,
                 proposal.model_dump_json(), proposal.proposed_at.isoformat()),
            )

    def get_proposal(self, proposal_id: str) -> DirectionProposal | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT proposal_json FROM direction_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return DirectionProposal.model_validate_json(row[0]) if row else None

    def record_answer(self, answer: DirectionAnswer) -> None:
        """Store the one answer to a proposal; it must restate exactly what was proposed."""
        proposal = self.get_proposal(answer.proposal_id)
        if (proposal is None or proposal.candidate_id != answer.candidate_id
                or proposal.job_id != answer.job_id or proposal.rule_ids != answer.rule_ids
                or answer.occurred_at < proposal.proposed_at):
            raise ContractValidationError("The answer does not match a recorded skip proposal.")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO direction_answers VALUES (?, ?, ?, ?, ?)",
                    (answer.answer_id, answer.proposal_id, answer.candidate_id,
                     answer.model_dump_json(), answer.occurred_at.isoformat()),
                )
        except sqlite3.IntegrityError:
            raise ContractValidationError("This skip proposal already has an answer.") from None
