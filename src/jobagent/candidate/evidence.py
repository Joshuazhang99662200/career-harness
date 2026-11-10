"""Explicit candidate evidence lifecycle policies."""

from collections.abc import Sequence

from jobagent.candidate.ports import CandidateRepository
from jobagent.digest import canonical_digest
from jobagent.errors import (
    ContractValidationError,
    MissingEvidenceError,
    PolicyRejectionError,
    StaleApprovalError,
)
from jobagent.schemas.candidate import Confidence, EvidenceItem
from jobagent.schemas.common import SourceReference, SourceType


def statement_digest(evidence: EvidenceItem) -> str:
    """Everything the person reads about a fact, without its confirmation flag.

    A confirmation that names this digest is bound to the exact wording shown.
    """
    return canonical_digest(evidence.model_dump(mode="json", exclude={"user_confirmed"}))


class CandidateEvidenceService:
    """Keep draft creation, user editing, and confirmation as distinct operations."""

    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository

    def get(self, candidate_id: str, evidence_id: str) -> EvidenceItem | None:
        return self.repository.get_evidence(candidate_id, evidence_id)

    def add_draft(self, candidate_id: str, evidence: EvidenceItem) -> EvidenceItem:
        if evidence.user_confirmed:
            raise PolicyRejectionError(
                "Draft evidence cannot arrive already confirmed.",
                details={"candidate_id": candidate_id, "evidence_id": evidence.id},
            )
        self.repository.upsert_evidence(candidate_id, evidence)
        return evidence

    def confirm(
        self, candidate_id: str, evidence_id: str, *, expected_digest: str | None = None
    ) -> EvidenceItem:
        """Promote one admissible item; with a digest, only the exact wording that was shown."""
        evidence = self._required(candidate_id, evidence_id, expected_digest)
        if evidence.confidence is Confidence.WEAK:
            raise PolicyRejectionError(
                "Weak evidence cannot be confirmed.",
                details={"candidate_id": candidate_id, "evidence_id": evidence_id},
            )
        confirmed = EvidenceItem.model_validate(
            {**evidence.model_dump(mode="python"), "user_confirmed": True}
        )
        self.repository.upsert_evidence(candidate_id, confirmed)
        return confirmed

    def confirm_shown(
        self, candidate_id: str, shown: Sequence[tuple[str, str]]
    ) -> list[EvidenceItem]:
        """Confirm a table of facts the person approved, each bound to the wording shown.

        Every item is checked before any is promoted, so one stale, missing or weak
        item leaves the whole table unconfirmed. Promotion still goes through confirm.
        """
        if not shown or len({evidence_id for evidence_id, _ in shown}) != len(shown):
            raise ContractValidationError("List each shown fact exactly once.")
        for evidence_id, digest in shown:
            evidence = self._required(candidate_id, evidence_id, digest)
            if evidence.confidence is Confidence.WEAK:
                raise PolicyRejectionError(
                    "Weak evidence cannot be confirmed.",
                    details={"candidate_id": candidate_id, "evidence_id": evidence_id},
                )
        return [
            self.confirm(candidate_id, evidence_id, expected_digest=digest)
            for evidence_id, digest in shown
        ]

    def replace_with_user_edit(
        self,
        candidate_id: str,
        evidence_id: str,
        statement: str,
        *,
        expected_digest: str | None = None,
    ) -> EvidenceItem:
        if not statement.strip():
            raise ContractValidationError(
                "A restated fact cannot be empty.", details={"evidence_id": evidence_id}
            )
        evidence = self._required(candidate_id, evidence_id, expected_digest)
        edited = EvidenceItem.model_validate(
            {
                **evidence.model_dump(mode="python"),
                "statement": statement.strip(),
                "source": SourceReference(
                    type=SourceType.USER_EDIT,
                    reference=f"{evidence_id}:revision",
                ),
                "confidence": Confidence.EXPLICIT,
                "user_confirmed": False,
            }
        )
        self.repository.upsert_evidence(candidate_id, edited)
        return edited

    def _required(
        self, candidate_id: str, evidence_id: str, expected_digest: str | None = None
    ) -> EvidenceItem:
        evidence = self.repository.get_evidence(candidate_id, evidence_id)
        if evidence is None:
            raise MissingEvidenceError(
                "Candidate evidence was not found.",
                details={"candidate_id": candidate_id, "evidence_id": evidence_id},
            )
        if expected_digest is not None and statement_digest(evidence) != expected_digest:
            raise StaleApprovalError(
                "The fact changed after it was shown; show it again before acting on it.",
                details={"candidate_id": candidate_id, "evidence_id": evidence_id},
            )
        return evidence
