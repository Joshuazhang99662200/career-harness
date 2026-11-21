"""Human-feedback signals from one Bitable record-changed event.

The captured names match the official ``drive.file.bitable_record_changed_v1``
body (schema 2.0): header ``event_id`` / ``create_time``, event ``operator_id``,
``action_list[].record_id``, ``before_value`` / ``after_value`` ``field_id`` and
``field_value``, and ``update_time``. Display names are not part of that body
and do not identify the operator. This contract does not grant a send.
"""

from typing import Literal

from pydantic import Field, model_validator

from jobagent.schemas.common import CandidateId, ContractModel, Digest, JobId, NonEmptyString

PreferenceLabel = Literal[
    "Matching Preference / Calibration",
    "Greeting Preference",
    "Workflow / Operational Preference",
]
OperatorKind = Literal["human", "bot", "unknown"]
ValueState = Literal["present", "unknown"]
MemoryKind = Literal["search", "matching", "greeting", "workflow"]


class WatchedJobFields(ContractModel):
    """Live field IDs for 匹配档位, 处理进度 and 招呼语. IDs are configuration."""

    table_id: NonEmptyString
    match_grade_field_id: NonEmptyString
    progress_field_id: NonEmptyString
    greeting_field_id: NonEmptyString

    @model_validator(mode="after")
    def distinct_fields(self) -> "WatchedJobFields":
        ids = (self.match_grade_field_id, self.progress_field_id, self.greeting_field_id)
        if len(set(ids)) != 3:
            raise ValueError("The three watched field IDs must be distinct.")
        return self


class OperatorDirectory(ContractModel):
    """Explicit open_id and union_id sets. Unlisted operators stay unknown."""

    bot_open_ids: list[NonEmptyString] = Field(default_factory=list)
    bot_union_ids: list[NonEmptyString] = Field(default_factory=list)
    human_open_ids: list[NonEmptyString] = Field(default_factory=list)
    human_union_ids: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def disjoint_identities(self) -> "OperatorDirectory":
        if set(self.bot_open_ids) & set(self.human_open_ids):
            raise ValueError("An open_id cannot be both bot and human.")
        if set(self.bot_union_ids) & set(self.human_union_ids):
            raise ValueError("A union_id cannot be both bot and human.")
        return self


class FieldObservation(ContractModel):
    """One watched field inside one event, including changes that must not be learned."""

    event_id: NonEmptyString
    record_id: NonEmptyString
    table_id: NonEmptyString
    revision: int | None = None
    field_id: NonEmptyString
    preference: PreferenceLabel
    action: Literal["record_added", "record_edited", "record_deleted", "unknown"]
    before_value: str | None = None
    after_value: str | None = None
    value_state: ValueState
    operator_kind: OperatorKind
    operator_open_id: str | None = None
    operator_union_id: str | None = None
    create_time: str | None = None
    update_time: int | None = None


class HumanFeedbackSignal(ContractModel):
    """A human edit of one watched field with both values present and different."""

    signal_id: NonEmptyString
    event_id: NonEmptyString
    record_id: NonEmptyString
    field_id: NonEmptyString
    preference: PreferenceLabel
    before_value: str
    after_value: str
    operator_open_id: str | None = None
    operator_union_id: str | None = None
    create_time: str | None = None
    update_time: int | None = None
    grants_send: Literal[False] = False


class SignalReceiveResult(ContractModel):
    event_id: NonEmptyString
    table_id: NonEmptyString
    duplicate: bool
    observations: list[FieldObservation] = Field(default_factory=list)
    human_signals: list[HumanFeedbackSignal] = Field(default_factory=list)
    ignored_field_ids: list[str] = Field(default_factory=list)
    send_dispatched: Literal[False] = False


class JobSignalContext(ContractModel):
    """JD and the greeting already generated for this Bitable record."""

    candidate_id: CandidateId
    record_id: NonEmptyString
    job_id: JobId
    jd_text: NonEmptyString
    generated_greeting: str | None = None
    title: str | None = None
    company: str | None = None
    role_direction: str | None = None


