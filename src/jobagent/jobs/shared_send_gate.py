"""Decide that an unapproved shared-table row must not be sent.

The signal path never dispatches outreach. A matching approval value still
returns send_dispatched false; a later execution host has to re-read the
shared table and pass the existing send gate.
"""

from collections.abc import Sequence

from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import CurrentSharedProjection, SendGateDecision


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
