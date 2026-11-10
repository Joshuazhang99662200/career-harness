"""Bounded repair, structured output, per-step settings and call records for the runner."""

import json
import sys
from pathlib import Path

import pytest

from jobagent.bridge.gemini_runner import GeminiTextRunner
from jobagent.errors import InvalidProviderOutputError, UserInterventionRequiredError
from jobagent.schemas.roleplay import GeminiCliConfig
from tests.bridge.test_gemini_runner import AGY_ARGV, REQUEST, Answer

OK = '{"text": "ok", "score": 3}'
LIMIT = "Your previous response was cut off because it exceeded the output token limit"


def agy(response: str, *, status: str = "SUCCESS", error: str | None = None, tool=False) -> str:
    steps = [{"step_type": "user_input"}, {"step_type": "agent_response"}]
    if tool:
        steps.insert(1, {"step_type": "tool"})
    result: dict[str, object] = {
        "status": status, "response": response, "duration_seconds": 12.5,
        "usage": {"input_tokens": 100, "output_tokens": 40, "thinking_tokens": 30},
    }
    if error:
        result["error"] = error
    lines = [{"event": "step_update", "step_update": s} for s in steps]
    lines.append({"event": "result", "result": result})
    return "".join(json.dumps(line) + "\n" for line in lines)


def sequence(tmp_path: Path, *bodies: str) -> Path:
    """A stand-in CLI that prints the next body on each call and logs what it received."""
    script = tmp_path / "seq.py"
    script.write_text(
        "import json, os, sys\n"
        "sys.stdin.reconfigure(encoding='utf-8')\n"
        f"state = {str(tmp_path / 'n.txt')!r}\n"
        "n = int(open(state).read()) if os.path.exists(state) else 0\n"
        "open(state, 'w').write(str(n + 1))\n"
        f"log = {str(tmp_path / 'calls.json')!r}\n"
        "seen = json.load(open(log)) if os.path.exists(log) else []\n"
        "args = sys.argv[1:]\n"
        "seen.append({'argv': args, 'stdin': sys.stdin.read()})\n"
        "json.dump(seen, open(log, 'w'))\n"
        f"bodies = {list(bodies)!r}\n"
        "sys.stdout.write(bodies[min(n, len(bodies) - 1)])\n",
        encoding="utf-8",
    )
    return script


def runner(tmp_path: Path, script: Path, **config: object) -> GeminiTextRunner:
    settings = {
        "argv": [sys.executable, str(script), *AGY_ARGV], "timeout_seconds": 30,
        "protocol": "agy_stream_json", **config,
    }
    return GeminiTextRunner(
        GeminiCliConfig.model_validate(settings), tmp_path / "runtime",
        call_log=tmp_path / "calls.jsonl",
    )


def calls(tmp_path: Path) -> list[dict]:
    return json.loads((tmp_path / "calls.json").read_text())


def records(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


@pytest.mark.parametrize(
    ("first", "kind"),
    [
        (agy('{"text": "ok", "score": 3]'), "invalid_json"),
        (agy("", status="ERROR", error=LIMIT), "output_limit"),
        (agy("", status="ERROR", error="The stream was interrupted. Please continue."),
         "stream_interrupted"),
    ],
)
def test_one_repair_retry_for_mechanical_failures_when_enabled(tmp_path, first, kind):
    script = sequence(tmp_path, first, agy(OK))
    assert runner(tmp_path, script, repair_retries=1).run(REQUEST, Answer).score == 3
    sent = calls(tmp_path)
    assert len(sent) == 2 and kind in sent[1]["stdin"] and "shorter" in sent[1]["stdin"]
    assert [(r["attempt"], r["status"]) for r in records(tmp_path)] == [(1, kind), (2, "ok")]


def test_without_repair_enabled_the_first_failure_stands(tmp_path):
    script = sequence(tmp_path, agy("", status="ERROR", error=LIMIT), agy(OK))
    with pytest.raises(UserInterventionRequiredError):
        runner(tmp_path, script).run(REQUEST, Answer)
    assert len(calls(tmp_path)) == 1


@pytest.mark.parametrize("first", [agy('{"text": "ok"}'), agy(OK, tool=True)])
def test_contract_violations_and_tool_activity_are_never_retried(tmp_path, first):
    script = sequence(tmp_path, first, agy(OK))
    with pytest.raises(InvalidProviderOutputError):
        runner(tmp_path, script, repair_retries=1).run(REQUEST, Answer)
    assert len(calls(tmp_path)) == 1


def test_a_second_mechanical_failure_fails_closed(tmp_path):
    bad = agy('{"text": "ok", "score": 3]')
    with pytest.raises(InvalidProviderOutputError):
        runner(tmp_path, sequence(tmp_path, bad, bad), repair_retries=1).run(REQUEST, Answer)
    assert len(calls(tmp_path)) == 2


def test_steps_override_argv_and_timeout_by_output_contract(tmp_path):
    script = sequence(tmp_path, agy(OK))
    override = [sys.executable, str(script), *AGY_ARGV, "--model", "low-tier"]
    runner(tmp_path, script, steps={"Answer": {"argv": override, "timeout_seconds": 5}}).run(
        REQUEST, Answer
    )
    assert calls(tmp_path)[0]["argv"][-2:] == ["--model", "low-tier"]
    assert records(tmp_path)[0]["timeout_seconds"] == 5


def test_step_overrides_cannot_auto_approve_tools():
    with pytest.raises(ValueError, match="auto-approve"):
        GeminiCliConfig.model_validate({
            "argv": ["agy"], "timeout_seconds": 30,
            "steps": {"GreetingDraft": {"argv": ["agy", "--yolo"]}},
        })


def test_call_records_carry_usage_and_sizes_but_no_prompt(tmp_path):
    runner(tmp_path, sequence(tmp_path, agy(OK))).run(REQUEST, Answer)
    [record] = records(tmp_path)
    assert record["contract"] == "Answer" and record["status"] == "ok"
    assert record["usage"]["thinking_tokens"] == 30 and record["model_seconds"] == 12.5
    assert record["response_chars"] == len(OK) and record["request_id"] == "CTX_SYNTHETIC"
    assert "Synthetic record" not in json.dumps(record)
