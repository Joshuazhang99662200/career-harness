"""First-use onboarding: read back from Candidate Core, confirm only the exact fact shown."""

import json
from pathlib import Path

import pytest
from reportlab.pdfgen.canvas import Canvas

from jobagent.console.onboarding import OnboardingWriter, onboarding_state
from jobagent.errors import ContractValidationError, PolicyRejectionError, StaleApprovalError
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
    Skill,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange

CANDIDATE = "CAND_SYNTHETIC"


def pdf_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "synthetic.pdf"
    canvas = Canvas(str(path))
    canvas.drawString(72, 720, "Synthetic Person - built an evaluation set")
    canvas.save()
    return path.read_bytes()


def private_db(tmp_path: Path) -> Path:
    return tmp_path / ".jobagent" / "jobagent.sqlite3"


def write_host_output(database: Path, state, *, weak: bool = False) -> str:
    """Play the host agent: answer the extraction request with a synthetic draft."""
    [resume] = state.resumes
    folder = database.parent / "handoff" / str(resume.request_id)
    request = json.loads(next(folder.glob("*.request.json")).read_text())
    draft = CandidateDraft(
        candidate_id=CANDIDATE,
        profile=CandidateProfile(
            id=CANDIDATE,
            experiences=[
                Experience(
                    id="EXP_1",
                    company="Synthetic Co",
                    title="Analyst",
                    time_range=TimeRange(),
                    evidence_ids=["EVID_ONE"],
                )
            ],
            skills=[Skill(name="Evaluation", evidence_ids=["EVID_ONE"])],
        ),
        evidence=[
            EvidenceItem(
                id="EVID_ONE",
                type=EvidenceType.EXPERIENCE,
                statement="Built an evaluation set for a synthetic QA product.",
                source=SourceReference(
                    type=SourceType.RESUME, reference=f"{resume.resume_id}:page:1"
                ),
                confidence=Confidence.WEAK if weak else Confidence.EXPLICIT,
            )
        ],
    )
    Path(request["output_path"]).write_text(draft.model_dump_json(), encoding="utf-8")
    return str(resume.request_id)


def test_reading_a_new_user_creates_nothing(tmp_path):
    database = private_db(tmp_path)
    state = onboarding_state(database, CANDIDATE)
    assert (state.source, state.stage, state.writable) == ("missing", "not_started", False)
    assert not database.exists() and not database.parent.exists()


def test_broken_source_is_unavailable_not_empty(tmp_path):
    database = private_db(tmp_path)
    database.parent.mkdir()
    database.write_bytes(b"not a database")
    state = onboarding_state(database, CANDIDATE)
    assert (state.source, state.stage) == ("unavailable", "unknown")


def test_start_is_idempotent_and_reuses_an_existing_profile(tmp_path):
    writer = OnboardingWriter(private_db(tmp_path), CANDIDATE)
    first = writer.start()
    assert (first.source, first.stage, first.writable) == ("complete", "collecting", True)
    assert [gap.gap_id for gap in first.gaps][:2] == ["GAP_EXPERIENCE", "GAP_SKILLS"]
    assert first.configuration.status == "not_initialized"
    asked = writer.ask()
    again = writer.start()
    assert again.open_question == asked.open_question  # nothing reset


def test_resume_goes_to_the_host_and_its_draft_stays_unconfirmed(tmp_path):
    database = private_db(tmp_path)
    writer = OnboardingWriter(database, CANDIDATE)
    with pytest.raises(ContractValidationError):
        writer.add_resume(pdf_bytes(tmp_path), "resume.pdf")  # not started yet
    writer.start()
    with pytest.raises(ContractValidationError):
        writer.add_resume(b"plain text", "resume.txt")
    state = writer.add_resume(pdf_bytes(tmp_path), "C:\\fake\\我的简历.pdf")
    [resume] = state.resumes
    assert resume.source_name == "我的简历.pdf" and resume.extraction == "waiting_host"
    assert "Synthetic Person" in resume.pages[0].text
    folder = database.parent / "handoff" / str(resume.request_id)
    request = json.loads(next(folder.glob("*.request.json")).read_text())
    assert request["resume_argv"][-2:] == ["--database", str(database)]
    # A second upload of the same file does not open a second request.
    assert writer.add_resume(pdf_bytes(tmp_path), "again.pdf").resumes[0].request_id == (
        resume.request_id
    )
    with pytest.raises(ContractValidationError, match="not written"):
        writer.import_extraction(str(resume.request_id))

    write_host_output(database, state)
    assert writer.state().resumes[0].extraction == "output_ready"
    imported = writer.import_extraction(str(resume.request_id))
    [fact] = imported.facts
    assert imported.resumes[0].extraction == "imported"
    assert (fact.resume_page, fact.confirmed, fact.confirmable) == (1, False, True)
    assert imported.experiences[0].company == "Synthetic Co"
    assert imported.stage == "collecting"


