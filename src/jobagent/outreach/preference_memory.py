"""Summarize owner signals into small notes, then select notes for this task."""

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from jobagent.capabilities import ReasoningOutputT, ReasoningProvider
from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError, InvalidProviderOutputError
from jobagent.schemas.preference_memory import (
    PreferenceApplication,
    PreferenceEditSet,
    PreferenceMemory,
    PreferenceRule,
    PreferenceSelection,
)
from jobagent.schemas.sourcing_feedback import SourcingFeedback

SUMMARIZE_PROMPT = "preference.memory.summarize.v2"
SELECT_PROMPT = "preference.memory.select.v1"


def memory_digest(memory: PreferenceMemory) -> str:
    return canonical_digest(memory.model_dump(mode="json"))


def _feedback_digest(event: SourcingFeedback) -> str:
    payload = event.model_dump(mode="json")
    if event.occurred_at.utcoffset() is not None:
        payload["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat()
    return canonical_digest(payload)


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
    ) -> PreferenceMemory:
        memory = PreferenceMemory.model_validate(memory.model_dump())
        unique: dict[str, SourcingFeedback] = {}
        digests: dict[str, str] = {}
        for event in events:
            event = SourcingFeedback.model_validate(event.model_dump())
            if event.candidate_id != memory.candidate_id:
                raise ContractValidationError("Preference feedback belongs to another candidate.")
            if event.event_id in unique and unique[event.event_id] != event:
                raise ContractValidationError("The same preference event has different content.")
            digest = _feedback_digest(event)
            if event.event_id in memory.consumed_event_ids:
                saved = memory.consumed_event_digests.get(event.event_id)
                if saved is None:
                    raise ContractValidationError(
                        "Consumed preference feedback has no saved digest; "
                        "verify its original source before replay."
                    )
                if saved != digest:
                    raise ContractValidationError(
                        "The same preference event has different content."
                    )
            unique[event.event_id] = event
            digests[event.event_id] = digest
        fresh = [event for event in unique.values()
                 if event.event_id not in memory.consumed_event_ids]
        if not fresh:
            return memory
        context = {"memory": memory.model_dump(mode="json"),
                   "events": [event.model_dump(mode="json") for event in fresh]}
        identity = canonical_digest(context)
        proposal = self._generate(
            SUMMARIZE_PROMPT, {**context, "input_digest": identity}, PreferenceEditSet,
        )
        if proposal.input_digest != identity:
            raise InvalidProviderOutputError("Preference summary has a stale input digest.")
        known = set(memory.consumed_event_ids) | set(unique)
        fresh_ids = {event.event_id for event in fresh}
        old_rules = {rule.rule_id: rule for rule in memory.rules}
        rules = _apply_edits(memory.rules, proposal, fresh_ids)
        for rule in rules:
            if not set(rule.source_event_ids) <= known:
                raise InvalidProviderOutputError("Preference rule refers to an unknown source.")
            sources = [unique[eid] for eid in rule.source_event_ids if eid in unique]
            if rule.scope == "role" and old_rules.get(rule.rule_id) != rule:
                condition = " ".join(rule.condition.split()).casefold()
                labels = {
                    " ".join(value.split()).casefold()
                    for event in sources for value in (event.job_title, event.company) if value
                }
                if condition in labels:
                    raise InvalidProviderOutputError(
                        "A role preference names a job title or company instead of a kind of "
                        "job; describe the category, or scope it to the job.",
                        details={"rule_id": rule.rule_id},
                    )
            if (not set(rule.source_event_ids) & fresh_ids
                    and old_rules.get(rule.rule_id) != rule):
                raise InvalidProviderOutputError("Changed preferences need a fresh owner source.")
            if rule.scope == "job" and sources and not any(
                event.job_id == rule.job_id for event in sources
            ):
                raise InvalidProviderOutputError("Job-specific memory refers to a different JD.")
            # Unexplained individual decisions cannot become general restrictions.
            if (rule.scope == "general" and len(set(rule.source_event_ids)) < 2
                    and sources and not any(event.free_text.strip() for event in sources)):
                raise InvalidProviderOutputError(
                    "An unexplained single decision cannot become a general preference."
                )
            if rule.category == "greetings" and sources and all(
                event.action == "decline" for event in sources
            ):
                raise InvalidProviderOutputError("A JD rejection does not judge the greeting.")
            if (rule.category == "jobs" and rule.scope != "job" and len(sources) == 1
                    and sources[0].action == "decline" and not sources[0].free_text.strip()):
                raise InvalidProviderOutputError(
                    "An unexplained JD rejection must stay specific to that JD."
                )
        consumed = list(dict.fromkeys([*memory.consumed_event_ids,
                                      *(event.event_id for event in fresh)]))
        try:
            result = PreferenceMemory(
                candidate_id=memory.candidate_id,
                version="PMEM_" + canonical_digest([memory.version, identity,
                                                   proposal.model_dump(mode="json")])[7:27].upper(),
                previous_version=memory.version, consumed_event_ids=consumed,
                consumed_event_digests={
                    **memory.consumed_event_digests,
                    **{event.event_id: digests[event.event_id] for event in fresh},
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
