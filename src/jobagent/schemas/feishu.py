"""Host-owned Feishu field mappings and I/O receipts; no second business ledger."""

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from jobagent.schemas.common import ContractModel, Digest, NonEmptyString

FeishuRole = Literal["generation", "execution"]


class FeishuTable(ContractModel):
    table_id: NonEmptyString
    fields: dict[NonEmptyString, NonEmptyString] = Field(min_length=1)
    writable: dict[FeishuRole, list[NonEmptyString]] = Field(default_factory=dict)
    material_fields: list[NonEmptyString] = Field(default_factory=list)
    approved_values: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_permissions(self) -> "FeishuTable":
        if len(set(self.fields.values())) != len(self.fields):
            raise ValueError("Field mappings must not alias the same field ID.")
        for names in self.writable.values():
            if "approval" in names or not set(names) <= set(self.fields):
                raise ValueError("Agent writes must name mapped, non-approval fields.")
        if self.material_fields and (
            not set(self.material_fields) <= set(self.fields)
            or "approval" not in self.fields or not self.approved_values
        ):
            raise ValueError("Material guards require mapped fields and explicit approval options.")
        return self


class FeishuConfig(ContractModel):
    base_token: NonEmptyString
    identity: Literal["user", "bot"]
    executable: NonEmptyString
    timeout_seconds: float = Field(gt=0, le=300)
    tables: dict[NonEmptyString, FeishuTable] = Field(min_length=1)


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
