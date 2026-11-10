"""Thin Candidate Core CLI commands."""

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Never

import typer
from pydantic import ValidationError

from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.candidate.interview_session import ask_follow_up, ask_next, record_answer
from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.capabilities import ReasoningProvider
from jobagent.cli.private_io import fail
from jobagent.errors import AgentHandoffRequiredError, ContractValidationError, JobAgentError
from jobagent.parsing.pdf_resume import PdfResumeParser
from jobagent.reasoning.candidate_extractor import ReasoningCandidateDraftExtractor
from jobagent.reasoning.claude import ClaudeReasoningProvider
from jobagent.reasoning.handoff import AgentHandoffProvider
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    InterviewAnswer,
    MetricFact,
)
from jobagent.schemas.common import ContractModel
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database

DEFAULT_DATABASE = Path(".jobagent/jobagent.sqlite3")
DEFAULT_HANDOFF_DIR = Path(".jobagent/handoff")
AGENT_PROVIDER = "agent"
CLAUDE_PROVIDER = "claude"
DatabaseOption = Annotated[Path, typer.Option("--database", help="Local SQLite database path.")]

candidate_app = typer.Typer(help="Build and review the local candidate knowledge base.")


def _repository(path: Path) -> SqliteCandidateRepository:
    path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(path)
    database.migrate()
    return SqliteCandidateRepository(database)


def _emit(value: ContractModel | None) -> None:
    typer.echo("null" if value is None else value.model_dump_json(indent=2))


def _input_error(message: str) -> Never:
    fail(ContractValidationError(message))


def _parse_metric(raw: str) -> MetricFact:
    parts = [part.strip() for part in raw.split("|")]
    if len(parts) != 3 or not all(parts):
        _input_error("A --metric must be written as 'name|value|unit'.")
    try:
        return MetricFact(name=parts[0], value=Decimal(parts[1]), unit=parts[2])
    except (InvalidOperation, ValidationError):
        _input_error("A --metric value must be a number.")


