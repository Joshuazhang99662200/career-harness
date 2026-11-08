# ruff: noqa: RUF001  -- user-facing reasons and receipts are written in Chinese.
"""Panel execution lists for approved first greetings. Nothing here sends.

A list holds only greetings that already carry a bound human approval, each
pointing at that real approval; every other selected contact is listed with
the reason it was left out. Confirming records which items the person chose
and hands them to the host, which sends through the existing outreach
lease/next/record cadence. Each item's status is read from facts only: no
send audit is still queued, a sent audit is verified only with the exact
readback bound to that audit, failures keep their reason, and anything else
stays unknown and must be checked before any retry.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from jobagent.bridge.panel_decisions import (
    asked_items,
    is_liepin_job,
    owned_evidence,
    panel_operation,
)
from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import JobAgentError
from jobagent.outreach.service import contacted_job_ids, platform_halted_today, policy_digest
from jobagent.schemas.console_host import (
    HostBatch,
    HostExcluded,
    HostExecutionItem,
    HostExecutionRequest,
    HostMaterial,
    HostReadback,
    HostReceipt,
)
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAudit,
    OutreachBatch,
    OutreachItem,
    OutreachResult,
)
from jobagent.storage.database import Database
from jobagent.storage.execution_repository import (
    Confirmation,
    ItemRef,
    SqliteExecutionRepository,
    StoredBatch,
)
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_repository import PipelineRepository
from jobagent.storage.sent_tracking_repository import SqliteSentTrackingRepository

_CHANNEL_NAMES = {"boss": "BOSS", "zhaopin": "智联"}
LIEPIN_EXCLUDED = "猎聘用平台上的统一在线简历直接投递，没有首条招呼，不进招呼语执行清单。"
_NOT_SENT = {
    OutreachResult.FAILED: "发送失败",
    OutreachResult.INTERVENTION: "需要人工接手（登录、验证或风控）",
    OutreachResult.DUPLICATE_FOUND: "对话里已有我们发过的招呼，这次没有发送，不要重试",
    OutreachResult.WITHDRAWN: "这条已撤回，不发送",
}


@dataclass(frozen=True)
class _Approved:
    batch: OutreachBatch
    approval: OutreachApproval
    item: OutreachItem


def _approved_item(db: Database, candidate_id: str, normalized_job_id: str) -> _Approved | None:
    """The most recently approved first greeting for this job, if any."""
    store = SqliteOutreachRepository(db)
    owned = owned_evidence(db, candidate_id)
    found = []
    for batch in store.list_batches():
        approval = store.get_approval(batch.batch_id)
        if approval is None or approval.batch_digest != batch.batch_digest:
            continue
        for item in batch.items:
            if (item.job_id == normalized_job_id and item.number in approval.approved_numbers
                    and item.evidence_ids and set(item.evidence_ids) <= owned):
                found.append(_Approved(batch, approval, item))
    return max(found, key=lambda a: a.approval.approved_at, default=None)


def _eligibility(
    db: Database, candidate_id: str, contact_id: str, audits: list[OutreachAudit],
    now: datetime,
) -> tuple[_Approved | None, str | None, str]:
    """The approved item that may run for this contact now, or why none may."""
    try:
        job, meta = PipelineRepository(db).get(contact_id, candidate_id)
    except JobAgentError:
        return None, "这个岗位不属于当前候选人。", contact_id
    if meta.normalized_job_id is None:
        return None, "这个岗位尚未关联已保存的职位。", job.job_id
    if is_liepin_job(db, job.job_id):
        return None, LIEPIN_EXCLUDED, job.job_id
    approved = _approved_item(db, candidate_id, meta.normalized_job_id)
    if approved is None:
        return None, "还没有已批准的首条招呼。", job.job_id
    batch, approval, item = approved.batch, approved.approval, approved.item
    store = SqliteOutreachRepository(db)
    if approval.policy_digest != policy_digest(batch.policy):
        return None, "批准时的发送节奏规则已变化，需要重新批准。", job.job_id
    if store.is_withdrawn(batch.batch_id):
        return None, "这份已批准的清单已撤回。", job.job_id
    if platform_halted_today(audits, item.platform, now):
        return None, "这个平台今天已叫停（发送失败或需要人工接手），今天不执行。", job.job_id
    own = [a for a in audits if a.batch_id == batch.batch_id and a.number == item.number]
    if any(a.result is OutreachResult.SENT for a in own):
        return None, "这条招呼已经发送过。", job.job_id
    if own:
        outcome = _NOT_SENT[own[-1].result]
        return None, f"这条招呼已有执行结果（{outcome}），不重复执行。", job.job_id
    if item.job_id in contacted_job_ids(audits):
        return None, "这个岗位已经联系过。", job.job_id
    asked = asked_items(db, candidate_id, meta.normalized_job_id)
    if asked and asked[0][2].item_digest != item.item_digest \
            and asked[0][1].asked_at > approval.approved_at:
        return None, "材料已更新，需要重新批准新版。", job.job_id
    return approved, None, job.job_id


def create_execution_batch(
    database: Path, candidate_id: str, contact_ids: list[str], *, now: datetime
) -> HostBatch:
    """List the selected contacts' approved greetings; everything else with its reason."""
    db = Database(database)
    db.migrate()
    audits = SqliteOutreachRepository(db).list_audits()
    batch_id = "XBATCH_" + uuid4().hex[:20].upper()
    items: list[HostExecutionItem] = []
    excluded: list[HostExcluded] = []
    refs: dict[str, ItemRef] = {}
    for contact_id in dict.fromkeys(contact_ids):
        approved, reason, job_id = _eligibility(db, candidate_id, contact_id, audits, now)
        if approved is None:
            excluded.append(HostExcluded(job_id=job_id, reason=reason or "不能执行。"))
            continue
        item = approved.item
        item_id = "XITEM_" + canonical_digest(
            [batch_id, approved.approval.approval_id, item.number]
        )[7:27].upper()
        items.append(HostExecutionItem(
            item_id=item_id, job_id=job_id, contact_id=contact_id, title=item.title,
            channel=_CHANNEL_NAMES.get(item.platform, item.platform),
            material=HostMaterial(
                revision=item.item_digest, label="首条招呼（已批准）", body=item.text,
                attachments=[],
            ),
            approval_event_id=approved.approval.approval_id, status="queued", readback=None,
        ))
        refs[item_id] = ItemRef(approved.batch.batch_id, item.number,
                                approved.approval.approval_id)
    batch = HostBatch(batch_id=batch_id, status="ready", items=items, excluded=excluded)
    SqliteExecutionRepository(db).save_batch(candidate_id, batch, refs, now)
    return batch


