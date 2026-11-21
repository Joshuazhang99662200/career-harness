"""Shared memory contracts for Workflow-written Human Signals.

Table ids, workflow ids and field ids come from the host's private Feishu
setup. This module names the semantic tables and columns. It does not create
tables, enable workflows, or call a model. GPT still owns attribution and Dream.
The retired activity table ``records`` is not part of this mapping and is not
Human Signals. Materials stays in the mapping.
"""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from jobagent.schemas.candidate import CandidateId
from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.jobs import JobId
from jobagent.schemas.memory_signal import (
    OperatorDirectory,
    OperatorKind,
    PublishedMemory,
)

LearningStatus = Literal[
    "pending_history_enrichment",
    "pending_dream",
    "learned",
    "unknown",
]
SignalType = Literal["matching_correction", "greeting_revision", "workflow_outcome"]
MemoryDomain = Literal["search_match", "greeting", "workflow_context"]
PublicationStatus = Literal["published", "retained"]
HistoryReason = Literal[
    "matched_human",
    "matched_bot",
    "no_field_change",
    "ambiguous_field_change",
    "value_unreadable",
    "operator_unmatched",
    "revision_missing",
    "time_missing",
]
EnrichmentReason = Literal[HistoryReason, "duplicate", "write_unverified"]

# Semantic keys the memory path requires from private setup. No personal table ids.
# ``records`` is intentionally absent: it is a retired activity table, not Human Signals.
SHARED_MEMORY_TABLE_KEYS: tuple[str, ...] = (
    "jobs",
    "materials",
    "human_signals",
    "search_memory",
    "greeting_memory",
)
HUMAN_SIGNAL_WRITTEN_FIELDS = (
    "source_table",
    "source_record_id",
    "job_title",
    "field_name",
    "field_id",
    "signal_type",
    "memory_domain",
    "learning_status",
)
HUMAN_SIGNAL_ENRICHMENT_FIELDS = (
    "signal_id",
    "source_context",
    "operator_id",
    "operator_name",
    "changed_at",
    "before_value",
    "after_value",
)
HUMAN_SIGNAL_FIELDS = (*HUMAN_SIGNAL_WRITTEN_FIELDS, *HUMAN_SIGNAL_ENRICHMENT_FIELDS)
HUMAN_SIGNAL_MUTABLE_FIELDS = ("learning_status", *HUMAN_SIGNAL_ENRICHMENT_FIELDS)

SEARCH_MEMORY_FIELDS = (
    "memory_id",
    "version",
    "publication_status",
    "kind",
    "preference",
    "candidate_id",
    "source_signal_record_id",
    "source_signal_id",
    "job_record_id",
    "job_id",
    "reason",
    "keywords",
    "role_directions",
    "exclusions",
    "notes",
    "jd_digest",
    "supersedes_version",
    "content_digest",
)
GREETING_MEMORY_FIELDS = (
    "memory_id",
    "version",
    "publication_status",
    "kind",
    "preference",
    "candidate_id",
    "source_signal_record_id",
    "source_signal_id",
    "job_record_id",
    "job_id",
    "reason",
    "notes",
    "jd_digest",
    "supersedes_version",
    "content_digest",
)


class DisabledWorkflowBinding(ContractModel):
    """One workflow the private setup already has, kept disabled.

    Ids are whatever that Base uses. Enabling a workflow is outside this contract.
    """

    workflow_id: NonEmptyString
    signal_type: SignalType
    memory_domain: MemoryDomain
    field_name: NonEmptyString
    field_id: NonEmptyString
    enabled: Literal[False] = False

    @model_validator(mode="after")
    def domain_matches_signal(self) -> "DisabledWorkflowBinding":
        expected = {
            "matching_correction": "search_match",
            "greeting_revision": "greeting",
            "workflow_outcome": "workflow_context",
        }[self.signal_type]
        if self.memory_domain != expected:
            raise ValueError("Workflow memory domain does not match its signal type.")
        return self