def _emit_handoff(handoff: AgentHandoffRequiredError) -> None:
    """Report a delegated reasoning step. A handoff is a pause, not a failure."""
    typer.echo(
        json.dumps(
            {
                "handoff": {
                    "code": handoff.code,
                    "message": handoff.message,
                    "details": handoff.details,
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _reasoning_provider(
    name: str, handoff_dir: Path, effort: str, database: Path
) -> ReasoningProvider:
    if name == AGENT_PROVIDER:
        # The host replays resume_argv as is, so it must name the database used here.
        return AgentHandoffProvider(
            handoff_dir,
            resume_argv=[
                "jobagent", "candidate", "import-draft", "{output_path}",
                "--database", str(database),
            ],
        )
    if name == CLAUDE_PROVIDER:
        return ClaudeReasoningProvider(effort=effort)  # type: ignore[arg-type]
    raise ContractValidationError(
        "Unknown reasoning provider.",
        details={"provider": name, "known": [AGENT_PROVIDER, CLAUDE_PROVIDER]},
    )


def _required_profile(
    repository: SqliteCandidateRepository,
    candidate_id: str,
) -> CandidateProfile:
    profile = repository.get_profile(candidate_id)
    if profile is None:
        raise ContractValidationError(
            "Candidate profile was not found.",
            details={"candidate_id": candidate_id},
        )
    return profile


@candidate_app.command("ingest")
def ingest(
    candidate_id: str,
    resume_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Parse and store a local PDF source without interpreting its claims."""
    try:
        repository = _repository(database)
        if repository.get_profile(candidate_id) is None:
            repository.save_profile(CandidateProfile(id=candidate_id))
        parsed = PdfResumeParser().parse(resume_path, candidate_id)
        repository.save_resume(parsed)
        _emit(parsed)
    except JobAgentError as error:
        fail(error)


@candidate_app.command("onboard")
def onboard(
    candidate_id: str,
    resume_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
    provider_name: Annotated[str, typer.Option("--provider")] = AGENT_PROVIDER,
    handoff_dir: Annotated[Path, typer.Option("--handoff-dir")] = DEFAULT_HANDOFF_DIR,
    effort: Annotated[str, typer.Option("--effort")] = "high",
) -> None:
    """Parse a PDF and turn it into a structured draft.

    Default `--provider agent` needs no credentials: it emits a typed reasoning
    request for the calling coding agent to satisfy. `--provider claude` calls the
    Claude API instead, for headless runs.

    Either way the extracted evidence stays unconfirmed; promoting it to canonical
    evidence still requires an explicit `candidate confirm` per evidence ID.
    """
    try:
        repository = _repository(database)
        if repository.get_profile(candidate_id) is None:
            repository.save_profile(CandidateProfile(id=candidate_id))
        # Parsing is deterministic, so the resume and its page provenance are
        # persisted before the reasoning step. A handoff pauses the workflow, and
        # the evidence the agent writes back must have a resume row to cite.
        parsed = PdfResumeParser().parse(resume_path, candidate_id)
        repository.save_resume(parsed)
        extractor = ReasoningCandidateDraftExtractor(
            _reasoning_provider(provider_name, handoff_dir, effort, database)
        )
        draft = extractor.extract(parsed)
        repository.save_draft(draft)
        _emit(draft)
    except AgentHandoffRequiredError as handoff:
        _emit_handoff(handoff)
    except JobAgentError as error:
        fail(error)


@candidate_app.command("import-draft")
def import_draft(
    draft_path: Path,
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Import a reviewed structured draft; all evidence remains unconfirmed."""
    try:
        draft = CandidateDraft.model_validate_json(draft_path.read_text(encoding="utf-8"))
        _repository(database).save_draft(draft)
        _emit(draft)
    except (OSError, ValidationError) as error:
        _input_error(f"Candidate draft could not be loaded: {type(error).__name__}.")
    except JobAgentError as error:
        fail(error)


@candidate_app.command("question")
def question(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    target_role: Annotated[str | None, typer.Option("--target-role")] = None,
) -> None:
    """Select and record at most one adaptive interview question."""
    try:
        _emit(
            ask_next(
                _repository(database),
                candidate_id,
                now=datetime.now(UTC),
                target_role=target_role,
            )
        )
    except JobAgentError as error:
        fail(error)


@candidate_app.command("ask")
def ask(
    candidate_id: str,
    text: Annotated[str, typer.Option("--text", help="The exact question the agent asks.")],
    database: DatabaseOption = DEFAULT_DATABASE,
    about: Annotated[
        str | None, typer.Option("--about", help="EVID_... the follow-up digs into.")
    ] = None,
) -> None:
    """Save the agent's own follow-up question verbatim; answer it with `candidate answer`."""
    try:
        _emit(
            ask_follow_up(
                _repository(database), candidate_id, text, now=datetime.now(UTC), about=about
            )
        )
    except JobAgentError as error:
        fail(error)


@candidate_app.command("answer")
def answer(
    candidate_id: str,
    question_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    answer_text: Annotated[str | None, typer.Option("--answer")] = None,
    skip: Annotated[bool, typer.Option("--skip")] = False,
    metric: Annotated[
        list[str] | None,
        typer.Option(
            "--metric",
            help="A number stated in the answer, as 'name|value|unit'. Repeatable.",
        ),
    ] = None,
) -> None:
    """Record an answer or skip and create only draft evidence."""
    if skip == (answer_text is not None):
        _input_error("Provide exactly one of --answer or --skip.")
    metrics = [_parse_metric(raw) for raw in metric or []]
    try:
        interview_answer = InterviewAnswer(
            question_id=question_id,
            answer=answer_text,
            skipped=skip,
            metrics=metrics,
        )
        outcome = record_answer(
            _repository(database), candidate_id, interview_answer, now=datetime.now(UTC)
        )
        _emit(outcome)
    except (JobAgentError, ValidationError) as error:
        if isinstance(error, JobAgentError):
            fail(error)
        _input_error("Interview answer is invalid.")


DigestOption = Annotated[
    str | None,
    typer.Option(
        "--statement-digest",
        help="statement_digest of the fact as shown to the person (console onboarding); "
        "refused if the fact has changed since.",
    ),
]


@candidate_app.command("start")
def start(candidate_id: str, database: DatabaseOption = DEFAULT_DATABASE) -> None:
    """Begin first use without a resume. An existing profile is reused, never reset."""
    try:
        repository = _repository(database)
        created = repository.get_profile(candidate_id) is None
        if created:
            repository.save_profile(CandidateProfile(id=candidate_id))
        typer.echo(json.dumps({"candidate_id": candidate_id, "created": created}))
    except (JobAgentError, ValidationError) as error:
        if isinstance(error, JobAgentError):
            fail(error)
        _input_error("Candidate ID is invalid.")


@candidate_app.command("confirm")
def confirm(
    candidate_id: str,
    evidence_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    statement_digest: DigestOption = None,
) -> None:
    """Explicitly confirm one admissible evidence item."""
    try:
        confirmed = CandidateEvidenceService(_repository(database)).confirm(
            candidate_id,
            evidence_id,
            expected_digest=statement_digest,
        )
        _emit(confirmed)
    except JobAgentError as error:
        fail(error)


@candidate_app.command("confirm-many")
def confirm_many(
    candidate_id: str,
    item: Annotated[
        list[str],
        typer.Option(
            "--item",
            help="EVID_...=statement_digest of one fact the person confirmed as shown. "
            "Repeat per fact; if any item is stale, missing or weak, none is confirmed.",
        ),
    ],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Confirm a whole table of facts the person approved, all or nothing."""
    shown: list[tuple[str, str]] = []
    for raw in item:
        evidence_id, separator, digest = raw.partition("=")
        if not separator or not evidence_id or not digest:
            _input_error("Each --item must be written as 'EVID_...=sha256:...'.")
        shown.append((evidence_id.strip(), digest.strip()))
    try:
        confirmed = CandidateEvidenceService(_repository(database)).confirm_shown(
            candidate_id, shown
        )
        typer.echo(
            json.dumps(
                {"confirmed": [evidence.model_dump(mode="json") for evidence in confirmed]},
                ensure_ascii=False,
                indent=2,
            )
        )
    except JobAgentError as error:
        fail(error)


@candidate_app.command("resolve-unknown")
def resolve_unknown(
    candidate_id: str,
    path: Annotated[str, typer.Argument(help="unknown_fields path the person has answered.")],
    database: DatabaseOption = DEFAULT_DATABASE,
) -> None:
    """Clear one unknown left by extraction once the person has answered or skipped it.

    Only the profile's open-question list changes; no evidence is created or confirmed.
    """
    try:
        repository = _repository(database)
        profile = _required_profile(repository, candidate_id)
        remaining = [field for field in profile.unknown_fields if field.path != path]
        if len(remaining) == len(profile.unknown_fields):
            raise ContractValidationError(
                "That unknown field is not on the profile.",
                details={"candidate_id": candidate_id, "path": path},
            )
        updated = CandidateProfile.model_validate(
            {**profile.model_dump(mode="python"), "unknown_fields": remaining}
        )
        repository.save_profile(updated)
        _emit(updated)
    except JobAgentError as error:
        fail(error)


@candidate_app.command("revise")
def revise(
    candidate_id: str,
    evidence_id: str,
    statement: Annotated[str, typer.Option("--statement", help="The person's own wording.")],
    database: DatabaseOption = DEFAULT_DATABASE,
    statement_digest: DigestOption = None,
) -> None:
    """Replace a fact's wording with the person's correction; it must be confirmed again."""
    try:
        _emit(
            CandidateEvidenceService(_repository(database)).replace_with_user_edit(
                candidate_id, evidence_id, statement, expected_digest=statement_digest
            )
        )
    except JobAgentError as error:
        fail(error)


@candidate_app.command("status")
def status(
    candidate_id: str,
    database: DatabaseOption = DEFAULT_DATABASE,
    target_role: Annotated[str | None, typer.Option("--target-role")] = None,
) -> None:
    """Report profile completeness, gaps, and evidence readiness."""
    try:
        repository = _repository(database)
        profile = _required_profile(repository, candidate_id)
        result = CandidateReadinessService().evaluate(
            profile,
            repository.list_evidence(candidate_id),
            target_role=target_role,
        )
        _emit(result)
    except JobAgentError as error:
        fail(error)

