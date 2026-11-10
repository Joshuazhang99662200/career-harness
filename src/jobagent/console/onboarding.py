# ruff: noqa: RUF001  -- The person reads these Chinese prompts with full-width punctuation.
"""First-use onboarding over Candidate Core: one read-back projection and the panel's writes.

Reading never creates a file. Every write goes through the existing Candidate
Core services and returns the state read back from storage afterwards, so the
panel only ever shows what was saved. Resume extraction is delegated to the
host agent through the standard reasoning handoff; confirming a fact still
goes through `CandidateEvidenceService.confirm`, one evidence item at a time,
bound to the exact statement the person saw.
"""

import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from jobagent.candidate.evidence import CandidateEvidenceService
from jobagent.candidate.gaps import GapDetector
from jobagent.candidate.interview_session import ask_next, open_question, record_answer
from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.capabilities import ReasoningOutputT
from jobagent.digest import bytes_digest, canonical_digest
from jobagent.errors import (
    AgentHandoffRequiredError,
    ContractValidationError,
    JobAgentError,
    MissingEvidenceError,
    StaleApprovalError,
    StorageError,
)
from jobagent.parsing.pdf_resume import PdfResumeParser
from jobagent.reasoning.candidate_extractor import PROMPT_ID, ReasoningCandidateDraftExtractor
from jobagent.reasoning.handoff import AgentHandoffProvider
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateGap,
    CandidateId,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    InterviewAnswer,
    InterviewEventType,
    ParsedResume,
)
from jobagent.schemas.onboarding import (
    OnboardingConfiguration,
    OnboardingFact,
    OnboardingGap,
    OnboardingQuestion,
    OnboardingResume,
    OnboardingResumePage,
    OnboardingState,
)
from jobagent.schemas.reasoning import ReasoningHandoffRequest
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import LATEST_SCHEMA_VERSION, Database

MAX_RESUME_BYTES = 10 * 1024 * 1024
_RESUME_SOURCE = re.compile(r"^(RESUME_[A-Z0-9_]+):page:(\d+)$")
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")

_GAP_PROMPTS = {
    "GAP_EXPERIENCE": (
        "还没有工作或项目经历",
        "最近哪一段工作或项目最能代表你想找的方向？说说你负责什么、做成了什么。",
    ),
    "GAP_SKILLS": (
        "还没有能对应到经历的技能",
        "你在真实工作或项目里实际用过哪些技能？可以举一个用到它的例子。",
    ),
    "GAP_FULL_NAME": ("姓名未填写", "投递材料上应写的姓名是什么？"),
}


class _ReadOnlyDatabase(Database):
    """Open an existing file read-only so a panel read can never create or migrate it."""

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
        except sqlite3.Error as error:
            raise StorageError(
                "Could not open SQLite database read-only.", details={"operation": "connect"}
            ) from error
        try:
            yield connection
        finally:
            connection.close()


def handoff_directory(database: Path) -> Path:
    return database.parent / "handoff"


def statement_digest(evidence: EvidenceItem) -> str:
    """Everything the person reads about a fact, without its confirmation flag."""
    return canonical_digest(evidence.model_dump(mode="json", exclude={"user_confirmed"}))


def _fact(evidence: EvidenceItem) -> OnboardingFact:
    match = _RESUME_SOURCE.fullmatch(evidence.source.reference)
    return OnboardingFact(
        evidence_id=evidence.id,
        type=evidence.type,
        statement=evidence.statement,
        entity=evidence.entity,
        skills=evidence.skills,
        metrics=evidence.metrics,
        source_type=evidence.source.type,
        source_reference=evidence.source.reference,
        resume_id=match.group(1) if match else None,
        resume_page=int(match.group(2)) if match else None,
        confidence=evidence.confidence,
        confirmed=evidence.user_confirmed,
        confirmable=evidence.confidence is not Confidence.WEAK,
        statement_digest=statement_digest(evidence),
    )


