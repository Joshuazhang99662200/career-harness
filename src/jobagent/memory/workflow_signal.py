"""Parse Workflow-written Human Signals rows. Not a native event subscription."""

from collections.abc import Mapping, Sequence
from typing import Never

from pydantic import JsonValue, ValidationError

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.shared_memory import (
    HUMAN_SIGNAL_ENRICHMENT_FIELDS,
    HUMAN_SIGNAL_FIELDS,
    DisabledWorkflowBinding,
    WorkflowSignal,
)

_OPTIONAL = frozenset(HUMAN_SIGNAL_ENRICHMENT_FIELDS)
_STATUSES = frozenset({
    "pending_history_enrichment",
    "pending_dream",
    "learned",
    "unknown",
})


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


def _required(value: object) -> str:
    if not isinstance(value, str) or not value:
        _reject("Human Signal row is missing a workflow field.")
    return value


def _optional(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _reject("Human Signal row has a value that is not text.")
    return value or None


def parse_workflow_signal(
    signal_record_id: str,
    fields: Mapping[str, JsonValue],
    *,
    jobs_table_id: str,
    workflows: Sequence[DisabledWorkflowBinding],
) -> WorkflowSignal:
    """Read one Human Signals record. The record id is the unique signal id."""
    if not isinstance(signal_record_id, str) or not signal_record_id:
        _reject("Human Signal record_id is required.")
    if any(name not in fields for name in HUMAN_SIGNAL_FIELDS):
        _reject("Human Signal row is missing a workflow field.")
    title = fields["job_title"]
    if not isinstance(title, str):
        _reject("Human Signal row has a value that is not text.")
    status = _required(fields["learning_status"])
    if status not in _STATUSES:
        _reject("Human Signal learning_status is not a known state.")
    normalized: dict[str, str | None] = {
        "source_table": _required(fields["source_table"]),
        "source_record_id": _required(fields["source_record_id"]),
        "job_title": title,
        "field_name": _required(fields["field_name"]),
        "field_id": _required(fields["field_id"]),
        "signal_type": _required(fields["signal_type"]),
        "memory_domain": _required(fields["memory_domain"]),
        "learning_status": status,
    }
    for name in _OPTIONAL:
        normalized[name] = _optional(fields[name])
    workflow = next(
        (item for item in workflows if item.signal_type == normalized["signal_type"]),
        None,
    )
    if (
        workflow is None
        or workflow.enabled is not False
        or workflow.memory_domain != normalized["memory_domain"]
        or workflow.field_id != normalized["field_id"]
        or workflow.field_name != normalized["field_name"]
        or normalized["source_table"] != jobs_table_id
    ):
        _reject("Human Signal row does not match the configured disabled workflow.")
    try:
        return WorkflowSignal.model_validate({
            "signal_record_id": signal_record_id,
            "content_digest": canonical_digest(
                {"signal_record_id": signal_record_id, "fields": normalized}
            ),
            **normalized,
        })
    except ValidationError as error:
        raise ContractValidationError(
            "Human Signal row does not match the configured disabled workflow."
        ) from error


class WorkflowSignalLedger:
    """Process-local dedup of Human Signal record ids. Not a business ledger."""

    def __init__(self) -> None:
        self._digests: dict[str, str] = {}

    def receive(self, signal: WorkflowSignal) -> WorkflowSignal:
        signal = WorkflowSignal.model_validate(signal.model_dump())
        previous = self._digests.get(signal.signal_record_id)
        if previous is not None and previous != signal.content_digest:
            _reject("The same Human Signal record has different content.")
        duplicate = previous == signal.content_digest
        self._digests[signal.signal_record_id] = signal.content_digest
        stored = signal.model_copy(update={"duplicate": False})
        if duplicate:
            return stored.model_copy(update={"duplicate": True})
        return stored
