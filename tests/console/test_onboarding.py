"""First-use state read back from Candidate Core while the conversation drives the steps."""

import json
from pathlib import Path

from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.console.onboarding import onboarding_state
from jobagent.schemas.candidate import (
    CandidateDraft,
    CandidateProfile,
    Confidence,
    EvidenceItem,
    EvidenceType,
    Experience,
)
from jobagent.schemas.common import SourceReference, SourceType, TimeRange

CANDIDATE = "CAND_SYNTHETIC"
runner = CliRunner()


def private_db(tmp_path: Path) -> Path:
    return tmp_path / ".jobagent" / "jobagent.sqlite3"


def cli(*args: str) -> dict:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_reading_a_new_user_creates_nothing(tmp_path):
    database = private_db(tmp_path)
    state = onboarding_state(database, CANDIDATE)
    assert (state.source, state.stage) == ("missing", "not_started")
    assert not database.exists() and not database.parent.exists()
    read = cli("console", "onboarding", "--candidate", CANDIDATE, "--database", str(database))
    assert read["stage"] == "not_started" and not database.exists()


def test_broken_source_is_unavailable_not_empty(tmp_path):
    database = private_db(tmp_path)
    database.parent.mkdir()
    database.write_bytes(b"not a database")
    state = onboarding_state(database, CANDIDATE)
    assert (state.source, state.stage) == ("unavailable", "unknown")


def test_resume_handoff_is_visible_until_the_host_draft_is_imported(tmp_path):
    database = private_db(tmp_path)
    pdf = tmp_path / "synthetic.pdf"
    canvas = Canvas(str(pdf))
    canvas.drawString(72, 720, "Synthetic Person - built an evaluation set")
    canvas.save()
    handoff = database.parent / "handoff"
    paused = cli(
        "candidate",
        "onboard",
        CANDIDATE,
        str(pdf),
        "--database",
        str(database),
        "--handoff-dir",
        str(handoff),
    )
    request = json.loads(Path(paused["handoff"]["details"]["request_path"]).read_text())
    [resume] = onboarding_state(database, CANDIDATE).resumes
    assert resume.extraction == "waiting_host" and "Synthetic Person" in resume.pages[0].text

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
        ),
        evidence=[
            EvidenceItem(
                id="EVID_ONE",
                type=EvidenceType.EXPERIENCE,
                statement="Built an evaluation set for a synthetic QA product.",
                source=SourceReference(
                    type=SourceType.RESUME, reference=f"{resume.resume_id}:page:1"
                ),
                confidence=Confidence.EXPLICIT,
            )
        ],
    )
    Path(request["output_path"]).write_text(draft.model_dump_json(), encoding="utf-8")
    assert onboarding_state(database, CANDIDATE).resumes[0].extraction == "output_ready"

    cli("candidate", "import-draft", request["output_path"], "--database", str(database))
    state = onboarding_state(database, CANDIDATE)
    [fact] = state.facts
    assert state.resumes[0].extraction == "imported" and state.stage == "collecting"
    assert (fact.resume_page, fact.confirmed, fact.confirmable) == (1, False, True)
    assert state.experiences[0].company == "Synthetic Co"


def test_the_open_question_is_shown_in_plain_chinese(tmp_path):
    database = private_db(tmp_path)
    cli("candidate", "start", CANDIDATE, "--database", str(database))
    cli("candidate", "question", CANDIDATE, "--database", str(database))
    question = onboarding_state(database, CANDIDATE).open_question
    assert question is not None and question.gap_id == "GAP_EXPERIENCE"
    assert "工作或项目" in question.text and question.stored_text != question.text
    cli(
        "candidate",
        "answer",
        CANDIDATE,
        question.question_id,
        "--skip",
        "--database",
        str(database),
    )
    state = onboarding_state(database, CANDIDATE)
    assert state.open_question is None and state.skipped_count == 1 and state.facts == []
