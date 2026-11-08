# ruff: noqa: RUF001  -- user-facing receipts are written in Chinese.
"""Per-item greeting decisions from a host panel (such as Muse), through existing gates.

The panel is only a front end. A decision names the candidate, the pipeline
contact, the exact material revision (the asked item's digest) and the exact
words. Approval reuses the outreach approval gate on a single-item list built
from the asked item, so it is bound to the same digests as any other approval;
edited words are never approved directly. Declines and revisions become owner
feedback. Nothing here sends, and every outcome can be read back by its key.
"""

from datetime import datetime
from pathlib import Path

from jobagent.bridge.greeting_freshness import verify_greeting_sources
from jobagent.digest import canonical_digest, text_digest
from jobagent.errors import JobAgentError
from jobagent.outreach.service import OutreachService, contacted_job_ids, policy_digest
from jobagent.schemas.console_host import (
    HostDecisionRequest,
    HostEvent,
    HostMaterial,
    HostOption,
    HostReceipt,
    HostTodo,
)
from jobagent.schemas.outreach import (
    OutreachApproval,
    OutreachAsk,
    OutreachBatch,
    OutreachDraft,
    OutreachItem,
)
from jobagent.schemas.sourcing_feedback import PagedCardState, SourcingFeedback
from jobagent.storage.candidate_repository import SqliteCandidateRepository
from jobagent.storage.database import Database
from jobagent.storage.feedback_repository import SqliteFeedbackRepository, panel_events
from jobagent.storage.job_repository import SqliteJobRepository
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_repository import PipelineRepository

CHANNEL = "Muse 面板"
# Same meaning as the panel transport everywhere else: approve_material approves the
# exact material; approve_text only says the wording is fine and never approves.
_ACTIONS = {"approve_material": "approve", "save_draft": "revise", "decline": "decline"}
_DECIDED = {"approve": "approved", "revise": "revision_requested", "decline": "declined"}


class _Rejected(Exception):
    pass


def _event_id(candidate_id: str, operation_key: str) -> str:
    return "PANEL_" + canonical_digest([candidate_id, operation_key])[7:31].upper()


def _state_id(ask_id: str) -> str:
    return "PANEL_" + ask_id


def owned_evidence(db: Database, candidate_id: str) -> set[str]:
    return {
        e.id for e in SqliteCandidateRepository(db).list_evidence(candidate_id)
        if e.user_confirmed and e.confidence.value != "weak"
    }


LIEPIN_NOT_WIRED = (
    "猎聘用平台上的统一在线简历直接投递，没有首条招呼；"
    "猎聘的投递批准尚未接入面板，没有保存，请在对话中处理。"
)


def is_liepin_job(db: Database, platform_job_id: str) -> bool:
    with db.connect() as connection:
        return connection.execute(
            "SELECT 1 FROM normalized_jobs WHERE json_extract(job_json, '$.source') = 'liepin' "
            "AND json_extract(job_json, '$.source_job_id') = ? LIMIT 1",
            (platform_job_id,),
        ).fetchone() is not None


def _normalized_job_id(db: Database, candidate_id: str, contact_id: str) -> tuple[str, str]:
    try:
        job, meta = PipelineRepository(db).get(contact_id, candidate_id)
    except JobAgentError:
        raise _Rejected("这个岗位不属于当前候选人。") from None
    if meta.normalized_job_id is None:
        raise _Rejected("这个岗位尚未关联已保存的职位。")
    return job.job_id, meta.normalized_job_id


PANEL_CHILD_PREFIX = "OBATCH_PANEL_"


def asked_items(
    db: Database, candidate_id: str, normalized_job_id: str
) -> list[tuple[OutreachBatch, OutreachAsk, OutreachItem]]:
    """Every asked item for this job whose evidence the person confirmed, newest ask first."""
    store = SqliteOutreachRepository(db)
    owned = owned_evidence(db, candidate_id)
    with db.connect() as connection:
        asks = [
            OutreachAsk.model_validate_json(row[0])
            for row in connection.execute("SELECT ask_json FROM outreach_asks")
        ]
    result = []
    for ask in sorted(asks, key=lambda a: a.asked_at, reverse=True):
        # A panel approval's single-item list carries the approval; it asks nothing.
        if ask.batch_id.startswith(PANEL_CHILD_PREFIX):
            continue
        batch = store.get_batch(ask.batch_id)
        if batch is None or ask.batch_digest != batch.batch_digest:
            continue
        for item in batch.items:
            if (item.job_id == normalized_job_id and item.evidence_ids
                    and set(item.evidence_ids) <= owned):
                result.append((batch, ask, item))
    return result