def _handoffs(directory: Path, candidate_id: str) -> dict[str, tuple[str, bool]]:
    """Latest extraction request per resume: resume_id -> (request_id, output written)."""
    found: dict[str, tuple[float, str, bool]] = {}
    if not directory.is_dir():
        return {}
    for path in directory.glob(f"*/{PROMPT_ID}.request.json"):
        try:
            request = ReasoningHandoffRequest.model_validate_json(path.read_bytes())
        except (OSError, ValidationError):
            continue
        context = request.context
        if context.get("candidate_id") != candidate_id or not request.request_id:
            continue
        resume_id = str(context.get("resume_id", ""))
        stamp = path.stat().st_mtime
        if resume_id and (resume_id not in found or found[resume_id][0] < stamp):
            found[resume_id] = (stamp, request.request_id, Path(request.output_path).is_file())
    return {key: (value[1], value[2]) for key, value in found.items()}


def _gap(gap: CandidateGap, evidence: Mapping[str, EvidenceItem]) -> tuple[str, str]:
    if gap.id in _GAP_PROMPTS:
        return _GAP_PROMPTS[gap.id]
    item = evidence.get(gap.id.removeprefix("GAP_"))
    if item is not None:
        return f"待确认：{item.statement}", f"关于“{item.statement}”，能补充具体范围和结果吗？"
    return f"未知：{gap.field_path}", f"关于 {gap.field_path}，你能确认哪些情况？"


def _configuration(database: Database, candidate_id: str) -> OnboardingConfiguration:
    try:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT rules_version FROM configuration_initializations WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
    except (sqlite3.Error, StorageError):
        return OnboardingConfiguration(status="unknown")
    if row is None:
        return OnboardingConfiguration(status="not_initialized")
    return OnboardingConfiguration(status="initialized", rules_version=row["rules_version"])


def _schema_version(database: Database) -> int:
    with database.connect() as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _read(database: Path, candidate_id: str, writable: bool) -> OnboardingState:
    store = _ReadOnlyDatabase(database)
    version = _schema_version(store)
    if not 1 <= version <= LATEST_SCHEMA_VERSION:
        raise StorageError("Unsupported candidate schema.", details={"version": version})
    repository = SqliteCandidateRepository(store)
    configuration = _configuration(store, candidate_id)
    profile = repository.get_profile(candidate_id)
    if profile is None:
        return OnboardingState(
            candidate_id=candidate_id,
            source="complete",
            writable=writable,
            stage="not_started",
            configuration=configuration,
        )
    evidence = repository.list_evidence(candidate_id)
    by_id = {item.id: item for item in evidence}
    events = repository.list_interview_events(candidate_id)
    gaps = GapDetector().detect(profile, evidence)
    gaps_by_id = {gap.id: gap for gap in gaps}
    imported = {fact.resume_id for fact in map(_fact, evidence) if fact.resume_id}
    handoffs = _handoffs(handoff_directory(database), candidate_id)
    resumes = []
    for resume in repository.list_resumes(candidate_id):
        request_id, output_ready = handoffs.get(resume.id, (None, False))
        resumes.append(
            OnboardingResume(
                resume_id=resume.id,
                source_name=resume.source_name,
                pages=[
                    OnboardingResumePage(page_number=page.page_number, text=page.text)
                    for page in resume.pages
                ],
                warnings=resume.warnings,
                extraction=(
                    "imported"
                    if resume.id in imported
                    else "output_ready"
                    if output_ready
                    else "waiting_host"
                    if request_id
                    else "not_requested"
                ),
                request_id=request_id,
            )
        )
    current = open_question(events)
    question = None
    if current is not None:
        asked, event = current
        gap = gaps_by_id.get(asked.primary_gap_id)
        text = _gap(gap, by_id)[1] if gap is not None else asked.text
        question = OnboardingQuestion(
            question_id=asked.id,
            gap_id=asked.primary_gap_id,
            text=text,
            stored_text=asked.text,
            asked_at=event.created_at,
        )
    readiness = CandidateReadinessService().evaluate(profile, evidence)
    return OnboardingState(
        candidate_id=candidate_id,
        source="complete",
        writable=writable,
        stage="ready" if readiness.readiness.confirmed_evidence_count else "collecting",
        resumes=resumes,
        experiences=profile.experiences,
        facts=[_fact(item) for item in evidence],
        open_question=question,
        answered_count=sum(e.event_type is InterviewEventType.ANSWER for e in events),
        skipped_count=sum(e.event_type is InterviewEventType.SKIP for e in events),
        # Unconfirmed facts are listed as facts; the gap list keeps what is still unknown.
        gaps=[
            OnboardingGap(gap_id=gap.id, label=_gap(gap, by_id)[0], priority=gap.priority.value)
            for gap in gaps
            if gap.id.removeprefix("GAP_") not in by_id
        ],
        readiness=readiness,
        configuration=configuration,
    )


