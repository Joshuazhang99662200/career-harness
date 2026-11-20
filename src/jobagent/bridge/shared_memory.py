"""Read Workflow signals and publish memory versions. Does not call a model."""

import json
import threading
from datetime import datetime
from typing import Never
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import JsonValue

from jobagent.bridge.feishu_gateway import FeishuGateway
from jobagent.digest import canonical_digest, canonical_json, text_digest
from jobagent.errors import ContractValidationError
from jobagent.memory.publication import (
    assert_publishable,
    decode_memory_row,
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


# Process-wide coordination across independent service instances. This is not
# a cross-process/distributed lease; the host must serialize the whole Dream
# lifecycle and all writers for the same candidate/storage domain.
_PUBLISH_GUARD = threading.Lock()
_PUBLISH_CLAIMS: set[tuple[str, str]] = set()


class SharedMemoryService:
    """Infrastructure for Human Signals and the two memory tables.

    GPT supplies attribution and Dream output. This service checks schema,
    deduplicates, versions, and writes. A failed write does not advance
    ``learning_status``.

    Publish is single-writer for one candidate and memory kind inside this
    process. ``_publish_claims`` is that technical claim. It is not a business
    ledger and it cannot see a publisher in another process. Each candidate has
    one current record per memory domain. A new snapshot overwrites that
    record. History stays in Feishu record history, not in extra rows.
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
        if self._candidate_id_for_signal(parsed) != memory.candidate_id:
            _reject("Memory publication candidate does not match the source job record.")
        if key == "search_memory" and parsed.memory_domain != "search_match":
            _reject("Memory kind does not match the signal domain.")
        if key == "greeting_memory" and parsed.memory_domain != "greeting":
            _reject("Memory kind does not match the signal domain.")
        # "search" and "matching" both publish into the same physical table.
        claim = (memory.candidate_id, key)
        self._claim_publish(claim)
        try:
            return self._publish_serial(request, memory, key, parsed.learning_status)
        finally:
            self._release_publish(claim)

    def read_search_round(self, round_input: SearchRoundInput) -> SearchRoundPlan:
        round_input = SearchRoundInput.model_validate(round_input.model_dump())
        self._validate_memory_table("search_memory")
        rows = [
            row for row in self._search_record(round_input.candidate_id)
            if row.memory.kind == "search" and row.publication_status == "published"
        ]
        return plan_search_round(rows, round_input)

    def start_dream_batch(self, request: DreamBatchStart) -> DreamBatchSnapshot:
        """Freeze pending human signals. A later edit stays out of this batch."""
        request = DreamBatchStart.model_validate(request.model_dump())
        window_start = _aware(request.window_start)
        cutoff = _aware(request.cutoff)
        if window_start > cutoff:
            _reject("Dream observation window start must not be after its cutoff.")
        try:
            ZoneInfo(request.window_timezone)
        except ZoneInfoNotFoundError:
            _reject("Dream observation window timezone must be a valid IANA timezone.")
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
        kind_claim = (request.snapshot.candidate_id, "search_memory")
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
        rows = [
            row for row in self._search_record(round_input.candidate_id)
            if row.memory.kind == "search" and row.publication_status == "published"
        ]
        plan = plan_search_round(rows, round_input)
        if not rows:
            return _pin_from_plan(plan, content_hash=None)
        row = rows[0]
        return _pin_from_plan(plan, content_hash=row.body_digest, record_id=row.record_id)

    def continue_fetch(self, pin: FetchMemoryPin, round_input: SearchRoundInput) -> FetchMemoryPin:
        """Keep the pinned version even when a newer snapshot is already published."""
        pin = FetchMemoryPin.model_validate(pin.model_dump())
        round_input = SearchRoundInput.model_validate(round_input.model_dump())
        if pin.candidate_id != round_input.candidate_id:
            _reject("Fetch pin belongs to another candidate.")
        if not pin.applied:
            # No memory at round start is itself a pinned state. Do not adopt a
            # memory published halfway through this Fetch round.
            return pin
        if pin.memory_record_id is None or pin.content_hash is None:
            _reject("Applied Fetch pin is missing its memory identity or content hash.")
        self._validate_memory_table("search_memory")
        # The table keeps one current record, so an in-place update would replace
        # this round's snapshot. The pin already holds the snapshot observed at start.
        return pin

    def _start_dream_batch(self, request: DreamBatchStart) -> DreamBatchSnapshot:
        self._validate_human_signals()
        records, data_version = self._pending_signal_page()
        parsed = [parse_workflow_signal(record.record_id, record.fields) for record in records]
        open_batches = [
            item for item in parsed
            if _search_dream_signal(item)
            and (stamp := _batch_stamp(item)) is not None
            and stamp.get("candidate_id") == request.candidate_id
        ]
        if open_batches:
            return self._resume_batch(request.candidate_id, open_batches)
        eligible: list[WorkflowSignal] = []
        for item in parsed:
            if not _human_ready(item, self.operators):
                continue
            if item.changed_at is None or _batch_stamp(item) is not None:
                continue
            if not _at_or_after(item.changed_at, request.window_start):
                continue
            if not _at_or_before(item.changed_at, request.cutoff):
                continue
            if self._candidate_id_for_signal(item) != request.candidate_id:
                continue
            eligible.append(item)
        eligible.sort(key=lambda item: (item.changed_at or "", item.signal_record_id))
        chosen = eligible[: request.batch_size]
        overflow = [item.signal_record_id for item in eligible[request.batch_size :]]
        signal_ids = [item.signal_record_id for item in chosen]
        batch_id = canonical_digest({
            "candidate_id": request.candidate_id,
            "window_start": request.window_start,
            "window_timezone": request.window_timezone,
            "window_business_days": request.window_business_days,
            "cutoff": request.cutoff,
            "data_version": data_version,
            "signal_ids": signal_ids,
        })
        snapshot = DreamBatchSnapshot(
            batch_id=batch_id,
            candidate_id=request.candidate_id,
            window_start=request.window_start,
            window_timezone=request.window_timezone,
            window_business_days=request.window_business_days,
            cutoff=request.cutoff,
            data_version=data_version,
            signal_ids=signal_ids,
            overflow_signal_ids=overflow,
            resumed=False,
        )
        self._stamp_batch(snapshot)
        return snapshot

    def _resume_batch(self, candidate_id: str, signals: list[WorkflowSignal]) -> DreamBatchSnapshot:
        stamps = [
            stamp for item in signals
            if (stamp := _batch_stamp(item)) is not None
            and stamp.get("candidate_id") == candidate_id
        ]
        if not stamps:
            _reject("No unfinished Dream batch belongs to this candidate.")
        batch_ids = {str(item.get("batch_id")) for item in stamps}
        if len(batch_ids) != 1:
            _reject("More than one unfinished Dream batch is open for this candidate.")
        stamp = stamps[0]
        raw_ids = stamp.get("signal_ids")
        window_start = stamp.get("window_start")
        window_timezone = stamp.get("window_timezone")
        window_business_days = stamp.get("window_business_days")
        cutoff = stamp.get("cutoff")
        data_version = stamp.get("data_version")
        if (
            not isinstance(raw_ids, list)
            or not raw_ids
            or not isinstance(window_start, str)
            or not window_start
            or not isinstance(window_timezone, str)
            or not window_timezone
            or type(window_business_days) is not int
            or window_business_days != 10
            or not isinstance(cutoff, str)
            or not cutoff
            or not isinstance(data_version, str)
            or not data_version
        ):
            _reject("Unfinished Dream batch does not name its complete 10-workday observation window.")
        if _aware(window_start) > _aware(cutoff):
            _reject("Unfinished Dream batch has an invalid observation window.")
        try:
            ZoneInfo(window_timezone)
        except ZoneInfoNotFoundError:
            _reject("Unfinished Dream batch has an invalid IANA timezone.")
        signal_ids: list[str] = []
        for item in raw_ids:
            if not isinstance(item, str) or not item:
                _reject("Unfinished Dream batch does not name its frozen signals.")
            signal_ids.append(item)
        if len(signal_ids) != len(set(signal_ids)):
            _reject("Unfinished Dream batch contains duplicate signal ids.")
        snapshot = DreamBatchSnapshot(
            batch_id=str(stamp["batch_id"]),
            candidate_id=candidate_id,
            window_start=window_start,
            window_timezone=window_timezone,
            window_business_days=window_business_days,
            cutoff=cutoff,
            data_version=data_version,
            signal_ids=signal_ids,
            overflow_signal_ids=[],
            resumed=True,
        )
        expected_stamp = _batch_checkpoint(snapshot)
        # Recover the complete frozen set, including signals already marked learned.
        # A partial checkpoint write is also repaired here, but only into empty
        # source_context cells; conflicting context is never overwritten.
        for signal_id in signal_ids:
            record = self.gateway.get("human_signals", signal_id)
            signal = parse_workflow_signal(record.record_id, record.fields)
            if not _human_ready(signal, self.operators, allow_learned=True):
                _reject("Frozen Dream signal is no longer eligible human search feedback.")
            if self._candidate_id_for_signal(signal) != snapshot.candidate_id:
                _reject("Frozen Dream signal belongs to another candidate.")
            existing = _batch_stamp(signal)
            if existing is not None and existing != expected_stamp:
                _reject("Frozen Dream signal belongs to a different batch snapshot.")
            if existing is None and signal.source_context not in (None, ""):
                _reject("Frozen Dream signal has conflicting source_context.")
        self._stamp_batch(snapshot)
        return snapshot

    def _complete_dream_batch(self, request: DreamBatchComplete) -> DreamBatchResult:
        snapshot = request.snapshot
        if not snapshot.signal_ids:
            _reject("Dream batch is empty; skip model execution and completion.")
        if len(snapshot.signal_ids) != len(set(snapshot.signal_ids)):
            _reject("Dream batch contains duplicate signal ids.")
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
            None if previous is None else previous.memory, deltas, allow_empty=True
        )
        previous_keywords = [] if previous is None else previous.memory.keywords
        previous_directions = [] if previous is None else previous.memory.role_directions
        previous_exclusions = [] if previous is None else previous.memory.exclusions
        if (
            keywords == previous_keywords
            and directions == previous_directions
            and exclusions == previous_exclusions
        ):
            learned, pending = self._mark_batch_learned(ordered)
            return DreamBatchResult(
                batch_id=snapshot.batch_id,
                verified=not pending,
                republished=False,
                no_change=True,
                memory_version=None if previous is None else previous.version,
                memory_record_id=None if previous is None else previous.record_id,
                learned_signal_ids=learned,
                pending_signal_ids=pending,
                keywords=keywords,
                role_directions=directions,
                exclusions=exclusions,
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
                previous_snapshot_restored=published.previous_snapshot_restored,
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
        expected_stamp = _batch_checkpoint(snapshot)
        for signal_id in snapshot.signal_ids:
            record = self.gateway.get("human_signals", signal_id)
            signal = parse_workflow_signal(record.record_id, record.fields)
            if _batch_stamp(signal) != expected_stamp:
                _reject("Frozen Dream signal does not match the complete batch snapshot.")
            if not _human_ready(signal, self.operators, allow_learned=True):
                _reject("Frozen Dream signal is not eligible human search feedback.")
            if self._candidate_id_for_signal(signal) != snapshot.candidate_id:
                _reject("Frozen Dream signal belongs to another candidate.")
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
        expected = _batch_checkpoint(snapshot)
        body = canonical_json({"dream_batch": expected})
        for signal_id in snapshot.signal_ids:
            current = self.gateway.get("human_signals", signal_id)
            signal = parse_workflow_signal(current.record_id, current.fields)
            if not _human_ready(signal, self.operators, allow_learned=True):
                _reject("Only eligible human search signals can be frozen for Dream.")
            if self._candidate_id_for_signal(signal) != snapshot.candidate_id:
                _reject("Only signals owned by this candidate can be frozen for Dream.")
            existing = _batch_stamp(signal)
            if existing is not None:
                if existing != expected:
                    _reject("Human Signal is already frozen in a different Dream batch.")
                continue
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
        rows = self._search_record(candidate_id)
        if len(rows) != 1:
            return None
        if decode_source_signal_ids(rows[0].memory.source_signal_id) != signal_ids:
            return None
        return rows[0]

    def _current_search_memory(self, candidate_id: str) -> StoredMemoryRow | None:
        rows = self._search_record(candidate_id)
        if not rows:
            return None
        return rows[0]

    def _search_record(self, candidate_id: str) -> list[StoredMemoryRow]:
        return self._domain_rows("search_memory", candidate_id)

    def _claim_publish(self, claim: tuple[str, str]) -> None:
        """Claim one candidate/storage-domain slot across service instances in this process."""
        with _PUBLISH_GUARD:
            if claim in _PUBLISH_CLAIMS:
                _reject(
                    "Memory publish is single-writer for this candidate and storage domain; "
                    "wait for the current publisher to finish."
                )
            _PUBLISH_CLAIMS.add(claim)

    def _release_publish(self, claim: tuple[str, str]) -> None:
        with _PUBLISH_GUARD:
            _PUBLISH_CLAIMS.discard(claim)

    def _publish_serial(
        self,
        request: MemoryPublishRequest,
        memory: PublishedMemory,
        key: str,
        learning_status: LearningStatus,
        *,
        advance_signal: bool = True,
    ) -> MemoryPublishResult:
        if learning_status not in {"pending_dream", "learned"}:
            _reject("Memory publish requires a signal that finished history enrichment.")
        rows = self._domain_rows(key, memory.candidate_id)
        if len(rows) > 1:
            return _publish_failure(learning_status, None, None)
        expected = _expected_hash(memory, request.signal_record_id)
        duplicate = False
        if rows and rows[0].body_digest == expected:
            record_id = rows[0].record_id
            version = rows[0].version
            duplicate = True
        elif not rows:
            if learning_status != "pending_dream":
                _reject("Memory publish requires a signal that finished history enrichment.")
            version = "1"
            fields = memory_row_fields(
                memory, request.signal_record_id, version=version,
                publication_status="published", supersedes_version=None,
            )
            self.gateway.append_memory_row(key, fields)
            landed = self._confirmed_row(key, memory.candidate_id, None, expected, version)
            if landed is None:
                return _publish_failure(learning_status, None, None)
            record_id = landed.record_id
        else:
            if learning_status != "pending_dream":
                _reject("Memory publish requires a signal that finished history enrichment.")
            current = rows[0]
            version = str(int(current.version) + 1)
            fields = memory_row_fields(
                memory, request.signal_record_id, version=version,
                publication_status="published", supersedes_version=current.version,
            )
            live = self.gateway.get(key, current.record_id)
            previous_fields = dict(live.fields)
            self.gateway.patch(FeishuPatch(
                table=key,
                record_id=current.record_id,
                role="memory",
                expected_digest=live.content_digest,
                fields=fields,
                evidence_reference="memory-update:" + memory.memory_id,
            ))
            landed = self._confirmed_row(
                key, memory.candidate_id, current.record_id, expected, version
            )
            if landed is None:
                restored = self._restore_previous_snapshot(
                    key, current.record_id, previous_fields, fields,
                )
                return _publish_failure(
                    learning_status,
                    current.version,
                    current.record_id,
                    previous_snapshot_restored=restored,
                )
            record_id = current.record_id
        if not advance_signal or learning_status == "learned":
            return MemoryPublishResult(
                duplicate=duplicate or learning_status == "learned",
                verified=True,
                advanced_to_learned=False,
                learning_status=learning_status,
                version=version,
                record_id=record_id,
            )
        advanced = self._set_learning_status(request.signal_record_id, "learned")
        return MemoryPublishResult(
            duplicate=duplicate,
            verified=advanced,
            advanced_to_learned=advanced,
            learning_status="learned" if advanced else learning_status,
            version=version,
            record_id=record_id,
        )

    def _confirmed_row(
        self,
        key: str,
        candidate_id: str,
        record_id: str | None,
        expected_hash: str,
        version: str,
    ) -> StoredMemoryRow | None:
        """Re-read the one domain record. A matching hash means the write landed."""
        try:
            rows = self._domain_rows(key, candidate_id)
        except ContractValidationError:
            return None
        if len(rows) != 1:
            return None
        row = rows[0]
        if record_id is not None and row.record_id != record_id:
            return None
        if row.body_digest != expected_hash or row.version != version:
            return None
        if row.publication_status != "published":
            return None
        return row

    def _restore_previous_snapshot(
        self,
        key: str,
        record_id: str,
        previous_fields: dict[str, JsonValue],
        attempted_fields: dict[str, JsonValue],
    ) -> bool:
        """Restore only a provable partial write; never overwrite concurrent edits."""
        try:
            observed = self.gateway.get(key, record_id)
        except ContractValidationError:
            return False
        if observed.fields == previous_fields:
            return True
        if set(observed.fields) != set(previous_fields):
            return False
        for name, value in observed.fields.items():
            if name in attempted_fields:
                if value not in (previous_fields[name], attempted_fields[name]):
                    return False
            elif value != previous_fields[name]:
                return False
        restore_fields = {name: previous_fields[name] for name in attempted_fields}
        try:
            self.gateway.patch(FeishuPatch(
                table=key,
                record_id=record_id,
                role="memory",
                expected_digest=observed.content_digest,
                fields=restore_fields,
                evidence_reference="memory-restore:" + record_id,
            ))
            restored = self.gateway.get(key, record_id)
        except ContractValidationError:
            return False
        return restored.fields == previous_fields

    def _domain_rows(self, key: str, candidate_id: str) -> list[StoredMemoryRow]:
        greeting = key == "greeting_memory"
        names = GREETING_MEMORY_FIELDS if greeting else SEARCH_MEMORY_FIELDS
        records = self._collect(
            key, list(names), [["candidate_id", "is", candidate_id]],
        )
        # Rows retained by the superseded multi-row publisher are inert history.
        # Continue only when exactly one current published row exists. If only
        # retained rows remain, do not silently treat that candidate as memory-free.
        statuses = [record.fields.get("publication_status") for record in records]
        if any(
            not isinstance(status, str) or status not in {"published", "retained"}
            for status in statuses
        ):
            _reject("Memory row has an unknown publication status.")
        published_records = [
            record for record in records if record.fields.get("publication_status") == "published"
        ]
        if records and not published_records:
            _reject("Only legacy retained memory rows remain; reconcile before publishing.")
        loaded = [
            decode_memory_row(record.record_id, record.fields, greeting=greeting)
            for record in published_records
        ]
        if len(loaded) > 1:
            _reject("This candidate has more than one published memory record in this domain.")
        return loaded

    def _candidate_id_for_signal(self, signal: WorkflowSignal) -> str:
        """Resolve candidate ownership through the configured source Jobs record."""
        jobs = self.gateway.config.tables.get("jobs")
        if jobs is None or "candidate_id" not in jobs.fields:
            _reject("Jobs mapping must include the candidate_id field before Memory can publish.")
        schema = self.gateway.schema("jobs")
        if schema["candidate_id"].get("type") != "text":
            _reject("Jobs candidate_id must be a text field in the live schema.")
        source = self.gateway.get("jobs", signal.source_record_id)
        candidate_id = source.fields.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            _reject("Source job record has no verified candidate_id.")
        return candidate_id

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


def _expected_hash(memory: PublishedMemory, signal_record_id: str) -> str:
    digest = memory_row_fields(
        memory, signal_record_id, version="1",
        publication_status="published", supersedes_version=None,
    )["content_digest"]
    if not isinstance(digest, str):
        _reject("Memory content hash is missing.")
    return digest


def _publish_failure(
    learning_status: LearningStatus,
    version: str | None,
    record_id: str | None,
    retained: list[str] | None = None,
    *,
    duplicate: bool = False,
    previous_snapshot_restored: bool | None = None,
) -> MemoryPublishResult:
    return MemoryPublishResult(
        duplicate=duplicate,
        verified=False,
        advanced_to_learned=False,
        previous_snapshot_restored=previous_snapshot_restored,
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


def _batch_checkpoint(snapshot: DreamBatchSnapshot) -> dict[str, object]:
    return {
        "batch_id": snapshot.batch_id,
        "candidate_id": snapshot.candidate_id,
        "window_start": snapshot.window_start,
        "window_timezone": snapshot.window_timezone,
        "window_business_days": snapshot.window_business_days,
        "cutoff": snapshot.cutoff,
        "data_version": snapshot.data_version,
        "signal_ids": list(snapshot.signal_ids),
    }


def _search_dream_signal(signal: WorkflowSignal) -> bool:
    return (
        signal.signal_type == "matching_correction"
        and signal.memory_domain == "search_match"
    )


def _human_ready(
    signal: WorkflowSignal,
    operators: OperatorDirectory,
    *,
    allow_learned: bool = False,
) -> bool:
    if not _search_dream_signal(signal):
        return False
    if signal.learning_status != "pending_dream" and not (
        allow_learned and signal.learning_status == "learned"
    ):
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


def _at_or_after(changed_at: str, window_start: str) -> bool:
    return _aware(changed_at) >= _aware(window_start)


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
