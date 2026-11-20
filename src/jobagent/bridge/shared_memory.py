"""Read Workflow signals and publish memory versions. Does not call a model."""

import json
import threading
from datetime import datetime
from typing import Never

from pydantic import JsonValue

from jobagent.bridge.feishu_gateway import FeishuGateway
from jobagent.digest import canonical_digest, canonical_json, text_digest
from jobagent.errors import ContractValidationError
from jobagent.memory.publication import (
    assert_publishable,
    decode_memory_row,
    memory_field_names,
    memory_row_fields,
    published_memory_id,
)
from jobagent.memory.search_round import plan_search_round
from jobagent.memory.snapshot import (
    decode_source_signal_ids,
    encode_source_signal_ids,
    fold_search_snapshot,
)
from jobagent.memory.workflow_signal import WorkflowSignalLedger, parse_workflow_signal
from jobagent.schemas.feishu import FeishuPatch, FeishuRecord
from jobagent.schemas.memory_signal import OperatorDirectory, PublishedMemory
from jobagent.schemas.shared_memory import (
    GREETING_MEMORY_FIELDS,
    HUMAN_SIGNAL_FIELD_COUNT,
    HUMAN_SIGNAL_FIELDS,
    HUMAN_SIGNAL_MUTABLE_FIELDS,
    PRODUCTION_TABLE_IDS,
    SEARCH_MEMORY_FIELDS,
    DreamBatchComplete,
    DreamBatchResult,
    DreamBatchSnapshot,
    DreamBatchStart,
    FetchMemoryPin,
    LearningStatus,
    MemoryPublishRequest,
    MemoryPublishResult,
    RecordHistoryDiff,
    SearchRoundInput,
    SearchRoundPlan,
    SignalEnrichment,
    StoredMemoryRow,
    WorkflowSignal,
    WorkflowSignalPage,
)


def _reject(message: str) -> Never:
    raise ContractValidationError(message)