def onboarding_state(
    database: Path, candidate_id: str, *, writable: bool = False
) -> OnboardingState:
    """Read the person's onboarding progress; a missing or broken source is never "empty"."""
    candidate_id = TypeAdapter(CandidateId).validate_python(candidate_id)
    if not database.exists():
        return OnboardingState(
            candidate_id=candidate_id,
            source="missing",
            message="还没有本人资料记录；读取时未创建任何文件。",
            writable=writable,
            stage="not_started",
        )
    try:
        return _read(database, candidate_id, writable)
    except (JobAgentError, sqlite3.Error, ValidationError, OSError, ValueError):
        return OnboardingState(
            candidate_id=candidate_id,
            source="unavailable",
            message="本人资料记录读取失败，未当作空资料处理。",
            writable=writable,
            stage="unknown",
        )


class _StoredOutput:
    """Hand a host-written draft back to the extractor so its resume-binding checks run."""

    def __init__(self, draft: CandidateDraft) -> None:
        self._draft = draft

    def generate(
        self,
        *,
        prompt_id: str,
        context: Mapping[str, Any],
        output_type: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        if not isinstance(self._draft, output_type):
            raise ContractValidationError("Unexpected extraction contract.")
        return self._draft


class OnboardingWriter:
    """The panel's onboarding writes; each returns the state read back afterwards."""

    def __init__(self, database: Path, candidate_id: str) -> None:
        # The resume and its facts are personal data: keep them out of the repository.
        parts = [part.casefold() for part in database.expanduser().resolve().parts]
        if ".jobagent" not in parts and not any(
            parts[i : i + 2] == ["candidate", "private"] for i in range(len(parts) - 1)
        ):
            raise ContractValidationError("Onboarding data must stay in a private directory.")
        self.database = database
        self.candidate_id = TypeAdapter(CandidateId).validate_python(candidate_id)

    def _repository(self) -> SqliteCandidateRepository:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        database = Database(self.database)
        database.migrate()
        return SqliteCandidateRepository(database)

    def _profile(self, repository: SqliteCandidateRepository) -> CandidateProfile:
        profile = repository.get_profile(self.candidate_id)
        if profile is None:
            raise ContractValidationError(
                "Onboarding has not been started.", details={"candidate_id": self.candidate_id}
            )
        return profile

    def state(self) -> OnboardingState:
        return onboarding_state(self.database, self.candidate_id, writable=True)

    def start(self) -> OnboardingState:
        """Create an empty profile once; an existing profile is reused, never reset."""
        repository = self._repository()
        if repository.get_profile(self.candidate_id) is None:
            repository.save_profile(CandidateProfile(id=self.candidate_id))
        return self.state()

    def add_resume(self, content: bytes, source_name: str) -> OnboardingState:
        """Store and parse a PDF, then hand fact extraction to the host agent."""
        if not content.startswith(b"%PDF-") or len(content) > MAX_RESUME_BYTES:
            raise ContractValidationError(
                "Resume must be a PDF of at most 10 MB.", details={"bytes": len(content)}
            )
        repository = self._repository()
        self._profile(repository)
        uploads = self.database.parent / "onboarding" / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        stored = uploads / f"{bytes_digest(content).removeprefix('sha256:')}.pdf"
        if not stored.exists():
            stored.write_bytes(content)
        parsed = PdfResumeParser().parse(stored, self.candidate_id)
        name = re.split(r"[\\/]", source_name)[-1].strip()[:200] or stored.name
        resume = ParsedResume.model_validate({**parsed.model_dump(), "source_name": name})
        repository.save_resume(resume)
        if resume.id not in _handoffs(handoff_directory(self.database), self.candidate_id):
            provider = AgentHandoffProvider(
                handoff_directory(self.database),
                resume_argv=[
                    "jobagent",
                    "candidate",
                    "import-draft",
                    "{output_path}",
                    "--database",
                    str(self.database),
                ],
            )
            # Waiting on the host agent is the expected outcome, not a failure.
            with suppress(AgentHandoffRequiredError):
                ReasoningCandidateDraftExtractor(provider).extract(resume)
        return self.state()

    def import_extraction(self, request_id: str) -> OnboardingState:
        """Check the host's draft against the stored resume and save it, all unconfirmed."""
        if not _REQUEST_ID.fullmatch(request_id):
            raise ContractValidationError("Unknown extraction request.")
        folder = handoff_directory(self.database).resolve() / request_id
        try:
            request = ReasoningHandoffRequest.model_validate_json(
                (folder / f"{PROMPT_ID}.request.json").read_bytes()
            )
        except (OSError, ValidationError) as error:
            raise ContractValidationError("Unknown extraction request.") from error
        output = Path(request.output_path).resolve()
        if request.context.get("candidate_id") != self.candidate_id or output.parent != folder:
            raise ContractValidationError("Extraction request belongs elsewhere.")
        repository = self._repository()
        profile = self._profile(repository)
        resume = repository.get_resume(str(request.context.get("resume_id", "")))
        if resume is None or resume.candidate_id != self.candidate_id:
            raise ContractValidationError("Extraction request resume was not found.")
        if profile != CandidateProfile(id=self.candidate_id):
            # save_draft replaces the profile; merging resumes is not supported here.
            raise ContractValidationError(
                "The profile already holds material; merge another resume with the host."
            )
        try:
            draft = CandidateDraft.model_validate_json(output.read_bytes())
        except OSError as error:
            raise ContractValidationError("The host has not written the extraction yet.") from error
        except ValidationError as error:
            raise ContractValidationError(
                "The host extraction violates the draft contract."
            ) from error
        checked = ReasoningCandidateDraftExtractor(_StoredOutput(draft)).extract(resume)
        repository.save_draft(checked)
        return self.state()

    def ask(self) -> OnboardingState:
        """Ask one question; an unanswered question is shown again instead of a new one."""
        repository = self._repository()
        self._profile(repository)
        if open_question(repository.list_interview_events(self.candidate_id)) is None:
            ask_next(repository, self.candidate_id, now=datetime.now(UTC))
        return self.state()

    def answer(self, question_id: str, answer: str | None, *, skip: bool) -> OnboardingState:
        repository = self._repository()
        current = open_question(repository.list_interview_events(self.candidate_id))
        if current is None or current[0].id != question_id:
            raise StaleApprovalError(
                "That question is no longer the open one.", details={"question_id": question_id}
            )
        try:
            reply = InterviewAnswer(question_id=question_id, answer=answer, skipped=skip)
        except ValidationError as error:
            raise ContractValidationError("Provide an answer or skip the question.") from error
        record_answer(repository, self.candidate_id, reply, now=datetime.now(UTC))
        return self.state()

    def _current(
        self, repository: SqliteCandidateRepository, evidence_id: str, digest: str
    ) -> EvidenceItem:
        evidence = repository.get_evidence(self.candidate_id, evidence_id)
        if evidence is None:
            raise MissingEvidenceError(
                "Candidate evidence was not found.", details={"evidence_id": evidence_id}
            )
        if statement_digest(evidence) != digest:
            raise StaleApprovalError(
                "The fact changed after it was shown; read it again before confirming.",
                details={"evidence_id": evidence_id},
            )
        return evidence

    def confirm(self, evidence_id: str, digest: str) -> OnboardingState:
        """Promote exactly the statement the person saw, through the one confirm path."""
        repository = self._repository()
        self._current(repository, evidence_id, digest)
        CandidateEvidenceService(repository).confirm(self.candidate_id, evidence_id)
        return self.state()

    def edit(self, evidence_id: str, digest: str, statement: str) -> OnboardingState:
        """Replace the wording with the person's own; the new statement starts unconfirmed."""
        if not statement.strip():
            raise ContractValidationError("A corrected statement cannot be empty.")
        repository = self._repository()
        self._current(repository, evidence_id, digest)
        CandidateEvidenceService(repository).replace_with_user_edit(
            self.candidate_id, evidence_id, statement.strip()
        )
        return self.state()


def dumps(state: OnboardingState) -> bytes:
    return json.dumps(state.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
