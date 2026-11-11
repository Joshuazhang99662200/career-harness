# ruff: noqa: RUF001  -- Synthetic Chinese answers keep full-width punctuation.
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


def _two_facts(database: Path) -> list[dict]:
    invoke(database, "candidate", "start", CANDIDATE)
    for answer in ("做过合成评测集。", "带过两人的合成项目小组。"):
        _, question = invoke(database, "candidate", "question", CANDIDATE)
        invoke(database, "candidate", "answer", CANDIDATE, question["id"], "--answer", answer)
    return state(database)["facts"]


def test_confirm_many_promotes_every_shown_fact_in_one_call(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    facts = _two_facts(database)
    assert len(facts) == 2
    items = [x for f in facts for x in ("--item", f"{f['evidence_id']}={f['statement_digest']}")]
    code, confirmed = invoke(database, "candidate", "confirm-many", CANDIDATE, *items)
    assert code == 0 and [c["user_confirmed"] for c in confirmed["confirmed"]] == [True, True]
    assert all(f["confirmed"] for f in state(database)["facts"])


def test_confirm_many_is_all_or_nothing(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    first, second = _two_facts(database)
    code, failed = invoke(
        database,
        "candidate",
        "confirm-many",
        CANDIDATE,
        "--item",
        f"{first['evidence_id']}={first['statement_digest']}",
        "--item",
        f"{second['evidence_id']}=sha256:not-what-was-shown",
    )
    assert code == 1 and failed["error"]["code"] == "STALE_APPROVAL"
    assert not any(f["confirmed"] for f in state(database)["facts"])
    code, bad = invoke(database, "candidate", "confirm-many", CANDIDATE, "--item", "no-digest")
    assert code == 1 and bad["error"]["code"] == "CONTRACT_VALIDATION_ERROR"


def test_resolve_unknown_clears_one_answered_gap(tmp_path):
    from jobagent.schemas.candidate import CandidateDraft, CandidateProfile, UnknownField

    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    draft = tmp_path / ".jobagent" / "draft.json"
    database.parent.mkdir(parents=True)
    draft.write_text(
        CandidateDraft(
            candidate_id=CANDIDATE,
            profile=CandidateProfile(
                id=CANDIDATE,
                unknown_fields=[
                    UnknownField(path="experiences[0].end", reason="Not stated."),
                    UnknownField(path="education", reason="Not stated."),
                ],
            ),
        ).model_dump_json(),
        encoding="utf-8",
    )
    invoke(database, "candidate", "import-draft", str(draft))
    assert len(state(database)["gaps"]) == 5  # experience, skills, name, two unknowns
    code, profile = invoke(
        database, "candidate", "resolve-unknown", CANDIDATE, "experiences[0].end"
    )
    assert code == 0 and [u["path"] for u in profile["unknown_fields"]] == ["education"]
    labels = [g["label"] for g in state(database)["gaps"]]
    assert not any("experiences[0].end" in label for label in labels)
    assert any("education" in label for label in labels)
    code, missing = invoke(database, "candidate", "resolve-unknown", CANDIDATE, "nope")
    assert code == 1 and missing["error"]["code"] == "CONTRACT_VALIDATION_ERROR"


def test_agent_follow_ups_are_saved_verbatim_and_answered_one_at_a_time(tmp_path):
    database = tmp_path / ".jobagent" / "jobagent.sqlite3"
    invoke(database, "candidate", "start", CANDIDATE)
    _, first = invoke(database, "candidate", "question", CANDIDATE)
    invoke(database, "candidate", "answer", CANDIDATE, first["id"], "--answer", "做过评测集。")
    [fact] = state(database)["facts"]
    layer_one = "我理解你搭了一套评测集：它用来评什么，你负责哪一部分？"
    code, asked = invoke(
        database,
        "candidate",
        "ask",
        CANDIDATE,
        "--text",
        layer_one,
        "--about",
        fact["evidence_id"],
    )
    assert code == 0 and asked["text"] == layer_one
    assert state(database)["open_question"]["text"] == layer_one
    code, busy = invoke(database, "candidate", "ask", CANDIDATE, "--text", "另一个问题？")
    assert code == 1 and busy["error"]["code"] == "CONTRACT_VALIDATION_ERROR"
    invoke(
        database,
        "candidate",
        "answer",
        CANDIDATE,
        asked["id"],
        "--answer",
        "评问答准确率，用例由我设计。",
    )
    layer_two = "用例是怎么设计的，最后怎么判断准确率达标？"
    code, deeper = invoke(database, "candidate", "ask", CANDIDATE, "--text", layer_two)
    assert code == 0 and deeper["id"] != asked["id"]
    invoke(database, "candidate", "answer", CANDIDATE, deeper["id"], "--skip")
    after = state(database)
    assert after["open_question"] is None and after["skipped_count"] == 1
    assert [f["source_type"] for f in after["facts"]] == ["interview", "interview"]
    assert not any(f["confirmed"] for f in after["facts"])
