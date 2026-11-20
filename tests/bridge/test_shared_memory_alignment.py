"""Workflow Human Signals, record history, and memory tables. Mock transport only."""

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jobagent.bridge.feishu_gateway import FeishuGateway
from jobagent.bridge.shared_memory import SharedMemoryService
from jobagent.cli.app import app
from jobagent.digest import text_digest
from jobagent.errors import ContractValidationError
from jobagent.memory.publication import published_memory_id
from jobagent.memory.signal import SignalInbox
from jobagent.memory.workflow_signal import WorkflowSignalLedger, parse_workflow_signal
from jobagent.schemas.feishu import FeishuConfig, FeishuPatch
from jobagent.schemas.memory_signal import (
    OperatorDirectory,
    PreferenceLabel,
    PublishedMemory,
)
from jobagent.schemas.shared_memory import (
    DISABLED_WORKFLOWS,
    GREETING_MEMORY_FIELDS,
    HUMAN_SIGNAL_FIELD_COUNT,
    HUMAN_SIGNAL_FIELDS,
    HUMAN_SIGNAL_MUTABLE_FIELDS,
    PRODUCTION_TABLE_IDS,
    SEARCH_MEMORY_FIELDS,
    MemoryPublishRequest,
    RecordHistoryRequest,
    SearchRoundInput,
)

FIXTURE = Path(__file__).parent / "fixtures" / "workflow_human_signal.json"
JOBS = PRODUCTION_TABLE_IDS["jobs"]
SIGNALS = PRODUCTION_TABLE_IDS["human_signals"]
SEARCH = PRODUCTION_TABLE_IDS["search_memory"]
GREETING = PRODUCTION_TABLE_IDS["greeting_memory"]
MATCH_FIELD = "flddtn4pvI"
GREETING_FIELD = "fld0jsS3ei"
PROGRESS_FIELD = "fldarFiHsF"
OPERATORS = OperatorDirectory(
    bot_open_ids=["ou_bot_fixture"],
    human_open_ids=["ou_human_fixture"],
)


def _field(name: str) -> str:
    return "fldsig_" + name


def _memory_field(name: str) -> str:
    return "fldmem_" + name


def _greeting_field(name: str) -> str:
    return "fldgre_" + name


def config() -> FeishuConfig:
    signal_fields = {name: _field(name) for name in HUMAN_SIGNAL_FIELDS}
    search_fields = {name: _memory_field(name) for name in SEARCH_MEMORY_FIELDS}
    greeting_fields = {name: _greeting_field(name) for name in GREETING_MEMORY_FIELDS}
    return FeishuConfig.model_validate({
        "base_token": "BASE_SYNTHETIC",
        "identity": "user",
        "executable": "synthetic-lark.exe",
        "timeout_seconds": 8,
        "tables": {
            "jobs": {
                "table_id": JOBS,
                "fields": {
                    "match_grade": MATCH_FIELD,
                    "greeting": GREETING_FIELD,
                    "progress": PROGRESS_FIELD,
                    "candidate_id": _field("candidate_id"),
                },
            },
            "human_signals": {
                "table_id": SIGNALS,
                "fields": signal_fields,
                "writable": {"memory": list(HUMAN_SIGNAL_MUTABLE_FIELDS)},
            },
            "search_memory": {
                "table_id": SEARCH,
                "fields": search_fields,
                "writable": {"memory": list(SEARCH_MEMORY_FIELDS)},
            },
            "greeting_memory": {
                "table_id": GREETING,
                "fields": greeting_fields,
                "writable": {"memory": list(GREETING_MEMORY_FIELDS)},
            },
        },
    })


def _signal_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row.update(overrides)
    return row


def _history_item(
    field_id: str,
    before: object,
    after: object,
    *,
    operator: object,
    revision: int = 150,
    create_time: int = 1717040601,
    activity: str = "update",
) -> dict[str, object]:
    return {
        "rev": revision,
        "operator": operator,
        "create_time": create_time,
        "activity_type": activity,
        "field_changes": [{
            "field_id": field_id,
            "field_name": "匹配档位",
            "before": before,
            "after": after,
        }],
    }


def _page(items: list[dict[str, object]], *, more: bool = False, cursor: int | None = None) -> dict:
    page: dict[str, object] = {"has_more": more, "items": items}
    if cursor is not None:
        page["next_max_version"] = cursor
    return page


