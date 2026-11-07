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


def test_general_rules_always_apply_and_the_model_only_picks_scoped_ones():
    from jobagent.schemas.preference_memory import PreferenceMemory, PreferenceRule

    rules = [
        PreferenceRule.model_validate(rule("RULE_GENERAL", ["EVENT_1", "EVENT_2"], scope="general")),
        PreferenceRule.model_validate(rule("RULE_ROLE", ["EVENT_3"], scope="role")),
        PreferenceRule.model_validate(rule("RULE_JOB", ["EVENT_4"], job="JOB_FOUR")),
    ]
    memory = PreferenceMemory(
        candidate_id="CAND_TEST", consumed_event_ids=[f"EVENT_{n}" for n in range(1, 5)],
        rules=rules, updated_at=NOW,
    )

    class Picker:
        def __init__(self, picks):
            self.picks, self.offered = picks, None

        def generate(self, *, prompt_id, context, output_type):
            self.offered = [r["rule_id"] for r in context["memory"]["rules"]]
            return output_type(input_digest=context["input_digest"], selected_rule_ids=self.picks)

    none = Picker([])
    chosen = PreferenceLearner(none).select(memory, task="greeting", job_id="JOB_FOUR", context="JD")
    assert none.offered == ["RULE_ROLE", "RULE_JOB"]
    assert [r.rule_id for r in chosen.rules] == ["RULE_GENERAL"]

    some = Picker(["RULE_JOB"])
    chosen = PreferenceLearner(some).select(memory, task="greeting", job_id="JOB_FOUR", context="JD")
    assert [r.rule_id for r in chosen.rules] == ["RULE_GENERAL", "RULE_JOB"]

    never = Picker(["RULE_GENERAL"])
    with pytest.raises(InvalidProviderOutputError):
        PreferenceLearner(never).select(memory, task="greeting", job_id="JOB_FOUR", context="JD")

    class NoCall:
        def generate(self, **_):
            raise AssertionError("nothing scoped to choose, so no model call")

    only_general = memory.model_copy(update={"rules": rules[:1]})
    chosen = PreferenceLearner(NoCall()).select(
        only_general, task="greeting", job_id="JOB_OTHER", context="JD"
    )
    assert [r.rule_id for r in chosen.rules] == ["RULE_GENERAL"]


@pytest.mark.parametrize("condition", ["Evaluation PM", "  evaluation pm ", "Synthetic"])
def test_a_role_rule_cannot_be_pinned_to_a_job_title_or_company(condition):
    memory = base()
    pinned = rule("RULE_ROLE", ["EVENT_2"], scope="role") | {"condition": condition}
    learner = PreferenceLearner(Edits([{"op": "add", "rule": pinned}]))
    with pytest.raises(InvalidProviderOutputError, match="title"):
        learner.update(memory, [event(1, "JOB_ONE"), event(2, "JOB_TWO")], now=NOW)
