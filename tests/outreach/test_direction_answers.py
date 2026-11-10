"""Skip answers teach jobs rules; removed wording becomes a deterministic check."""

import pytest

from jobagent.bridge.preference_memory import MarkdownPreferenceStore
from jobagent.errors import InvalidProviderOutputError
from jobagent.outreach.preference_memory import (
    PreferenceLearner,
    forbidden_phrase_problems,
    memory_digest,
)
from jobagent.schemas.preference_memory import DirectionAnswer, PreferenceRule
from tests.outreach.test_preference_edits import Edits, event, rule
from tests.outreach.test_preference_memory import NOW, empty, signal


def answer(action="confirm_skip", note="背续费指标也是商务岗", job="JOB_CS"):
    return DirectionAnswer(
        answer_id="ODIR_ONE", proposal_id="ODIRP_ONE", candidate_id="CAND_TEST", job_id=job,
        rule_ids=["RULE_SALES"], action=action, words="跳过。", free_text=note,
        job_title="Customer Success Manager", company="Synthetic",
        jd_text="Own renewal and upsell targets.", occurred_at=NOW,
    )


def jobs_rule(sources, *, scope="role", condition="jobs carrying sales or renewal targets"):
    return {**rule("RULE_SALES", sources, scope=scope), "category": "jobs",
            "condition": condition, "text": "Skip jobs measured on sales targets."}


def test_a_confirmed_skip_alone_can_widen_a_jobs_rule():
    learner = PreferenceLearner(Edits([{"op": "add", "rule": jobs_rule(["ODIR_ONE"])}]))
    updated = learner.update(empty(), [], answers=[answer()], now=NOW)
    assert updated.consumed_event_ids == ["ODIR_ONE"]
    assert updated.rules[0].source_event_ids == ["ODIR_ONE"]
    context = learner.provider.contexts[0]
    assert context["events"] == [] and context["direction_answers"][0]["answer_id"] == "ODIR_ONE"
    # Replaying the same answer is a no-op, and a changed replay is refused.
    assert learner.update(updated, [], answers=[answer()], now=NOW) == updated
    with pytest.raises(Exception, match="different content"):
        learner.update(updated, [], answers=[answer(note="changed")], now=NOW)


def test_skip_answers_never_shape_greetings_and_need_a_reason_to_generalize():
    greet = PreferenceLearner(Edits([{"op": "add", "rule": rule("RULE_G", ["ODIR_ONE"],
                                                                 scope="general")}]))
    with pytest.raises(InvalidProviderOutputError, match="skip answer"):
        greet.update(empty(), [], answers=[answer()], now=NOW)
    silent = PreferenceLearner(Edits([{"op": "add", "rule": jobs_rule(["ODIR_ONE"])}]))
    with pytest.raises(InvalidProviderOutputError, match="unexplained"):
        silent.update(empty(), [], answers=[answer(note="")], now=NOW)


def test_a_skip_answer_for_another_candidate_is_refused():
    foreign = answer().model_copy(update={"candidate_id": "CAND_OTHER"})
    with pytest.raises(Exception, match="another candidate"):
        PreferenceLearner(Edits([])).update(empty(), [], answers=[foreign], now=NOW)


def phrase_rule(phrases, sources=("EVENT_1",)):
    return {**rule("RULE_P", list(sources), job="JOB_ONE"), "forbidden_phrases": phrases}


def test_forbidden_phrases_must_be_wording_the_person_removed():
    revised = event(1, "JOB_ONE").model_copy(update={
        "original_text": "我是林舟。我做过评测。期待交流。", "revised_text": "我做过评测。",
    })
    kept = PreferenceLearner(Edits([{"op": "add", "rule": phrase_rule(["期待交流"])}]))
    memory = kept.update(empty(), [revised], now=NOW)
    assert memory.rules[0].forbidden_phrases == ["期待交流"]
    for invented in (["很荣幸"], ["我做过评测"]):  # never shown, or kept by the person
        learner = PreferenceLearner(Edits([{"op": "add", "rule": phrase_rule(invented)}]))
        with pytest.raises(InvalidProviderOutputError, match="removed"):
            learner.update(empty(), [revised], now=NOW)


def test_forbidden_phrases_are_checked_by_program_and_old_rules_keep_their_digest():
    selected = PreferenceRule.model_validate({**phrase_rule(["期待交流"]), "rule_id": "RULE_P"})
    assert forbidden_phrase_problems([selected], "您好。期待交流。") == [
        "rule:RULE_P:forbidden_phrase:期待交流"
    ]
    assert forbidden_phrase_problems([selected], "您好。") == []
    plain = PreferenceRule.model_validate(rule("RULE_A", ["EVENT_1"]))
    assert "forbidden_phrases" not in plain.model_dump(mode="json")
    with pytest.raises(ValueError, match="greeting"):
        PreferenceRule.model_validate({**jobs_rule(["EVENT_1"]), "forbidden_phrases": ["x" * 3]})


def test_memory_with_phrases_round_trips_through_the_markdown_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    revised = signal().model_copy(update={
        "original_text": "我是林舟。期待交流。", "revised_text": "我做过评测。",
        "event_id": "EVENT_1", "idempotency_key": "EVENT_1",
    })
    memory = PreferenceLearner(Edits([{"op": "add", "rule": phrase_rule(["期待交流"])}])).update(
        empty(), [revised], now=NOW,
    )
    store = MarkdownPreferenceStore(tmp_path / ".jobagent" / "memory.md", "CAND_TEST")
    store.save(memory, expected_version=empty().version)
    assert memory_digest(store.load()) == memory_digest(memory)