class FakeBase:
    """In-memory Base. No subprocess and no live token."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail_history = False
        self.fail_writes = False
        self.fail_next_status_writes = 0
        self.fail_after_source_context_writes: int | None = None
        self.timeout_after_apply = 0
        self.signal_field_count = HUMAN_SIGNAL_FIELD_COUNT
        self.changed_at_type = "datetime"
        self.revisions = {JOBS: 7, SIGNALS: 11, SEARCH: 3, GREETING: 4}
        self.jobs: dict[str, dict[str, object]] = {}
        self.signals: dict[str, dict[str, object]] = {}
        self.search_rows: dict[str, dict[str, object]] = {}
        self.greeting_rows: dict[str, dict[str, object]] = {}
        self.history: dict[tuple[str, str], list[dict[str, object]]] = {}
        self._seq = 0
        settings = config()
        self.names = {
            table.table_id: {field_id: name for name, field_id in table.fields.items()}
            for table in settings.tables.values()
        }
        self.ids = {
            table.table_id: dict(table.fields) for table in settings.tables.values()
        }

    def call(self, argv: list[str]) -> dict[str, object]:
        self.calls.append(list(argv))
        table_id = argv[argv.index("--table-id") + 1]
        if "+field-list" in argv:
            return self._fields(table_id)
        if "+record-history-list" in argv:
            if self.fail_history:
                raise ContractValidationError("Synthetic history failure")
            return self._history(argv, table_id)
        if "+record-get" in argv or "+record-list" in argv:
            return self._read(argv, table_id)
        if "+record-batch-update" in argv:
            return self._update(argv, table_id)
        if "+record-batch-create" in argv:
            return self._create(argv, table_id)
        raise AssertionError(argv)

    def _fields(self, table_id: str) -> dict[str, object]:
        if table_id == SIGNALS:
            rows = []
            for name in HUMAN_SIGNAL_FIELDS:
                kind = self.changed_at_type if name == "changed_at" else "text"
                rows.append({"id": _field(name), "name": name, "type": kind})
            for index in range(self.signal_field_count - len(HUMAN_SIGNAL_FIELDS)):
                rows.append({
                    "id": f"fld_opaque_{index}",
                    "name": f"opaque_{index}",
                    "type": "text",
                })
            return {"fields": rows, "total": len(rows)}
        names = self.ids[table_id]
        rows = [{"id": field_id, "name": name, "type": "text"} for name, field_id in names.items()]
        return {"fields": rows, "total": len(rows)}

    def _store(self, table_id: str) -> dict[str, dict[str, object]]:
        if table_id == JOBS:
            return self.jobs
        if table_id == SIGNALS:
            return self.signals
        if table_id == SEARCH:
            return self.search_rows
        if table_id == GREETING:
            return self.greeting_rows
        raise AssertionError(table_id)

    def _matrix(
        self, table_id: str, rows: list[tuple[str, dict[str, object]]], *, more: bool
    ) -> dict[str, object]:
        mapping = self.ids[table_id]
        columns = list(mapping.values())
        data = []
        ids = []
        for record_id, semantic in rows:
            data.append([semantic.get(name) for name in mapping])
            ids.append(record_id)
        return {
            "field_id_list": columns,
            "data": data,
            "record_id_list": ids,
            "has_more": more,
            "rev": self.revisions[table_id],
        }

    def _read(self, argv: list[str], table_id: str) -> dict[str, object]:
        store = self._store(table_id)
        if "+record-get" in argv:
            record_id = argv[argv.index("--record-id") + 1]
            if record_id not in store:
                return self._matrix(table_id, [], more=False)
            return self._matrix(table_id, [(record_id, store[record_id])], more=False)
        raw = json.loads(argv[argv.index("--filter-json") + 1])
        matched = []
        for record_id in sorted(store):
            row = store[record_id]
            if self._matches(table_id, row, raw["conditions"]):
                matched.append((record_id, row))
        offset = int(argv[argv.index("--offset") + 1])
        limit = int(argv[argv.index("--limit") + 1])
        window = matched[offset:offset + limit]
        return self._matrix(table_id, window, more=offset + limit < len(matched))

    def _matches(
        self, table_id: str, row: dict[str, object], conditions: list[list[object]]
    ) -> bool:
        names = self.names[table_id]
        for condition in conditions:
            field_id, operator = condition[0], condition[1]
            expected = condition[2] if len(condition) > 2 else None
            if operator != "is" or row.get(names[str(field_id)]) != expected:
                return False
        return True

    def _update(self, argv: list[str], table_id: str) -> dict[str, object]:
        if self.fail_writes:
            raise ContractValidationError("Synthetic write failure")
        body = json.loads(argv[argv.index("--json") + 1])
        names = self.names[table_id]
        if self.fail_after_source_context_writes is not None:
            updates = body.get("update_records")
            writes_context = (
                isinstance(updates, dict)
                and any(
                    isinstance(fields, dict)
                    and any(names.get(str(field_id)) == "source_context" for field_id in fields)
                    for fields in updates.values()
                )
            )
            if writes_context:
                if self.fail_after_source_context_writes == 0:
                    self.fail_after_source_context_writes = None
                    raise ContractValidationError("Synthetic checkpoint failure")
                self.fail_after_source_context_writes -= 1
        if self.fail_next_status_writes and self._marks_learned(names, body):
            self.fail_next_status_writes -= 1
            raise ContractValidationError("Synthetic status failure")
        store = self._store(table_id)
        for record_id, fields in body["update_records"].items():
            for field_id, value in fields.items():
                store[record_id][names[field_id]] = value
        self.revisions[table_id] += 1
        self._maybe_timeout()
        return {}

    def _maybe_timeout(self) -> None:
        if self.timeout_after_apply:
            self.timeout_after_apply -= 1
            raise ContractValidationError("Synthetic write timeout")

    def _create(self, argv: list[str], table_id: str) -> dict[str, object]:
        if self.fail_writes:
            raise ContractValidationError("Synthetic write failure")
        body = json.loads(argv[argv.index("--json") + 1])
        names = self.names[table_id]
        store = self._store(table_id)
        ids = []
        for fields in body["create_records"]:
            self._seq += 1
            record_id = f"rec_mem_{self._seq}"
            store[record_id] = {names[field_id]: value for field_id, value in fields.items()}
            ids.append(record_id)
        self.revisions[table_id] += 1
        self._maybe_timeout()
        return {"record_id_list": ids}

    def _marks_learned(self, names: dict[str, str], body: dict[str, object]) -> bool:
        updates = body.get("update_records")
        if not isinstance(updates, dict):
            return False
        for fields in updates.values():
            if not isinstance(fields, dict):
                continue
            for field_id, value in fields.items():
                if names.get(str(field_id)) == "learning_status" and value == "learned":
                    return True
        return False

    def _history(self, argv: list[str], table_id: str) -> dict[str, object]:
        record_id = argv[argv.index("--record-id") + 1]
        pages = self.history[(table_id, record_id)]
        if "--max-version" not in argv:
            return pages[0]
        cursor = int(argv[argv.index("--max-version") + 1])
        for index, page in enumerate(pages[:-1]):
            if page.get("next_max_version") == cursor:
                return pages[index + 1]
        raise ContractValidationError(
            "Synthetic history cursor was not produced by the previous page."
        )

    def writes(self) -> list[list[str]]:
        return [
            call for call in self.calls
            if "+record-batch-update" in call or "+record-batch-create" in call
        ]


@pytest.fixture(autouse=True)
def no_real_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("tests must not start a real Feishu process")

    monkeypatch.setattr(subprocess, "run", boom)


def service(base: FakeBase | None = None) -> tuple[FakeBase, SharedMemoryService]:
    transport = base or FakeBase()
    return transport, SharedMemoryService(FeishuGateway(config(), transport), OPERATORS)


def _put_signal(
    base: FakeBase,
    record_id: str,
    *,
    candidate_id: str = "CAND_FIXTURE",
    **overrides: object,
) -> None:
    row = _signal_row(**overrides)
    base.signals[record_id] = row
    source_record_id = str(row["source_record_id"])
    base.jobs.setdefault(source_record_id, {
        "match_grade": "B",
        "greeting": "",
        "progress": "",
        "candidate_id": candidate_id,
    })


def _memory(
    signal_record_id: str,
    *,
    kind: str = "search",
    keywords: list[str] | None = None,
    exclusions: list[str] | None = None,
    notes: list[str] | None = None,
    preference: PreferenceLabel = "Matching Preference / Calibration",
) -> PublishedMemory:
    draft = {
        "kind": kind,
        "preference": preference,
        "candidate_id": "CAND_FIXTURE",
        "source_event_id": signal_record_id,
        "source_signal_id": signal_record_id,
        "record_id": "rec_job_data",
        "job_id": "JOB_DATA_PLATFORM",
        "reason": "Grade rose to A for data platform.",
        "keywords": (
            ["data platform"] if keywords is None and kind == "search" else list(keywords or [])
        ),
        "role_directions": ["data platform"] if kind == "search" else [],
        "exclusions": (
            ["retail floor"] if exclusions is None and kind == "search" else list(exclusions or [])
        ),
        "notes": list(notes or []),
        "jd_digest": text_digest("Synthetic JD: data platform engineer."),
    }
    draft["memory_id"] = published_memory_id(draft, signal_record_id)
    return PublishedMemory.model_validate(draft)


def test_production_tables_and_workflows_stay_disabled() -> None:
    assert set(PRODUCTION_TABLE_IDS) == {
        "jobs", "materials", "records", "human_signals", "search_memory", "greeting_memory",
    }
    assert len(HUMAN_SIGNAL_FIELDS) == 15
    assert HUMAN_SIGNAL_FIELD_COUNT == 19
    assert len(DISABLED_WORKFLOWS) == 3
    assert {item.workflow_id for item in DISABLED_WORKFLOWS} == {
        "wkfjRzrXEgmYazMu", "wkfYItz0dO451i0C", "wkf7gZH53nNP5f6y",
    }
    assert all(item.enabled is False for item in DISABLED_WORKFLOWS)


def test_parse_workflow_written_human_signal_and_reject_native_event() -> None:
    signal = parse_workflow_signal("rec_signal_grade", _signal_row())
    assert signal.signal_record_id == "rec_signal_grade"
    assert signal.signal_id is None
    assert signal.field_id == MATCH_FIELD
    assert signal.memory_domain == "search_match"
    assert signal.learning_status == "pending_history_enrichment"
    assert signal.before_value is None and signal.after_value is None
    native_path = Path(__file__).parents[1] / "memory" / "fixtures"
    native_path = native_path / "drive_file_bitable_record_changed_v1.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    with pytest.raises(ContractValidationError):
        parse_workflow_signal("rec_signal_grade", native)
    assert SignalInbox.__doc__ is not None
    assert "test tool" in SignalInbox.__doc__.lower()
    workflow_source = Path(parse_workflow_signal.__code__.co_filename)
    assert workflow_source.name == "workflow_signal.py"
    assert "bitable_record_changed" not in workflow_source.read_text(encoding="utf-8")


def test_signal_ledger_is_idempotent_and_rejects_conflicting_content() -> None:
    ledger = WorkflowSignalLedger()
    first = ledger.receive(parse_workflow_signal("rec_signal_grade", _signal_row()))
    second = ledger.receive(parse_workflow_signal("rec_signal_grade", _signal_row()))
    assert first.duplicate is False
    assert second.duplicate is True
    assert second.content_digest == first.content_digest
    with pytest.raises(ContractValidationError):
        ledger.receive(parse_workflow_signal(
            "rec_signal_grade", _signal_row(job_title="Other title")
        ))


def test_page_reads_pending_workflow_rows_without_writing(monkeypatch: pytest.MonkeyPatch) -> None:
    base, store = service()
    _put_signal(base, "rec_signal_1")
    _put_signal(base, "rec_signal_2", source_record_id="rec_job_two", job_title="Second role")
    _put_signal(base, "rec_signal_3", source_record_id="rec_job_three", job_title="Third role")
    _put_signal(base, "rec_signal_done", learning_status="learned")
    first = store.page_workflow_signals(limit=2, offset=0)
    assert [item.signal_record_id for item in first.signals] == ["rec_signal_1", "rec_signal_2"]
    assert first.has_more is True and first.next_offset == 2
    assert all(item.duplicate is False for item in first.signals)
    second = store.page_workflow_signals(
        limit=2, offset=first.next_offset or 0, expected_table_revision=first.table_revision,
    )
    assert [item.signal_record_id for item in second.signals] == ["rec_signal_3"]
    assert second.has_more is False
    again = store.page_workflow_signals(
        limit=2, offset=0, expected_table_revision=first.table_revision
    )
    assert all(item.duplicate for item in again.signals)
    assert base.writes() == []
    assert monkeypatch is not None


def test_history_associates_one_human_diff_and_marks_pending_dream() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade")
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(
            MATCH_FIELD, "B", "A",
            operator={"open_id": "ou_human_fixture", "name": "Synthetic Human"},
        ),
    ])]
    result = store.enrich_signal("rec_signal_grade")
    assert result.human_feedback is True
    assert result.advanced is True
    assert result.learning_status == "pending_dream"
    assert result.diff is not None
    assert result.diff.state == "matched"
    assert result.diff.before_value == "B"
    assert result.diff.after_value == "A"
    assert result.diff.operator.kind == "human"
    assert result.diff.revision == 150
    assert result.diff.changed_at == "2024-05-30T03:43:21+00:00"
    assert base.signals["rec_signal_grade"]["learning_status"] == "pending_dream"
    assert base.signals["rec_signal_grade"]["before_value"] == "B"
    assert base.signals["rec_signal_grade"]["after_value"] == "A"
    assert base.signals["rec_signal_grade"]["operator_id"] == "ou_human_fixture"
    assert base.signals["rec_signal_grade"]["signal_id"] is None
    again = store.enrich_signal("rec_signal_grade")
    assert again.duplicate is True and again.advanced is False
    assert sum("+record-batch-update" in call for call in base.calls) == 1


def test_duplicate_history_or_display_name_stays_unknown() -> None:
    base, store = service()
    _put_signal(base, "rec_ambiguous")
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(
            MATCH_FIELD, "B", "A", operator={"open_id": "ou_human_fixture"}, revision=150,
        ),
        _history_item(
            MATCH_FIELD, "A", "S", operator={"open_id": "ou_human_fixture"}, revision=151,
        ),
    ])]
    ambiguous = store.enrich_signal("rec_ambiguous")
    assert ambiguous.human_feedback is False
    assert ambiguous.learning_status == "unknown"
    assert base.signals["rec_ambiguous"]["before_value"] is None

    _put_signal(base, "rec_display_name")
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(MATCH_FIELD, "B", "A", operator="Synthetic Display Name"),
    ])]
    named = store.enrich_signal("rec_display_name")
    assert named.human_feedback is False
    assert named.diff is not None and named.diff.operator.kind == "unknown"
    assert named.learning_status == "unknown"
    assert base.signals["rec_display_name"]["operator_name"] is None


def test_bot_history_is_not_human_feedback_and_does_not_publish_memory() -> None:
    base, store = service()
    _put_signal(base, "rec_bot")
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(
            MATCH_FIELD, "B", "A",
            operator={"open_id": "ou_bot_fixture", "name": "Fixture Bot"},
        ),
    ])]
    result = store.enrich_signal("rec_bot")
    assert result.human_feedback is False
    assert result.diff is not None and result.diff.operator.kind == "bot"
    assert result.diff.grants_learning is False
    assert result.learning_status == "unknown"
    assert base.search_rows == {} and base.greeting_rows == {}
    assert not any("+record-batch-create" in call for call in base.calls)


def test_history_failure_and_unverified_write_do_not_advance_status() -> None:
    base, store = service()
    _put_signal(base, "rec_fail")
    base.fail_history = True
    with pytest.raises(ContractValidationError):
        store.enrich_signal("rec_fail")
    assert base.signals["rec_fail"]["learning_status"] == "pending_history_enrichment"
    assert base.writes() == []

    base.fail_history = False
    base.fail_writes = True
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(MATCH_FIELD, "B", "A", operator={"open_id": "ou_human_fixture"}),
    ])]
    failed = store.enrich_signal("rec_fail")
    assert failed.advanced is False
    assert failed.write_verified is False
    assert failed.learning_status == "pending_history_enrichment"
    assert base.signals["rec_fail"]["learning_status"] == "pending_history_enrichment"


def test_truncated_history_does_not_advance_status() -> None:
    base, store = service()
    _put_signal(base, "rec_short")
    base.history[(JOBS, "rec_job_data")] = [
        _page([
            _history_item(MATCH_FIELD, "B", "A", operator={"open_id": "ou_human_fixture"}),
        ], more=True, cursor=149),
        _page([], more=False),
    ]
    with pytest.raises(ContractValidationError):
        store.enrich_signal("rec_short", max_pages=1)
    assert base.signals["rec_short"]["learning_status"] == "pending_history_enrichment"
    assert base.writes() == []


def test_memory_schema_version_publish_and_idempotent_replay() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    first = _memory("rec_signal_grade")
    published = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=first,
    ))
    assert published.verified is True
    assert published.version == "1"
    assert published.advanced_to_learned is True
    assert base.signals["rec_signal_grade"]["learning_status"] == "learned"
    replay = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=first,
    ))
    assert replay.duplicate is True and replay.version == "1"
    assert len(base.search_rows) == 1

    _put_signal(
        base, "rec_signal_next", learning_status="pending_dream", job_title="Platform role",
    )
    second = _memory("rec_signal_next", keywords=["distributed systems"])
    nxt = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_next", memory=second,
    ))
    assert nxt.version == "2"
    assert nxt.record_id == published.record_id
    assert len(base.search_rows) == 1
    only = next(iter(base.search_rows.values()))
    assert only["version"] == "2"
    assert only["publication_status"] == "published"
    assert "distributed systems" in str(only["keywords"])

    base.signal_field_count = 18
    with pytest.raises(ContractValidationError):
        store.page_workflow_signals(limit=1, offset=0)
    base.signal_field_count = 19
    base.changed_at_type = "select"
    with pytest.raises(ContractValidationError):
        store.page_workflow_signals(limit=1, offset=0)


def test_in_place_update_keeps_one_record_and_bumps_version() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    first = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
    ))
    assert first.verified is True and first.version == "1"
    assert len(base.search_rows) == 1
    _put_signal(
        base, "rec_signal_next", learning_status="pending_dream", job_title="Platform role",
    )
    second = _memory("rec_signal_next", keywords=["distributed systems"])
    updated = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_next", memory=second,
    ))
    assert updated.verified is True
    assert updated.version == "2"
    assert updated.record_id == first.record_id
    assert len(base.search_rows) == 1
    row = base.search_rows[first.record_id or ""]
    assert row["version"] == "2"
    assert "distributed systems" in str(row["keywords"])
    assert base.signals["rec_signal_next"]["learning_status"] == "learned"


def test_failed_update_leaves_the_previous_record_readable() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    first = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
    ))
    _put_signal(base, "rec_signal_next", learning_status="pending_dream", job_title="Next")
    base.fail_writes = True
    failed = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_next",
        memory=_memory("rec_signal_next", keywords=["distributed systems"]),
    ))
    assert failed.verified is False
    assert failed.advanced_to_learned is False
    assert base.signals["rec_signal_next"]["learning_status"] == "pending_dream"
    assert len(base.search_rows) == 1
    row = base.search_rows[first.record_id or ""]
    assert row["version"] == "1"
    assert "data platform" in str(row["keywords"])


def test_timeout_after_a_successful_update_is_confirmed_by_reread() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    first = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
    ))
    _put_signal(base, "rec_signal_next", learning_status="pending_dream", job_title="Next")
    base.timeout_after_apply = 1
    second = _memory("rec_signal_next", keywords=["distributed systems"])
    confirmed = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_next", memory=second,
    ))
    assert confirmed.verified is True
    assert confirmed.version == "2"
    assert confirmed.record_id == first.record_id
    assert len(base.search_rows) == 1
    creates = [call for call in base.calls if "+record-batch-create" in call]
    assert len(creates) == 1


def test_retry_of_the_same_snapshot_does_not_create_a_second_record() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    memory = _memory("rec_signal_grade")
    store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=memory,
    ))
    again = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=memory,
    ))
    assert again.duplicate is True
    assert again.verified is True
    assert again.version == "1"
    assert len(base.search_rows) == 1
    assert sum("+record-batch-create" in call for call in base.calls) == 1


def test_overlapping_publish_is_rejected_without_a_second_ledger() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    store._publish_claims.add(("CAND_FIXTURE", "search"))
    with pytest.raises(ContractValidationError, match="single-writer"):
        store.publish_memory(MemoryPublishRequest(
            signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
        ))
    assert base.signals["rec_signal_grade"]["learning_status"] == "pending_dream"
    assert base.search_rows == {}
    assert not any("+record-batch-create" in call for call in base.calls)


def test_publish_rejects_candidate_mismatch_from_the_source_job() -> None:
    base, store = service()
    _put_signal(base, "rec_candidate_signal", candidate_id="CAND_A", learning_status="pending_dream")
    with pytest.raises(ContractValidationError, match="candidate does not match"):
        store.publish_memory(MemoryPublishRequest(
            signal_record_id="rec_candidate_signal",
            memory=_memory("rec_candidate_signal"),
        ))
    assert base.search_rows == {}
    assert base.signals["rec_candidate_signal"]["learning_status"] == "pending_dream"
    assert base.writes() == []


def test_failed_publish_does_not_mark_the_signal_learned() -> None:
    base, store = service()
    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    base.fail_writes = True
    result = store.publish_memory(
        MemoryPublishRequest(
            signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
        ),
    )
    assert result.verified is False
    assert result.advanced_to_learned is False
    assert base.signals["rec_signal_grade"]["learning_status"] == "pending_dream"
    assert base.search_rows == {}


def test_workflow_memory_and_bot_status_are_not_published() -> None:
    base, store = service()
    _put_signal(
        base,
        "rec_progress",
        field_name="处理进度",
        field_id=PROGRESS_FIELD,
        signal_type="workflow_outcome",
        memory_domain="workflow_context",
        learning_status="pending_dream",
    )
    with pytest.raises(ContractValidationError):
        store.publish_memory(MemoryPublishRequest(
            signal_record_id="rec_progress",
            memory=_memory("rec_progress", kind="workflow", notes=["progress changed"]),
        ))
    assert base.writes() == []


def test_legacy_retained_rows_are_inert_when_one_published_row_exists() -> None:
    base, store = service()
    _put_signal(base, "rec_first", learning_status="pending_dream")
    first = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_first", memory=_memory("rec_first"),
    ))
    assert first.verified is True and first.record_id is not None
    legacy = dict(base.search_rows[first.record_id])
    legacy["publication_status"] = "retained"
    base.search_rows["rec_legacy_retained"] = legacy

    _put_signal(base, "rec_next", learning_status="pending_dream", job_title="Next role")
    updated = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_next",
        memory=_memory("rec_next", keywords=["distributed systems"]),
    ))
    assert updated.verified is True
    assert updated.record_id == first.record_id
    assert len(base.search_rows) == 2
    assert base.search_rows["rec_legacy_retained"]["publication_status"] == "retained"
    assert base.search_rows[first.record_id]["version"] == "2"


def test_retained_only_memory_domain_requires_reconciliation() -> None:
    base, store = service()
    _put_signal(base, "rec_first", learning_status="pending_dream")
    first = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_first", memory=_memory("rec_first"),
    ))
    assert first.record_id is not None
    base.search_rows[first.record_id]["publication_status"] = "retained"
    with pytest.raises(ContractValidationError, match="Only legacy retained"):
        store.read_search_round(SearchRoundInput(
            candidate_id="CAND_FIXTURE", keywords=["backend engineer"],
        ))


def test_search_round_applies_published_memory_and_falls_back_without_it() -> None:
    base, store = service()
    limits = {
        "hard_constraints": {"minimum_compensation": 30000, "cities": ["Shanghai"]},
        "queries_per_site_per_round": 2,
        "top_per_query": 30,
        "search_frequency": "synthetic-weekly",
    }
    empty = store.read_search_round(SearchRoundInput(
        candidate_id="CAND_FIXTURE",
        keywords=["backend engineer"],
        role_directions=["backend"],
        exclusions=["intern"],
        **limits,
    ))
    assert empty.applied is False
    assert empty.memory_version is None
    assert empty.original_keywords == ["backend engineer"]
    assert empty.keywords == ["backend engineer"]
    assert empty.additions == []
    assert empty.exclusions == ["intern"]
    assert empty.role_directions == ["backend"]
    assert empty.hard_constraints == limits["hard_constraints"]
    assert empty.queries_per_site_per_round == 2
    assert empty.top_per_query == 30
    assert empty.search_frequency == "synthetic-weekly"
    assert empty.grants_fetch is False
    assert base.writes() == []

    _put_signal(base, "rec_signal_grade", learning_status="pending_dream")
    store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_signal_grade",
        memory=_memory("rec_signal_grade"),
    ))
    applied = store.read_search_round(SearchRoundInput(
        candidate_id="CAND_FIXTURE",
        keywords=["backend engineer", "retail floor"],
        role_directions=["backend"],
        exclusions=["intern"],
        **limits,
    ))
    assert applied.applied is True
    assert applied.memory_version == "1"
    assert applied.original_keywords == ["backend engineer", "retail floor"]
    assert applied.keywords == ["backend engineer", "data platform"]
    assert applied.additions == ["data platform"]
    assert "retail floor" not in applied.keywords
    assert applied.exclusions == ["intern", "retail floor"]
    assert "data platform" in applied.role_directions
    assert applied.role_directions[0] == "backend"
    assert applied.hard_constraints == limits["hard_constraints"]
    assert applied.queries_per_site_per_round == 2
    assert applied.top_per_query == 30
    assert applied.search_frequency == "synthetic-weekly"
    assert applied.changes_hard_constraints is False
    assert applied.grants_fetch is False


def test_greeting_memory_is_not_used_as_search_memory() -> None:
    base, store = service()
    _put_signal(
        base,
        "rec_greet",
        field_name="招呼语",
        field_id=GREETING_FIELD,
        signal_type="greeting_revision",
        memory_domain="greeting",
        learning_status="pending_dream",
    )
    greeting = _memory(
        "rec_greet",
        kind="greeting",
        keywords=[],
        exclusions=[],
        notes=["Shorter greeting focused on pipeline ownership."],
        preference="Greeting Preference",
    )
    published = store.publish_memory(MemoryPublishRequest(
        signal_record_id="rec_greet", memory=greeting,
    ))
    assert published.version == "1"
    assert len(base.greeting_rows) == 1 and base.search_rows == {}
    created = next(call for call in base.calls if "+record-batch-create" in call)
    payload = json.loads(created[created.index("--json") + 1])
    assert _memory_field("keywords") not in payload["create_records"][0]
    plan = store.read_search_round(SearchRoundInput(
        candidate_id="CAND_FIXTURE", keywords=["backend engineer"],
    ))
    assert plan.applied is False
    assert plan.keywords == ["backend engineer"]


def test_datetime_status_field_rejects_a_non_string_without_writing() -> None:
    base = FakeBase()
    gateway = FeishuGateway(config(), base)
    _put_signal(base, "rec_signal_grade")
    current = gateway.get("human_signals", "rec_signal_grade")
    with pytest.raises(ContractValidationError):
        gateway.patch(FeishuPatch.model_validate({
            "table": "human_signals",
            "record_id": "rec_signal_grade",
            "role": "memory",
            "expected_digest": current.content_digest,
            "fields": {"changed_at": 1717040601},
            "evidence_reference": "synthetic-datetime-guard",
        }))
    assert base.writes() == []


def test_record_history_gateway_is_read_only() -> None:
    base = FakeBase()
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(MATCH_FIELD, ["B"], ["A"], operator={"open_id": "ou_human_fixture"}),
    ])]
    diff = FeishuGateway(config(), base).record_history(
        "jobs", "rec_job_data", MATCH_FIELD, operators=OPERATORS,
    )
    assert diff.before_value == "B" and diff.after_value == "A"
    assert diff.grants_learning is True
    assert base.writes() == []
    assert all("+record-history-list" in call or "+field-list" in call for call in base.calls)
    with pytest.raises(ContractValidationError):
        FeishuGateway(config(), base).append_memory_row("jobs", {"match_grade": "A"})


def test_cli_commands_use_the_mock_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jobagent.cli import feishu as feishu_cli

    base = FakeBase()
    _put_signal(base, "rec_signal_grade")
    base.history[(JOBS, "rec_job_data")] = [_page([
        _history_item(MATCH_FIELD, "B", "A", operator={"open_id": "ou_human_fixture"}),
    ])]
    monkeypatch.setattr(feishu_cli, "LarkCliTransport", lambda _config: base)
    settings = tmp_path / "config.json"
    settings.write_text(config().model_dump_json(), encoding="utf-8")
    history_request = tmp_path / "history.json"
    history_request.write_text(RecordHistoryRequest(
        table="jobs", record_id="rec_job_data", field_id=MATCH_FIELD, operators=OPERATORS,
    ).model_dump_json(), encoding="utf-8")
    operators = tmp_path / "operators.json"
    operators.write_text(OPERATORS.model_dump_json(), encoding="utf-8")
    draft = tmp_path / "draft.json"
    draft.write_text(MemoryPublishRequest(
        signal_record_id="rec_signal_grade", memory=_memory("rec_signal_grade"),
    ).model_dump_json(), encoding="utf-8")
    search = tmp_path / "round.json"
    search.write_text(SearchRoundInput(
        candidate_id="CAND_FIXTURE",
        keywords=["backend engineer"],
        hard_constraints={"cities": ["Shanghai"]},
        top_per_query=30,
    ).model_dump_json(), encoding="utf-8")
    runner = CliRunner()
    page = runner.invoke(app, [
        "memory", "workflow-page", "--config", str(settings), "--limit", "10", "--offset", "0",
    ])
    assert page.exit_code == 0, page.output
    assert json.loads(page.output)["signals"][0]["signal_record_id"] == "rec_signal_grade"
    history = runner.invoke(app, [
        "feishu", "record-history", "--config", str(settings), "--request", str(history_request),
    ])
    assert history.exit_code == 0, history.output
    assert json.loads(history.output)["before_value"] == "B"
    enriched = runner.invoke(app, [
        "memory", "enrich-signal", "--config", str(settings),
        "--record-id", "rec_signal_grade", "--operators", str(operators),
    ])
    assert enriched.exit_code == 0, enriched.output
    assert json.loads(enriched.output)["learning_status"] == "pending_dream"
    published = runner.invoke(app, [
        "memory", "publish-version", "--config", str(settings), "--request", str(draft),
    ])
    assert published.exit_code == 0, published.output
    assert json.loads(published.output)["version"] == "1"
    planned = runner.invoke(app, [
        "memory", "search-round", "--config", str(settings), "--request", str(search),
    ])
    assert planned.exit_code == 0, planned.output
    plan = json.loads(planned.output)
    assert plan["applied"] is True
    assert plan["memory_version"] == "1"
    assert plan["keywords"] == ["backend engineer", "data platform"]
    assert plan["hard_constraints"] == {"cities": ["Shanghai"]}
    assert plan["top_per_query"] == 30
    assert plan["grants_fetch"] is False
    assert not list(tmp_path.glob("*.sqlite*"))
    assert all("BASE_SYNTHETIC" in call for call in base.calls if "--base-token" in call)
