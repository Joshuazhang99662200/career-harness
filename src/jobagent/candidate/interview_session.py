"""Interview steps over the candidate repository port, shared by the CLI and the panel."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from jobagent.candidate.gaps import GapDetector
from jobagent.candidate.interview import AdaptiveInterview
from jobagent.candidate.ports import CandidateRepository
from jobagent.errors import ContractValidationError
from jobagent.schemas.candidate import (
    InterviewAnswer,
    InterviewEvent,
    InterviewEventType,
    InterviewOutcome,
    InterviewQuestion,
)


def _question(event: InterviewEvent) -> InterviewQuestion:
    payload: Any = event.payload.get("question")
    try:
        return InterviewQuestion.model_validate(payload)
    except ValidationError as error:
        raise ContractValidationError(
            "Stored interview question is invalid.",
            details={"candidate_id": event.candidate_id, "question_id": event.question_id},
        ) from error


def open_question(
    events: Sequence[InterviewEvent],
) -> tuple[InterviewQuestion, InterviewEvent] | None:
    """The most recently asked question that has neither an answer nor a skip."""
    pending: dict[str, InterviewEvent] = {}
    for event in events:
        if event.question_id is None:
            continue
        if event.event_type is InterviewEventType.QUESTION:
            pending[event.question_id] = event
        else:
            pending.pop(event.question_id, None)
    if not pending:
        return None
    latest = max(pending.values(), key=lambda event: (event.created_at, event.id))
    return _question(latest), latest


def ask_next(
    repository: CandidateRepository,
    candidate_id: str,
    *,
    now: datetime,
    target_role: str | None = None,
) -> InterviewQuestion | None:
    """Select and record at most one question, avoiding gaps asked in the last five events."""
    profile = repository.get_profile(candidate_id)
    if profile is None:
        raise ContractValidationError(
            "Candidate profile was not found.", details={"candidate_id": candidate_id}
        )
    evidence = repository.list_evidence(candidate_id)
    gaps = GapDetector().detect(profile, evidence, target_role=target_role)
    events = repository.list_interview_events(candidate_id)
    recent_gap_ids = {
        str(event.payload["question"]["primary_gap_id"])
        for event in events[-5:]
        if event.event_type is InterviewEventType.QUESTION
        and isinstance(event.payload.get("question"), dict)
        and "primary_gap_id" in event.payload["question"]
    }
    selected = AdaptiveInterview().next_question(
        candidate_id, gaps, target_role=target_role, recent_gap_ids=recent_gap_ids
    )
    if selected is not None:
        repository.append_interview_event(
            InterviewEvent(
                id=f"EVENT_{uuid4().hex.upper()}",
                candidate_id=candidate_id,
                event_type=InterviewEventType.QUESTION,
                question_id=selected.id,
                payload={"question": selected.model_dump(mode="json")},
                created_at=now,
            )
        )
    return selected


def ask_follow_up(
    repository: CandidateRepository,
    candidate_id: str,
    text: str,
    *,
    now: datetime,
    about: str | None = None,
) -> InterviewQuestion:
    """Record the agent's own follow-up question word for word, one open question at a time.

    The answer then goes through record_answer like any interview answer: it becomes
    unconfirmed draft evidence, and a skip leaves the point unknown.
    """
    if repository.get_profile(candidate_id) is None:
        raise ContractValidationError(
            "Candidate profile was not found.", details={"candidate_id": candidate_id}
        )
    if not text.strip():
        raise ContractValidationError("A follow-up question cannot be empty.")
    events = repository.list_interview_events(candidate_id)
    if open_question(events) is not None:
        raise ContractValidationError(
            "Answer or skip the open question before asking another.",
            details={"candidate_id": candidate_id},
        )
    if about is not None and repository.get_evidence(candidate_id, about) is None:
        raise ContractValidationError(
            "The fact this follow-up is about was not found.", details={"evidence_id": about}
        )
    key = uuid4().hex[:16].upper()
    question = InterviewQuestion(
        id=f"QUESTION_FOLLOWUP_{key}",
        candidate_id=candidate_id,
        primary_gap_id=f"GAP_FOLLOWUP_{key}",
        text=text.strip(),
        reason=f"Agent follow-up on {about}." if about else "Agent follow-up.",
        expected_information="Verified detail for an experience",
        score=0.5,
    )
    repository.append_interview_event(
        InterviewEvent(
            id=f"EVENT_{uuid4().hex.upper()}",
            candidate_id=candidate_id,
            event_type=InterviewEventType.QUESTION,
            question_id=question.id,
            payload={"question": question.model_dump(mode="json")},
            created_at=now,
        )
    )
    return question


def find_question(
    repository: CandidateRepository, candidate_id: str, question_id: str
) -> InterviewQuestion:
    for event in reversed(repository.list_interview_events(candidate_id)):
        if event.event_type is InterviewEventType.QUESTION and event.question_id == question_id:
            return _question(event)
    raise ContractValidationError(
        "Interview question was not found.",
        details={"candidate_id": candidate_id, "question_id": question_id},
    )


def record_answer(
    repository: CandidateRepository,
    candidate_id: str,
    answer: InterviewAnswer,
    *,
    now: datetime,
) -> InterviewOutcome:
    """Store an answer as unconfirmed draft evidence, or a skip that leaves the gap unknown."""
    if repository.get_profile(candidate_id) is None:
        raise ContractValidationError(
            "Candidate profile was not found.", details={"candidate_id": candidate_id}
        )
    selected = find_question(repository, candidate_id, answer.question_id)
    outcome = AdaptiveInterview().record_answer(
        selected,
        answer,
        evidence_id=f"EVID_INTERVIEW_{uuid4().hex[:16].upper()}",
        event_id=f"EVENT_{uuid4().hex.upper()}",
        created_at=now,
    )
    repository.save_interview_outcome(outcome)
    return outcome
