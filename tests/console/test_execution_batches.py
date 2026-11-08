"""Execution batches for approved first greetings: create, confirm, and read back by facts.

The repository never sends. A batch lists approved items with the reason any
other selected contact was left out; confirming hands the selected items to
the host's existing outreach lease/next/record cadence; each item's status is
derived from the send audit and the pipeline's exact readback.
"""

import json
from datetime import timedelta

import pytest
from typer.testing import CliRunner

from jobagent.cli.app import app
from jobagent.console.execution import (
    confirm_execution,
    create_execution_batch,
    operation_receipt,
    read_execution_batch,
)
from jobagent.console.host_state import host_state
from jobagent.digest import text_digest
from jobagent.schemas.console_host import HostExecutionRequest
from jobagent.schemas.outreach import OutreachAudit, OutreachResult
from jobagent.schemas.pipeline import PipelineMeta, PipelineTransition
from jobagent.storage.database import Database
from jobagent.storage.outreach_repository import SqliteOutreachRepository
from jobagent.storage.pipeline_proofs import PipelineProofResolver
from jobagent.storage.pipeline_repository import PipelineRepository
from tests.bridge.test_greeting_context import NOW, populated
from tests.bridge.test_panel_decisions import decision, record
from tests.jobs.test_pipeline_contracts import row

TEXT = "Hello, I built research agents. Can we talk?"
PIPE = "PIPE_00000000000000A1"
URL = "https://careers.fixture-company.org/role"
LATER = NOW + timedelta(minutes=5)
SENT = NOW + timedelta(minutes=30)


def build(tmp_path, *, approved=False, source="boss"):
    """An asked greeting and a pipeline contact whose draft is exactly that greeting."""
    path, job_id = populated(tmp_path, approved=approved, source=source, url=URL)
    job = row(
        # Pipeline contacts carry boss/zhaopin; a Liepin job is known by its saved source.
        pipeline_id=PIPE, candidate_id="CAND_TEST", job_id="fixture-role",
        platform=source if source in {"boss", "zhaopin"} else "boss",
        job_url=URL, draft_greeting=TEXT, draft_digest=text_digest(TEXT),
        draft_version="SYNTHETIC_V1", entered_at=NOW, state_changed_at=NOW, updated_at=NOW,
    )
    meta = PipelineMeta(
        pipeline_id=PIPE, normalized_job_id=job_id, entered_evidence_reference="ENTRY"
    )
    PipelineRepository(Database(path)).create(
        job, meta, event_id="PANEL_ENTRY", evidence_reference="ENTRY"
    )
    return path


def approve_from_panel(path):
    assert record(path, decision(path, "approve_material", key="OP_APPROVE")).status == "saved"


def approved_item(path):
    store = SqliteOutreachRepository(Database(path))
    for batch in store.list_batches():
        approval = store.get_approval(batch.batch_id)
        if approval is not None:
            return batch, approval, batch.items[0]
    raise AssertionError("no approval")


def confirm(path, batch, *, key="OP_CONFIRM", **changes):
    item = batch.items[0]
    selection = dict(item_id=item.item_id, material_revision=item.material.revision,
                     body=item.material.body, attachment_digests=[])
    selection.update(changes)
    request = HostExecutionRequest(
        candidate_id="CAND_TEST", operation_key=key, batch_id=batch.batch_id,
        selected=[selection],
    )
    return confirm_execution(path, request, actor_id="OWNER_SYNTHETIC", now=LATER)


def audit(path, result, *, at=SENT, reason=None):
    batch, approval, item = approved_item(path)
    entry = OutreachAudit(
        audit_id="OAUDIT_" + result.value.upper()[:4] + "000000000001", batch_id=batch.batch_id,
        number=item.number, job_id=item.job_id, platform=item.platform,
        item_digest=item.item_digest, approval_id=approval.approval_id,
        approval_channel=approval.channel, result=result, reason=reason, recorded_at=at,
    )
    SqliteOutreachRepository(Database(path)).append_audit(entry)
    return entry


def read_back(path, sent):
    """The host's exact readback, applied through the pipeline's own proof gate."""
    db = Database(path)
    pipelines = PipelineRepository(db)
    job, meta = pipelines.get(PIPE, "CAND_TEST")
    event = PipelineTransition(
        event_id="EVENT_READBACK", pipeline_id=PIPE, candidate_id="CAND_TEST",
        expected_version=meta.version, from_state=job.pipeline_state, to_state="greeting_sent",
        changed_at=SENT + timedelta(minutes=1), evidence_kind="send_audit",
        evidence_reference=sent.audit_id, reason_code="normal", send_reference=sent.audit_id,
        readback_text=TEXT,
    )
    proof = PipelineProofResolver(db).resolve(job, meta, event, now=event.changed_at)
    pipelines.transition(event, proof, now=event.changed_at)