def _settled(
    db: Database, batch: OutreachBatch, ask: OutreachAsk, item: OutreachItem
) -> str | None:
    """How the list or the panel already closed this item, or None while it is open."""
    store = SqliteOutreachRepository(db)
    approval = store.get_approval(batch.batch_id)
    if approval is not None and approval.batch_digest == batch.batch_digest:
        return ("已在整份清单里批准这条，尚未发送。" if item.number in approval.approved_numbers
                else "整份清单批准时没有选这条。")
    state = SqliteFeedbackRepository(db).state(_state_id(ask.ask_id))
    decided = state.decisions.get(str(item.number)) if state else None
    if decided is not None:
        return {
            "approved": "已批准这条招呼的准确全文，尚未发送。",
            "declined": "已记下不发这条。",
            "revision_requested": "已保存你的修改意见，待重新生成并复核。",
        }[decided]
    if store.is_withdrawn(batch.batch_id):
        return "这份清单已撤回。"
    return None


def open_items(
    db: Database, candidate_id: str, normalized_job_id: str
) -> list[tuple[OutreachBatch, OutreachAsk, OutreachItem]]:
    """Asked, unapproved, unwithdrawn items for this job that no decision has closed."""
    return [
        entry for entry in asked_items(db, candidate_id, normalized_job_id)
        if _settled(db, *entry) is None
    ]


def todo_id(ask_id: str, number: int) -> str:
    return "TODO_" + canonical_digest([ask_id, number])[7:31].upper()


_TODO_OPTIONS = (
    HostOption(
        option_id="revise", label="招呼语要改",
        consequence="记下要求重写，不批准、不发送；新稿生成并复核后再请你决定。",
    ),
    HostOption(
        option_id="hold", label="暂缓处理",
        consequence="记下暂缓，不批准、不发送；之后仍可以批准或放弃这条。",
    ),
)
_OPTION = {option.option_id: option for option in _TODO_OPTIONS}
_ANSWER_RECEIPT = {
    "revise": "已记下要求重写这条招呼，没有批准或发送；新稿生成并复核后再请你决定。",
    "hold": "已记下暂缓处理这条招呼，没有批准或发送；之后仍可以批准或放弃。",
}


def _answers(events: list[HostEvent]) -> dict[str, HostEvent]:
    """The latest saved answer per todo; events arrive oldest first."""
    return {e.todo_id: e for e in events if e.kind == "answer_todo" and e.todo_id}


def panel_todos(db: Database, candidate_id: str, events: list[HostEvent]) -> list[HostTodo]:
    """One personal todo per asked first greeting, pending until it is decided or answered.

    Only asked lists with confirmed evidence produce todos; nothing is inferred for
    jobs without such a record.
    """
    answers = _answers(events)
    todos = []
    for job, meta in PipelineRepository(db).list_records(candidate_id):
        if meta.normalized_job_id is None or is_liepin_job(db, job.job_id):
            continue
        for batch, ask, item in asked_items(db, candidate_id, meta.normalized_job_id):
            key = todo_id(ask.ask_id, item.number)
            result = _settled(db, batch, ask, item)
            answer = answers.get(key)
            if result is None and answer is not None:
                option = _OPTION[answer.option_id or ""]
                result = f"{option.label}：{option.consequence}"
            todos.append(HostTodo(
                todo_id=key, job_id=job.job_id, contact_id=job.pipeline_id,
                question=f"清单第 {item.number} 条首条招呼还等你决定。",
                material_revision=item.item_digest, requires_person=True, host_resolved=True,
                basis=[
                    f"岗位：{item.title} · {item.company}",
                    f"待决定的是这条首条招呼的准确全文，提问时间 {ask.asked_at.isoformat()}。",
                    "只有批准这份原文才会进入发送；暂缓或要求重写都不会发送。",
                ],
                options=list(_TODO_OPTIONS), status="pending" if result is None else "resolved",
                result=result,
            ))
    return todos


def panel_materials(database: Path, candidate_id: str, contact_id: str) -> list[HostMaterial]:
    """The exact greetings currently awaiting this person's decision for one contact."""
    db = Database(database)
    try:
        _, job_id = _normalized_job_id(db, candidate_id, contact_id)
    except _Rejected:
        return []
    return [
        HostMaterial(
            revision=item.item_digest, label=f"首条招呼（待你决定，清单第 {item.number} 条）",
            body=item.text, attachments=[],
        )
        for _, _, item in open_items(db, candidate_id, job_id)
    ]