class WorkflowSignal(ContractModel):
    """One Human Signals row. ``signal_record_id`` is the Feishu record id."""

    signal_record_id: NonEmptyString
    signal_id: str | None = None
    source_table: NonEmptyString
    source_record_id: NonEmptyString
    job_title: str
    field_name: NonEmptyString
    field_id: NonEmptyString
    signal_type: SignalType
    memory_domain: MemoryDomain
    learning_status: LearningStatus
    source_context: str | None = None
    operator_id: str | None = None
    operator_name: str | None = None
    changed_at: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    content_digest: Digest
    duplicate: bool = False
    grants_send: Literal[False] = False


class WorkflowSignalPage(ContractModel):
    signals: list[WorkflowSignal] = Field(default_factory=list)
    has_more: bool
    next_offset: int | None = None
    table_revision: int | str | None = None
    send_dispatched: Literal[False] = False


class HistoryOperator(ContractModel):
    kind: OperatorKind
    open_id: str | None = None
    union_id: str | None = None
    display_name: str | None = None


class RecordHistoryDiff(ContractModel):
    """One field's history. Unknown leaves the values unset instead of guessing."""

    record_id: NonEmptyString
    field_id: NonEmptyString
    state: Literal["matched", "unknown"]
    reason: HistoryReason
    before_value: str | None = None
    after_value: str | None = None
    operator: HistoryOperator
    changed_at: str | None = None
    revision: int | None = None
    pages_read: int = Field(ge=0)
    grants_learning: bool
    send_dispatched: Literal[False] = False

    @model_validator(mode="after")
    def learning_requires_one_human_edit(self) -> "RecordHistoryDiff":
        human = (
            self.state == "matched"
            and self.reason == "matched_human"
            and self.operator.kind == "human"
        )
        if self.grants_learning is not human:
            raise ValueError("Only a uniquely matched human edit can be learned.")
        if human and (
            self.before_value is None
            or self.after_value is None
            or self.revision is None
            or self.changed_at is None
        ):
            raise ValueError("A matched human diff needs before, after, revision and time.")
        return self


class SignalEnrichment(ContractModel):
    signal_record_id: NonEmptyString
    duplicate: bool
    advanced: bool
    learning_status: LearningStatus
    human_feedback: bool
    reason: EnrichmentReason
    write_verified: bool
    diff: RecordHistoryDiff | None = None
    grants_send: Literal[False] = False
    send_dispatched: Literal[False] = False


class StoredMemoryRow(ContractModel):
    record_id: NonEmptyString
    version: NonEmptyString
    publication_status: PublicationStatus
    source_signal_record_id: NonEmptyString
    memory: PublishedMemory
    body_digest: Digest

    @model_validator(mode="after")
    def version_is_a_positive_integer(self) -> "StoredMemoryRow":
        if not self.version.isdigit() or self.version.startswith("0"):
            raise ValueError("Memory version must be a positive integer.")
        return self


class MemoryPublishRequest(ContractModel):
    """A draft GPT already produced. This request does not call a model."""

    signal_record_id: NonEmptyString
    memory: PublishedMemory


class MemoryPublishResult(ContractModel):
    duplicate: bool
    verified: bool
    advanced_to_learned: bool
    previous_snapshot_restored: bool | None = None
    learning_status: LearningStatus | None = None
    version: str | None = None
    record_id: str | None = None
    retained_record_ids: list[str] = Field(default_factory=list)
    grants_send: Literal[False] = False
    send_dispatched: Literal[False] = False


class SearchRoundInput(ContractModel):
    """The user's current search config. Missing limits stay missing."""

    candidate_id: CandidateId
    keywords: list[NonEmptyString] = Field(min_length=1)
    role_directions: list[NonEmptyString] = Field(default_factory=list)
    exclusions: list[NonEmptyString] = Field(default_factory=list)
    hard_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    queries_per_site_per_round: int | None = Field(default=None, ge=1)
    top_per_query: int | None = Field(default=None, ge=1)
    search_frequency: str | None = None


