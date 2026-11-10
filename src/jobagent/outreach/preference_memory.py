"""Summarize owner signals into small notes, then select notes for this task."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningOutputT, ReasoningProvider
from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.schemas.preference_memory import (
    DirectionAnswer,
    DirectionCheck,
    DirectionDecision,
    PreferenceApplication,
    PreferenceEditSet,
    PreferenceMemory,
    PreferenceRule,
    PreferenceSelection,
)
from jobagent.schemas.sourcing_feedback import SourcingFeedback

SUMMARIZE_PROMPT = "preference.memory.summarize.v2"
SELECT_PROMPT = "preference.memory.select.v1"
DIRECTION_PROMPT = "preference.direction.check.v1"


def memory_digest(memory: PreferenceMemory) -> str:
    return canonical_digest(memory.model_dump(mode="json"))


def _record_digest(record: SourcingFeedback | DirectionAnswer) -> str:
    payload = record.model_dump(mode="json")
    if record.occurred_at.utcoffset() is not None:
        payload["occurred_at"] = record.occurred_at.astimezone(UTC).isoformat()
    return canonical_digest(payload)


def _check_forbidden_phrases(rule: PreferenceRule, sources: list[SourcingFeedback]) -> None:
    """A forbidden phrase must be wording the person cut from a greeting they revised."""
    for phrase in rule.forbidden_phrases:
        if not any(
            event.action == "revise" and event.original_text and event.revised_text
            and phrase in event.original_text and phrase not in event.revised_text
            for event in sources
        ):
            raise InvalidProviderOutputError(
                "A forbidden phrase must be wording the person removed in a cited revision.",
                details={"rule_id": rule.rule_id},
            )


def forbidden_phrase_problems(rules: Sequence[PreferenceRule], text: str) -> list[str]:
    """Deterministic: wording the person removed under a selected rule must not return."""
    return [f"rule:{rule.rule_id}:forbidden_phrase:{phrase}"
            for rule in rules for phrase in rule.forbidden_phrases if phrase in text]


class PreferenceLearner:
    def __init__(self, provider: ReasoningProvider) -> None:
        self.provider = provider

    def _generate(
        self, prompt: str, context: dict[str, Any], contract: type[ReasoningOutputT],
    ) -> ReasoningOutputT:
        try:
            raw = self.provider.generate(prompt_id=prompt, context=context, output_type=contract)
            return contract.model_validate(raw.model_dump())
        except (ValidationError, TypeError, AttributeError):
            raise InvalidProviderOutputError(
                "The preference proposal is not valid bounded data."
            ) from None

    def update(
        self, memory: PreferenceMemory, events: list[SourcingFeedback], *, now: datetime,
        answers: Sequence[DirectionAnswer] = (),
    ) -> PreferenceMemory:
        memory = PreferenceMemory.model_validate(memory.model_dump())
        unique: dict[str, SourcingFeedback] = {}
        replies: dict[str, DirectionAnswer] = {}
        digests: dict[str, str] = {}
        records: list[tuple[str, str | None, str]] = []
        for event in events:
            event = SourcingFeedback.model_validate(event.model_dump())
            if event.event_id in unique and unique[event.event_id] != event:
                raise ContractValidationError("The same preference event has different content.")
            unique[event.event_id] = event
            records.append((event.event_id, event.candidate_id, _record_digest(event)))
        for answer in answers:
            answer = DirectionAnswer.model_validate(answer.model_dump())
            if answer.answer_id in replies and replies[answer.answer_id] != answer:
                raise ContractValidationError("The same preference event has different content.")
            replies[answer.answer_id] = answer
            records.append((answer.answer_id, answer.candidate_id, _record_digest(answer)))
        for record_id, candidate_id, digest in records:
            if candidate_id != memory.candidate_id:
                raise ContractValidationError("Preference feedback belongs to another candidate.")
            if record_id in memory.consumed_event_ids:
                saved = memory.consumed_event_digests.get(record_id)
                if saved is None:
                    raise ContractValidationError(
                        "Consumed preference feedback has no saved digest; "
                        "verify its original source before replay."
                    )
                if saved != digest:
                    raise ContractValidationError(
                        "The same preference event has different content."
                    )
            digests[record_id] = digest
        fresh = [event for event in unique.values()
                 if event.event_id not in memory.consumed_event_ids]
        fresh_answers = [answer for answer in replies.values()
                         if answer.answer_id not in memory.consumed_event_ids]
        if not fresh and not fresh_answers:
            return memory
        context = {"memory": memory.model_dump(mode="json"),
                   "events": [event.model_dump(mode="json") for event in fresh],
                   "direction_answers": [a.model_dump(mode="json") for a in fresh_answers]}
        identity = canonical_digest(context)
        proposal = self._generate(
            SUMMARIZE_PROMPT, {**context, "input_digest": identity}, PreferenceEditSet,
        )
        if proposal.input_digest != identity:
            raise InvalidProviderOutputError("Preference summary has a stale input digest.")
        known = set(memory.consumed_event_ids) | set(unique) | set(replies)
        fresh_ids = {event.event_id for event in fresh} | {a.answer_id for a in fresh_answers}
        old_rules = {rule.rule_id: rule for rule in memory.rules}
        rules = _apply_edits(memory.rules, proposal, fresh_ids)
        for rule in rules:
            if not set(rule.source_event_ids) <= known:
                raise InvalidProviderOutputError("Preference rule refers to an unknown source.")
            changed = old_rules.get(rule.rule_id) != rule
            sources = [unique[eid] for eid in rule.source_event_ids if eid in unique]
            skips = [replies[eid] for eid in rule.source_event_ids if eid in replies]
            cited: list[SourcingFeedback | DirectionAnswer] = [*sources, *skips]
            if rule.category == "greetings" and skips:
                raise InvalidProviderOutputError("A skip answer does not judge a greeting.")
            if rule.scope == "role" and changed:
                condition = " ".join(rule.condition.split()).casefold()
                labels = {
                    " ".join(value.split()).casefold()
                    for item in cited for value in (item.job_title, item.company) if value
                }
                if condition in labels:
                    raise InvalidProviderOutputError(
                        "A role preference names a job title or company instead of a kind of "
                        "job; describe the category, or scope it to the job.",
                        details={"rule_id": rule.rule_id},
                    )
            if not set(rule.source_event_ids) & fresh_ids and changed:
                raise InvalidProviderOutputError("Changed preferences need a fresh owner source.")
            if rule.scope == "job" and cited and not any(
                item.job_id == rule.job_id for item in cited
            ):
                raise InvalidProviderOutputError("Job-specific memory refers to a different JD.")
            explained = any(item.free_text.strip() for item in cited)
            # Unexplained individual decisions cannot become general restrictions.
            if (rule.scope == "general" and len(set(rule.source_event_ids)) < 2
                    and cited and not explained):
                raise InvalidProviderOutputError(
                    "An unexplained single decision cannot become a general preference."
                )
            if rule.category == "greetings" and sources and all(
                event.action == "decline" for event in sources
            ):
                raise InvalidProviderOutputError("A JD rejection does not judge the greeting.")
            if (rule.category == "jobs" and rule.scope != "job" and len(cited) == 1
                    and not explained and (skips or sources[0].action == "decline")):
                raise InvalidProviderOutputError(
                    "An unexplained JD rejection must stay specific to that JD."
                )
            if changed:
                _check_forbidden_phrases(rule, sources)
        consumed = list(dict.fromkeys([*memory.consumed_event_ids,
                                      *(event.event_id for event in fresh),
                                      *(answer.answer_id for answer in fresh_answers)]))
        try:
            result = PreferenceMemory(
                candidate_id=memory.candidate_id,
                version="PMEM_" + canonical_digest([memory.version, identity,
                                                   proposal.model_dump(mode="json")])[7:27].upper(),
                previous_version=memory.version, consumed_event_ids=consumed,
                consumed_event_digests={
                    **memory.consumed_event_digests,
                    **{key: digests[key] for key in consumed if key in fresh_ids},
                },
                rules=rules, updated_at=now,
            )
        except ValidationError:
            raise InvalidProviderOutputError(
                "Preference summary has inconsistent sources."
            ) from None
        return result

    def select(
        self, memory: PreferenceMemory, *, task: str, job_id: str | None, context: str,
    ) -> PreferenceSelection:
        memory = PreferenceMemory.model_validate(memory.model_dump())
        if task not in {"search", "greeting"}:
            raise ContractValidationError("Unknown preference-consumption task.")
        category = "jobs" if task == "search" else "greetings"
        eligible = [rule for rule in memory.rules if rule.category == category
                    and (rule.scope != "job" or rule.job_id == job_id)
                    and (job_id is not None or task == "search" or rule.scope == "general")]
        # General rules apply to every task of their category by definition, so they are
        # always used; the model only judges which scoped rules fit this task.
        general = [rule for rule in eligible if rule.scope == "general"]
        eligible = [rule for rule in eligible if rule.scope != "general"]
        selection = PreferenceSelection(memory_version=memory.version,
                                        memory_digest=memory_digest(memory), rules=general)
        if not eligible:
            return selection
        # The model may only choose IDs from host-filtered applicable categories.
        view = memory.model_copy(update={"rules": eligible}).model_dump(mode="json")
        payload = {"memory": view, "task": task, "job_id": job_id, "context": context}
        identity = canonical_digest(payload)
        applied = self._generate(SELECT_PROMPT, {**payload, "input_digest": identity},
                                 PreferenceApplication)
        by_id = {rule.rule_id: rule for rule in eligible}
        if (applied.input_digest != identity
                or not set(applied.selected_rule_ids) <= set(by_id)
                or len(set(applied.selected_rule_ids)) != len(applied.selected_rule_ids)
                or (task != "search" and applied.search_queries)):
            raise InvalidProviderOutputError("Preference selection is stale or outside its scope.")
        selection.rules = [*general, *(by_id[key] for key in applied.selected_rule_ids)]
        selection.search_queries = applied.search_queries
        return selection


    def direction(
        self, memory: PreferenceMemory, *, job_id: str, context: str
    ) -> DirectionDecision:
        """Before drafting: do the person's jobs rules say to skip this posting?"""
        memory = PreferenceMemory.model_validate(memory.model_dump())
        eligible = [rule for rule in memory.rules if rule.category == "jobs"
                    and (rule.scope != "job" or rule.job_id == job_id)]
        if not eligible:
            return DirectionDecision(memory_version=memory.version, decision="draft")
        view = memory.model_copy(update={"rules": eligible}).model_dump(mode="json")
        payload = {"memory": view, "job_id": job_id, "context": context}
        identity = canonical_digest(payload)
        check = self._generate(DIRECTION_PROMPT, {**payload, "input_digest": identity},
                               DirectionCheck)
        by_id = {rule.rule_id: rule for rule in eligible}
        matched = check.matched_rule_ids
        if (check.input_digest != identity or not set(matched) <= set(by_id)
                or len(set(matched)) != len(matched)
                or (check.decision == "suggest_skip") != bool(matched)):
            raise InvalidProviderOutputError(
                "A direction check must cite exactly the jobs rules it relies on."
            )
        return DirectionDecision(
            memory_version=memory.version, decision=check.decision,
            rules=[by_id[rule_id] for rule_id in matched], reason=check.reason,
        )