def _readback(
    db: Database, candidate_id: str, contact_id: str, audit: OutreachAudit, body: str
) -> tuple[datetime, str] | None:
    """When and where the exact sent text was read back for this very send audit."""
    digest = text_digest(body)
    pipelines = PipelineRepository(db)
    try:
        job, _ = pipelines.get(contact_id, candidate_id)
        history = pipelines.history(contact_id, candidate_id)
    except JobAgentError:
        job, history = None, []
    if job is not None and job.send_readback == "exact" and job.sent_text_hash == digest \
            and job.sent_at == audit.recorded_at:
        for entry in history:
            if (entry.to_state == "greeting_sent" and entry.evidence_kind == "send_audit"
                    and entry.evidence_reference == audit.audit_id):
                return entry.changed_at, f"流水线回读 {entry.history_id}"
    try:
        records = SqliteSentTrackingRepository(db).list_records(candidate_id)
    except JobAgentError:
        records = []
    for record in records:
        if audit.audit_id in record.send_references and record.sent_text_hash == digest:
            return record.registered_at or record.sent_at, f"跟踪回读 {record.tracking_id}"
    return None


def _item_status(
    db: Database, candidate_id: str, item: HostExecutionItem, ref: ItemRef,
    audits: list[OutreachAudit],
) -> tuple[str, HostReadback | None]:
    audit = next(
        (a for a in audits if a.batch_id == ref.batch_id and a.number == ref.number
         and a.item_digest == item.material.revision),
        None,
    )
    if audit is None:
        return "queued", None
    if audit.result is OutreachResult.SENT:
        observed = _readback(db, candidate_id, item.contact_id, audit, item.material.body)
        if observed is None:
            return "unknown", HostReadback(
                status="unknown", evidence=audit.audit_id,
                detail="已登记发送，但还没有逐字回读核实；先核实，不要重复发送。",
            )
        return "verified", HostReadback(
            status="verified", detail="发送已回读核实：对话里的正文与批准原文一致。",
            evidence=f"{audit.audit_id} · {observed[1]}",
            material_revision=item.material.revision, observed_at=observed[0],
        )
    detail = _NOT_SENT[audit.result] + (f"：{audit.reason}" if audit.reason else "")
    return "failed", HostReadback(status="failed", detail=detail, evidence=audit.audit_id)


def _derived(db: Database, stored: StoredBatch, audits: list[OutreachAudit]) -> HostBatch:
    confirmation = SqliteExecutionRepository(db).confirmation_for_batch(stored.batch.batch_id)
    chosen = set(confirmation.item_ids) if confirmation else set()
    items = []
    for item in stored.batch.items:
        status, readback = _item_status(
            db, stored.candidate_id, item, stored.refs[item.item_id], audits
        )
        items.append(item.model_copy(update={
            "status": status, "readback": readback, "selected": item.item_id in chosen,
        }))
    selected = [i for i in items if i.selected]
    if not selected:
        batch_status = "ready"
    elif any(i.status in {"queued", "running"} for i in selected):
        batch_status = "executing"
    elif all(i.status == "verified" for i in selected):
        batch_status = "completed"
    elif any(i.status == "unknown" for i in selected):
        batch_status = "unknown"
    else:
        batch_status = "partial"
    return stored.batch.model_copy(update={"items": items, "status": batch_status})


