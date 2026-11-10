"""First-use onboarding read model: what the person has given, and what still waits on them.

Every field is read back from Candidate Core storage. Nothing here confirms a
fact; `statement_digest` only lets a confirmation name the exact wording the
person saw, so a statement that changed in between is refused.
"""

from typing import Literal

from pydantic import AwareDatetime, Field

from jobagent.schemas.candidate import (
    CandidateId,
    CandidateStatus,
    Confidence,
    EvidenceId,
    EvidenceType,
    Experience,
    MetricFact,
    ResumeId,
)
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString, SourceType


class OnboardingFact(ContractModel):
    evidence_id: EvidenceId
    type: EvidenceType
    statement: NonEmptyString
    entity: str = ""
    skills: list[str] = Field(default_factory=list)
    metrics: list[MetricFact] = Field(default_factory=list)
    source_type: SourceType
    source_reference: NonEmptyString
    resume_id: ResumeId | None = None
    resume_page: int | None = None
    confidence: Confidence
    confirmed: bool
    # Weak evidence can never be confirmed; the person must restate it first.
    confirmable: bool
    statement_digest: Digest


class OnboardingResumePage(ContractModel):
    page_number: int
    text: str


class OnboardingResume(ContractModel):
    resume_id: ResumeId
    source_name: NonEmptyString
    pages: list[OnboardingResumePage]
    warnings: list[str] = Field(default_factory=list)
    # imported: facts from this resume are stored. waiting_host: the extraction
    # request is with the host agent. output_ready: the host wrote its answer and
    # it can be checked and imported. not_requested: parsed, nothing asked yet.
    extraction: Literal["imported", "waiting_host", "output_ready", "not_requested"]
    request_id: str | None = None


class OnboardingQuestion(ContractModel):
    question_id: NonEmptyString
    gap_id: NonEmptyString
    # The person reads `text`; `stored_text` is the recorded interview question.
    text: NonEmptyString
    stored_text: NonEmptyString
    asked_at: AwareDatetime


class OnboardingGap(ContractModel):
    gap_id: NonEmptyString
    label: NonEmptyString
    priority: str


class OnboardingConfiguration(ContractModel):
    status: Literal["initialized", "not_initialized", "unknown"]
    rules_version: str | None = None


class OnboardingState(ContractModel):
    protocol_version: Literal["1.0"] = "1.0"
    candidate_id: CandidateId
    source: Literal["complete", "missing", "unavailable"]
    message: str | None = None
    stage: Literal["not_started", "collecting", "ready", "unknown"]
    resumes: list[OnboardingResume] = Field(default_factory=list)
    experiences: list[Experience] = Field(default_factory=list)
    facts: list[OnboardingFact] = Field(default_factory=list)
    open_question: OnboardingQuestion | None = None
    answered_count: int = 0
    skipped_count: int = 0
    gaps: list[OnboardingGap] = Field(default_factory=list)
    readiness: CandidateStatus | None = None
    configuration: OnboardingConfiguration = Field(
        default_factory=lambda: OnboardingConfiguration(status="unknown")
    )