def _apply_edits(
    current: list[PreferenceRule], proposal: PreferenceEditSet, fresh_ids: set[str]
) -> list[PreferenceRule]:
    """Apply edits in order; every rule an edit does not name stays exactly as it was."""
    rules = list(current)
    touched: set[str] = set()

    def position(rule_id: str) -> int:
        for index, rule in enumerate(rules):
            if rule.rule_id == rule_id:
                return index
        raise InvalidProviderOutputError(
            "A preference edit names an unknown rule.", details={"rule_id": rule_id}
        )

    for edit in proposal.edits:
        names = set(edit.replaces) | ({edit.rule.rule_id} if edit.rule else set())
        if names & touched:
            raise InvalidProviderOutputError("One summary changes the same rule twice.")
        touched |= names
        if edit.op == "add":
            assert edit.rule is not None
            if any(rule.rule_id == edit.rule.rule_id for rule in rules):
                raise InvalidProviderOutputError("A new preference reuses an existing rule ID.")
            rules.append(edit.rule)
        elif edit.op == "edit":
            assert edit.rule is not None
            rules[position(edit.rule.rule_id)] = edit.rule
        elif edit.op == "merge":
            assert edit.rule is not None
            if len(edit.replaces) < 2:
                raise InvalidProviderOutputError("A merge combines at least two rules.")
            indexes = [position(rule_id) for rule_id in edit.replaces]
            merged_sources = {
                source for index in indexes for source in rules[index].source_event_ids
            }
            if not merged_sources <= set(edit.rule.source_event_ids):
                raise InvalidProviderOutputError(
                    "A merged preference must keep all sources of the rules it replaces."
                )
            if (edit.rule.rule_id not in edit.replaces
                    and any(rule.rule_id == edit.rule.rule_id for rule in rules)):
                raise InvalidProviderOutputError("A merged preference reuses another rule ID.")
            first = min(indexes)
            rules = [rule for index, rule in enumerate(rules) if index not in indexes]
            rules.insert(first, edit.rule)
        else:
            if not set(edit.because_event_ids) & fresh_ids:
                raise InvalidProviderOutputError(
                    "Retiring a preference needs fresh owner feedback as its reason."
                )
            for rule_id in edit.replaces:
                rules.pop(position(rule_id))
    return rules
