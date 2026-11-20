"""Test tool for one local ``drive.file.bitable_record_changed_v1`` fixture.

Production human signals are Workflow-written Human Signals rows. This parser
is not a connected production event path: it does not import an official SDK,
open a socket, or enable a subscription. A missing CLI event catalog is not
proof the platform event does not exist.
"""

from collections.abc import Mapping
from typing import Any, Literal, Never

from jobagent.digest import canonical_digest
from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import (
    FieldObservation,
    HumanFeedbackSignal,
    OperatorDirectory,
    OperatorKind,
    PreferenceLabel,
    SignalReceiveResult,
    WatchedJobFields,
)

_EVENT_TYPE = "drive.file.bitable_record_changed_v1"
_ACTIONS = frozenset({"record_added", "record_edited", "record_deleted"})


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


def _string_id(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _millis(value: object) -> str | None:
    if isinstance(value, str) and value.isdigit():
        return value
    return None


def _seconds(value: object) -> int | None:
    if type(value) is int:
        return value
    return None


def _classify(
    open_id: str | None, union_id: str | None, directory: OperatorDirectory
) -> OperatorKind:
    if open_id is None and union_id is None:
        return "unknown"
    bot = open_id in directory.bot_open_ids or union_id in directory.bot_union_ids
    human = open_id in directory.human_open_ids or union_id in directory.human_union_ids
    if bot == human:
        # Both true is a conflicting directory hit; both false is an unrecognized id.
        return "unknown"
    return "bot" if bot else "human"


def _action_name(
    value: object,
) -> Literal["record_added", "record_edited", "record_deleted", "unknown"]:
    if value == "record_added" or value == "record_edited" or value == "record_deleted":
        return value
    return "unknown"


def _field_map(action: Mapping[str, Any], key: str) -> tuple[dict[str, str | None], bool]:
    """Map field_id to the raw field_value string. The flag is true when the side is unknown."""
    if key not in action or action[key] is None:
        return {}, True
    raw = action[key]
    if not isinstance(raw, list):
        return {}, True
    found: dict[str, str | None] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        field_id = _string_id(item.get("field_id"))
        if field_id is None:
            continue
        value = item.get("field_value")
        found[field_id] = value if isinstance(value, str) else None
    return found, False


class SignalInbox:
    """Test tool. In-process fixture idempotency, not a production event subscription.

    Same id and digest replays; a changed body conflicts.

    The digest map is technical dedup of one event payload. It is not a job ledger
    and it does not store approval or progress as business state.
    """

    def __init__(
        self,
        fields: WatchedJobFields,
        operators: OperatorDirectory,
        *,
        prior_digests: Mapping[str, str] | None = None,
    ) -> None:
        self.fields = WatchedJobFields.model_validate(fields.model_dump())
        self.operators = OperatorDirectory.model_validate(operators.model_dump())
        self._digests = dict(prior_digests or {})
        self._results: dict[str, SignalReceiveResult] = {}
        self._labels: dict[str, PreferenceLabel] = {
            self.fields.match_grade_field_id: "Matching Preference / Calibration",
            self.fields.progress_field_id: "Workflow / Operational Preference",
            self.fields.greeting_field_id: "Greeting Preference",
        }

    @property
    def digests(self) -> dict[str, str]:
        return dict(self._digests)

    def receive(self, payload: Mapping[str, Any]) -> SignalReceiveResult:
        event_id, table_id, result = self._extract(payload)
        digest = canonical_digest(dict(payload))
        previous = self._digests.get(event_id)
        if previous is not None and previous != digest:
            _reject("The same Feishu event id has different content.")
        duplicate = previous == digest or event_id in self._results
        self._digests[event_id] = digest
        stored = result.model_copy(update={"duplicate": False, "table_id": table_id})
        self._results[event_id] = stored
        if duplicate:
            return stored.model_copy(update={"duplicate": True})
        return stored

    def _extract(
        self, payload: Mapping[str, Any]
    ) -> tuple[str, str, SignalReceiveResult]:
        if payload.get("schema") != "2.0":
            _reject("Bitable event schema is not 2.0.")
        header_raw = payload.get("header")
        event_raw = payload.get("event")
        if not isinstance(header_raw, dict):
            _reject("Bitable event is missing header or event.")
        if not isinstance(event_raw, dict):
            _reject("Bitable event is missing header or event.")
        header: dict[str, Any] = header_raw
        event: dict[str, Any] = event_raw
        if header.get("event_type") != _EVENT_TYPE:
            _reject("Event type is not drive.file.bitable_record_changed_v1.")
        event_id = _string_id(header.get("event_id"))
        table_id = _string_id(event.get("table_id"))
        if event_id is None or table_id is None:
            _reject("Bitable event is missing event_id or table_id.")
        if event.get("file_type") != "bitable":
            _reject("Record-changed event file_type must be bitable.")
        create_time = _millis(header.get("create_time"))
        update_time = _seconds(event.get("update_time"))
        revision = _seconds(event.get("revision"))
        operator = event.get("operator_id")
        open_id = union_id = None
        if isinstance(operator, dict):
            open_id = _string_id(operator.get("open_id"))
            union_id = _string_id(operator.get("union_id"))
        operator_kind = _classify(open_id, union_id, self.operators)
        observations: list[FieldObservation] = []
        ignored: list[str] = []
        actions = event.get("action_list")
        if table_id == self.fields.table_id and isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                self._action(
                    action,
                    event_id=event_id,
                    table_id=table_id,
                    revision=revision,
                    create_time=create_time,
                    update_time=update_time,
                    open_id=open_id,
                    union_id=union_id,
                    operator_kind=operator_kind,
                    observations=observations,
                    ignored=ignored,
                )
        elif not isinstance(actions, list):
            _reject("Bitable event action_list must be a list.")
        signals = [_signal(item) for item in observations if _learnable(item)]
        result = SignalReceiveResult(
            event_id=event_id,
            table_id=table_id,
            duplicate=False,
            observations=observations,
            human_signals=[item for item in signals if item is not None],
            ignored_field_ids=list(dict.fromkeys(ignored)),
        )
        return event_id, table_id, result

    def _action(
        self,
        action: Mapping[str, Any],
        *,
        event_id: str,
        table_id: str,
        revision: int | None,
        create_time: str | None,
        update_time: int | None,
        open_id: str | None,
        union_id: str | None,
        operator_kind: OperatorKind,
        observations: list[FieldObservation],
        ignored: list[str],
    ) -> None:
        record_id = _string_id(action.get("record_id"))
        if record_id is None:
            return
        action_name = _action_name(action.get("action"))
        before, before_unknown = _field_map(action, "before_value")
        after, after_unknown = _field_map(action, "after_value")
        for field_id in list(dict.fromkeys([*before, *after])):
            label = self._labels.get(field_id)
            if label is None:
                ignored.append(field_id)
                continue
            before_value = None if before_unknown else before.get(field_id)
            after_value = None if after_unknown else after.get(field_id)
            seen_before = field_id in before
            seen_after = field_id in after
            value_known = (
                not before_unknown
                and not after_unknown
                and seen_before
                and seen_after
                and before_value is not None
                and after_value is not None
            )
            observations.append(
                FieldObservation(
                    event_id=event_id,
                    record_id=record_id,
                    table_id=table_id,
                    revision=revision,
                    field_id=field_id,
                    preference=label,
                    action=action_name,
                    before_value=before_value,
                    after_value=after_value,
                    value_state="present" if value_known else "unknown",
                    operator_kind=operator_kind,
                    operator_open_id=open_id,
                    operator_union_id=union_id,
                    create_time=create_time,
                    update_time=update_time,
                )
            )


def _learnable(item: FieldObservation) -> bool:
    return (
        item.operator_kind == "human"
        and item.value_state == "present"
        and item.action == "record_edited"
        and item.before_value is not None
        and item.after_value is not None
        and item.before_value != item.after_value
    )


def _signal(item: FieldObservation) -> HumanFeedbackSignal | None:
    if item.before_value is None or item.after_value is None:
        return None
    identity = canonical_digest(
        {
            "event_id": item.event_id,
            "record_id": item.record_id,
            "field_id": item.field_id,
            "before_value": item.before_value,
            "after_value": item.after_value,
        }
    )
    return HumanFeedbackSignal(
        signal_id="SIG_" + identity[7:27].upper(),
        event_id=item.event_id,
        record_id=item.record_id,
        field_id=item.field_id,
        preference=item.preference,
        before_value=item.before_value,
        after_value=item.after_value,
        operator_open_id=item.operator_open_id,
        operator_union_id=item.operator_union_id,
        create_time=item.create_time,
        update_time=item.update_time,
    )