def _stored(db: Database, event_id: str) -> SourcingFeedback | None:
    with db.connect() as connection:
        row = connection.execute(
            "SELECT event_json FROM sourcing_feedback_events WHERE event_id = ?", (event_id,)
        ).fetchone()
    return None if row is None else SourcingFeedback.model_validate_json(row[0])


def panel_operation(database: Path, candidate_id: str, operation_key: str) -> HostReceipt:
    """Read back one panel operation; an absent record was never stored."""
    db = Database(database)
    with db.connect() as connection:
        stored = next(
            (e for e in panel_events(connection, candidate_id) if e.operation_key == operation_key),
            None,
        )
    if stored is not None:
        return HostReceipt(
            operation_key=operation_key, status="saved", event_id=stored.event_id,
            message=receipt_message(stored),
        )
    # Decisions saved before operations were stored are found by their derived event id.
    event_id = _event_id(candidate_id, operation_key)
    event = _stored(db, event_id)
    if event is None or event.candidate_id != candidate_id:
        return HostReceipt(
            operation_key=operation_key, status="rejected",
            message="没有找到这次操作的保存记录，可以重新提交。",
        )
    return HostReceipt(
        operation_key=operation_key, status="saved", event_id=event_id,
        message=_MESSAGES[event.action],
    )


def receipt_message(event: HostEvent) -> str:
    """The person-facing receipt for a saved panel operation."""
    if event.kind == "answer_todo":
        return _ANSWER_RECEIPT.get(event.option_id or "", "已记下你的回答，没有批准或发送。")
    return _MESSAGES[_ACTIONS[event.kind]]


_MESSAGES = {
    "approve": "已批准这条招呼的准确全文，尚未发送。",
    "revise": "已保存你的修改意见，需要重新生成并复核后再审批，没有发送权。",
    "decline": "已记下不发这条，没有发送授权。",
}


def record_panel_decision(
    database: Path, request: HostDecisionRequest, *, actor_id: str, now: datetime
) -> HostReceipt:
    def rejected(message: str) -> HostReceipt:
        return HostReceipt(operation_key=request.operation_key, status="rejected", message=message)

    db = Database(database)
    db.migrate()
    action = _ACTIONS.get(request.kind)
    if request.kind == "approve_text":
        return rejected(
            "文案意见不构成批准，也没有保存；要批准这条原文，请提交 approve_material。"
        )
    with db.connect() as connection:
        prior = next(
            (e for e in panel_events(connection, request.candidate_id)
             if e.operation_key == request.operation_key),
            None,
        )
    if prior is not None and prior.kind != request.kind:
        return rejected("同一操作键已保存了不同的决定，已停止写入。")
    if request.kind == "answer_todo":
        try:
            return _answer(db, request, prior, now)
        except _Rejected as error:
            return rejected(str(error))
        except JobAgentError as error:
            return rejected(error.message)
    if action is None:
        return rejected("这个操作还没有接入面板保存，请在对话中处理。")
    if request.attachment_digests:
        return rejected("首条招呼不带附件；附件材料需走简历审批。")
    event_id = _event_id(request.candidate_id, request.operation_key)
    previous = _stored(db, event_id)
    if previous is not None:
        same = (previous.candidate_id == request.candidate_id and previous.action == action
                and previous.content_digest == text_digest(request.body))
        return panel_operation(database, request.candidate_id, request.operation_key) if same \
            else rejected("同一操作键已保存了不同的决定，已停止写入。")
    if is_liepin_job(db, request.job_id):
        return rejected(LIEPIN_NOT_WIRED)
    try:
        platform_job, job_id = _normalized_job_id(db, request.candidate_id, request.contact_id)
        if platform_job != request.job_id:
            raise _Rejected("岗位与面板联系记录不一致。")
        matches = [
            entry for entry in open_items(db, request.candidate_id, job_id)
            if entry[2].item_digest == request.material_revision
        ]
        if not matches:
            raise _Rejected("这条招呼已变化、已处理或已撤回，请刷新后查看最新版本。")
        batch, ask, item = matches[0]
        if action == "approve" and request.body != item.text:
            raise _Rejected("修改后的文字不能直接批准；请先保存修改，重新生成并复核后再审批。")
        if action == "revise" and request.body.strip() == item.text.strip():
            raise _Rejected("文字没有变化；如果接受原文请直接批准。")
        return _commit(db, request, batch, ask, item, action, event_id, actor_id, now)
    except _Rejected as error:
        return rejected(str(error))
    except JobAgentError as error:
        return rejected(error.message)


