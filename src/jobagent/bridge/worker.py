"""Bounded worker gateway: observations in, approved single sends out, receipts back.

This adapter never operates a browser, approves content, or accepts arbitrary SQL.
The host executor must obey its own access checks and report uncertain results.
"""

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.connectors.observations import check_observation
from jobagent.digest import canonical_digest, spaced_json_digest
from jobagent.errors import ApprovalRequiredError, ContractValidationError, JobAgentError
from jobagent.jobs.normalization import JobNormalizer
from jobagent.jobs.shared_send_gate import current_work_decision
from jobagent.outreach.service import OutreachService, contacted_job_ids
from jobagent.schemas.applications import ApprovalChannel
from jobagent.schemas.common import ContractModel
from jobagent.schemas.feishu import FeishuRecord, SharedSendPolicy, SharedWorkDecision
from jobagent.schemas.job_intelligence import (
    ImportedObservation,
    JobSearchHit,
    ObservationImportReport,
    RejectedObservation,
)
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAudit,
    OutreachBatch,
    OutreachItem,
    OutreachResult,
)
from jobagent.schemas.sources import SourceManifest
from jobagent.schemas.worker import (
    WorkerEvent,
    WorkerEventAck,
    WorkerFetchReceipt,
    WorkerFetchRequest,
    WorkerFetchStatus,
    WorkerReadback,
    WorkerSendClaim,
    WorkerSendReceipt,
)
from jobagent.sources import SourceRegistry
from jobagent.storage.database import Database
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.worker_repository import SqliteWorkerRepository, WorkerState


def _digest(value: ContractModel) -> str:
    return spaced_json_digest(value.model_dump(mode="json"))


def _event_id(task_id: str) -> str:
    return "WEVT_" + hashlib.sha256(task_id.encode()).hexdigest()[:24].upper()


class SharedJobReader(Protocol):
    """Re-read one current shared record. Implementations must not serve a stale copy."""

    def current(self, record_id: str) -> FeishuRecord: ...