class SearchRoundPlan(ContractModel):
    candidate_id: CandidateId
    memory_version: str | None = None
    memory_record_id: str | None = None
    source_signal_record_id: str | None = None
    original_keywords: list[str]
    keywords: list[str]
    additions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    role_directions: list[str] = Field(default_factory=list)
    applied: bool
    hard_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    queries_per_site_per_round: int | None = None
    top_per_query: int | None = None
    search_frequency: str | None = None
    changes_hard_constraints: Literal[False] = False
    grants_fetch: Literal[False] = False
    grants_send: Literal[False] = False

    @model_validator(mode="after")
    def version_matches_application(self) -> "SearchRoundPlan":
        named = self.memory_version is not None and self.memory_record_id is not None
        if self.applied is not named:
            raise ValueError("Applied search memory must name the version that was read.")
        return self


class DreamBatchStart(ContractModel):
    """Freeze a rolling ten-business-day window using the host's configured calendar."""

    candidate_id: CandidateId
    batch_size: int = Field(ge=1)
    window_start: NonEmptyString
    window_timezone: NonEmptyString
    window_business_days: Literal[10] = 10
    cutoff: NonEmptyString


class DreamBatchSnapshot(ContractModel):
    """Frozen signal ids and observation window for one Dream run."""

    batch_id: NonEmptyString
    candidate_id: CandidateId
    window_start: NonEmptyString
    window_timezone: NonEmptyString
    window_business_days: Literal[10] = 10
    cutoff: NonEmptyString
    data_version: NonEmptyString
    signal_ids: list[NonEmptyString]
    overflow_signal_ids: list[str] = Field(default_factory=list)
    resumed: bool
    quiet_window_seconds: None = None
    grants_send: Literal[False] = False


class SignalPreferenceDelta(ContractModel):
    """One signal's preference change, supplied by the caller. Not a model call."""

    signal_record_id: NonEmptyString
    add_keywords: list[NonEmptyString] = Field(default_factory=list)
    remove_keywords: list[NonEmptyString] = Field(default_factory=list)
    add_role_directions: list[NonEmptyString] = Field(default_factory=list)
    remove_role_directions: list[NonEmptyString] = Field(default_factory=list)
    add_exclusions: list[NonEmptyString] = Field(default_factory=list)
    remove_exclusions: list[NonEmptyString] = Field(default_factory=list)
    reason: NonEmptyString


class DreamBatchComplete(ContractModel):
    snapshot: DreamBatchSnapshot
    deltas: list[SignalPreferenceDelta]
    job_id: JobId


class DreamBatchResult(ContractModel):
    batch_id: NonEmptyString
    verified: bool
    republished: bool
    no_change: bool = False
    previous_snapshot_restored: bool | None = None
    memory_version: str | None = None
    memory_record_id: str | None = None
    learned_signal_ids: list[str] = Field(default_factory=list)
    pending_signal_ids: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    role_directions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    grants_send: Literal[False] = False


class FetchMemoryPin(ContractModel):
    """One Fetch round's pinned search memory. A newer publish does not replace it."""

    candidate_id: CandidateId
    memory_version: str | None = None
    memory_record_id: str | None = None
    content_hash: str | None = None
    last_consumed_version: str | None = None
    applied: bool
    original_keywords: list[str]
    keywords: list[str]
    additions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    role_directions: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, JsonValue] = Field(default_factory=dict)
    queries_per_site_per_round: int | None = None
    top_per_query: int | None = None
    search_frequency: str | None = None
    changes_hard_constraints: Literal[False] = False
    grants_fetch: Literal[False] = False
    grants_send: Literal[False] = False

    @model_validator(mode="after")
    def pin_names_the_version_it_applied(self) -> "FetchMemoryPin":
        named = self.memory_version is not None and self.memory_record_id is not None
        if self.applied is not named:
            raise ValueError("Applied fetch memory must name the pinned version.")
        if self.applied and self.content_hash is None:
            raise ValueError("Applied fetch memory must name the content hash that was checked.")
        if self.last_consumed_version != self.memory_version:
            raise ValueError("Consumption audit must match the pinned version.")
        return self


class RecordHistoryRequest(ContractModel):
    table: NonEmptyString
    record_id: NonEmptyString
    field_id: NonEmptyString
    operators: OperatorDirectory
    page_size: int = Field(default=50, ge=1, le=50)
    max_pages: int = Field(default=20, ge=1, le=50)
