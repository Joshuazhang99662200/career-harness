"""Memory updates are incremental edits applied by code, under the same source rules."""

import pytest

from jobagent.errors import InvalidProviderOutputError
from jobagent.outreach.preference_memory import SUMMARIZE_PROMPT, PreferenceLearner
from jobagent.schemas.preference_memory import PreferenceEditSet
from tests.outreach.test_preference_memory import NOW, Provider, empty, signal


def event(n: int, job: str, note: str = "explained"):
    return signal(note=note).model_copy(update={
        "event_id": f"EVENT_{n}", "idempotency_key": f"EVENT_{n}", "job_id": job,
    })


def rule(rule_id, sources, *, scope="job", job="JOB_ONE", text="Lead with evaluation work."):
    return {
        "rule_id": rule_id, "category": "greetings", "scope": scope,
        "condition": "evaluation-heavy product roles" if scope != "job" else "this JD",
        "job_id": job if scope == "job" else None, "text": text,
        "source_event_ids": sources, "updated_at": NOW.isoformat(),
    }


class Edits:
    def __init__(self, edits):
        self.edits, self.contexts = edits, []

    def generate(self, *, prompt_id, context, output_type):
        assert prompt_id == SUMMARIZE_PROMPT and output_type is PreferenceEditSet
        self.contexts.append(context)
        return PreferenceEditSet.model_validate(
            {"input_digest": context["input_digest"], "edits": self.edits}
        )


def base():
    first = PreferenceLearner(Edits([{"op": "add", "rule": rule("RULE_A", ["EVENT_1"])}]))
    return first.update(empty(), [event(1, "JOB_ONE")], now=NOW)


def test_unchanged_rules_are_kept_without_being_rewritten():
    memory = base()
    learner = PreferenceLearner(Edits([
        {"op": "add", "rule": rule("RULE_B", ["EVENT_2"], job="JOB_TWO", text="Be brief.")},
    ]))
    updated = learner.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
    assert [r.rule_id for r in updated.rules] == ["RULE_A", "RULE_B"]
    assert updated.rules[0] == memory.rules[0]


def test_merge_turns_repeated_job_rules_into_one_general_rule_keeping_all_sources():
    memory = base()
    learner = PreferenceLearner(Edits([{
        "op": "merge", "replaces": ["RULE_A"],
        "rule": rule("RULE_GENERAL", ["EVENT_1", "EVENT_2"], scope="general"),
    }]))
    with pytest.raises(InvalidProviderOutputError, match="two"):
        learner.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)

    two = PreferenceLearner(Edits([
        {"op": "add", "rule": rule("RULE_B", ["EVENT_2"], job="JOB_TWO")},
    ])).update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
    merged = PreferenceLearner(Edits([{
        "op": "merge", "replaces": ["RULE_A", "RULE_B"],
        "rule": rule("RULE_GENERAL", ["EVENT_1", "EVENT_2", "EVENT_3"], scope="general"),
    }])).update(two, [event(1, "JOB_ONE"), event(2, "JOB_TWO"), event(3, "JOB_THREE")], now=NOW)
    assert [(r.rule_id, r.scope) for r in merged.rules] == [("RULE_GENERAL", "general")]

    dropped = PreferenceLearner(Edits([{
        "op": "merge", "replaces": ["RULE_A", "RULE_B"],
        "rule": rule("RULE_GENERAL", ["EVENT_2", "EVENT_4"], scope="general"),
    }]))
    with pytest.raises(InvalidProviderOutputError, match="sources"):
        dropped.update(two, [event(1, "JOB_ONE"), event(2, "JOB_TWO"), event(4, "JOB_X")], now=NOW)


def test_retire_needs_fresh_owner_feedback_and_known_rules():
    memory = base()
    silent = PreferenceLearner(Edits([{"op": "retire", "replaces": ["RULE_A"]}]))
    with pytest.raises(InvalidProviderOutputError, match="fresh"):
        silent.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
    reasoned = PreferenceLearner(Edits([
        {"op": "retire", "replaces": ["RULE_A"], "because_event_ids": ["EVENT_2"]},
    ])).update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
    assert reasoned.rules == []
    unknown = PreferenceLearner(Edits([
        {"op": "edit", "replaces": ["RULE_MISSING"], "rule": rule("RULE_MISSING", ["EVENT_2"])},
    ]))
    with pytest.raises(InvalidProviderOutputError, match="unknown"):
        unknown.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)


def test_edits_still_obey_the_existing_source_rules():
    memory = base()
    stale = PreferenceLearner(Edits([{
        "op": "edit", "replaces": ["RULE_A"],
        "rule": rule("RULE_A", ["EVENT_1"], text="Changed without new feedback."),
    }]))
    with pytest.raises(InvalidProviderOutputError, match="fresh owner source"):
        stale.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)


def test_the_model_sees_the_current_rules_and_only_the_new_events():
    memory = base()
    model = Edits([])
    PreferenceLearner(model).update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
    [context] = model.contexts
    assert [r["rule_id"] for r in context["memory"]["rules"]] == ["RULE_A"]
    assert [e["event_id"] for e in context["events"]] == ["EVENT_2"]
    assert Provider  # the shared fixture module stays importable
