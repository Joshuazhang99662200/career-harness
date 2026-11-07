"""Small, source-bound preference notes, not candidate facts or permissions."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId

FeedbackEventDigest = Annotated[str, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class PreferenceRule(ContractModel):
    rule_id: NonEmptyString
    category: Literal["jobs", "greetings"]
    scope: Literal["general", "role", "job"]
    condition: Annotated[str, Field(min_length=1, max_length=500)]
    job_id: JobId | None = None
    text: Annotated[str, Field(min_length=1, max_length=500)]
    source_event_ids: list[NonEmptyString] = Field(min_length=1, max_length=30)
    updated_at: datetime

    @model_validator(mode="after")
    def validate_scope(self) -> "PreferenceRule":
        if (self.scope == "job") != (self.job_id is not None):
            raise ValueError("Only job-specific preferences bind an individual JD.")
        if len(set(self.source_event_ids)) != len(self.source_event_ids):
            raise ValueError("Preference sources must be unique.")
        return self


class PreferenceMemory(ContractModel):
    candidate_id: CandidateId
    version: NonEmptyString = "PMEM_EMPTY"
    previous_version: str | None = None
    consumed_event_ids: list[NonEmptyString] = Field(default_factory=list)
    consumed_event_digests: dict[NonEmptyString, FeedbackEventDigest] = Field(default_factory=dict)
    rules: list[PreferenceRule] = Field(default_factory=list, max_length=24)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_provenance(self) -> "PreferenceMemory":
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Preference rule IDs must be unique.")
        if len(self.consumed_event_ids) != len(set(self.consumed_event_ids)):
            raise ValueError("Consumed events must be unique.")
        if not set(self.consumed_event_digests) <= set(self.consumed_event_ids):
            raise ValueError("Event digests must refer to consumed preference events.")
        if any(not set(rule.source_event_ids) <= set(self.consumed_event_ids)
               for rule in self.rules):
            raise ValueError("Every preference needs consumed source events.")
        return self


class PreferenceEdit(ContractModel):
    """One change to the current rules. Unmentioned rules are kept exactly as they are.

    add: a new rule. edit: replace one rule (`replaces` names it). merge: replace two or
    more rules by one that keeps all their sources. retire: drop rules, citing the new
    feedback that ends them in `because_event_ids`.
    """

    op: Literal["add", "edit", "merge", "retire"]
    rule: PreferenceRule | None = None
    replaces: list[NonEmptyString] = Field(default_factory=list, max_length=24)
    because_event_ids: list[NonEmptyString] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def shape(self) -> "PreferenceEdit":
        if (self.op == "retire") == (self.rule is not None):
            raise ValueError("Only retire carries no rule; every other edit carries one.")
        if self.op == "add" and self.replaces:
            raise ValueError("A new rule replaces nothing.")
        if self.op in {"edit", "retire"} and not self.replaces:
            raise ValueError("Edit and retire must name the rules they change.")
        if self.op == "edit" and self.rule is not None and self.replaces != [self.rule.rule_id]:
            raise ValueError("An edit replaces exactly the rule it rewrites.")
        if len(set(self.replaces)) != len(self.replaces):
            raise ValueError("Replaced rules must be unique.")
        return self


class PreferenceEditSet(ContractModel):
    """The summarizer's answer: only what the new feedback changes."""

    input_digest: Digest
    edits: list[PreferenceEdit] = Field(default_factory=list, max_length=24)


class PreferenceApplication(ContractModel):
    input_digest: Digest
    selected_rule_ids: list[NonEmptyString] = Field(default_factory=list, max_length=24)
    search_queries: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=12,
    )


class PreferenceSelection(ContractModel):
    memory_version: NonEmptyString
    memory_digest: Digest
    rules: list[PreferenceRule] = Field(default_factory=list, max_length=24)
    search_queries: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=12,
    )
