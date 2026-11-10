# ruff: noqa: RUF001  -- The person reads these Chinese prompts with full-width punctuation.
"""First-use onboarding state, read back from Candidate Core.

First use happens in the conversation: the host agent asks one question at a
time and records answers and confirmations through the `candidate` commands.
This read model lets the agent and the console see where it stands. Reading
never creates or migrates a file; a missing source is "missing" and a broken
one "unavailable", never an empty profile.
"""

import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from jobagent.candidate.evidence import statement_digest
from jobagent.candidate.gaps import GapDetector
from jobagent.candidate.interview_session import open_question
from jobagent.candidate.readiness import CandidateReadinessService
from jobagent.errors import (
    JobAgentError,
    StorageError,
)
from jobagent.reasoning.candidate_extractor import PROMPT_ID
from jobagent.schemas.candidate import (
    CandidateGap,
    CandidateId,
    Confidence,
    EvidenceItem,
    InterviewEventType,
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

_RESUME_SOURCE = re.compile(r"^(RESUME_[A-Z0-9_]+):page:(\d+)$")

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


def _read(database: Path, candidate_id: str) -> OnboardingState:
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


def onboarding_state(database: Path, candidate_id: str) -> OnboardingState:
    """Read the person's onboarding progress; a missing or broken source is never "empty"."""
    candidate_id = TypeAdapter(CandidateId).validate_python(candidate_id)
    if not database.exists():
        return OnboardingState(
            candidate_id=candidate_id,
            source="missing",
            message="还没有本人资料记录；读取时未创建任何文件。",
            stage="not_started",
        )
    try:
        return _read(database, candidate_id)
    except (JobAgentError, sqlite3.Error, ValidationError, OSError, ValueError):
        return OnboardingState(
            candidate_id=candidate_id,
            source="unavailable",
            message="本人资料记录读取失败，未当作空资料处理。",
            stage="unknown",
        )