class SharedMemoryService:
    """Infrastructure for Human Signals and the two memory tables.

    GPT supplies attribution and Dream output. This service checks schema,
    deduplicates, versions, and writes. A failed write does not advance
    ``learning_status``.

    Publish is single-writer for one candidate and memory kind inside this
    process. ``_publish_claims`` is that technical claim. It is not a business
    ledger and it cannot see a publisher in another process. After the writes,
    the version set is read back; duplicate versions or more than one published
    row block ``learned``.
    """

    def __init__(self, gateway: FeishuGateway, operators: OperatorDirectory) -> None:
        self.gateway = gateway
        self.operators = OperatorDirectory.model_validate(operators.model_dump())
        self.ledger = WorkflowSignalLedger()
        self._publish_guard = threading.Lock()
        self._publish_claims: set[tuple[str, str]] = set()

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
        claim = (memory.candidate_id, memory.kind)
        self._claim_publish(claim)
        try:
            return self._publish_serial(request, memory, key, parsed.learning_status)
        finally:
            self._release_publish(claim)

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

    def start_dream_batch(self, request: DreamBatchStart) -> DreamBatchSnapshot:
        """Freeze pending human signals. A later edit stays out of this batch."""
        request = DreamBatchStart.model_validate(request.model_dump())
        _aware(request.cutoff)
        claim = (request.candidate_id, "dream-batch")
        self._claim_publish(claim)
        try:
            return self._start_dream_batch(request)
        finally:
            self._release_publish(claim)

    def complete_dream_batch(self, request: DreamBatchComplete) -> DreamBatchResult:
        """Publish one complete snapshot for the frozen signals, then mark them learned."""
        request = DreamBatchComplete.model_validate(request.model_dump())
        claim = (request.snapshot.candidate_id, "dream-batch")
        kind_claim = (request.snapshot.candidate_id, "search")
        self._claim_publish(claim)
        try:
            self._claim_publish(kind_claim)
            try:
                return self._complete_dream_batch(request)
            finally:
                self._release_publish(kind_claim)
        finally:
            self._release_publish(claim)

    def pin_fetch_memory(self, round_input: SearchRoundInput) -> FetchMemoryPin:
        """Read the latest unique published snapshot and pin it for one Fetch round."""
        round_input = SearchRoundInput.model_validate(round_input.model_dump())
        self._validate_memory_table("search_memory")
        rows = self._published_search_rows(round_input.candidate_id)
        plan = plan_search_round(rows, round_input)
        if not rows:
            return _pin_from_plan(plan, content_hash=None)
        row = rows[0]
        return _pin_from_plan(plan, content_hash=row.body_digest, record_id=row.record_id)

    def continue_fetch(self, pin: FetchMemoryPin, round_input: SearchRoundInput) -> FetchMemoryPin:
        """Keep the pinned version even when a newer snapshot is already published."""
        pin = FetchMemoryPin.model_validate(pin.model_dump())
        round_input = SearchRoundInput.model_validate(round_input.model_dump())
        if not pin.applied or pin.memory_record_id is None or pin.content_hash is None:
            return self.pin_fetch_memory(round_input)
        self._validate_memory_table("search_memory")
        if pin.candidate_id != round_input.candidate_id:
            _reject("Fetch pin belongs to another candidate.")
        record = self.gateway.get("search_memory", pin.memory_record_id)
        row = decode_memory_row(record.record_id, record.fields, greeting=False)
        if row.version != pin.memory_version or row.body_digest != pin.content_hash:
            _reject("Pinned search memory failed version or content hash validation.")
        if row.memory.candidate_id != round_input.candidate_id or row.memory.kind != "search":
            _reject("Pinned search memory does not match this Fetch round.")
        # The pinned row may already be retained. The Fetch keeps that content.
        pinned_row = row.model_copy(update={"publication_status": "published"})
        plan = plan_search_round([pinned_row], round_input)
        return _pin_from_plan(plan, content_hash=row.body_digest, record_id=row.record_id)

    def _start_dream_batch(self, request: DreamBatchStart) -> DreamBatchSnapshot:
        self._validate_human_signals()
        records, data_version = self._pending_signal_page()
        parsed = [parse_workflow_signal(record.record_id, record.fields) for record in records]
        open_batches = [item for item in parsed if _batch_stamp(item) is not None]
        if open_batches:
            return self._resume_batch(request.candidate_id, open_batches)
        eligible = [
            item for item in parsed
            if _human_ready(item, self.operators)
            and item.changed_at is not None
            and _at_or_before(item.changed_at, request.cutoff)
            and _batch_stamp(item) is None
        ]
        eligible.sort(key=lambda item: (item.changed_at or "", item.signal_record_id))
        chosen = eligible[: request.batch_size]
        overflow = [item.signal_record_id for item in eligible[request.batch_size :]]
        signal_ids = [item.signal_record_id for item in chosen]
        batch_id = canonical_digest({
            "candidate_id": request.candidate_id,
            "cutoff": request.cutoff,
            "data_version": data_version,
            "signal_ids": signal_ids,
        })
        snapshot = DreamBatchSnapshot(
            batch_id=batch_id,
            candidate_id=request.candidate_id,
            cutoff=request.cutoff,
            data_version=data_version,
            signal_ids=signal_ids,
            overflow_signal_ids=overflow,
            resumed=False,
        )
        self._stamp_batch(snapshot)
        return snapshot

    def _resume_batch(self, candidate_id: str, signals: list[WorkflowSignal]) -> DreamBatchSnapshot:
        stamps = [_batch_stamp(item) for item in signals]
        if any(item is None for item in stamps):
            _reject("An unfinished Dream batch could not be read.")
        batch_ids = {str(item["batch_id"]) for item in stamps if item is not None}
        if len(batch_ids) != 1:
            _reject("More than one unfinished Dream batch is open for this candidate.")
        stamp = next(item for item in stamps if item is not None)
        if str(stamp.get("candidate_id")) != candidate_id:
            _reject("Unfinished Dream batch belongs to another candidate.")
        raw_ids = stamp.get("signal_ids")
        if not isinstance(raw_ids, list):
            _reject("Unfinished Dream batch does not name its frozen signals.")
        signal_ids: list[str] = []
        for item in raw_ids:
            if not isinstance(item, str) or not item:
                _reject("Unfinished Dream batch does not name its frozen signals.")
            signal_ids.append(item)
        pending = {item.signal_record_id for item in signals}
        frozen = [item for item in signal_ids if item in pending]
        return DreamBatchSnapshot(
            batch_id=str(stamp["batch_id"]),
            candidate_id=candidate_id,
            cutoff=str(stamp["cutoff"]),
            data_version=str(stamp["data_version"]),
            signal_ids=frozen,
            overflow_signal_ids=[],
            resumed=True,
        )

    def _complete_dream_batch(self, request: DreamBatchComplete) -> DreamBatchResult:
        snapshot = request.snapshot
        signals = self._frozen_signals(snapshot)
        if [item.signal_record_id for item in signals] != list(snapshot.signal_ids):
            _reject("Dream batch signals do not match the frozen snapshot.")
        by_id = {item.signal_record_id: item for item in request.deltas}
        same_signals = set(by_id) == set(snapshot.signal_ids)
        if not same_signals or len(request.deltas) != len(snapshot.signal_ids):
            _reject("Dream batch deltas must cover the frozen signals exactly once.")
        ordered = sorted(signals, key=lambda item: (item.changed_at or "", item.signal_record_id))
        deltas = [by_id[item.signal_record_id] for item in ordered]
        previous = self._current_search_memory(snapshot.candidate_id)
        keywords, directions, exclusions = fold_search_snapshot(
            None if previous is None else previous.memory, deltas
        )
        anchor = ordered[-1]
        ordered_ids = [item.signal_record_id for item in ordered]
        covering = self._published_covering(snapshot.candidate_id, ordered_ids)
        if covering is not None:
            learned, pending = self._mark_batch_learned(ordered)
            return DreamBatchResult(
                batch_id=snapshot.batch_id,
                verified=not pending,
                republished=False,
                memory_version=covering.version,
                memory_record_id=covering.record_id,
                learned_signal_ids=learned,
                pending_signal_ids=pending,
                keywords=keywords,
                role_directions=directions,
                exclusions=exclusions,
            )
        source_ids = encode_source_signal_ids(ordered_ids)
        reasons = "; ".join(delta.reason for delta in deltas)
        draft = {
            "kind": "search",
            "preference": "Matching Preference / Calibration",
            "candidate_id": snapshot.candidate_id,
            "source_signal_id": source_ids,
            "record_id": anchor.source_record_id,
            "job_id": request.job_id,
            "reason": reasons,
            "keywords": keywords,
            "role_directions": directions,
            "exclusions": exclusions,
            "notes": [],
            "jd_digest": text_digest(canonical_json({
                "keywords": keywords,
                "role_directions": directions,
                "exclusions": exclusions,
            })),
        }
        draft["memory_id"] = published_memory_id(draft, anchor.signal_record_id)
        memory = PublishedMemory.model_validate({
            **draft, "source_event_id": anchor.signal_record_id,
        })
        published = self._publish_serial(
            MemoryPublishRequest(signal_record_id=anchor.signal_record_id, memory=memory),
            memory,
            "search_memory",
            anchor.learning_status,
            advance_signal=False,
        )
        stored_ids = decode_source_signal_ids(memory.source_signal_id)
        if stored_ids != ordered_ids:
            _reject("Published memory source_signal_ids do not match the frozen batch.")
        if not published.verified or published.version is None or published.record_id is None:
            return DreamBatchResult(
                batch_id=snapshot.batch_id,
                verified=False,
                republished=False,
                memory_version=published.version,
                memory_record_id=published.record_id,
                pending_signal_ids=list(snapshot.signal_ids),
                keywords=keywords,
                role_directions=directions,
                exclusions=exclusions,
            )
        learned, pending = self._mark_batch_learned(ordered)
        return DreamBatchResult(
            batch_id=snapshot.batch_id,
            verified=not pending,
            republished=not published.duplicate,
            memory_version=published.version,
            memory_record_id=published.record_id,
            learned_signal_ids=learned,
            pending_signal_ids=pending,
            keywords=keywords,
            role_directions=directions,
            exclusions=exclusions,
        )

    def _frozen_signals(self, snapshot: DreamBatchSnapshot) -> list[WorkflowSignal]:
        found: list[WorkflowSignal] = []
        for signal_id in snapshot.signal_ids:
            record = self.gateway.get("human_signals", signal_id)
            signal = parse_workflow_signal(record.record_id, record.fields)
            stamp = _batch_stamp(signal)
            if stamp is None or stamp.get("batch_id") != snapshot.batch_id:
                _reject("Frozen Dream signal belongs to another batch.")
            if signal.learning_status == "pending_dream":
                if not _human_ready(signal, self.operators):
                    _reject("Frozen Dream signal is not human feedback with a completed diff.")
            elif signal.learning_status != "learned":
                _reject("Frozen Dream signal is no longer pending in this batch.")
            found.append(signal)
        return found

    def _mark_batch_learned(self, signals: list[WorkflowSignal]) -> tuple[list[str], list[str]]:
        learned: list[str] = []
        pending: list[str] = []
        for signal in signals:
            if self._set_learning_status(signal.signal_record_id, "learned"):
                learned.append(signal.signal_record_id)
            else:
                pending.append(signal.signal_record_id)
        return learned, pending

    def _stamp_batch(self, snapshot: DreamBatchSnapshot) -> None:
        body = canonical_json({
            "dream_batch": {
                "batch_id": snapshot.batch_id,
                "candidate_id": snapshot.candidate_id,
                "cutoff": snapshot.cutoff,
                "data_version": snapshot.data_version,
                "signal_ids": list(snapshot.signal_ids),
            }
        })
        for signal_id in snapshot.signal_ids:
            current = self.gateway.get("human_signals", signal_id)
            if current.fields.get("source_context") not in (None, ""):
                _reject(
                    "Human Signal source_context is already in use; batch checkpoint has no column."
                )
            receipt = self.gateway.patch(FeishuPatch(
                table="human_signals",
                record_id=signal_id,
                role="memory",
                expected_digest=current.content_digest,
                fields={"source_context": body},
                evidence_reference="dream-batch:" + snapshot.batch_id,
            ))
            if not receipt.verified:
                _reject("Dream batch checkpoint was not written.")

    def _pending_signal_page(self) -> tuple[list[FeishuRecord], str]:
        offset = 0
        revision: int | str | None = None
        found: list[FeishuRecord] = []
        while True:
            page = self.gateway.query(
                "human_signals",
                fields=list(HUMAN_SIGNAL_FIELDS),
                conditions=[["learning_status", "is", "pending_dream"]],
                limit=200,
                offset=offset,
                expected_table_revision=revision,
            )
            if revision is None:
                if page.table_revision is None:
                    _reject("Human Signals page did not report a data version.")
                revision = page.table_revision
            found.extend(page.records)
            if not page.has_more:
                return found, str(revision)
            if page.next_offset is None:
                _reject("Human Signals page did not continue safely.")
            offset = page.next_offset
            if len(found) > 5000:
                _reject("Human Signals read stopped before the page sequence finished.")

    def _published_covering(
        self, candidate_id: str, signal_ids: list[str]
    ) -> StoredMemoryRow | None:
        rows = self._published_search_rows(candidate_id)
        if len(rows) != 1:
            return None
        if decode_source_signal_ids(rows[0].memory.source_signal_id) != signal_ids:
            return None
        return rows[0]

    def _current_search_memory(self, candidate_id: str) -> StoredMemoryRow | None:
        rows = self._published_search_rows(candidate_id)
        if not rows:
            return None
        if len(rows) != 1:
            _reject("More than one published search memory version is current.")
        return rows[0]

    def _published_search_rows(self, candidate_id: str) -> list[StoredMemoryRow]:
        rows = []
        for record in self._collect(
            "search_memory",
            list(SEARCH_MEMORY_FIELDS),
            [
                ["candidate_id", "is", candidate_id],
                ["publication_status", "is", "published"],
                ["kind", "is", "search"],
            ],
        ):
            row = decode_memory_row(record.record_id, record.fields, greeting=False)
            if row.publication_status != "published" or row.memory.kind != "search":
                _reject("Search memory row does not match the published search query.")
            rows.append(row)
        return rows

    def _claim_publish(self, claim: tuple[str, str]) -> None:
        """One in-process publisher per candidate and kind. Not a shared ledger."""
        with self._publish_guard:
            if claim in self._publish_claims:
                _reject(
                    "Memory publish is single-writer for this candidate and kind; "
                    "wait for the in-process publisher to finish."
                )
            self._publish_claims.add(claim)

    def _release_publish(self, claim: tuple[str, str]) -> None:
        with self._publish_guard:
            self._publish_claims.discard(claim)

    def _publish_serial(
        self,
        request: MemoryPublishRequest,
        memory: PublishedMemory,
        key: str,
        learning_status: LearningStatus,
        *,
        advance_signal: bool = True,
    ) -> MemoryPublishResult:
        rows = self._kind_rows(key, memory)
        existing = next((row for row in rows if row.memory.memory_id == memory.memory_id), None)
        created_id = existing.record_id if existing is not None else None
        version = existing.version if existing is not None else None
        duplicate = existing is not None
        if existing is None:
            if learning_status != "pending_dream":
                _reject("Memory publish requires a signal that finished history enrichment.")
            version = str(1 + max((int(row.version) for row in rows), default=0))
            if any(row.version == version for row in rows):
                return _publish_failure(learning_status, version, None)
            published = [row for row in rows if row.publication_status == "published"]
            supersedes = max((row.version for row in published), key=int) if published else None
            receipt = self.gateway.append_memory_row(key, memory_row_fields(
                memory,
                request.signal_record_id,
                version=version,
                publication_status="published",
                supersedes_version=supersedes,
            ))
            if not receipt.verified or receipt.record_id is None:
                return _publish_failure(learning_status, version, receipt.record_id)
            created_id = receipt.record_id
            rows = self._kind_rows(key, memory)
        closed, retained = self._close_previous(key, rows, memory.memory_id)
        if not closed:
            return _publish_failure(
                learning_status, version, created_id, retained, duplicate=duplicate
            )
        confirmed = self._kind_rows(key, memory)
        if not _one_current_publication(confirmed, memory.memory_id):
            current = next(
                (row for row in confirmed if row.memory.memory_id == memory.memory_id), None
            )
            return _publish_failure(
                learning_status,
                current.version if current is not None else version,
                current.record_id if current is not None else created_id,
                duplicate=duplicate,
            )
        if learning_status == "learned":
            current = next(row for row in confirmed if row.memory.memory_id == memory.memory_id)
            return MemoryPublishResult(
                duplicate=True,
                verified=True,
                advanced_to_learned=False,
                learning_status="learned",
                version=current.version,
                record_id=current.record_id,
            )
        if learning_status != "pending_dream":
            _reject("Memory publish requires a signal that finished history enrichment.")
        current = next(row for row in confirmed if row.memory.memory_id == memory.memory_id)
        if not advance_signal:
            return MemoryPublishResult(
                duplicate=duplicate,
                verified=True,
                advanced_to_learned=False,
                learning_status=learning_status,
                version=current.version,
                record_id=current.record_id,
                retained_record_ids=retained,
            )
        advanced = self._set_learning_status(request.signal_record_id, "learned")
        current = next(row for row in confirmed if row.memory.memory_id == memory.memory_id)
        return MemoryPublishResult(
            duplicate=duplicate,
            verified=advanced,
            advanced_to_learned=advanced,
            learning_status="learned" if advanced else learning_status,
            version=current.version,
            record_id=current.record_id,
            retained_record_ids=retained,
        )

    def _kind_rows(self, key: str, memory: PublishedMemory) -> list[StoredMemoryRow]:
        greeting = key == "greeting_memory"
        loaded = [
            decode_memory_row(record.record_id, record.fields, greeting=greeting)
            for record in self._collect(
                key,
                list(memory_field_names(memory.kind)),
                [["candidate_id", "is", memory.candidate_id]],
            )
        ]
        return [row for row in loaded if row.memory.kind == memory.kind]

    def _close_previous(
        self, key: str, rows: list[StoredMemoryRow], memory_id: str
    ) -> tuple[bool, list[str]]:
        retained: list[str] = []
        for row in rows:
            if row.memory.memory_id == memory_id or row.publication_status != "published":
                continue
            if not self._retain(key, row.record_id, memory_id):
                return False, retained
            retained.append(row.record_id)
        return True, retained

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