class AttributionRequest(ContractModel):
    signal: HumanFeedbackSignal
    candidate_id: CandidateId
    job_id: JobId
    jd_text: NonEmptyString
    jd_digest: Digest
    generated_greeting: str | None = None
    original_greeting_digest: Digest | None = None
    title: str | None = None
    company: str | None = None
    role_direction: str | None = None
    input_digest: Digest


class MemoryDraft(ContractModel):
    kind: MemoryKind
    reason: NonEmptyString
    keywords: list[NonEmptyString] = Field(default_factory=list)
    role_directions: list[NonEmptyString] = Field(default_factory=list)
    exclusions: list[NonEmptyString] = Field(default_factory=list)
    notes: list[NonEmptyString] = Field(default_factory=list)


class SignalAttribution(ContractModel):
    """Host model output. Actor, class and digests are checked, not trusted."""

    signal_id: NonEmptyString
    event_id: NonEmptyString
    record_id: NonEmptyString
    jd_digest: Digest
    original_greeting_digest: Digest | None = None
    input_digest: Digest
    drafts: list[MemoryDraft] = Field(min_length=1)


class PublishedMemory(ContractModel):
    memory_id: NonEmptyString
    kind: MemoryKind
    preference: PreferenceLabel
    candidate_id: CandidateId
    source_event_id: NonEmptyString
    source_signal_id: NonEmptyString
    record_id: NonEmptyString
    job_id: JobId
    reason: NonEmptyString
    keywords: list[str] = Field(default_factory=list)
    role_directions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    jd_digest: Digest
    grants_send: Literal[False] = False


class CompileResult(ContractModel):
    memories: list[PublishedMemory] = Field(default_factory=list)
    duplicate_signal_ids: list[str] = Field(default_factory=list)
    unassociated_signal_ids: list[str] = Field(default_factory=list)
    send_dispatched: Literal[False] = False


class SearchParameters(ContractModel):
    keywords: list[NonEmptyString] = Field(min_length=1)
    role_directions: list[NonEmptyString] = Field(default_factory=list)
    exclusions: list[NonEmptyString] = Field(default_factory=list)


class SearchParameterChange(ContractModel):
    op: Literal["add", "remove"]
    parameter: Literal["keywords", "role_directions", "exclusions"]
    value: NonEmptyString
    memory_id: NonEmptyString
    source_event_id: NonEmptyString
    job_id: JobId
    reason: NonEmptyString


class AppliedSearchParameters(ContractModel):
    candidate_id: CandidateId
    before: SearchParameters
    after: SearchParameters
    changes: list[SearchParameterChange] = Field(default_factory=list)
    ignored_memory_ids: list[str] = Field(default_factory=list)
    grants_send: Literal[False] = False


class CurrentSharedProjection(ContractModel):
    """Current 处理进度 and 批准状态 already read from the shared table."""

    record_id: NonEmptyString
    progress: str | None = None
    approval: str | None = None


class SendGateDecision(ContractModel):
    record_id: NonEmptyString
    allowed: Literal[False]
    send_dispatched: Literal[False] = False
    reason: Literal["unapproved", "approval_missing", "signal_path_does_not_send"]


class SignalReceiptFile(ContractModel):
    """Event-id digests only. Not a copy of job, approval or progress state."""

    digests: dict[str, Digest] = Field(default_factory=dict)


class HumanSignalFile(ContractModel):
    signals: list[HumanFeedbackSignal] = Field(default_factory=list)


class JobContextFile(ContractModel):
    contexts: list[JobSignalContext] = Field(default_factory=list)


class AttributionFile(ContractModel):
    attributions: list[SignalAttribution] = Field(default_factory=list)


class PublishedMemoryFile(ContractModel):
    memories: list[PublishedMemory] = Field(default_factory=list)