def read_execution_batch(database: Path, candidate_id: str, batch_id: str) -> HostBatch | None:
    db = Database(database)
    stored = SqliteExecutionRepository(db).get_batch(candidate_id, batch_id)
    if stored is None:
        return None
    return _derived(db, stored, SqliteOutreachRepository(db).list_audits())


def execution_batches(db: Database, candidate_id: str) -> list[HostBatch]:
    audits = SqliteOutreachRepository(db).list_audits()
    stored = SqliteExecutionRepository(db).list_batches(candidate_id)
    return [_derived(db, s, audits) for s in stored]


def _confirmed_message(count: int) -> str:
    return (f"已确认 {count} 条，交给宿主按发送节奏逐条发送；没有选中的项保持原状，"
            "结果以回读核实为准。")


def _saved(confirmation: Confirmation) -> HostReceipt:
    return HostReceipt(
        operation_key=confirmation.operation_key, status="saved",
        event_id=confirmation.event_id, message=_confirmed_message(len(confirmation.item_ids)),
    )


def confirm_execution(
    database: Path, request: HostExecutionRequest, *, actor_id: str, now: datetime
) -> HostReceipt:
    """Record which approved items the person chose to run; the host then sends them."""

    def rejected(message: str) -> HostReceipt:
        return HostReceipt(operation_key=request.operation_key, status="rejected", message=message)

    db = Database(database)
    db.migrate()
    repository = SqliteExecutionRepository(db)
    digest = canonical_digest(request.model_dump(mode="json"))
    prior = repository.confirmation_for_key(request.candidate_id, request.operation_key)
    if prior is not None:
        if prior.request_digest == digest:
            return _saved(prior)
        return rejected("同一操作键已保存了不同的确认，已停止写入。")
    stored = repository.get_batch(request.candidate_id, request.batch_id)
    if stored is None:
        return rejected("这份执行清单不存在或属于其他候选人。")
    if repository.confirmation_for_batch(request.batch_id) is not None:
        return rejected("这份执行清单已经确认过；要再执行，请重新生成清单。")
    chosen = [s.item_id for s in request.selected]
    if len(set(chosen)) != len(chosen):
        return rejected("同一条不能重复选择。")
    by_id = {item.item_id: item for item in stored.batch.items}
    audits = SqliteOutreachRepository(db).list_audits()
    for selection in request.selected:
        item = by_id.get(selection.item_id)
        if item is None:
            return rejected("所选的条目不在这份清单里，请重新核对。")
        if (selection.material_revision != item.material.revision
                or selection.body != item.material.body or selection.attachment_digests):
            return rejected("所选条目的正文或版本和清单不一致，请重新核对。")
        approved, reason, _ = _eligibility(
            db, request.candidate_id, item.contact_id, audits, now
        )
        if approved is None:
            return rejected(f"{item.title}：{reason}")
        ref = stored.refs[item.item_id]
        if (approved.approval.approval_id, approved.batch.batch_id, approved.item.number,
                approved.item.item_digest) != (ref.approval_id, ref.batch_id, ref.number,
                                               item.material.revision):
            return rejected(f"{item.title}：批准或材料已变化，请重新生成清单。")
    confirmation = Confirmation(
        event_id="XCONF_" + canonical_digest(
            [request.candidate_id, request.operation_key]
        )[7:31].upper(),
        candidate_id=request.candidate_id, operation_key=request.operation_key,
        batch_id=request.batch_id, request_digest=digest, item_ids=tuple(chosen),
    )
    if repository.save_confirmation(confirmation, actor_id=actor_id, now=now) == "duplicate":
        mine = repository.confirmation_for_key(request.candidate_id, request.operation_key)
        if mine is not None and mine.request_digest == digest:
            return _saved(mine)
        return rejected("这份执行清单刚被确认过，请刷新后再看。")
    return _saved(confirmation)


def execution_receipts(db: Database, candidate_id: str) -> list[HostReceipt]:
    repository = SqliteExecutionRepository(db)
    receipts = []
    for stored in repository.list_batches(candidate_id):
        confirmation = repository.confirmation_for_batch(stored.batch.batch_id)
        if confirmation is not None:
            receipts.append(_saved(confirmation))
    return receipts


def operation_receipt(database: Path, candidate_id: str, operation_key: str) -> HostReceipt:
    """Read back any panel operation: an execution confirmation or a decision."""
    db = Database(database)
    confirmation = SqliteExecutionRepository(db).confirmation_for_key(candidate_id, operation_key)
    if confirmation is not None:
        return _saved(confirmation)
    return panel_operation(database, candidate_id, operation_key)
