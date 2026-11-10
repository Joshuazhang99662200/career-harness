"""First use in the conversation: start, ask, answer, restate and confirm through the CLI."""

import json
from pathlib import Path

from typer.testing import CliRunner

from jobagent.cli.app import app

CANDIDATE = "CAND_SYNTHETIC"
runner = CliRunner()


def invoke(database: Path, *args: str) -> tuple[int, dict]:
    result = runner.invoke(app, [*args, "--database", str(database)])
    return result.exit_code, json.loads(result.stdout) if result.stdout.strip() else {}


def state(database: Path) -> dict:
    return invoke(database, "console", "onboarding", "--candidate", CANDIDATE)[1]


def test_start_creates_an_empty_profile_once_and_reuses_it(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    assert state(database)["stage"] == "not_started" and not database.exists()
    code, started = invoke(database, "candidate", "start", CANDIDATE)
    assert code == 0 and started == {"candidate_id": CANDIDATE, "created": True}
    invoke(database, "candidate", "question", CANDIDATE)
    code, again = invoke(database, "candidate", "start", CANDIDATE)
    assert code == 0 and again["created"] is False
    assert state(database)["open_question"] is not None  # nothing was reset


def test_answer_then_confirm_only_the_wording_that_was_shown(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    invoke(database, "candidate", "start", CANDIDATE)
    _, question = invoke(database, "candidate", "question", CANDIDATE)
    invoke(
        database,
        "candidate",
        "answer",
        CANDIDATE,
        question["id"],
        "--answer",
        "我在合成项目里搭过评测集。",
    )
    [fact] = state(database)["facts"]
    assert fact["source_type"] == "interview" and fact["confirmed"] is False
    shown = fact["statement_digest"]

    code, revised = invoke(
        database,
        "candidate",
        "revise",
        CANDIDATE,
        fact["evidence_id"],
        "--statement",
        "我在合成项目里搭过 300 条用例的评测集。",
        "--statement-digest",
        shown,
    )
    assert code == 0 and revised["source"]["type"] == "user_edit"
    assert revised["user_confirmed"] is False

    code, stale = invoke(
        database,
        "candidate",
        "confirm",
        CANDIDATE,
        fact["evidence_id"],
        "--statement-digest",
        shown,
    )
    assert code == 1 and stale["error"]["code"] == "STALE_APPROVAL"

    [current] = state(database)["facts"]
    code, confirmed = invoke(
        database,
        "candidate",
        "confirm",
        CANDIDATE,
        current["evidence_id"],
        "--statement-digest",
        current["statement_digest"],
    )
    assert code == 0 and confirmed["user_confirmed"] is True
    after = state(database)
    assert after["stage"] == "ready"
    assert after["readiness"]["readiness"]["confirmed_evidence_count"] == 1


def test_revise_refuses_an_empty_statement(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    invoke(database, "candidate", "start", CANDIDATE)
    _, question = invoke(database, "candidate", "question", CANDIDATE)
    invoke(database, "candidate", "answer", CANDIDATE, question["id"], "--answer", "做过评测。")
    [fact] = state(database)["facts"]
    code, _ = invoke(
        database,
        "candidate",
        "revise",
        CANDIDATE,
        fact["evidence_id"],
        "--statement",
        "  ",
        "--statement-digest",
        fact["statement_digest"],
    )
    assert code == 1
