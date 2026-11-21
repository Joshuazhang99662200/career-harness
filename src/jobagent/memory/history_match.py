"""Match one job field to a single record-history diff. Do not invent values."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Never

from jobagent.errors import ContractValidationError
from jobagent.schemas.memory_signal import OperatorDirectory, OperatorKind
from jobagent.schemas.shared_memory import HistoryOperator, HistoryReason, RecordHistoryDiff


@dataclass(frozen=True)
class ParsedChange:
    field_id: str
    before: object
    after: object


@dataclass(frozen=True)
class ParsedItem:
    revision: int | None
    create_time: int | None
    activity_type: str
    operator: object
    changes: tuple[ParsedChange, ...]


@dataclass(frozen=True)
class ParsedPage:
    items: tuple[ParsedItem, ...]
    has_more: bool
    next_max_version: int | None


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


def parse_history_page(data: object) -> ParsedPage:
    if not isinstance(data, dict):
        _reject("Record history response is incomplete or invalid.")
    items = data.get("items")
    has_more = data.get("has_more")
    if not isinstance(items, list) or type(has_more) is not bool:
        _reject("Record history response is incomplete or invalid.")
    cursor = data.get("next_max_version")
    if has_more and (type(cursor) is not int or cursor <= 0):
        _reject("Record history page did not continue.")
    if not has_more and cursor is not None and type(cursor) is not int:
        _reject("Record history response is incomplete or invalid.")
    parsed: list[ParsedItem] = []
    for item in items:
        parsed.append(_item(item))
    next_version = cursor if type(cursor) is int else None
    return ParsedPage(items=tuple(parsed), has_more=has_more, next_max_version=next_version)


def _item(item: object) -> ParsedItem:
    if not isinstance(item, dict):
        _reject("Record history response is incomplete or invalid.")
    revision = item.get("rev")
    if revision is not None and type(revision) is not int:
        _reject("Record history response is incomplete or invalid.")
    created = item.get("create_time")
    if created is not None and (type(created) is not int or created < 0):
        _reject("Record history response is incomplete or invalid.")
    activity = item.get("activity_type")
    if not isinstance(activity, str) or not activity or "operator" not in item:
        _reject("Record history response is incomplete or invalid.")
    operator = item.get("operator")
    if operator is not None and not isinstance(operator, (str, dict)):
        _reject("Record history response is incomplete or invalid.")
    raw_changes = item.get("field_changes")
    if not isinstance(raw_changes, list):
        _reject("Record history response is incomplete or invalid.")
    changes: list[ParsedChange] = []
    for change in raw_changes:
        if not isinstance(change, dict) or "before" not in change or "after" not in change:
            _reject("Record history response is incomplete or invalid.")
        field_id = change.get("field_id")
        if not isinstance(field_id, str) or not field_id:
            _reject("Record history response is incomplete or invalid.")
        changes.append(ParsedChange(field_id, change.get("before"), change.get("after")))
    return ParsedItem(
        revision=revision if type(revision) is int else None,
        create_time=created if type(created) is int else None,
        activity_type=activity,
        operator=operator,
        changes=tuple(changes),
    )


def _cell_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        return value[0]
    return None


def classify_history_operator(operator: object, directory: OperatorDirectory) -> HistoryOperator:
    directory = OperatorDirectory.model_validate(directory.model_dump())
    if isinstance(operator, str):
        name = operator.strip()
        return HistoryOperator(kind="unknown", display_name=name or None)
    if not isinstance(operator, dict):
        return HistoryOperator(kind="unknown")
    open_id = operator.get("open_id")
    union_id = operator.get("union_id")
    raw_name = operator.get("name")
    open_text = open_id if isinstance(open_id, str) and open_id else None
    union_text = union_id if isinstance(union_id, str) and union_id else None
    display = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    if open_text is None and union_text is None:
        return HistoryOperator(kind="unknown", display_name=display)
    bot = open_text in directory.bot_open_ids or union_text in directory.bot_union_ids
    human = open_text in directory.human_open_ids or union_text in directory.human_union_ids
    if bot == human:
        kind: OperatorKind = "unknown"
    else:
        kind = "bot" if bot else "human"
    return HistoryOperator(
        kind=kind, open_id=open_text, union_id=union_text, display_name=display
    )


def _unknown(
    *,
    record_id: str,
    field_id: str,
    pages_read: int,
    reason: HistoryReason,
    before_value: str | None = None,
    after_value: str | None = None,
    operator: HistoryOperator | None = None,
    changed_at: str | None = None,
    revision: int | None = None,
) -> RecordHistoryDiff:
    return RecordHistoryDiff(
        record_id=record_id,
        field_id=field_id,
        state="unknown",
        reason=reason,
        before_value=before_value,
        after_value=after_value,
        operator=operator or HistoryOperator(kind="unknown"),
        changed_at=changed_at,
        revision=revision,
        pages_read=pages_read,
        grants_learning=False,
    )


def match_history(
    pages: Sequence[ParsedPage],
    *,
    record_id: str,
    field_id: str,
    operators: OperatorDirectory,
) -> RecordHistoryDiff:
    found: list[tuple[ParsedItem, ParsedChange]] = []
    for page in pages:
        for item in page.items:
            for change in item.changes:
                if change.field_id == field_id:
                    found.append((item, change))
    pages_read = len(pages)
    if not found:
        return _unknown(
            record_id=record_id, field_id=field_id, pages_read=pages_read, reason="no_field_change"
        )
    if len(found) != 1:
        return _unknown(
            record_id=record_id,
            field_id=field_id,
            pages_read=pages_read,
            reason="ambiguous_field_change",
        )
    item, change = found[0]
    before = _cell_text(change.before)
    after = _cell_text(change.after)
    if item.activity_type != "update" or before is None or after is None or before == after:
        return _unknown(
            record_id=record_id,
            field_id=field_id,
            pages_read=pages_read,
            reason="value_unreadable",
        )
    operator = classify_history_operator(item.operator, operators)
    changed_at = None if item.create_time is None else _utc(item.create_time)
    if item.revision is None:
        return _unknown(
            record_id=record_id,
            field_id=field_id,
            pages_read=pages_read,
            reason="revision_missing",
            before_value=before,
            after_value=after,
            operator=operator,
            changed_at=changed_at,
        )
    if changed_at is None:
        return _unknown(
            record_id=record_id,
            field_id=field_id,
            pages_read=pages_read,
            reason="time_missing",
            before_value=before,
            after_value=after,
            operator=operator,
            revision=item.revision,
        )
    if operator.kind == "unknown":
        return _unknown(
            record_id=record_id,
            field_id=field_id,
            pages_read=pages_read,
            reason="operator_unmatched",
            before_value=before,
            after_value=after,
            operator=operator,
            changed_at=changed_at,
            revision=item.revision,
        )
    reason: HistoryReason = "matched_human" if operator.kind == "human" else "matched_bot"
    return RecordHistoryDiff(
        record_id=record_id,
        field_id=field_id,
        state="matched",
        reason=reason,
        before_value=before,
        after_value=after,
        operator=operator,
        changed_at=changed_at,
        revision=item.revision,
        pages_read=pages_read,
        grants_learning=operator.kind == "human",
    )


def _utc(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
