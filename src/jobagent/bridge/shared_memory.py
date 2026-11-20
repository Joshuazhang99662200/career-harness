"""Read Workflow signals and publish memory versions. Does not call a model."""

from typing import Never

from pydantic import JsonValue

from jobagent.bridge.feishu_gateway import FeishuGateway
from jobagent.errors import ContractValidationError
from jobagent.memory.publication import (
    assert_publishable,
    decode_memory_row,
    memory_field_names,
    memory_row_fields,
    published_memory_id,
)
from jobagent.memory.search_round import plan_search_round
from jobagent.memory.workflow_signal import WorkflowSignalLedger, parse_workflow_signal
from jobagent.schemas.feishu import FeishuPatch, FeishuRecord
from jobagent.schemas.memory_signal import OperatorDirectory
from jobagent.schemas.shared_memory import (
    GREETING_MEMORY_FIELDS,
    HUMAN_SIGNAL_FIELD_COUNT,
    HUMAN_SIGNAL_FIELDS,
    HUMAN_SIGNAL_MUTABLE_FIELDS,
    PRODUCTION_TABLE_IDS,
    SEARCH_MEMORY_FIELDS,
    LearningStatus,
    MemoryPublishRequest,
    MemoryPublishResult,
    RecordHistoryDiff,
    SearchRoundInput,
    SearchRoundPlan,
    SignalEnrichment,
    StoredMemoryRow,
    WorkflowSignalPage,
)


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