class WorkerGateway:
    def __init__(
        self,
        database: Database,
        *,
        manifests: Sequence[SourceManifest] | None = None,
        clock: Callable[[], datetime] | None = None,
        shared: SharedJobReader | None = None,
        shared_record_id: str | None = None,
        send_policy: SharedSendPolicy | None = None,
    ) -> None:
        self.database = database
        self.clock = clock or (lambda: datetime.now(UTC))
        self.manifests = {
            m.id: m for m in (SourceRegistry.default().all() if manifests is None else manifests)
        }
        self.store = SqliteWorkerRepository(database)
        self.jobs = SqliteJobRepository(database)
        self.outreach = SqliteOutreachRepository(database)
        self.service = OutreachService()
        self.shared = shared
        self.shared_record_id = shared_record_id
        self.send_policy = None
        if send_policy is not None:
            self.send_policy = SharedSendPolicy.model_validate(send_policy.model_dump())

    def ingest(self, request: WorkerFetchRequest) -> WorkerFetchReceipt:
        digest = _digest(request)
        with self.store.transaction() as connection:
            previous = connection.execute(
                "SELECT request_digest, receipt_json FROM worker_fetch_receipts WHERE task_id = ?",
                (request.task_id,),
            ).fetchone()
            if previous is not None:
                if previous["request_digest"] != digest:
                    raise ContractValidationError("Worker task already holds different input.")
                return WorkerFetchReceipt.model_validate_json(previous["receipt_json"])
            report = ObservationImportReport()
            contacted = contacted_job_ids(self.outreach.list_audits())
            for index, raw in enumerate(request.observations):
                reason, record = check_observation(raw, self.manifests)
                if record is None:
                    report.rejected.append(
                        RejectedObservation(
                            index=index,
                            source_job_id=raw.source_job_id,
                            reason=reason,
                        )
                    )
                    continue
                manifest = self.manifests[record.source]
                job = JobNormalizer(default_currency=manifest.default_currency).normalize(record)
                known = (
                    connection.execute(
                        "SELECT 1 FROM normalized_jobs WHERE job_id = ?",
                        (job.id,),
                    ).fetchone()
                    is not None
                )
                self.jobs.save_observation(record, job, connection=connection)
                if record.search_term and record.search_term.strip():
                    self.jobs.record_search_hit(
                        JobSearchHit(
                            job_id=job.id,
                            source=job.source,
                            search_term=record.search_term.strip(),
                            collected_at=record.collected_at,
                        ),
                        connection=connection,
                    )
                report.stored.append(
                    ImportedObservation(
                        job_id=job.id,
                        source=job.source,
                        source_job_id=job.source_job_id,
                        title=job.title,
                        company=job.company,
                        known_before=known,
                        contacted=job.id in contacted,
                    )
                )
            status: WorkerFetchStatus = (
                "partial"
                if report.stored and report.rejected
                else ("stored" if report.stored else "rejected")
            )
            receipt = WorkerFetchReceipt(
                task_id=request.task_id,
                worker_id=request.worker_id,
                request_digest=digest,
                status=status,
                report=report,
                completed_at=self.clock(),
                event_id=_event_id(request.task_id),
            )
            connection.execute(
                "INSERT INTO worker_fetch_receipts VALUES (?, ?, ?, ?)",
                (request.task_id, digest, request.model_dump_json(), receipt.model_dump_json()),
            )
            self.store.append_event(
                connection,
                WorkerEvent(
                    event_id=receipt.event_id,
                    task_id=receipt.task_id,
                    kind="fetch_completed",
                    status=receipt.status,
                    job_ids=[i.job_id for i in report.stored],
                    created_at=receipt.completed_at,
                ),
            )
        return receipt

    def _read_shared(self) -> SharedWorkDecision:
        if self.shared is None or not self.shared_record_id or self.send_policy is None:
            raise ApprovalRequiredError(
                "Worker send requires a current shared-table read.",
                details={"send_dispatched": False},
            )
        record = self.shared.current(self.shared_record_id)
        if record.record_id != self.shared_record_id:
            raise ContractValidationError("Shared read returned a different record.")
        return current_work_decision(record, self.send_policy)

    def _execution_batch(self, batch_id: str) -> OutreachBatch:
        """Load the greeting payload. Local approval rows are not consulted."""
        batch = self.outreach.get_batch(batch_id)
        if batch is None:
            raise ContractValidationError("Outreach batch was not found.")
        found = {item.job_id: self.jobs.get_job(item.job_id) for item in batch.items}
        self.service.verify_current_batch(batch, {k: v for k, v in found.items() if v is not None})
        verify_greeting_sources(self.database, batch.items)
        return batch

    def _match_item(
        self, batch: OutreachBatch, decision: SharedWorkDecision, platform: str
    ) -> OutreachItem:
        greeting = decision.greeting
        matches = [
            item for item in batch.items if item.platform == platform and item.text == greeting
        ] if greeting else []
        if len(matches) != 1:
            raise ContractValidationError(
                "Current shared greeting does not match one execution item.",
                details={"send_dispatched": False},
            )
        return matches[0]

    def _observed_approval(
        self, batch: OutreachBatch, item: OutreachItem, decision: SharedWorkDecision
    ) -> OutreachApproval:
        """In-memory view for pacing only. It is not written to the outreach ledger."""
        if decision.approval is None:
            raise ApprovalRequiredError("Shared approval is missing.")
        identity = canonical_digest({"record_id": decision.record_id, "batch_id": batch.batch_id})
        return OutreachApproval(
            approval_id="OAPPROVAL_SHARED_" + identity[7:27].upper(),
            batch_id=batch.batch_id,
            batch_digest=batch.batch_digest,
            policy_digest=batch.policy_digest,
            approved_numbers=[item.number],
            channel=ApprovalChannel.SHARED_TABLE,
            attestation=decision.approval,
            approved_at=self.clock(),
        )

    def _next(
        self, batch_id: str, platform: str, session_id: str
    ) -> tuple[OutreachBatch, OutreachApproval, OutreachItem, SharedWorkDecision]:
        decision = self._read_shared()
        if not decision.business_allowed:
            raise ApprovalRequiredError(
                "Shared table does not currently approve this send.",
                details={"reason": decision.reason, "send_dispatched": False},
            )
        batch = self._execution_batch(batch_id)
        item = self._match_item(batch, decision, platform)
        observed = self._observed_approval(batch, item, decision)
        audits = self.outreach.list_audits()
        paced = self.service.next_item(
            batch,
            observed,
            platform=platform,
            audits=audits,
            lease_held=self.outreach.holds_lease(platform, session_id, now=self.clock()),
            now=self.clock(),
        )
        if not paced.allowed or paced.item != item:
            raise ContractValidationError(
                "Greeting gate refused: " + (paced.reason or "no_item"),
                details={"reason": paced.reason, "send_dispatched": False},
            )
        if item.job_id in contacted_job_ids(audits):
            raise ContractValidationError("Greeting gate refused: already_contacted")
        return batch, observed, item, decision

    def claim_greeting(self, batch_id: str, platform: str, session_id: str) -> WorkerSendClaim:
        with self.store.transaction() as connection:
            batch, approval, item, decision = self._next(batch_id, platform, session_id)
            if (
                connection.execute(
                    "SELECT 1 FROM worker_send_claims WHERE platform = ? AND status != 'completed'",
                    (platform,),
                ).fetchone()
                is not None
            ):
                raise ContractValidationError("This platform already has an unfinished claim.")
            claim = WorkerSendClaim(
                task_id="WSEND_" + uuid4().hex.upper(),
                worker_id=session_id,
                batch_id=batch_id,
                batch_digest=batch.batch_digest,
                policy_digest=batch.policy_digest,
                approval_id=approval.approval_id,
                approval_channel=approval.channel,
                shared_record_id=decision.record_id,
                shared_content_digest=decision.content_digest,
                item=item,
                claimed_at=self.clock(),
            )
            connection.execute(
                "INSERT INTO worker_send_claims "
                "(task_id, batch_id, number, platform, worker_id, status, claim_json) "
                "VALUES (?, ?, ?, ?, ?, 'claimed', ?)",
                (
                    claim.task_id,
                    batch_id,
                    item.number,
                    platform,
                    session_id,
                    claim.model_dump_json(),
                ),
            )
        return claim

    @staticmethod
    def _claim(connection: sqlite3.Connection, task_id: str, worker_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM worker_send_claims WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None or row["worker_id"] != worker_id:
            raise ContractValidationError("Worker claim not found for this session.")
        assert isinstance(row, sqlite3.Row)
        return row

    def _verify_claim(self, claim: WorkerSendClaim) -> None:
        if claim.shared_record_id != self.shared_record_id:
            raise ContractValidationError("Worker claim belongs to a different shared record.")
        batch, _approval, item, decision = self._next(
            claim.batch_id,
            claim.item.platform,
            claim.worker_id,
        )
        if (
            batch.batch_digest != claim.batch_digest
            or batch.policy_digest != claim.policy_digest
            or decision.content_digest != claim.shared_content_digest
            or item != claim.item
        ):
            raise ContractValidationError(
                "Worker claim no longer matches the current shared record."
            )

    def authorize_greeting(self, task_id: str, session_id: str) -> WorkerSendClaim:
        with self.store.transaction() as connection:
            row = self._claim(connection, task_id, session_id)
            if row["status"] != "claimed":
                raise ContractValidationError(
                    "A dispatch authorization is single-use; reconcile it."
                )
            claim = WorkerSendClaim.model_validate_json(row["claim_json"])
            self._verify_claim(claim)
            claim = claim.model_copy(update={"state": "authorized"})
            connection.execute(
                "UPDATE worker_send_claims SET status = 'authorized', claim_json = ? "
                "WHERE task_id = ?",
                (claim.model_dump_json(), task_id),
            )
        return claim

    def record_greeting(self, readback: WorkerReadback) -> WorkerSendReceipt:
        with self.store.transaction() as connection:
            row = self._claim(connection, readback.task_id, readback.worker_id)
            if row["receipt_json"] is not None:
                if row["readback_digest"] != _digest(readback):
                    raise ContractValidationError(
                        "A different readback already completed this task."
                    )
                return WorkerSendReceipt.model_validate_json(row["receipt_json"])
            claim = WorkerSendClaim.model_validate_json(row["claim_json"])
            result, reason = self._readback_result(readback, claim, row["status"])
            audit = OutreachAudit(
                audit_id="OAUDIT_" + uuid4().hex.upper(),
                batch_id=claim.batch_id,
                number=claim.item.number,
                job_id=claim.item.job_id,
                platform=claim.item.platform,
                item_digest=claim.item.item_digest,
                approval_id=claim.approval_id,
                approval_channel=claim.approval_channel,
                result=result,
                reason=reason,
                recorded_at=self.clock(),
            )
            self.outreach.append_audit(audit, connection=connection)
            receipt = WorkerSendReceipt(
                task_id=claim.task_id,
                worker_id=claim.worker_id,
                result=result,
                observed_result=readback.result,
                audit_id=audit.audit_id,
                event_id=_event_id(claim.task_id),
                completed_at=audit.recorded_at,
                reason=reason,
            )
            connection.execute(
                "UPDATE worker_send_claims SET status = 'completed', readback_digest = ?, "
                "receipt_json = ? WHERE task_id = ?",
                (_digest(readback), receipt.model_dump_json(), claim.task_id),
            )
            self.store.append_event(
                connection,
                WorkerEvent(
                    event_id=receipt.event_id,
                    task_id=claim.task_id,
                    kind="greeting_completed",
                    status=result.value,
                    job_ids=[claim.item.job_id],
                    created_at=receipt.completed_at,
                ),
            )
        return receipt

    def _readback_result(
        self,
        readback: WorkerReadback,
        claim: WorkerSendClaim,
        state: str,
    ) -> tuple[OutreachResult, str | None]:
        if readback.result == "unknown":
            return OutreachResult.INTERVENTION, "unconfirmed_browser_result"
        if readback.result in {"sent", "duplicate_found"}:
            if (
                state != "authorized"
                or readback.observed_text != claim.item.text
                or str(readback.observed_url) != claim.item.url
            ):
                return OutreachResult.INTERVENTION, "readback_or_authorization_mismatch"
            try:
                self._verify_claim(claim)
            except JobAgentError as error:
                return OutreachResult.INTERVENTION, "gate_changed_during_execution:" + error.code
        return OutreachResult(readback.result), readback.reason

    def show(self, task_id: str) -> WorkerState | None:
        return self.store.show(task_id)

    def events(self) -> list[WorkerEvent]:
        return self.store.events()

    def acknowledge(self, event_id: str) -> WorkerEventAck:
        return self.store.acknowledge(event_id, self.clock())