def _one_current_publication(rows: list[StoredMemoryRow], memory_id: str) -> bool:
    versions = [row.version for row in rows]
    if len(versions) != len(set(versions)):
        return False
    published = [row for row in rows if row.publication_status == "published"]
    return len(published) == 1 and published[0].memory.memory_id == memory_id


def _publish_failure(
    learning_status: LearningStatus,
    version: str | None,
    record_id: str | None,
    retained: list[str] | None = None,
    *,
    duplicate: bool = False,
) -> MemoryPublishResult:
    return MemoryPublishResult(
        duplicate=duplicate,
        verified=False,
        advanced_to_learned=False,
        learning_status=learning_status,
        version=version,
        record_id=record_id,
        retained_record_ids=list(retained or []),
    )


def _pin_from_plan(
    plan: SearchRoundPlan, *, content_hash: str | None, record_id: str | None = None
) -> FetchMemoryPin:
    return FetchMemoryPin(
        candidate_id=plan.candidate_id,
        memory_version=plan.memory_version,
        memory_record_id=record_id or plan.memory_record_id,
        content_hash=content_hash,
        last_consumed_version=plan.memory_version,
        applied=plan.applied,
        original_keywords=list(plan.original_keywords),
        keywords=list(plan.keywords),
        additions=list(plan.additions),
        exclusions=list(plan.exclusions),
        role_directions=list(plan.role_directions),
        hard_constraints=dict(plan.hard_constraints),
        queries_per_site_per_round=plan.queries_per_site_per_round,
        top_per_query=plan.top_per_query,
        search_frequency=plan.search_frequency,
    )


def _batch_stamp(signal: WorkflowSignal) -> dict[str, object] | None:
    if not signal.source_context:
        return None
    try:
        loaded = json.loads(signal.source_context)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    batch = loaded.get("dream_batch")
    if not isinstance(batch, dict) or not batch.get("batch_id"):
        return None
    return batch


def _human_ready(signal: WorkflowSignal, operators: OperatorDirectory) -> bool:
    if signal.learning_status != "pending_dream":
        return False
    before, after = signal.before_value, signal.after_value
    if not before or not after or before == after:
        return False
    if not signal.operator_id or not signal.changed_at:
        return False
    bot_ids = set(operators.bot_open_ids) | set(operators.bot_union_ids)
    if signal.operator_id in bot_ids:
        return False
    return (
        signal.operator_id in operators.human_open_ids
        or signal.operator_id in operators.human_union_ids
    )


def _aware(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ContractValidationError("Dream cutoff must be a timezone-aware timestamp.") from error
    if parsed.tzinfo is None:
        _reject("Dream cutoff must be a timezone-aware timestamp.")
    return parsed


def _at_or_before(changed_at: str, cutoff: str) -> bool:
    return _aware(changed_at) <= _aware(cutoff)


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