def _answer_detail(request: HostDecisionRequest) -> str:
    label = _OPTION[request.option_id or ""].label
    return label + (f"；备注：{request.note}" if request.note else "")


def _answer(
    db: Database, request: HostDecisionRequest, prior: HostEvent | None, now: datetime
) -> HostReceipt:
    """Store the person's answer to one todo: a deferral or a request to rewrite.

    Neither approves, sends or becomes preference feedback. A rewrite request carries
    no new words (the panel collects only a note), so it is not a "revise" event in
    the preference memory, which needs the full rewritten text; the host regenerates
    and the person decides on the new draft as a new item.
    """
    option_id, asked_todo = request.option_id, request.todo_id
    if option_id is None or option_id not in _OPTION or asked_todo is None:
        raise _Rejected("这条待办没有这个选项，请刷新后再看。")
    if prior is not None:
        same = (prior.todo_id == request.todo_id and prior.option_id == request.option_id
                and prior.detail == _answer_detail(request)
                and prior.contact_id == request.contact_id
                and prior.material is not None and prior.material.body == request.body)
        if not same:
            raise _Rejected("同一操作键已保存了不同的决定，已停止写入。")
        return panel_operation(db.path, request.candidate_id, request.operation_key)
    if request.attachment_digests:
        raise _Rejected("首条招呼不带附件；附件材料需走简历审批。")
    if is_liepin_job(db, request.job_id):
        raise _Rejected(LIEPIN_NOT_WIRED)
    platform_job, job_id = _normalized_job_id(db, request.candidate_id, request.contact_id)
    if platform_job != request.job_id:
        raise _Rejected("岗位与面板联系记录不一致。")
    matches = [
        entry for entry in asked_items(db, request.candidate_id, job_id)
        if todo_id(entry[1].ask_id, entry[2].number) == asked_todo
    ]
    if not matches:
        raise _Rejected("这条待办已变化或不存在，请刷新后再看。")
    batch, ask, item = matches[0]
    if item.item_digest != request.material_revision or request.body != item.text:
        raise _Rejected("这条招呼已变化，请刷新后查看最新版本。")
    with db.connect() as connection:
        answered = asked_todo in _answers(panel_events(connection, request.candidate_id))
    if answered or _settled(db, batch, ask, item) is not None:
        raise _Rejected("这条待办已经处理过了，请刷新后再看。")
    feedback_store = SqliteFeedbackRepository(db)
    state = feedback_store.state(_state_id(ask.ask_id)) or PagedCardState(
        message_id=_state_id(ask.ask_id), batch_id=batch.batch_id, ask_id=ask.ask_id,
        candidate_id=request.candidate_id, expires_at=None,
    )
    if state.candidate_id != request.candidate_id:
        raise _Rejected("这份清单的决定记录属于其他候选人。")
    event_id = _event_id(request.candidate_id, request.operation_key)
    event = HostEvent(
        event_id=event_id, operation_key=request.operation_key, job_id=request.job_id,
        contact_id=request.contact_id, kind="answer_todo", occurred_at=now,
        detail=_answer_detail(request),
        material=HostMaterial(
            revision=item.item_digest, label=f"首条招呼（清单第 {item.number} 条）",
            body=item.text, attachments=[],
        ),
        todo_id=request.todo_id, option_id=request.option_id,
    )
    if feedback_store.record_panel_answer(
        state, event_id=event_id, panel_event=event, now=now
    ) == "duplicate":
        return panel_operation(db.path, request.candidate_id, request.operation_key)
    return HostReceipt(
        operation_key=request.operation_key, status="saved", event_id=event_id,
        message=_ANSWER_RECEIPT[option_id],
    )


