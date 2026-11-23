"""Select verified owner changes before making any Human Signals write plan."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from jobagent.memory.history_match import classify_history_operator
from jobagent.schemas.memory_signal import OperatorDirectory
from jobagent.setup.bootstrap import Contract, PrivateInput, Signal

EVENT_TYPE = "drive.file.bitable_record_changed_v1"
TRACE_SOURCE = "lark_owner_event"


class TraceRow(BaseModel):
    signal_record_id: str = Field(min_length=1)
    signal_id: str
    event_id: str
    source_record_id: str
    field_id: str
    before_value: str
    after_value: str
    source_context: str


class TraceRequest(PrivateInput):
    """Private input from an authenticated, single-writer host event handler."""

    app_id: str = Field(min_length=1)
    tenant_key: str = Field(min_length=1)
    base_token: str = Field(min_length=1)
    jobs_table_id: str = Field(min_length=1)
    operators: OperatorDirectory
    fields: dict[str, str] = Field(min_length=1)
    event: dict[str, Any]
    bot_events: list[dict[str, Any]] = Field(default_factory=list)
    rows_complete: bool = False
    rows: list[TraceRow] = Field(default_factory=list)


class TraceWrite(BaseModel):
    signal_record_id: str | None = None
    fields: dict[str, str]


class TracePlan(BaseModel):
    status: str
    signal_ids: list[str] = Field(default_factory=list)
    writes: list[TraceWrite] = Field(default_factory=list)
    grants_send: Literal[False] = False


class TraceContext(PrivateInput):
    source: str
    revision: int = Field(ge=0)
    operator_kind: Literal["human"] = "human"
    baseline_event_id: str | None = None
    baseline_revision: int | None = Field(default=None, ge=0)


@dataclass(frozen=True)
class Event:
    event_id: str
    revision: int
    changed_at: str
    operator: object
    actions: list[dict[str, Any]]


@dataclass(frozen=True)
class Edit:
    record_id: str
    field_id: str
    before: str
    after: str


def plan_human_trace(contract: Contract, request: TraceRequest) -> TracePlan:
    if not _single_owner(request.operators):
        return TracePlan(status="owner_required")
    event = _event(request.event, request)
    if event is None:
        return TracePlan(status="scope_ignored")
    owner_id = _owner_id(event.operator, request.operators)
    if owner_id is None:
        return TracePlan(status="operator_ignored")

    specs = {signal.field: signal for signal in contract.signals}
    watched = {field_id: specs[name] for name, field_id in request.fields.items()
               if name in specs and field_id}
    if len(watched) != len(request.fields):
        return TracePlan(status="mapping_conflict")
    edits = _edits(event, watched)
    ids = {_signal_id(request, edit): edit for edit in edits}
    if len(ids) != len(edits):
        return TracePlan(status="trace_conflict")
    if not ids:
        return TracePlan(status="no_change")
    if not request.rows_complete:
        return TracePlan(status="inspect_traces", signal_ids=list(ids))

    previous: dict[str, TraceRow] = {}
    for stored in request.rows:
        if stored.signal_id in ids:
            if stored.signal_id in previous:
                return TracePlan(status="trace_conflict", signal_ids=list(ids))
            previous[stored.signal_id] = stored

    baseline = _bot_baselines(request, event, watched)
    writes = []
    for signal_id, edit in ids.items():
        row = previous.get(signal_id)
        context = _previous_context(row, edit) if row else None
        if row and context is None:
            return TracePlan(status="trace_conflict", signal_ids=list(ids))
        if row and context and row.event_id == event.event_id:
            if context.revision != event.revision or row.after_value != edit.after:
                return TracePlan(status="trace_conflict", signal_ids=list(ids))
            continue
        if context and context.revision >= event.revision:
            if context.revision == event.revision:
                return TracePlan(status="trace_conflict", signal_ids=list(ids))
            continue
        original = baseline.get((edit.record_id, edit.field_id))
        writes.append(_write(signal_id, edit, watched[edit.field_id], event, owner_id,
                             row, context, original))
    return TracePlan(status="write_traces" if writes else "no_change",
                     signal_ids=list(ids), writes=writes)


def _single_owner(directory: OperatorDirectory) -> bool:
    return bool(directory.human_open_ids or directory.human_union_ids) and (
        len(set(directory.human_open_ids)) <= 1 and len(set(directory.human_union_ids)) <= 1
    )


def _owner_id(operator: object, directory: OperatorDirectory) -> str | None:
    actual = classify_history_operator(operator, directory)
    if actual.kind != "human":
        return None
    if (actual.open_id and directory.human_open_ids
            and actual.open_id not in directory.human_open_ids):
        return None
    if (actual.union_id and directory.human_union_ids
            and actual.union_id not in directory.human_union_ids):
        return None
    if actual.open_id in directory.human_open_ids:
        return actual.open_id
    return actual.union_id


def _event(raw: dict[str, Any], request: TraceRequest) -> Event | None:
    header, body = raw.get("header"), raw.get("event")
    if not isinstance(header, dict) or not isinstance(body, dict):
        return None
    if (raw.get("schema") != "2.0" or header.get("event_type") != EVENT_TYPE
            or header.get("app_id") != request.app_id
            or header.get("tenant_key") != request.tenant_key
            or body.get("file_type") != "bitable" or body.get("file_token") != request.base_token
            or body.get("table_id") != request.jobs_table_id):
        return None
    event_id, revision, time = header.get("event_id"), body.get("revision"), body.get("update_time")
    actions = body.get("action_list")
    if (not isinstance(event_id, str) or not event_id or type(revision) is not int or revision < 0
            or type(time) is not int or time < 0 or not isinstance(actions, list)
            or not all(isinstance(action, dict) for action in actions)):
        return None
    try:
        changed_at = datetime.fromtimestamp(time, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None
    return Event(event_id, revision, changed_at, body.get("operator_id"), actions)


def _field_values(items: object, watched: dict[str, Signal]) -> dict[str, str]:
    if not isinstance(items, list):
        return {}
    values: dict[str, str] = {}
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        field, serialized = item.get("field_id"), item.get("field_value")
        if not isinstance(field, str) or field not in watched:
            continue
        if field in seen:
            values.pop(field, None)
            continue
        seen.add(field)
        if not isinstance(serialized, str):
            continue
        try:
            values[field] = _json(json.loads(serialized))
        except (ValueError, RecursionError):
            continue
    return values


def _edits(event: Event, watched: dict[str, Signal]) -> list[Edit]:
    edits: list[Edit] = []
    for action in event.actions:
        record = action.get("record_id")
        if action.get("action") != "record_edited" or not isinstance(record, str) or not record:
            continue
        before = _field_values(action.get("before_value"), watched)
        after = _field_values(action.get("after_value"), watched)
        edits.extend(Edit(record, key, prior, after[key]) for key, prior in before.items()
                     if key in after and prior != after[key])
    return edits


def _bot_baselines(
    request: TraceRequest, owner: Event, watched: dict[str, Signal],
) -> dict[tuple[str, str], tuple[Event, str]]:
    candidates: dict[tuple[str, str], tuple[Event, str]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for raw in request.bot_events:
        event = _event(raw, request)
        if event is None or event.revision >= owner.revision:
            continue
        if classify_history_operator(event.operator, request.operators).kind != "bot":
            continue
        for edit in _edits(event, watched):
            key = (edit.record_id, edit.field_id)
            previous = candidates.get(key)
            if previous is None or event.revision > previous[0].revision:
                candidates[key] = (event, edit.after)
                ambiguous.discard(key)
            elif event.revision == previous[0].revision and edit.after != previous[1]:
                ambiguous.add(key)
    return {key: value for key, value in candidates.items() if key not in ambiguous}


def _signal_id(request: TraceRequest, edit: Edit) -> str:
    items = [request.base_token, request.jobs_table_id, edit.record_id, edit.field_id]
    return "owner-trace-" + sha256(_json(items).encode()).hexdigest()


def _previous_context(row: TraceRow, edit: Edit) -> TraceContext | None:
    if row.source_record_id != edit.record_id or row.field_id != edit.field_id:
        return None
    try:
        context = TraceContext.model_validate_json(row.source_context)
        _json(json.loads(row.before_value))
        _json(json.loads(row.after_value))
    except (ValidationError, ValueError, RecursionError):
        return None
    if (context.source != TRACE_SOURCE
            or (context.baseline_event_id is None) != (context.baseline_revision is None)
            or (context.baseline_revision is not None
                and context.baseline_revision >= context.revision)):
        return None
    return context


def _write(
    signal_id: str, edit: Edit, signal: Signal, owner: Event, owner_id: str,
    previous: TraceRow | None, context: TraceContext | None, bot: tuple[Event, str] | None,
) -> TraceWrite:
    snapshot = TraceContext(source=TRACE_SOURCE, revision=owner.revision)
    initial = edit.before
    if previous is not None and context is not None:
        initial = previous.before_value
        snapshot.baseline_event_id = context.baseline_event_id
        snapshot.baseline_revision = context.baseline_revision
    if bot is not None:
        event, value = bot
        if snapshot.baseline_revision is None or event.revision > snapshot.baseline_revision:
            initial = value
            snapshot.baseline_event_id = event.event_id
            snapshot.baseline_revision = event.revision
    status = "unknown"
    if signal.domain in {"approval", "workflow_context"} or initial == edit.after:
        status = "context_only"
    elif snapshot.baseline_event_id:
        status = "pending_dream"
    return TraceWrite(signal_record_id=previous.signal_record_id if previous else None, fields={
        "signal_id": signal_id, "event_id": owner.event_id, "source_table": "岗位",
        "source_record_id": edit.record_id, "field_name": signal.field, "field_id": edit.field_id,
        "operator_id": owner_id, "changed_at": owner.changed_at,
        "signal_type": signal.signal_type, "memory_domain": signal.domain,
        "learning_status": status, "before_value": initial, "after_value": edit.after,
        "source_context": snapshot.model_dump_json(),
    })


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":"))