def test_confirm_binds_the_exact_statement_and_edits_restart_confirmation(tmp_path):
    writer = OnboardingWriter(private_db(tmp_path), CANDIDATE)
    writer.start()
    state = writer.add_resume(pdf_bytes(tmp_path), "resume.pdf")
    request_id = write_host_output(private_db(tmp_path), state)
    [fact] = writer.import_extraction(request_id).facts

    edited = writer.edit(
        fact.evidence_id, fact.statement_digest, "Built a 300-case evaluation set."
    )
    [changed] = edited.facts
    assert changed.source_type == "user_edit" and not changed.confirmed
    with pytest.raises(StaleApprovalError):
        writer.confirm(fact.evidence_id, fact.statement_digest)  # old wording
    confirmed = writer.confirm(changed.evidence_id, changed.statement_digest)
    assert confirmed.facts[0].confirmed and confirmed.stage == "ready"
    assert confirmed.readiness is not None
    assert confirmed.readiness.readiness.confirmed_evidence_count == 1
    # Readback after a fresh read is identical: nothing lived only in memory.
    assert onboarding_state(private_db(tmp_path), CANDIDATE, writable=True) == confirmed


def test_weak_facts_cannot_be_confirmed(tmp_path):
    writer = OnboardingWriter(private_db(tmp_path), CANDIDATE)
    writer.start()
    state = writer.add_resume(pdf_bytes(tmp_path), "resume.pdf")
    request_id = write_host_output(private_db(tmp_path), state, weak=True)
    [fact] = writer.import_extraction(request_id).facts
    assert not fact.confirmable
    with pytest.raises(PolicyRejectionError):
        writer.confirm(fact.evidence_id, fact.statement_digest)


def test_interview_asks_one_question_at_a_time_and_skip_keeps_unknown(tmp_path):
    writer = OnboardingWriter(private_db(tmp_path), CANDIDATE)
    writer.start()
    asked = writer.ask()
    question = asked.open_question
    assert question is not None and question.gap_id == "GAP_EXPERIENCE"
    assert "工作或项目" in question.text and question.stored_text != question.text
    assert writer.ask().open_question == question  # still the same open question

    skipped = writer.answer(question.question_id, None, skip=True)
    assert skipped.open_question is None and skipped.skipped_count == 1 and skipped.facts == []
    with pytest.raises(StaleApprovalError):
        writer.answer(question.question_id, "late answer", skip=False)

    following = writer.ask().open_question
    assert following is not None and following.gap_id != "GAP_EXPERIENCE"
    answered = writer.answer(
        following.question_id, "Python and SQL in a synthetic job.", skip=False
    )
    [fact] = answered.facts
    assert fact.source_type == "interview" and not fact.confirmed
    assert answered.answered_count == 1 and answered.stage == "collecting"


def test_onboarding_writes_refuse_a_database_outside_private_directories(tmp_path):
    with pytest.raises(ContractValidationError, match="private"):
        OnboardingWriter(tmp_path / "jobagent.sqlite3", CANDIDATE)


def test_cli_reads_onboarding_without_creating_the_database(tmp_path):
    from typer.testing import CliRunner

    from jobagent.cli.app import app

    database = private_db(tmp_path)
    result = CliRunner().invoke(
        app, ["console", "onboarding", "--candidate", CANDIDATE, "--database", str(database)]
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["stage"] == "not_started" and not database.exists()
