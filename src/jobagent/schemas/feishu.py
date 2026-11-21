"""Host-owned Feishu field mappings and I/O receipts; no second business ledger."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString
from jobagent.schemas.shared_memory import DisabledWorkflowBinding

FeishuRole = Literal["generation", "execution", "memory"]


class FeishuTable(ContractModel):
    table_id: NonEmptyString
    fields: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    writable: dict[FeishuRole, list[NonEmptyString]] = Field(default_factory=dict)
    material_fields: list[NonEmptyString] = Field(default_factory=list)
    approved_values: list[NonEmptyString] = Field(default_factory=list)
    pending_approval_value: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_permissions(self) -> "FeishuTable":
        if len(set(self.fields.values())) != len(self.fields):
            raise ValueError("Field mappings must not alias the same field ID.")
        for role, names in self.writable.items():
            pending_only = role == "generation" and self.pending_approval_value is not None
            if ("approval" in names and not pending_only) or not set(names) <= set(self.fields):
                raise ValueError(
                    "Agent writes must name mapped fields; only generation may set the "
                    "configured pending approval value."
                )
        if self.material_fields and (
            not set(self.material_fields) <= set(self.fields)
            or "approval" not in self.fields or not self.approved_values
        ):
            raise ValueError("Material guards require mapped fields and explicit approval options.")
        return self


class FeishuConfig(ContractModel):
    """Private setup mapping. Table and workflow ids are the user's, not a built-in Base."""

    base_token: NonEmptyString
    identity: Literal["user", "bot"]
    executable: NonEmptyString
    timeout_seconds: float = Field(gt=0, le=300)
    tables: dict[NonEmptyString, FeishuTable] = Field(min_length=1)
    workflows: list[DisabledWorkflowBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def workflows_do_not_alias(self) -> "FeishuConfig":
        ids = [item.workflow_id for item in self.workflows]
        types = [item.signal_type for item in self.workflows]
        fields = [item.field_id for item in self.workflows]
        if (
            len(set(ids)) != len(ids)
            or len(set(types)) != len(types)
            or len(set(fields)) != len(fields)
        ):
            raise ValueError(
                "Disabled workflows must not reuse an id, signal type, or field id."
            )
        return self


class FeishuRecord(ContractModel):
    table_id: NonEmptyString
    record_id: NonEmptyString
    fields: dict[str, JsonValue] = Field(repr=False)
    content_digest: Digest
    version_kind: Literal["mapped_content_sha256"] = "mapped_content_sha256"


class FeishuPage(ContractModel):
    table_id: str
    records: list[FeishuRecord]
    has_more: bool
    next_offset: int | None
    table_revision: int | str | None = None
    grants_execution_permission: Literal[False] = False


class FeishuPatch(ContractModel):
    table: NonEmptyString
    record_id: NonEmptyString
    role: FeishuRole
    expected_digest: Digest
    fields: dict[NonEmptyString, JsonValue] = Field(min_length=1, repr=False)
    evidence_reference: NonEmptyString


class FeishuQuery(ContractModel):
    table: NonEmptyString
    fields: list[NonEmptyString] = Field(min_length=1)
    conditions: list[list[JsonValue]]
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    expected_table_revision: int | str | None = None


class SharedSendPolicy(ContractModel):
    """Explicit current-state values that may be executed. No personal defaults."""

    approved_values: list[NonEmptyString] = Field(min_length=1)
    ready_progress: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_values(self) -> "SharedSendPolicy":
        if len(set(self.approved_values)) != len(self.approved_values):
            raise ValueError("Approved values must be unique.")
        if len(set(self.ready_progress)) != len(self.ready_progress):
            raise ValueError("Ready progress values must be unique.")
        return self


class SharedWorkDecision(ContractModel):
    """One fresh read of approval and progress. This object does not dispatch."""

    record_id: NonEmptyString
    progress: str | None = None
    approval: str | None = None
    greeting: str | None = None
    content_digest: Digest
    business_allowed: bool
    send_dispatched: Literal[False] = False
    reason: Literal[
        "unapproved", "approval_missing", "progress_missing", "progress_not_ready", "ready"
    ]


class FeishuWriteReceipt(ContractModel):
    record_id: str
    status: Literal["verified", "unverified", "unknown"]
    verified: bool
    dispatched: bool
    evidence_reference: str
    record: FeishuRecord | None = None
    diagnostic: str | None = None
    concurrency_guarantee: Literal["pre_read_only"] = "pre_read_only"
    grants_execution_permission: Literal[False] = False


class FeishuCreateReceipt(ContractModel):
    """One memory-table append. Unknown means the caller must not advance status."""

    record_id: str | None = None
    status: Literal["verified", "unverified", "unknown"]
    verified: bool
    dispatched: bool
    record: FeishuRecord | None = None
    diagnostic: str | None = None
    concurrency_guarantee: Literal["pre_read_only"] = "pre_read_only"
    grants_execution_permission: Literal[False] = False