def _commit(
    db: Database, request: HostDecisionRequest, batch: OutreachBatch, ask: OutreachAsk,
    item: OutreachItem, action: str, event_id: str, actor_id: str, now: datetime,
) -> HostReceipt:
    feedback_store = SqliteFeedbackRepository(db)
    state = feedback_store.state(_state_id(ask.ask_id))
    if state is None:
        feedback_store.register(PagedCardState(
            message_id=_state_id(ask.ask_id), batch_id=batch.batch_id, ask_id=ask.ask_id,
            candidate_id=request.candidate_id, expires_at=None,
        ))
        state = feedback_store.state(_state_id(ask.ask_id))
        assert state is not None
    if state.candidate_id != request.candidate_id:
        raise _Rejected("这份清单的决定记录属于其他候选人。")
    key = str(item.number)
    revised = state.model_copy(deep=True)
    revised.revision += 1
    revised.decisions[key] = _DECIDED[action]  # type: ignore[assignment]
    if action == "revise":
        revised.drafts[key] = request.body
    bundle = None
    if action == "approve":
        bundle = _approval(db, batch, item, request, actor_id, now)
        revised.approved_batches[key] = bundle[0].batch_id
    revised.closed = all(str(i.number) in revised.decisions for i in batch.items)
    job = SqliteJobRepository(db).get_job(item.job_id)
    if job is None:
        raise _Rejected("缺少当前完整职位说明，无法保存这次决定。")
    feedback = SourcingFeedback(
        event_id=event_id, idempotency_key=event_id, job_id=item.job_id, source=item.platform,
        query_strategy_version=state.query_strategy_version, action=action,  # type: ignore[arg-type]
        free_text=request.note, content_digest=text_digest(request.body), actor_id=actor_id,
        occurred_at=now, candidate_id=request.candidate_id, original_text=item.text,
        revised_text=request.body if action == "revise" else None,
        jd_text=job.jd_raw, job_title=job.title, company=job.company,
    )
    panel_event = HostEvent(
        event_id=event_id, operation_key=request.operation_key, job_id=request.job_id,
        contact_id=request.contact_id, kind=request.kind, occurred_at=now, detail=request.note,
        material=HostMaterial(
            revision=item.item_digest, label=f"首条招呼（清单第 {item.number} 条）",
            body=request.body, attachments=[],
        ),
    )
    saved = feedback_store.commit(
        revised, expected_revision=state.revision, event_id=event_id, now=now,
        feedback=feedback, approval_bundle=bundle, withdraw_parent=revised.closed,
        panel_event=panel_event,
    )
    if saved == "duplicate":
        return panel_operation(db.path, request.candidate_id, request.operation_key)
    if saved != "stored":
        raise _Rejected("清单的决定记录刚被更新，请刷新后再操作。")
    return HostReceipt(
        operation_key=request.operation_key, status="saved", event_id=event_id,
        message=_MESSAGES[action],
    )


def _approval(
    db: Database, batch: OutreachBatch, item: OutreachItem, request: HostDecisionRequest,
    actor_id: str, now: datetime,
) -> tuple[OutreachBatch, OutreachAsk, OutreachApproval]:
    """A single-item list from the asked item, approved through the outreach gate."""
    verify_greeting_sources(db, [item], candidate_id=request.candidate_id)
    store, jobs, service = SqliteOutreachRepository(db), SqliteJobRepository(db), OutreachService()
    job = jobs.get_job(item.job_id)
    draft = OutreachDraft(
        job_id=item.job_id, platform=item.platform, text=item.text,
        evidence_ids=item.evidence_ids, variant=item.variant,
        hook_requirement=item.hook_requirement, experiment_id=item.experiment_id,
        written_by=item.written_by, source_binding=item.source_binding,
    )
    tiers = jobs.latest_match_tiers(request.candidate_id, [item.job_id]) or (
        {item.job_id: item.match_tier} if item.match_tier else {}
    )
    child_id = PANEL_CHILD_PREFIX + canonical_digest(
        [batch.batch_id, item.number, item.item_digest]
    )[7:27].upper()
    report = service.build_batch(
        [draft], jobs={item.job_id: job} if job else {},
        already_contacted=contacted_job_ids(store.list_audits()),
        confirmed_evidence_ids=owned_evidence(db, request.candidate_id), batch_id=child_id,
        created_at=now, policy=batch.policy,
        match_tiers=tiers,
        harness_version=batch.harness_version,
    )
    if (report.batch is None or report.batch.items[0].item_digest != item.item_digest
            or policy_digest(batch.policy) != batch.policy_digest):
        reasons = "、".join(report.rejected[0].reasons) if report.rejected else "内容已变化"
        raise _Rejected("这条招呼不能再批准：" + reasons)
    child = report.batch
    ask = service.ask(child, asked_at=now)
    attestation = (
        f"本人在{CHANNEL}批准第 {item.number} 条最终原文：{item.text}"
        f"（{actor_id}；操作 {request.operation_key}；联系 {request.contact_id}）"
    )
    approval = service.approve(child, ask=ask, numbers=[1], attestation=attestation,
                               approved_at=now)
    return child, ask, approval