class SharedMemoryService:
    """Infrastructure for Human Signals and the two memory tables.

    GPT supplies attribution and Dream output. This service checks schema,
    deduplicates, versions, and writes. A failed write does not advance
    ``learning_status``.
    """

    def __init__(self, gateway: FeishuGateway, operators: OperatorDirectory) -> None:
        self.gateway = gateway
        self.operators = OperatorDirectory.model_validate(operators.model_dump())
        self.ledger = WorkflowSignalLedger()

    def page_workflow_signals(
        self,
        *,
        limit: int,
        offset: int,
        expected_table_revision: int | str | None = None,
    ) -> WorkflowSignalPage:
        self._validate_human_signals()
        page = self.gateway.query(
            "human_signals",
            fields=list(HUMAN_SIGNAL_FIELDS),
            conditions=[["learning_status", "is", "pending_history_enrichment"]],
            limit=limit,
            offset=offset,
            expected_table_revision=expected_table_revision,
        )
        signals = [
            self.ledger.receive(parse_workflow_signal(record.record_id, record.fields))
            for record in page.records
        ]
        return WorkflowSignalPage(
            signals=signals,
            has_more=page.has_more,
            next_offset=page.next_offset,
            table_revision=page.table_revision,
        )

    def enrich_signal(self, signal_record_id: str, *, max_pages: int = 20) -> SignalEnrichment:
        self._validate_human_signals()
        current = self.gateway.get("human_signals", signal_record_id)
        parsed = parse_workflow_signal(current.record_id, current.fields)
        if parsed.learning_status != "pending_history_enrichment":
            return SignalEnrichment(
                signal_record_id=signal_record_id,
                duplicate=True,
                advanced=False,
                learning_status=parsed.learning_status,
                human_feedback=False,
                reason="duplicate",
                write_verified=True,
            )
        diff = self.gateway.record_history(
            "jobs",
            parsed.source_record_id,
            parsed.field_id,
            operators=self.operators,
            max_pages=max_pages,
        )
        fresh = self.gateway.get("human_signals", signal_record_id)
        if (
            fresh.content_digest != current.content_digest
            or fresh.fields.get("learning_status") != "pending_history_enrichment"
        ):
            refreshed = parse_workflow_signal(fresh.record_id, fresh.fields)
            return SignalEnrichment(
                signal_record_id=signal_record_id,
                duplicate=True,
                advanced=False,
                learning_status=refreshed.learning_status,
                human_feedback=False,
                reason="duplicate",
                write_verified=True,
                diff=diff,
            )
        target: LearningStatus = "pending_dream" if diff.reason == "matched_human" else "unknown"
        receipt = self.gateway.patch(FeishuPatch(
            table="human_signals",
            record_id=signal_record_id,
            role="memory",
            expected_digest=fresh.content_digest,
            fields=_enrichment_fields(diff, target),
            evidence_reference="signal-enrich:" + signal_record_id,
        ))
        if not receipt.verified:
            return SignalEnrichment(
                signal_record_id=signal_record_id,
                duplicate=False,
                advanced=False,
                learning_status=parsed.learning_status,
                human_feedback=False,
                reason="write_unverified",
                write_verified=False,
                diff=diff,
            )
        return SignalEnrichment(
            signal_record_id=signal_record_id,
            duplicate=False,
            advanced=True,
            learning_status=target,
            human_feedback=diff.reason == "matched_human",
            reason=diff.reason,
            write_verified=True,
            diff=diff,
        )

    def publish_memory(self, request: MemoryPublishRequest) -> MemoryPublishResult:
        request = MemoryPublishRequest.model_validate(request.model_dump())
        memory = request.memory
        key = assert_publishable(memory)
        if published_memory_id(memory.model_dump(), request.signal_record_id) != memory.memory_id:
            _reject("Memory id does not match the publication body.")
        self._validate_memory_table(key)
        self._validate_human_signals()
        current = self.gateway.get("human_signals", request.signal_record_id)
        parsed = parse_workflow_signal(current.record_id, current.fields)
        if parsed.source_record_id != memory.record_id:
            _reject("Memory publication points at a different job record than the signal.")
        if key == "search_memory" and parsed.memory_domain != "search_match":
            _reject("Memory kind does not match the signal domain.")
        if key == "greeting_memory" and parsed.memory_domain != "greeting":
            _reject("Memory kind does not match the signal domain.")
        rows = [
            decode_memory_row(
                record.record_id, record.fields, greeting=key == "greeting_memory"
            )
            for record in self._collect(
                key,
                list(memory_field_names(memory.kind)),
                [["candidate_id", "is", memory.candidate_id]],
            )
        ]
        existing = next((row for row in rows if row.memory.memory_id == memory.memory_id), None)
        if existing is not None:
            return self._finish_existing(request.signal_record_id, parsed.learning_status, existing)
        if parsed.learning_status != "pending_dream":
            _reject("Memory publish requires a signal that finished history enrichment.")
        same_kind = [row for row in rows if row.memory.kind == memory.kind]
        version = str(1 + max((int(row.version) for row in same_kind), default=0))
        published_rows = [row for row in same_kind if row.publication_status == "published"]
        supersedes = (
            max((row.version for row in published_rows), key=int) if published_rows else None
        )
        receipt = self.gateway.append_memory_row(key, memory_row_fields(
            memory,
            request.signal_record_id,
            version=version,
            publication_status="published",
            supersedes_version=supersedes,
        ))
        if not receipt.verified or receipt.record_id is None:
            return MemoryPublishResult(
                duplicate=False,
                verified=False,
                advanced_to_learned=False,
                learning_status=parsed.learning_status,
            )
        retained: list[str] = []
        for row in published_rows:
            if not self._retain(key, row.record_id, memory.memory_id):
                return MemoryPublishResult(
                    duplicate=False,
                    verified=False,
                    advanced_to_learned=False,
                    learning_status="pending_dream",
                    version=version,
                    record_id=receipt.record_id,
                    retained_record_ids=retained,
                )
            retained.append(row.record_id)
        advanced = self._set_learning_status(request.signal_record_id, "learned")
        return MemoryPublishResult(
            duplicate=False,
            verified=True,
            advanced_to_learned=advanced,
            learning_status="learned" if advanced else "pending_dream",
            version=version,
            record_id=receipt.record_id,
            retained_record_ids=retained,
        )

    def read_search_round(self, round_input: SearchRoundInput) -> SearchRoundPlan:
        round_input = SearchRoundInput.model_validate(round_input.model_dump())
        self._validate_memory_table("search_memory")
        rows = []
        for record in self._collect(
            "search_memory",
            list(SEARCH_MEMORY_FIELDS),
            [
                ["candidate_id", "is", round_input.candidate_id],
                ["publication_status", "is", "published"],
                ["kind", "is", "search"],
            ],
        ):
            row = decode_memory_row(record.record_id, record.fields, greeting=False)
            if row.publication_status != "published" or row.memory.kind != "search":
                _reject("Search memory row does not match the published search query.")
            if row.memory.candidate_id != round_input.candidate_id:
                _reject("Search memory belongs to another candidate.")
            rows.append(row)
        return plan_search_round(rows, round_input)

    def _finish_existing(
        self, signal_record_id: str, status: LearningStatus, existing: StoredMemoryRow
    ) -> MemoryPublishResult:
        if status == "pending_history_enrichment":
            _reject("Memory publish requires a signal that finished history enrichment.")
        advanced = False
        if status == "pending_dream":
            advanced = self._set_learning_status(signal_record_id, "learned")
        learned = status == "learned" or advanced
        return MemoryPublishResult(
            duplicate=True,
            verified=True,
            advanced_to_learned=advanced,
            learning_status="learned" if learned else status,
            version=existing.version,
            record_id=existing.record_id,
        )

    def _set_learning_status(self, signal_record_id: str, status: LearningStatus) -> bool:
        current = self.gateway.get("human_signals", signal_record_id)
        if current.fields.get("learning_status") == status:
            return True
        receipt = self.gateway.patch(FeishuPatch(
            table="human_signals",
            record_id=signal_record_id,
            role="memory",
            expected_digest=current.content_digest,
            fields={"learning_status": status},
            evidence_reference="memory-status:" + signal_record_id,
        ))
        return receipt.verified

    def _retain(self, key: str, record_id: str, memory_id: str) -> bool:
        current = self.gateway.get(key, record_id)
        if current.fields.get("publication_status") == "retained":
            return True
        receipt = self.gateway.patch(FeishuPatch(
            table=key,
            record_id=record_id,
            role="memory",
            expected_digest=current.content_digest,
            fields={"publication_status": "retained"},
            evidence_reference="memory-retain:" + memory_id,
        ))
        return receipt.verified

    def _collect(
        self, key: str, fields: list[str], conditions: list[list[JsonValue]]
    ) -> list[FeishuRecord]:
        offset = 0
        revision: int | str | None = None
        found: list[FeishuRecord] = []
        while True:
            page = self.gateway.query(
                key,
                fields=fields,
                conditions=conditions,
                limit=200,
                offset=offset,
                expected_table_revision=revision,
            )
            found.extend(page.records)
            if not page.has_more:
                return found
            if page.next_offset is None or page.table_revision is None:
                _reject("Shared table page did not continue safely.")
            offset = page.next_offset
            revision = page.table_revision
            if len(found) > 5000:
                _reject("Shared table read stopped before the page sequence finished.")

    def _validate_human_signals(self) -> None:
        table = self.gateway.config.tables.get("human_signals")
        if table is None or table.table_id != PRODUCTION_TABLE_IDS["human_signals"]:
            _reject("Human Signals is not bound to the production table.")
        if set(table.fields) != set(HUMAN_SIGNAL_FIELDS):
            _reject("Human Signals mapping must be exactly the known semantic fields.")
        if set(table.writable.get("memory", [])) != set(HUMAN_SIGNAL_MUTABLE_FIELDS):
            _reject("Memory role may only update enrichment and learning_status.")
        live = self.gateway.catalog("human_signals")
        if len(live) != HUMAN_SIGNAL_FIELD_COUNT:
            _reject("Human Signals schema does not have the 19 existing fields.")
        seen: set[str] = set()
        for field in live:
            field_id = field.get("id")
            kind = field.get("type")
            if not isinstance(field_id, str) or field_id in seen:
                _reject("Human Signals fields must stay text or datetime.")
            if kind not in {"text", "datetime"}:
                _reject("Human Signals fields must stay text or datetime.")
            seen.add(field_id)
        mapped = self.gateway.schema("human_signals")
        for name in HUMAN_SIGNAL_FIELDS:
            expected = "datetime" if name == "changed_at" else "text"
            if mapped[name].get("type") != expected:
                _reject("Human Signals field type does not match the existing column.")

    def _validate_memory_table(self, key: str) -> None:
        names = GREETING_MEMORY_FIELDS if key == "greeting_memory" else SEARCH_MEMORY_FIELDS
        table = self.gateway.config.tables.get(key)
        if table is None or table.table_id != PRODUCTION_TABLE_IDS[key]:
            _reject("Memory table is not bound to the production table.")
        if set(table.fields) != set(names):
            _reject("Memory mapping does not match the semantic contract.")
        if set(table.writable.get("memory", [])) != set(names):
            _reject("Memory role must be able to write exactly the semantic columns.")
        mapped = self.gateway.schema(key)
        for name in names:
            if mapped[name].get("type") != "text":
                _reject("Memory columns used by this contract must be text.")


def _enrichment_fields(diff: RecordHistoryDiff, target: LearningStatus) -> dict[str, JsonValue]:
    fields: dict[str, JsonValue] = {"learning_status": target}
    if diff.before_value is not None and diff.after_value is not None:
        fields["before_value"] = diff.before_value
        fields["after_value"] = diff.after_value
    if diff.changed_at is not None:
        fields["changed_at"] = diff.changed_at
    if diff.operator.kind in {"human", "bot"}:
        identity = diff.operator.open_id or diff.operator.union_id
        if identity:
            fields["operator_id"] = identity
        if diff.operator.display_name:
            fields["operator_name"] = diff.operator.display_name
    return fields