def test_only_approved_greetings_enter_a_batch(tmp_path):
    path = build(tmp_path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    assert batch.items == [] and len(batch.excluded) == 1
    assert "还没有已批准" in batch.excluded[0].reason


def test_a_panel_approval_becomes_one_ready_item_bound_to_that_approval(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    _, approval, item = approved_item(path)

    batch = create_execution_batch(path, "CAND_TEST", [PIPE, PIPE], now=LATER)
    assert batch.status == "ready" and batch.excluded == []
    [entry] = batch.items
    assert entry.approval_event_id == approval.approval_id
    assert (entry.material.revision, entry.material.body) == (item.item_digest, TEXT)
    assert (entry.contact_id, entry.job_id) == (PIPE, "fixture-role")
    assert entry.status == "queued" and entry.selected is False and entry.readback is None
    assert read_execution_batch(path, "CAND_TEST", batch.batch_id) == batch
    assert read_execution_batch(path, "CAND_OTHER", batch.batch_id) is None


def test_a_list_approval_counts_too(tmp_path):
    path = build(tmp_path, approved=True)
    [entry] = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER).items
    assert entry.approval_event_id == approved_item(path)[1].approval_id


@pytest.mark.parametrize(
    ("arrange", "reason"),
    [
        (lambda p: audit(p, OutreachResult.SENT), "已经发送过"),
        (lambda p: audit(p, OutreachResult.FAILED, at=LATER, reason="页面冻结"), "叫停"),
        (lambda p: SqliteOutreachRepository(Database(p)).withdraw(
            approved_item(p)[0].batch_id, reason="本人撤回", withdrawn_at=LATER), "撤回"),
    ],
)
def test_items_that_must_not_run_are_excluded_with_a_reason(tmp_path, arrange, reason):
    path = build(tmp_path, approved=True)
    arrange(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    assert batch.items == []
    assert reason in batch.excluded[0].reason


def test_liepin_and_foreign_contacts_are_excluded(tmp_path):
    path = build(tmp_path, approved=True, source="liepin")
    [excluded] = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER).excluded
    assert "猎聘" in excluded.reason
    [excluded] = create_execution_batch(path, "CAND_OTHER", [PIPE], now=LATER).excluded
    assert "不属于" in excluded.reason


def test_confirming_hands_only_selected_items_to_the_host(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)

    receipt = confirm(path, batch)
    assert receipt.status == "saved" and receipt.event_id
    after = read_execution_batch(path, "CAND_TEST", batch.batch_id)
    assert after is not None and after.status == "executing"
    [entry] = after.items
    assert entry.selected is True and entry.status == "queued" and entry.readback is None
    # Nothing was sent by the repository.
    assert SqliteOutreachRepository(Database(path)).list_audits() == []
    # Replay returns the same receipt; the same key with other content is refused.
    assert confirm(path, batch).event_id == receipt.event_id
    assert confirm(path, batch, body="Edited words.").status == "rejected"
    # A batch is confirmed once.
    assert confirm(path, batch, key="OP_AGAIN").status == "rejected"
    assert operation_receipt(path, "CAND_TEST", "OP_CONFIRM").event_id == receipt.event_id
    assert [b.batch_id for b in host_state(path, "CAND_TEST").batches] == [batch.batch_id]


@pytest.mark.parametrize(
    "changes",
    [{"body": "Edited words."}, {"material_revision": "sha256:" + "0" * 64},
     {"item_id": "XITEM_UNKNOWN"}, {"attachment_digests": ["sha256:" + "1" * 64]}],
)
def test_a_selection_that_differs_from_the_list_is_refused(tmp_path, changes):
    path = build(tmp_path)
    approve_from_panel(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    assert confirm(path, batch, **changes).status == "rejected"
    assert read_execution_batch(path, "CAND_TEST", batch.batch_id).status == "ready"


def test_confirmation_rechecks_that_the_item_is_still_unsent(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    audit(path, OutreachResult.SENT)
    receipt = confirm(path, batch)
    assert receipt.status == "rejected" and "已经发送过" in receipt.message


def test_sent_without_readback_is_unknown_and_exact_readback_is_verified(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    confirm(path, batch)
    sent = audit(path, OutreachResult.SENT)

    [entry] = read_execution_batch(path, "CAND_TEST", batch.batch_id).items
    assert entry.status == "unknown" and entry.readback.status == "unknown"

    read_back(path, sent)
    after = read_execution_batch(path, "CAND_TEST", batch.batch_id)
    [entry] = after.items
    assert entry.status == "verified" and after.status == "completed"
    assert entry.readback.status == "verified"
    assert entry.readback.material_revision == entry.material.revision
    assert sent.audit_id in entry.readback.evidence and entry.readback.observed_at is not None


def test_a_failed_send_is_failed_with_its_reason(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    batch = create_execution_batch(path, "CAND_TEST", [PIPE], now=LATER)
    confirm(path, batch)
    audit(path, OutreachResult.FAILED, reason="对方已关闭沟通")
    after = read_execution_batch(path, "CAND_TEST", batch.batch_id)
    [entry] = after.items
    assert entry.status == "failed" and "对方已关闭沟通" in entry.readback.detail
    assert after.status == "partial"


def test_cli_round_trip(tmp_path):
    path = build(tmp_path)
    approve_from_panel(path)
    runner, db = CliRunner(), ["--database", str(path)]
    created = runner.invoke(app, [
        "console", "batch-create", "--candidate", "CAND_TEST", "--contact", PIPE, *db,
    ])
    assert created.exit_code == 0, created.stdout
    batch = json.loads(created.stdout)
    item = batch["items"][0]
    request = tmp_path / "confirm.json"
    request.write_text(json.dumps({
        "candidate_id": "CAND_TEST", "operation_key": "OP_CLI", "batch_id": batch["batch_id"],
        "selected": [{"item_id": item["item_id"], "material_revision": item["material"]["revision"],
                      "body": item["material"]["body"], "attachment_digests": []}],
    }), encoding="utf-8")
    confirmed = runner.invoke(app, [
        "console", "batch-confirm", str(request), "--actor", "OWNER_SYNTHETIC", *db,
    ])
    assert confirmed.exit_code == 0, confirmed.stdout
    assert json.loads(confirmed.stdout)["status"] == "saved"
    shown = runner.invoke(app, [
        "console", "batch", batch["batch_id"], "--candidate", "CAND_TEST", *db,
    ])
    assert json.loads(shown.stdout)["status"] == "executing"
    missing = runner.invoke(
        app, ["console", "batch", "XBATCH_NONE", "--candidate", "CAND_TEST", *db]
    )
    assert missing.exit_code == 0 and json.loads(missing.stdout) is None
