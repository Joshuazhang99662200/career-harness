"""Decide that an unapproved shared-table row must not be sent.

The signal path never dispatches outreach. A matching approval value still
returns send_dispatched false; a later execution host has to re-read the
shared table and pass the existing send gate.
"""

from collections.abc import Sequence

from pydantic import JsonValue

from jobagent.errors import ContractValidationError
from jobagent.schemas.feishu import FeishuRecord, SharedSendPolicy, SharedWorkDecision
from jobagent.schemas.memory_signal import CurrentSharedProjection, SendGateDecision


def _scalar(value: JsonValue | None) -> str | None:
    """One select option or one text string. Any other shape stays unknown."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str) and value[0]:
        return value[0]
    return None


def current_work_decision(record: FeishuRecord, policy: SharedSendPolicy) -> SharedWorkDecision:
    """Interpret the record just read. Callers must read again before the next decision."""
    record = FeishuRecord.model_validate(record.model_dump())
    policy = SharedSendPolicy.model_validate(policy.model_dump())
    approval = _scalar(record.fields.get("approval"))
    progress = _scalar(record.fields.get("progress"))
    greeting = record.fields.get("greeting")
    observed = SharedWorkDecision(
        record_id=record.record_id,
        progress=progress,
        approval=approval,
        greeting=greeting if isinstance(greeting, str) and greeting else None,
        content_digest=record.content_digest,
        business_allowed=False,
        reason="approval_missing",
    )
    if approval is None:
        return observed
    if approval not in policy.approved_values:
        return observed.model_copy(update={"reason": "unapproved"})
    if progress is None:
        return observed.model_copy(update={"reason": "progress_missing"})
    if progress not in policy.ready_progress:
        return observed.model_copy(update={"reason": "progress_not_ready"})
    return observed.model_copy(update={"business_allowed": True, "reason": "ready"})


def shared_send_decision(
    current: CurrentSharedProjection, *, approved_values: Sequence[str]
) -> SendGateDecision:
    current = CurrentSharedProjection.model_validate(current.model_dump())
    allowed = [value for value in approved_values if isinstance(value, str) and value]
    if not allowed or len(set(allowed)) != len(list(approved_values)):
        raise ContractValidationError("Approved values must be an explicit non-empty set.")
    if current.approval is None or current.approval == "":
        return SendGateDecision(
            record_id=current.record_id, allowed=False, reason="approval_missing"
        )
    if current.approval not in allowed:
        return SendGateDecision(record_id=current.record_id, allowed=False, reason="unapproved")
    return SendGateDecision(
        record_id=current.record_id, allowed=False, reason="signal_path_does_not_send"
    )
